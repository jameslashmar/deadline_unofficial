#!/usr/bin/env python3

from __future__ import absolute_import
import io
import os
import tempfile
import time
import sys

from Deadline.Plugins import DeadlinePlugin, PluginType
from Deadline.Scripting import FileUtils, RepositoryUtils, SystemUtils
from FranticX.Net import ListeningSocket, SimpleSocketException, SimpleSocketTimeoutException
from FranticX.Processes import ManagedProcess
from System import DateTime, TimeSpan
from System.Diagnostics import ProcessPriorityClass
from System.IO import File, Path
from System.Text import Encoding
from System.Text.RegularExpressions import Regex
from six.moves import range


######################################################################
## This is the function that Deadline calls to get an instance of the
## main DeadlinePlugin class.
######################################################################
def GetDeadlinePlugin():
    return Cinema4DBatchPlugin()

def CleanupDeadlinePlugin( deadlinePlugin ):
    deadlinePlugin.Cleanup()
    
######################################################################
## This is the main DeadlinePlugin class for the Cinema4D plugin.
######################################################################
class Cinema4DBatchPlugin( DeadlinePlugin ):
    MyCinema4DController = None

    def __init__( self ):
        if sys.version_info.major == 3:
            super().__init__()
        self.InitializeProcessCallback += self.InitializeProcess
        self.StartJobCallback += self.StartJob
        self.RenderTasksCallback += self.RenderTasks
        self.EndJobCallback += self.EndJob
        
    ## Called by Deadline to initialize the process.
    def InitializeProcess( self ):
        # Set the plugin specific settings.
        self.PluginType = PluginType.Advanced

        self.version = self.GetIntegerPluginInfoEntryWithDefault( "Version", 20 )
        
    def Cleanup( self ):
        del self.InitializeProcessCallback
        
    ## Called by Deadline when the job is first loaded.
    def StartJob( self ):
        self.LogInfo( "Start Job called - starting up Cinema 4D Batch plugin" )
        
        self.MyCinema4DController = Cinema4DController(self)
        self.MyCinema4DController.SetRenderExecutable()
        # Initialize the Cinema4D controller.
        self.MyCinema4DController.slaveDirectory = self.GetSlaveDirectory()
        
        # Start Cinema4D.
        self.MyCinema4DController.StartCinema4D()
        
    def RenderTasks( self ):
        self.LogInfo( "Render Tasks called" )
        self.MyCinema4DController.RenderTasks()
        
    def EndJob( self ):
        self.LogInfo( "End Job called - shutting down Cinema 4D Batch plugin" )
                
        if self.MyCinema4DController:
            # End the Cinema4D job (unloads the scene file, etc).
            self.MyCinema4DController.EndCinema4DJob()
        
class Cinema4DController( object ):
    Plugin = None
    ProgramName = "Cinema4DProcess"
    
    Cinema4DSocket = None
    Cinema4DStartupFile = ""
    slaveDirectory = ""
    Cinema4DFilename = ""
    Cinema4DRenderExecutable = ""
    ScriptFilename = ""
    ScriptJob = False
    
    ManagedCinema4DProcessRenderArgument = ""
    ManagedCinema4DProcessStartupDirectory = ""
    ManagedCinema4DProcessRenderExecutable = ""
    AuthenticationToken = ""
    
    LoadCinema4DTimeout = 1000
    ProgressUpdateTimeout = 8000
    
    LocalRendering = False
    NetworkFilePath = ""
    LocalFilePath = ""
    NetworkMPFilePath = ""
    LocalMPFilePath = ""
    VRay5NetworkFilePath = ""
    VRay5LocalFilePath = ""

    FunctionRegex = Regex( "FUNCTION: (.*)" )
    SuccessMessageRegex = Regex( "SUCCESS: (.*)" )
    SuccessNoMessageRegex = Regex( "SUCCESS" )
    CanceledRegex = Regex( "CANCELED" )
    ErrorRegex = Regex( "ERROR: (.*)" )
    
    StdoutRegex = Regex( "STDOUT: (.*)" )
    WarnRegex = Regex( "WARN: (.*)" )
    
    def __init__( self, plugin ):
        if sys.version_info.major == 3:
            super().__init__()
        self.Plugin = plugin
        self.ProgramName = "Cinema4DProcess"
        
        self.LoadCinema4DTimeout = self.Plugin.GetIntegerConfigEntryWithDefault( "LoadC4DTimeout", 1000 )
        self.ProgressUpdateTimeout = self.Plugin.GetIntegerConfigEntryWithDefault( "ProgressUpdateTimeout", 8000 )
        
        # Create the temp script file.
        self.renderTempDirectory = self.Plugin.CreateTempDirectory( "thread" + str(self.Plugin.GetThreadNumber()) )
        self.CancellationTokenPath = self.ProcessPath( os.path.join( self.renderTempDirectory, "cancellation.token" ) )

        # Disable Autodesk privacy settings window popup displaying during rendering
        self.Plugin.SetProcessEnvironmentVariable( "ARNOLD_ADP_DISABLE", "1" )
        # Disable Autodesk Analytics which has been observed to cause hangs
        self.Plugin.SetProcessEnvironmentVariable( "ARNOLD_ADP_OPTIN", "0" )

    def Cleanup( self ):
        pass
        
    ########################################################################
    ## Main functions (to be called from Deadline Entry Functions)
    ########################################################################
    # Reads in the plugin configuration settings and sets up everything in preparation to launch Cinema4D.
    # Also does some checking to ensure a Cinema4D job can be rendered on this machine.
    def SetRenderExecutable( self ):
        if self.Plugin.version < 15:
            self.Plugin.FailRender( "Cinema 4D " + str(self.Plugin.version) + " is not supported for the Batch plugin, please use the normal Cinema 4D plugin.")

        self.Cinema4DRenderExecutable = self.Plugin.GetRenderExecutable( "C4D_" + str(self.Plugin.version) + "_RenderExecutable" , "Cinema 4D %s" % self.Plugin.version )
    
    def ProcessPath( self, filepath ):
        if SystemUtils.IsRunningOnWindows():
            filepath = filepath.replace("/","\\")
            if filepath.startswith( "\\" ) and not filepath.startswith( "\\\\" ):
                filepath = "\\" + filepath
        else:
            filepath = filepath.replace("\\","/")
        return filepath

    def setDirectoryToLoadPlugin( self ):
        """
        Sets up the environment to tell Cinema 4D where to load DeadlineConnect.pyp.
        R19 and before use C4D_PLUGINS_DIR, R20 and later use g_additionalModulePath
        :return: None
        """
        # In Cinema 4D R20 the support for the C4D_PLUGINS_DIR environment variable has
        # been removed. This was done to avoid loading old plugins.
        envVariable = "g_additionalModulePath"
        if self.Plugin.version < 20:
            envVariable = "C4D_PLUGINS_DIR"

        pluginDirs = [self.Plugin.GetPluginDirectory()]

        existing_plugin_dirs = self.Plugin.GetProcessEnvironmentVariable( envVariable )
        if not existing_plugin_dirs:
            existing_plugin_dirs = os.getenv(envVariable, "")

        if existing_plugin_dirs:
            pluginDirs.extend(existing_plugin_dirs.split(';'))

        if self.Plugin.version in [23, 24]:
            """
            Cinema 4D R23 and S24 have a known bug which causes the commandline executable to not find the default plugins directory.
            As a workaround this function adds the default plugin directory to the g_additionalModulePath so it can be found.
            See: https://support.maxon.net/kb/faq.php?id=115 or https://support.maxon.net/hc/en-us/articles/1500006331481-Plug-ins-not-found-in-CommandLine-Render
            for additional info about the bug and other workarounds.
            """
            
            parent_dir = os.path.dirname(self.Cinema4DRenderExecutable)
            if SystemUtils.IsRunningOnMac():
                # On MacOS executable will be at '/Applications/MAXON CINEMA 4D R24/Commandline.app/Contents/MacOS/Commandline'.
                # The 'plugins' folder is located 3 levels higher, together with 'Commandline.app'
                parent_dir = os.path.dirname(os.path.dirname(os.path.dirname(parent_dir)))

            defaultPluginsDir = os.path.join(parent_dir, 'plugins')

            if defaultPluginsDir not in pluginDirs:
                if os.path.exists(defaultPluginsDir):
                    pluginDirs.append(defaultPluginsDir)
                else:
                    self.Plugin.LogWarning('Failed to find Default plugins directory (%s). If Cinema 4D is not able to access the default plugins directory it may render incorrectly.' %defaultPluginsDir)

        # Pre-pending our plugin dir due to a bug in R18 & R19 not supporting multiple paths for C4D_PLUGINS_DIR
        c4dPluginDirs = ';'.join(pluginDirs)

        self.Plugin.SetProcessEnvironmentVariable( envVariable, c4dPluginDirs )
        self.Plugin.LogInfo( "[%s] set to: %s" % ( envVariable, c4dPluginDirs ) )
        
    def StartCinema4D( self ):
        # Setup the command line parameters, and then start Cinema4D.
        sceneFile = self.Plugin.GetPluginInfoEntryWithDefault( "SceneFile", self.Plugin.GetDataFilename() )
        sceneFile = RepositoryUtils.CheckPathMapping( sceneFile )
        sceneFile = self.ProcessPath( sceneFile )
        
        self.setDirectoryToLoadPlugin()
        
        self.AuthenticationToken = str( int(time.time()) )
        
        if SystemUtils.IsRunningOnLinux() and self.Plugin.GetBooleanConfigEntryWithDefault( "SetLinuxEnvironment", True ):
            c4dDir = os.path.dirname( self.Cinema4DRenderExecutable )
            ldPath = os.environ.get( "LD_LIBRARY_PATH", "" )
            pyPath = os.environ.get( "PYTHONPATH", "" )
            path = os.environ.get( "PATH", "" )
            
            modLdPath = "%s/../lib64:%s/resource/modules/python/Python.linux64.framework/lib64:%s/resource/modules/embree.module/libs/linux64:%s" % ( c4dDir, c4dDir, c4dDir, ldPath )
            modPyPath = "%s/resource/modules/python/Python.linux64.framework/lib/python2.7:%s/resource/modules/python/Python.linux64.framework/lib64/python2.7/lib-dynload:%s" % ( c4dDir, c4dDir, pyPath )
            modPath = "%s:%s" % ( path, c4dDir )
            
            self.Plugin.LogInfo( "[LD_LIBRARY_PATH] set to %s" % modLdPath )
            self.Plugin.LogInfo( "[PYTHONPATH] set to %s" % modPyPath )
            self.Plugin.LogInfo( "[PATH] set to %s" % modPath )
            self.Plugin.SetProcessEnvironmentVariable( "LD_LIBRARY_PATH", modLdPath )
            self.Plugin.SetProcessEnvironmentVariable( "PYTHONPATH", modPyPath )
            self.Plugin.SetProcessEnvironmentVariable( "PATH", modPath )

        # Initialize the listening socket.
        self.Cinema4DSocket = ListeningSocket()
        self.Cinema4DSocket.StartListening( 0, True, True, 10 )
        if not self.Cinema4DSocket.IsListening:
            self.Plugin.FailRender( "Failed to open a port for listening to Cinema 4D" )
        else:
            self.Plugin.LogInfo( "Cinema 4D socket connection port: %d" % self.Cinema4DSocket.Port )
        
        parameters = [ "-nogui" ]

        # Check if using 3PL
        # The 'cinema4d_LICENSE' env variable is set by the Worker if we are using a UBL Limit
        c4d_3pl_server = os.environ.get('cinema4d_LICENSE')
        if c4d_3pl_server and (21 <= self.Plugin.version < 26):
            parameters.append('g_licenseServerRLM="%s"' % c4d_3pl_server)
            parameters.append('g_licenseServerUrl=""')

        # NOTE: Negate the "No OpenGL" plugin info option from the monitor submitter to make the logic below
        # easier to read
        self.loadOpenGL = not self.Plugin.GetBooleanPluginInfoEntryWithDefault( "NoOpenGL", False )

        # If the integrated submitter has specified a renderer other than Hardware OpenGL
        # we can skip loading OpenGL
        renderer = self.Plugin.GetPluginInfoEntryWithDefault( "Renderer", "" )
        if self.loadOpenGL and renderer not in ( "", "ogl_hardware" ):
            self.loadOpenGL = False

        if not self.loadOpenGL:
            parameters.append( "-noopengl" )
        
        # When Cinema4D starts, it will acquire a floating Redshift license if one is available. 
        # This is done even if Redshift is not the current renderer, and even if there is a node-locked Redshift license already on that machine.
        # The following lets the user set a System Environment Variable REDSHIFT_LICENSE_MAXON_DISABLE=True to disable the acquisition of a 
        # floating Redshift license on machines with a node-locked license. 
        # The same code will also disable the acquisition of a floating Redshift license if the current renderer is not Redshift, 
        # unless the renderer is unknown, e.g. because the submission came from the Monitor submitter:
        if os.environ.get( "REDSHIFT_LICENSE_MAXON_DISABLE", "False" ) == "True" or (renderer != "redshift" and renderer != ""):
            parameters.append("-redshift-license-maxon-disable")

        threads = self.GetNumThreads()
        if threads > 0:
            parameters.append( "-threads %s" % str( threads ) )

        selectedGPUs = self.GetGpuOverrides()
        if selectedGPUs:
            for gpu in selectedGPUs:
                parameters.append( "-redshift-gpu %s" % gpu )

        redshiftLogVerbosity = self.Plugin.GetConfigEntryWithDefault( "RedshiftLogging", "Debug" )
        if redshiftLogVerbosity != "None":
            parameters.append( "-redshift-log-console %s" % redshiftLogVerbosity )
        
        self.importTestFile = os.path.join( self.Plugin.CreateTempDirectory( "importTest" ), "importCheck.txt")
        parameters.append( '"-DeadlineConnect %s %s \'%s\'"' % ( self.Cinema4DSocket.Port, self.AuthenticationToken, self.importTestFile ) )

        parameterString = " ".join(parameters)
        self.Plugin.LogInfo( "Parameters: %s" % parameterString )

        # Luke Letellier - Clay Render Fix
        # Stagger startup based on GPU ID to avoid Redshift file access conflicts.
        gpusPerTask = self.Plugin.GetIntegerPluginInfoEntryWithDefault( "GPUsPerTask", 0 )
        if gpusPerTask > 0:
            # When GPUsPerTask is used, GetThreadNumber() corresponds to the task ID, which we can use
            # as a stand-in for the GPU ordinal to calculate a unique delay.
            gpuOrdinal = self.Plugin.GetThreadNumber()
            delay = gpuOrdinal * 2  # 2-second delay increment per GPU.
            
            if delay > 0:
                self.Plugin.LogInfo( "Clay-render fix: Startup is delayed by %d seconds for GPU ordinal %d to avoid file access conflicts." % (delay, gpuOrdinal) )
                time.sleep( delay )
            else:
                self.Plugin.LogInfo( "Clay-render fix: Startup is not delayed on this task, as this is GPU 0 (or all GPUs are rendering together). The code is still working." )
        # END OF FIX - Clay render fix

        self.LaunchCinema4D( self.Cinema4DRenderExecutable, parameterString, os.path.dirname( self.Cinema4DRenderExecutable ) )
        self.WaitForConnection( "Cinema 4D startup" )
        self.Plugin.LogInfo( "Connected to Cinema 4D" )
        
        verbose = self.Plugin.GetBooleanConfigEntryWithDefault( "Verbose", False )
        
        self.Cinema4DSocket.Send( "Verbose:" + str( verbose ) )
        self.Plugin.LogInfo( self.PollUntilComplete( False ) )

        self.Cinema4DSocket.Send( "DeadlineStartup:" + sceneFile )
        self.Plugin.LogInfo( self.PollUntilComplete( False ) )

        self.SendPathMapping()
    
    def GetNumThreads( self ):
        """
        Returns the number of threads we want to use based off the number of threads specified in the job and the Worker's CPU Affinity
        :return: The number of threads
        """
        threads = self.Plugin.GetIntegerPluginInfoEntryWithDefault( "Threads", 0 )
        # OverrideCpuAffinity - Returns whether the Worker has its CPU affinity override enabled
        if self.Plugin.OverrideCpuAffinity():
            #CPUAffinity - returns a list containing the indices of all CPUs the Worker has in its affinity
            affinity = len( self.Plugin.CpuAffinity() )
            if threads == 0:
                threads = affinity
            else:
                threads = min( affinity, threads )
                
        return threads   
    
    def GetGpuOverrides( self ):
        # If the number of gpus per task is set, then need to calculate the gpus to use.
        gpusPerTask = self.Plugin.GetIntegerPluginInfoEntryWithDefault( "GPUsPerTask", 0 )
        gpusSelectDevices = self.Plugin.GetPluginInfoEntryWithDefault( "GPUsSelectDevices", "" )
        resultGPUs = []

        if self.Plugin.OverrideGpuAffinity():
            overrideGPUs = self.Plugin.GpuAffinity()
            if gpusPerTask == 0 and gpusSelectDevices != "":
                gpus = gpusSelectDevices.split( "," )
                notFoundGPUs = []
                for gpu in gpus:
                    if int( gpu ) in overrideGPUs:
                        resultGPUs.append( gpu )
                    else:
                        notFoundGPUs.append( gpu )
                
                if len( notFoundGPUs ) > 0:
                    self.Plugin.LogWarning( "The Worker is overriding its GPU affinity and the following GPUs do not match the Workers affinity so they will not be used: " + ",".join(notFoundGPUs) )
                if len( resultGPUs ) == 0:
                    self.Plugin.FailRender( "The Worker does not have affinity for any of the GPUs specified in the job." )
            elif gpusPerTask > 0:
                if gpusPerTask > len( overrideGPUs ):
                    self.Plugin.LogWarning( "The Worker is overriding its GPU affinity and the Worker only has affinity for " + str( len( overrideGPUs ) ) + " Workers of the " + str( gpusPerTask ) + " requested." )
                    resultGPUs =  overrideGPUs
                else:
                    resultGPUs = list( overrideGPUs )[:gpusPerTask]
            else:
                resultGPUs = overrideGPUs
        elif gpusPerTask == 0 and gpusSelectDevices != "":
            resultGPUs = gpusSelectDevices.split( "," )

        elif gpusPerTask > 0:
            gpuList = []
            for i in range( ( self.Plugin.GetThreadNumber() * gpusPerTask ), ( self.Plugin.GetThreadNumber() * gpusPerTask ) + gpusPerTask ):
                gpuList.append( str( i ) )
            resultGPUs = gpuList
        
        resultGPUs = list( resultGPUs )
        
        return resultGPUs
        
    def SendPathMapping( self ):
        pathMappings = RepositoryUtils.GetPathMappings()
        if len( pathMappings ) > 0:
            args = [ self.Plugin.CreateTempDirectory( "pathmapping" ) ]
            texPathFile = self.createTexturePathFile(  )
            if texPathFile:
                args.append( texPathFile )
            
            self.Cinema4DSocket.Send( "Pathmap:" + ";".join(args) )
            self.Plugin.LogInfo( self.PollUntilComplete( False ) )
    
    def createTexturePathFile( self ):
        texPathFileName = None
        if self.Plugin.GetBooleanPluginInfoEntryWithDefault( "HasTexturePaths", False ):
            texPathFileName = os.path.join( self.renderTempDirectory, "texturePaths.txt" )
            with io.open( texPathFileName, mode="w", encoding="utf-8" ) as texPathFile:
                if self.Plugin.version >= 20:
                    index = 0
                    while True:
                        searchPath = self.Plugin.GetPluginInfoEntryWithDefault( "TexturePath%s" % index, "" )
                        if not searchPath:
                            break
                        texPathFile.write( RepositoryUtils.CheckPathMapping( searchPath ) + "\n" )
                        index += 1
                else:
                    for index in range(10):
                        texPath = self.Plugin.GetPluginInfoEntryWithDefault( "TexturePath%s" % index, "" )
                        texPathFile.write( RepositoryUtils.CheckPathMapping( texPath )+ "\n" )
        
        return texPathFileName
    
    def writeSetTakeData( self, globalScript, deadlineC4DThreadScript, activeTake ):
        

        globalScript.append( "# Iterate through objects in take (op)" )
        globalScript.append( "def GetNextObject( op ):" )
        globalScript.append( "    if op==None:" )
        globalScript.append( "        return None" )
        globalScript.append( "    if op.GetDown():" )
        globalScript.append( "        return op.GetDown()" )
        globalScript.append( "    while not op.GetNext() and op.GetUp():" )
        globalScript.append( "        op = op.GetUp()" )
        globalScript.append( "    return op.GetNext()" )                    
        
        deadlineC4DThreadScript.append( "        from c4d.modules import takesystem" )
        deadlineC4DThreadScript.append( "        takeData = self.deadlineDoc.GetTakeData()" )  
        deadlineC4DThreadScript.append( "        mainTake = takeData.GetMainTake()" )
        deadlineC4DThreadScript.append( "        take = GetNextObject( mainTake )" )
        deadlineC4DThreadScript.append( "        while take is not None:" )
        deadlineC4DThreadScript.append( "            if take.GetName() == \""+activeTake+"\":" )
        deadlineC4DThreadScript.append( "                takeData.SetCurrentTake(take)" )
        deadlineC4DThreadScript.append( "                break" )
        deadlineC4DThreadScript.append( "            take = GetNextObject( take )" )
        deadlineC4DThreadScript.append( "        if take is not None:" )
        deadlineC4DThreadScript.append( "            effectiveRenderData = take.GetEffectiveRenderData( takeData )" )
        deadlineC4DThreadScript.append( "            if effectiveRenderData is not None:" )
        deadlineC4DThreadScript.append( "                rd = effectiveRenderData[ 0 ]" )
    
    def RenderTasks( self ):
        self.Plugin.LogInfo("Pre Build Script")
        renderer = self.Plugin.GetPluginInfoEntryWithDefault( "Renderer", "" )
        exportJob = "Export" in renderer
        
        self.ScriptJob = self.Plugin.GetBooleanPluginInfoEntryWithDefault( "ScriptJob", False )
        
        if self.ScriptJob:
            self.Plugin.LogInfo( "This is a Python Script Job" )

            self.ScriptFilename = self.Plugin.GetPluginInfoEntryWithDefault( "ScriptFilename", "" )

            if not os.path.isabs( self.ScriptFilename ):
                self.ScriptFilename = os.path.join( self.Plugin.GetJobsDataDirectory(), self.ScriptFilename )
            else:
                self.ScriptFilename = RepositoryUtils.CheckPathMapping( self.ScriptFilename )
                self.ScriptFilename = self.ProcessPath( self.ScriptFilename )

            if not os.path.isfile( self.ScriptFilename ):
                self.Plugin.FailRender( "Python Script File is missing: %s" % self.ScriptFilename )

        else:
            globalScript = []
            deadlineC4DThreadScript = []
            
            if not exportJob:
                self.RegionRendering = self.Plugin.GetBooleanPluginInfoEntryWithDefault( "RegionRendering", False )
                self.SingleFrameRegionJob = self.Plugin.IsTileJob()
                self.SingleFrameRegionFrame = str(self.Plugin.GetStartFrame())
                self.SingleFrameRegionIndex = self.Plugin.GetCurrentTaskId()
                
                if self.RegionRendering and self.SingleFrameRegionJob:
                    self.StartFrame = str(self.SingleFrameRegionFrame)
                    self.EndFrame = str(self.SingleFrameRegionFrame)
                else:
                    self.StartFrame = str(self.Plugin.GetStartFrame())
                    self.EndFrame = str(self.Plugin.GetEndFrame())
                
                # This needs a newline at the beggining of the script otherwise the first line gets consumed somewhere along the way.
                deadlineC4DThreadScript.append( "" )
                deadlineC4DThreadScript.append( "#!/usr/bin/python" )
                deadlineC4DThreadScript.append( "# -*- coding: utf-16-le -*-" )
                deadlineC4DThreadScript.append( "import c4d" )
                deadlineC4DThreadScript.append( "from c4d import bitmaps" )
                deadlineC4DThreadScript.append( "from c4d import documents" )
                deadlineC4DThreadScript.append( "from c4d.threading import C4DThread" )
                deadlineC4DThreadScript.append( "import os.path" )

                # Some magic numbers for Arnold settings
                deadlineC4DThreadScript.append("ARNOLD_RENDERER = 1029988")
                deadlineC4DThreadScript.append("ARNOLD_RENDERER_COMMAND = 1039333")
                deadlineC4DThreadScript.append("ARNOLD_ABORT_ON_LICENSE_FAIL = 213851792")
                
                # V-Ray 5 settings
                deadlineC4DThreadScript.append("VRAY5_RENDERER = 1053272")

                # Build the thread class and main function
                deadlineC4DThreadScript.append( "class DeadlineC4DThread(C4DThread):" )

                # Define the function to get Arnold settings
                # This is the function provided by https://docs.arnoldrenderer.com/display/A5AFCUG/Render+Settings+%7C+Python
                deadlineC4DThreadScript.append( "    def GetArnoldRenderSettings(self, doc):" )
                deadlineC4DThreadScript.append( "        rdata = doc.GetActiveRenderData()" )
                # find the active Arnold render settings"
                deadlineC4DThreadScript.append( "        videopost = rdata.GetFirstVideoPost()" )
                deadlineC4DThreadScript.append( "        while videopost:" )
                deadlineC4DThreadScript.append( "            if videopost.GetType() == ARNOLD_RENDERER:" )
                deadlineC4DThreadScript.append( "                return videopost;")
                deadlineC4DThreadScript.append( "            videopost = videopost.GetNext()")
                deadlineC4DThreadScript.append( "  ")
                # create a new one when does not exist
                deadlineC4DThreadScript.append( "        if videopost is None:")
                deadlineC4DThreadScript.append( "            c4d.CallCommand(ARNOLD_RENDERER_COMMAND)")
                deadlineC4DThreadScript.append( "  ")
                deadlineC4DThreadScript.append( "            videopost = rdata.GetFirstVideoPost()")
                deadlineC4DThreadScript.append( "            while videopost:")
                deadlineC4DThreadScript.append( "                if videopost.GetType() == ARNOLD_RENDERER:")
                deadlineC4DThreadScript.append( "                    return videopost;")
                deadlineC4DThreadScript.append( "                videopost = videopost.GetNext()")
                deadlineC4DThreadScript.append( "  ")
                deadlineC4DThreadScript.append( "        return None")
                deadlineC4DThreadScript.append( "  ")

                # Define the function to get V-Ray 5 settings
                deadlineC4DThreadScript.append( "    def GetVray5RenderSettings(self, doc):" )
                deadlineC4DThreadScript.append( "        rdata = doc.GetActiveRenderData()" )
                # find the active V-Ray 5 render settings"
                deadlineC4DThreadScript.append( "        videopost = rdata.GetFirstVideoPost()" )
                deadlineC4DThreadScript.append( "        while videopost:" )
                deadlineC4DThreadScript.append( "            if videopost.GetType() == VRAY5_RENDERER:" )
                deadlineC4DThreadScript.append( "                return videopost;")
                deadlineC4DThreadScript.append( "            videopost = videopost.GetNext()")
                deadlineC4DThreadScript.append( "  ")
                deadlineC4DThreadScript.append( "        return None")
                deadlineC4DThreadScript.append( "  ")

                deadlineC4DThreadScript.append( "    def Main(self):" )
                deadlineC4DThreadScript.append( "        self.deadlineDoc = documents.GetActiveDocument()" )
                deadlineC4DThreadScript.append( "        self.renderData = self.deadlineDoc.GetActiveRenderData()" )
                
                activeTake = self.Plugin.GetPluginInfoEntryWithDefault( "Take", "" )
                if not activeTake == "" and self.Plugin.version >= 17  :
                    self.writeSetTakeData( globalScript, deadlineC4DThreadScript, activeTake )
                
                deadlineC4DThreadScript.append( "        fps = int( self.renderData[c4d.RDATA_FRAMERATE] )" )
                deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_FRAMESEQUENCE] = c4d.RDATA_FRAMESEQUENCE_MANUAL" )
                deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_FRAMEFROM]=c4d.BaseTime(" + str(self.StartFrame ) + ", fps)" )
                deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_FRAMETO]=c4d.BaseTime(" + str( self.EndFrame ) + ", fps)" )
                deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_FRAMESTEP]=1")

                # --- Luke Letellier fix: Disable double gamma transform when using 'Bake View Transform' ---
                # This is specifically for C4D 2025/2026+
                deadlineC4DThreadScript.append( "        if hasattr(c4d, 'RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER'):" )
                deadlineC4DThreadScript.append( "            self.renderData[c4d.RDATA_BAKE_OCIO_VIEW_TRANSFORM_RENDER] = False" )
                # ---END OF FIX --------------------------------------------------

                # Set AbortOnLicenseFail value to Arnold settings
                deadlineC4DThreadScript.append( "        arnoldRenderSettings = self.GetArnoldRenderSettings(self.deadlineDoc)")
                deadlineC4DThreadScript.append( "        if arnoldRenderSettings is not None:")
                deadlineC4DThreadScript.append( "            arnoldRenderSettings[ARNOLD_ABORT_ON_LICENSE_FAIL]=%s" %
                                                int(self.Plugin.GetBooleanConfigEntryWithDefault("AbortOnArnoldLicenseFail", True)))
                
                width = self.Plugin.GetIntegerPluginInfoEntryWithDefault( "Width", 0 )
                height = self.Plugin.GetIntegerPluginInfoEntryWithDefault( "Height", 0 )
                if width > 0 and height > 0:
                    deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_XRES]=" + str( width ) )
                    deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_YRES]=" + str( height ) )
                
                if self.RegionRendering:
                    if renderer == "octane":
                        globalScript.append( "def GetOctaneVideoPost(renderData):")
                        globalScript.append( "    video_post = renderData.GetFirstVideoPost()" )
                        globalScript.append( "    while video_post and video_post.GetType() != 1029525:" )
                        globalScript.append( "        video_post = video_post.GetNext()" )
                        globalScript.append( "    return video_post" )

                        deadlineC4DThreadScript.append( "        octane_video_post = GetOctaneVideoPost(self.renderData)" )
                        deadlineC4DThreadScript.append( "        octane_video_post[c4d.VP_RENDERREGION] = True" )
                    else:
                        deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_RENDERREGION] = True" )
                    
                    if self.SingleFrameRegionJob:
                        self.Left = self.Plugin.GetPluginInfoEntryWithDefault( "RegionLeft" + self.SingleFrameRegionIndex, "0" )
                        self.Right = self.Plugin.GetPluginInfoEntryWithDefault( "RegionRight" + self.SingleFrameRegionIndex, "0" )
                        self.Top = self.Plugin.GetPluginInfoEntryWithDefault( "RegionTop" + self.SingleFrameRegionIndex, "0" )
                        self.Bottom = self.Plugin.GetPluginInfoEntryWithDefault( "RegionBottom" + self.SingleFrameRegionIndex, "0" )
                    else:
                        self.Left = self.Plugin.GetPluginInfoEntryWithDefault( "RegionLeft", "0" ).strip()
                        self.Right = self.Plugin.GetPluginInfoEntryWithDefault( "RegionRight", "0" ).strip()
                        self.Top = self.Plugin.GetPluginInfoEntryWithDefault( "RegionTop", "0" ).strip()
                        self.Bottom = self.Plugin.GetPluginInfoEntryWithDefault( "RegionBottom", "0" ).strip()

                    if renderer == "octane":
                        deadlineC4DThreadScript.append( "        octane_video_post[c4d.VP_REGION_X1] = %s" % self.Left )
                        deadlineC4DThreadScript.append( "        octane_video_post[c4d.VP_REGION_Y1] = %s" % self.Top )
                        deadlineC4DThreadScript.append( "        octane_video_post[c4d.VP_REGION_X2] = %s" % self.Right )
                        deadlineC4DThreadScript.append( "        octane_video_post[c4d.VP_REGION_Y2] = %s" % self.Bottom )
                    else:
                        deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_RENDERREGION_LEFT] = %s" % self.Left  )
                        deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_RENDERREGION_TOP] = %s" % self.Top )
                        deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_RENDERREGION_RIGHT] = %s" % self.Right )
                        deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_RENDERREGION_BOTTOM] = %s" % self.Bottom )
                                    
                self.LocalRendering = self.Plugin.GetBooleanPluginInfoEntryWithDefault( "LocalRendering", False )
                
                # Build the output filename from the path and prefix
                filepath = self.Plugin.GetPluginInfoEntryWithDefault( "FilePath", "" ).strip()
                filepath = RepositoryUtils.CheckPathMapping( filepath )
                if filepath:
                    filepath = self.ProcessPath( filepath )
                    
                    if self.LocalRendering:
                        self.NetworkFilePath, postTokens = self.SplitTokens( filepath )
                        self.ValidateFilepath( self.NetworkFilePath )
                        
                        filepath = self.Plugin.CreateTempDirectory( "c4dOutput" )
                        filepath = self.ProcessPath( filepath )
                        
                        self.LocalFilePath = filepath
                        self.ValidateFilepath( self.LocalFilePath )
                        
                        filepath = os.path.join(filepath, postTokens)
                        filepath = self.ProcessPath( filepath )
                        
                        self.Plugin.LogInfo( "Rendering main output to local drive, will copy files and folders to final location after render is complete")
                    else:
                        pathBeforeTokens, _ = self.SplitTokens( filepath )
                        self.ValidateFilepath( pathBeforeTokens )

                        self.Plugin.LogInfo( "Rendering main output to network drive" )
                        
                    fileprefix = ""
                    if self.RegionRendering and self.SingleFrameRegionJob:
                        fileprefix = self.Plugin.GetPluginInfoEntryWithDefault( ( "RegionPrefix%s" % self.SingleFrameRegionIndex ), "" ).strip()
                    else:
                        fileprefix = self.Plugin.GetPluginInfoEntryWithDefault( "FilePrefix", "" ).strip()

                    outputPath = os.path.join( filepath, fileprefix )
                    outputPath = outputPath.replace( "\\", "\\\\" ) # Escape the backslashes in the path
                    deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_PATH]=\"" + outputPath + "\"" )
                
                # Build the multipass output filename from the path and prefix
                multifilepath = self.Plugin.GetPluginInfoEntryWithDefault( "MultiFilePath", "" ).strip()
                multifilepath = RepositoryUtils.CheckPathMapping( multifilepath )
                if multifilepath:
                    multifilepath = self.ProcessPath( multifilepath )

                    if self.LocalRendering:
                        self.NetworkMPFilePath, postTokens = self.SplitTokens( multifilepath )
                        self.ValidateFilepath( self.NetworkMPFilePath )
                        
                        multifilepath = self.Plugin.CreateTempDirectory( "c4dOutputMP" )
                        multifilepath = self.ProcessPath( multifilepath )
                        
                        self.LocalMPFilePath = multifilepath
                        self.ValidateFilepath( self.LocalMPFilePath )
                        
                        multifilepath = os.path.join(multifilepath, postTokens)
                        multifilepath = self.ProcessPath( multifilepath )
                        
                        self.Plugin.LogInfo( "Rendering multipass output to local drive, will copy files and folders to final location after render is complete" )
                    else:
                        pathBeforeTokens, _ = self.SplitTokens( multifilepath )
                        self.ValidateFilepath( pathBeforeTokens )

                        self.Plugin.LogInfo( "Rendering multipass output to network drive" )
                    
                    multifileprefix = ""
                    if self.RegionRendering and self.SingleFrameRegionJob:
                        multifileprefix = self.Plugin.GetPluginInfoEntryWithDefault( ( "MultiFileRegionPrefix%s" % self.SingleFrameRegionIndex ), "" ).strip()
                    else:
                        multifileprefix = self.Plugin.GetPluginInfoEntryWithDefault( "MultiFilePrefix", "" ).strip()
                    
                    outputMultiFilePath = os.path.join( multifilepath, multifileprefix )
                    outputMultiFilePath = outputMultiFilePath.replace( "\\", "\\\\" )
                    
                    deadlineC4DThreadScript.append( "        self.renderData[c4d.RDATA_MULTIPASS_FILENAME]=\"" + outputMultiFilePath + "\"" )
                
                # Build the output filename from the path and prefix for vray 5
                vray5_filepath = self.Plugin.GetPluginInfoEntryWithDefault( "VRay5FilePath", "" ).strip()
                vray5_filepath = RepositoryUtils.CheckPathMapping( vray5_filepath )
                if vray5_filepath:
                    vray5_filepath = self.ProcessPath( vray5_filepath )
                    
                    if self.LocalRendering:
                        self.VRay5NetworkFilePath, postTokens = self.SplitTokens( vray5_filepath )
                        self.ValidateFilepath( self.VRay5NetworkFilePath )
                        
                        vray5_filepath = self.Plugin.CreateTempDirectory( "c4dOutputVray" )
                        vray5_filepath = self.ProcessPath( vray5_filepath )
                        
                        self.VRay5LocalFilePath = vray5_filepath
                        self.ValidateFilepath( self.VRay5LocalFilePath )
                        
                        vray5_filepath = os.path.join(vray5_filepath, postTokens)
                        vray5_filepath = self.ProcessPath( vray5_filepath )
                        
                        self.Plugin.LogInfo( "Rendering V-Ray output to local drive, will copy files and folders to final location after render is complete")
                    else:
                        pathBeforeTokens, _ = self.SplitTokens( vray5_filepath )
                        self.ValidateFilepath( pathBeforeTokens )

                        self.Plugin.LogInfo( "Rendering VRay 5 output to network drive" )
                        
                    fileprefix = ""
                    if self.RegionRendering and self.SingleFrameRegionJob:
                        fileprefix = self.Plugin.GetPluginInfoEntryWithDefault( ( "VRay5RegionPrefix%s" % self.SingleFrameRegionIndex ), "" ).strip()
                    else:
                        fileprefix = self.Plugin.GetPluginInfoEntryWithDefault( "VRay5FilePrefix", "" ).strip()

                    vray5OutputPath = os.path.join( vray5_filepath, fileprefix )
                    vray5OutputPath = vray5OutputPath.replace( "\\", "\\\\" ) # Escape the backslashes in the path
                    deadlineC4DThreadScript.append( "        vray5Settings = self.GetVray5RenderSettings(self.deadlineDoc)")
                    deadlineC4DThreadScript.append( "        if vray5Settings is not None:")
                    deadlineC4DThreadScript.append( "            vray5Settings[c4d.VRAY_VP_OUTPUT_SETTINGS_FILENAME]=\"%s\"" % vray5OutputPath)

                # Start rendering the document and handle the results.
                deadlineC4DThreadScript.append( "        bmp = bitmaps.MultipassBitmap(int(self.renderData[c4d.RDATA_XRES]), int(self.renderData[c4d.RDATA_YRES]), c4d.COLORMODE_RGB)" )
                deadlineC4DThreadScript.append( "        results = documents.RenderDocument(self.deadlineDoc, self.renderData.GetDataInstance(), bmp, c4d.RENDERFLAGS_EXTERNAL | c4d.RENDERFLAGS_SHOWERRORS, self.Get())" )
                deadlineC4DThreadScript.append( "        if results != c4d.RENDERRESULT_OK and results != c4d.RENDERRESULT_USERBREAK:" )
                deadlineC4DThreadScript.append( "            resDict = {" )
                deadlineC4DThreadScript.append( "                c4d.RENDERRESULT_OUTOFMEMORY : 'Not enough memory.'," )
                deadlineC4DThreadScript.append( "                c4d.RENDERRESULT_ASSETMISSING : 'Assets (textures etc.) are missing.'," )
                deadlineC4DThreadScript.append( "                c4d.RENDERRESULT_SAVINGFAILED : 'Failed to save.'," )
                deadlineC4DThreadScript.append( "                c4d.RENDERRESULT_NOMACHINE : 'No Machine.'," )
                deadlineC4DThreadScript.append( "                c4d.RENDERRESULT_PROJECTNOTFOUND : 'Project not found.'," )
                deadlineC4DThreadScript.append( "                c4d.RENDERRESULT_ERRORLOADINGPROJECT : 'Error loading project.'," )
                deadlineC4DThreadScript.append( "                c4d.RENDERRESULT_NOOUTPUTSPECIFIED : 'No output specified.'," )
                deadlineC4DThreadScript.append( "                c4d.RENDERRESULT_GICACHEMISSING : 'GI cache is missing.'" )
                deadlineC4DThreadScript.append( "            }" )
                deadlineC4DThreadScript.append( "            print ( 'RenderDocument failed with return code ' + str(results) + ' meaning: ' + ( resDict[results] if results in resDict else 'Unknown Error.') )" )              
                
                # Overriding the function on c4d.threading.C4DThread that checks if we should stop rendering.
                deadlineC4DThreadScript.append( "    def TestDBreak(self):" )                           
                deadlineC4DThreadScript.append( "        if os.path.exists( r'" + self.CancellationTokenPath + "' ):" )
                deadlineC4DThreadScript.append( "            print ( r'RenderDocument cancelled because the cancel file exists: " + self.CancellationTokenPath + "' )" )
                deadlineC4DThreadScript.append( "            return True" )
                deadlineC4DThreadScript.append( "        return False" )
                
                # Start the thread and block until it's done.
                globalScript.append( "thread = DeadlineC4DThread()" )                     
                globalScript.append( "thread.Start()" )
                globalScript.append( "thread.Wait(True)" )
            else:
                # Common Export Code
                # This needs a newline at the beggining of the script otherwise the first line gets consumed somewhere along the way.
                globalScript.append( "" )
                globalScript.append( "#!/usr/bin/python" )
                globalScript.append( "# -*- coding: utf-16-le -*-" )
                globalScript.append( "import c4d" )
                globalScript.append( "from c4d import documents")
                globalScript.append( "scene = documents.GetActiveDocument()" )

                activeTake = self.Plugin.GetPluginInfoEntryWithDefault( "Take", "" )
                if not activeTake == "" and self.Plugin.version >= 17  :
                    globalScript.append( "from c4d.modules import takesystem" )
                    globalScript.append( "takeData = scene.GetTakeData()" )
                    globalScript.append( "mainTake = takeData.GetMainTake()" )
                    globalScript.append( "take = mainTake.GetDown()" )
                    globalScript.append( "while take is not None:" )
                    globalScript.append( "    if take.GetName() == \"" + activeTake + "\":" )
                    globalScript.append( "        takeData.SetCurrentTake(take)" )
                    globalScript.append( "        break" )
                    globalScript.append( "    take = take.GetNext()" )

                if renderer == "ArnoldExport":
                    self.Plugin.LogInfo( "Exporting to Arnold" )

                    globalScript.append( "ARNOLD_ASS_EXPORT = 1029993" )
                    globalScript.append( "options = c4d.BaseContainer()" )
                    globalScript.append( "options.SetInt32( 6, %s )" % self.Plugin.GetStartFrame() )
                    globalScript.append( "options.SetInt32( 7, %s )" % self.Plugin.GetEndFrame() )

                    assFile = self.ProcessPath( self.Plugin.GetPluginInfoEntryWithDefault( "ExportFile", "" ) )
                    assFile = RepositoryUtils.CheckPathMapping( assFile )
                    assFile = assFile.replace( "\\", "/" ) # Escape the backslashes in the path
                    if assFile != "":
                        self.ValidateFilepath( os.path.dirname( assFile ) )
                        globalScript.append( "options.SetFilename( 0, '%s' )" % assFile )

                    globalScript.append( "scene.GetSettingsInstance( c4d.DOCUMENTSETTINGS_DOCUMENT ).SetContainer( ARNOLD_ASS_EXPORT, options )" )
                    globalScript.append( "c4d.CallCommand( ARNOLD_ASS_EXPORT )" )

                elif renderer == "RedshiftExport":
                    self.Plugin.LogInfo( "Exporting to Redshift" )

                    globalScript.append( "REDSHIFT_EXPORT_PLUGIN_ID = 1038650" )
                    globalScript.append( "plug = c4d.plugins.FindPlugin( REDSHIFT_EXPORT_PLUGIN_ID, c4d.PLUGINTYPE_SCENESAVER )" )
                    globalScript.append( "op = {}" )
                    globalScript.append( "plug.Message( c4d.MSG_RETRIEVEPRIVATEDATA, op )" )
                    globalScript.append( "imexporter = op[ \"imexporter\" ]" )
                    globalScript.append( "imexporter[ c4d.REDSHIFT_PROXYEXPORT_AUTOPROXY_CREATE ] = False" )
                    globalScript.append( "imexporter[ c4d.REDSHIFT_PROXYEXPORT_ANIMATION_RANGE ] = c4d.REDSHIFT_PROXYEXPORT_ANIMATION_RANGE_MANUAL" )
                    globalScript.append( "imexporter[ c4d.REDSHIFT_PROXYEXPORT_ANIMATION_FRAME_START ] = %s" % self.Plugin.GetStartFrame() )
                    globalScript.append( "imexporter[ c4d.REDSHIFT_PROXYEXPORT_ANIMATION_FRAME_END ] = %s" % self.Plugin.GetEndFrame() )
                    globalScript.append( "imexporter[ c4d.REDSHIFT_PROXYEXPORT_ANIMATION_FRAME_STEP ] = 1" )

                    rsFile = self.ProcessPath( self.Plugin.GetPluginInfoEntryWithDefault( "ExportFile", "" ) )
                    rsFile = RepositoryUtils.CheckPathMapping( rsFile )
                    rsFile = rsFile.replace( "\\", "/" ) # Escape the backslashes in the path
                    rsFile = rsFile.replace("#","") # Redshift automatically adds the frame numbers.
                    if rsFile != "":
                        self.ValidateFilepath( os.path.dirname( rsFile ) )
                        globalScript.append( "documents.SaveDocument(scene, \"%s\", c4d.SAVEDOCUMENTFLAGS_0, REDSHIFT_EXPORT_PLUGIN_ID)" % rsFile )
                        globalScript.append( "print ( 'Exported: %s' )" % rsFile )
                    else:
                        self.Plugin.FailRender( "Failed to export Redshift Scene - No output file name set." )
            
             # This can make the logs look a bit messy, and can sometimes be misleading when an error occurs.
            full_script_contents = '\n'.join(deadlineC4DThreadScript + globalScript).replace( "\r", "" )
            if self.Plugin.GetBooleanConfigEntryWithDefault( "WriteScriptToLog", False ):
                self.Plugin.LogInfo( "Script contents:" )
                self.Plugin.LogInfo( full_script_contents )

            self.ScriptFilename = os.path.join( self.renderTempDirectory, "c4d_Batch_Script.py" )
            
            File.WriteAllText( self.ScriptFilename, full_script_contents, Encoding.UTF8 )
            self.Plugin.LogInfo( "" )
            if SystemUtils.IsRunningOnMac():
                os.chmod( self.ScriptFilename, os.stat( Path.GetTempFileName() ).st_mode )
        
        self.Cinema4DSocket.Send( "RunScript:" + self.ScriptFilename )
        self.Plugin.LogInfo( self.PollUntilComplete( False ) )
        self.Plugin.FlushMonitoredManagedProcessStdout( self.ProgramName )

        if self.LocalRendering:
            if self.NetworkFilePath != "":
                self.Plugin.LogInfo( "Moving main output files and folders from " + self.LocalFilePath + " to " + self.NetworkFilePath )
                self.Plugin.VerifyAndMoveDirectory( self.LocalFilePath, self.NetworkFilePath, False, -1 )
            if self.NetworkMPFilePath != "":
                self.Plugin.LogInfo( "Moving multipass output files and folders from " + self.LocalMPFilePath + " to " + self.NetworkMPFilePath )
                self.Plugin.VerifyAndMoveDirectory( self.LocalMPFilePath, self.NetworkMPFilePath, False, -1 )
            if self.VRay5NetworkFilePath != "":
                self.Plugin.LogInfo( "Moving VRay 5 output files and folders from " + self.VRay5LocalFilePath + " to " + self.VRay5NetworkFilePath )
                self.Plugin.VerifyAndMoveDirectory( self.VRay5LocalFilePath, self.VRay5NetworkFilePath, False, -1 )

        self.Plugin.LogInfo( "Finished Cinema 4D Task" )

    def SplitTokens( self, filePath ):
        if not "$" in filePath:
            return filePath, ""
            
        preTokenPath = ""
        postTokenPath = ""
        
        tokenIndex = -1
        tokenParts = filePath.replace("\\","/").split("/")
        for i, pathPart in enumerate(tokenParts):
            if "$" in pathPart:
                tokenIndex = i
                break
        
        preTokenPath = "/".join( tokenParts[:tokenIndex] )
        postTokenPath = "/".join( tokenParts[tokenIndex:] )
        
        return preTokenPath, postTokenPath

    def ValidateFilepath( self, directory ):
        self.Plugin.LogInfo( "Validating the path: '%s'" % directory )

        if not os.path.exists( directory ):
            try:
                os.makedirs( directory )
            except:
                self.Plugin.FailRender( "Failed to create path: '%s'" % directory )

        # Test to see if we have permission to create a file
        try:
            # TemporaryFile deletes the "file" when it closes, we only care that it can be created
            with tempfile.TemporaryFile( dir=directory ) as tempFile:
                pass
        except:
            self.Plugin.FailRender( "Failed to create test file in directory: '%s'" % directory )

    # This tells Cinema4D to unload the current scene file.
    def EndCinema4DJob( self ):
        if not self.Plugin.MonitoredManagedProcessIsRunning( self.ProgramName ):
            self.Plugin.LogWarning( "Cinema 4D.exe was shut down before the proper shut down sequence" )
        else:
            response = ""
            
            # This creates a temporary file which will trigger C4D to cancel the current render
            self.Plugin.LogInfo( "Writing the cancel file to tell C4D to cancel the current render: " + self.CancellationTokenPath )
            open(self.CancellationTokenPath, 'a').close()
            
            # If an error occurs while sending EndJob, set the response so that we don't enter the while loop below.
            try:
                self.Plugin.LogInfo("Sending End Job")
                self.Cinema4DSocket.Send( "EndJob" )
            except Exception as e:
                response = ( "ERROR: Error sending EndJob command: %s" % e.Message )
            
            countdown = 5000
            while countdown > 0 and not response:
                try:
                    countdown = countdown - 100
                    response = self.Cinema4DSocket.Receive( 100 )
                    
                    # If this is a STDOUT message, print it out and reset 'response' so that we keep looping
                    match = self.StdoutRegex.Match( response )
                    if match.Success:
                        self.Plugin.LogInfo( match.Groups[ 1 ].Value )
                        response = ""
                    
                    # If this is a WARN message, print it out and reset 'response' so that we keep looping
                    match = self.WarnRegex.Match( response )
                    if match.Success:
                        self.Plugin.LogWarning( match.Groups[ 1 ].Value )
                        response = ""
                    
                except Exception as e:
                    if not isinstance( e, SimpleSocketTimeoutException ):
                        response = ( "ERROR: Error when waiting for renderer to close: %s" % e.Message )
            
            if not response:
                self.Plugin.LogWarning( "Timed out waiting for the renderer to close." )
            else:
                self.Plugin.LogInfo( "The process took " + str( 5000 - countdown ) + "ms to respond." )
                
            if response.startswith( "ERROR: " ):
                self.Plugin.LogWarning( response[7:] )
            
            if not response.startswith( "SUCCESS" ):
                self.Plugin.LogWarning( "Did not receive a success message in response to EndJob: %s" % response )
 
        timeout = 10000
        while self.Plugin.MonitoredManagedProcessIsRunning( self.ProgramName ) and timeout > 0:
            # Sleep for 100ms while waiting for the process to end.
            time.sleep(.1)
            timeout = timeout - 100
            
        # If we waited 10 seconds and the process still hasn't closed then lets forcebly terminate it, this is to prevent Jobs hanging around forever.
        if self.Plugin.MonitoredManagedProcessIsRunning( self.ProgramName ):
            self.Plugin.LogWarning("Timed out waiting for the process to end, forcebly terminating.")
            self.Plugin.ShutdownMonitoredManagedProcess( self.ProgramName )
        else:
            self.Plugin.LogInfo( "The process took " + str( 10000 - timeout ) + "ms to exit." )
            
        self.Plugin.FlushMonitoredManagedProcessStdout( self.ProgramName )
        
    def PollUntilComplete( self, timeoutEnabled, timeoutOverride=-1 ):
        progressCountdown = (self.ProgressUpdateTimeout if timeoutOverride < 0 else timeoutOverride) * 1000
        
        while progressCountdown > 0 and self.Cinema4DSocket.IsConnected and not self.Plugin.IsCanceled():
            try:
                # Verify that Cinema 4D is still running.
                self.Plugin.VerifyMonitoredManagedProcess( self.ProgramName )
                self.Plugin.FlushMonitoredManagedProcessStdout( self.ProgramName )
                
                # Check for any popup dialogs.
                blockingDialogMessage = self.Plugin.CheckForMonitoredManagedProcessPopups( self.ProgramName )
                if blockingDialogMessage:
                    self.Plugin.FailRender( blockingDialogMessage )
                
                # Only decrement the timeout value if timeouts are enabled
                if timeoutEnabled:
                    progressCountdown = progressCountdown - 500
                
                start = DateTime.Now.Ticks
                while TimeSpan.FromTicks( DateTime.Now.Ticks - start ).Milliseconds < 500:
                    request = self.Cinema4DSocket.Receive( 500 )
                    
                    # We received a request, so reset the progress update timeout.
                    progressCountdown = (self.ProgressUpdateTimeout if timeoutOverride < 0 else timeoutOverride) * 1000
                                        
                    match = self.SuccessMessageRegex.Match( request )
                    if match.Success: # Render finished successfully
                        return match.Groups[ 1 ].Value
                    
                    if self.SuccessNoMessageRegex.IsMatch( request ): # Render finished successfully
                        return ""
                    
                    if self.CanceledRegex.IsMatch( request ): # Render was canceled
                        self.Plugin.FailRender( "Render was canceled" )
                        continue
                    
                    match = self.ErrorRegex.Match( request )
                    if match.Success: # There was an error
                        self.Plugin.FailRender( "%s" % match.Groups[ 1 ].Value )
                        continue
                    
            except Exception as e:
                if isinstance( e, SimpleSocketTimeoutException ):
                    if progressCountdown <= 0:
                        if timeoutOverride < 0:
                            self.Plugin.FailRender( "Timed out waiting for the next progress update. The ProgressUpdateTimeout setting can be modified in the Cinema4D Batch plugin configuration." )
                        else:
                            self.Plugin.FailRender( "Timed out waiting for the next progress update." )
                elif isinstance( e, SimpleSocketException ):
                    self.Plugin.FailRender( "RenderTask: Cinema4D may have crashed (%s)" % e.Message )
                else:
                    self.Plugin.FailRender( "RenderTask: Unexpected exception (%s)" % e.Message )
        
        if self.Plugin.IsCanceled():
            self.Plugin.FailRender( "Render was canceled" )
        
        if not self.Cinema4DSocket.IsConnected:
            self.Plugin.FailRender( "Socket disconnected unexpectedly" )
        
        return "undefined"
        
    def LaunchCinema4D( self, executable, arguments, startupDir ):
        self.ManagedCinema4DProcessRenderExecutable = executable
        self.ManagedCinema4DProcessRenderArgument = arguments
        self.ManagedCinema4DProcessStartupDirectory = startupDir
        
        self.Cinema4DProcess = Cinema4DProcess(self)
        self.Plugin.StartMonitoredManagedProcess( self.ProgramName, self.Cinema4DProcess )
        self.Plugin.VerifyMonitoredManagedProcess( self.ProgramName )
    
    def WaitForConnection( self, errorMessageOperation ):
        startTime = DateTime.Now
        receivedToken = ""

        while  DateTime.Now.Subtract( startTime ).TotalSeconds < self.LoadCinema4DTimeout:
            # If the task has been cancelled then exit.
            if self.Plugin.IsCanceled():
                self.Plugin.FailRender( "%s: Initialization was canceled by Deadline" % errorMessageOperation )
            # Confirm that the process is running and fail if it isn't
            try:
                self.Plugin.VerifyMonitoredManagedProcess( self.ProgramName )
            except Exception as e:
                if os.path.isfile(self.importTestFile):
                    with open( self.importTestFile, "r" ) as importFileHandle:
                        failedImports = [line.strip() for line in importFileHandle]
                    self.Plugin.FailRender( "Failed to import the following modules: %s\nPlease ensure that your environment is set correctly or that you are allowing Deadline to set the render environment." % ", ".join(failedImports) )
                raise e
            
            # Check if there is a blocking popup and fail if one exists
            blockingDialogMessage = self.Plugin.CheckForMonitoredManagedProcessPopups( self.ProgramName )
            if blockingDialogMessage:
                self.Plugin.FailRender( blockingDialogMessage )
            
            self.Plugin.FlushMonitoredManagedProcessStdout( self.ProgramName )
            try:
                self.Cinema4DSocket.WaitForConnection( 500, True )
            except SimpleSocketTimeoutException:
                continue
            break
        else:
            self.Plugin.FailRender( "%s: Timed out waiting for Cinema4D to start - consider increasing the LoadCinema4DTimeout in the Cinema4D plugin configuration" % (errorMessageOperation) )

        receivedToken = self.Cinema4DSocket.Receive( 3000 )
        if receivedToken.startswith( "TOKEN:" ):
            receivedToken = receivedToken[6:]
        else:
            self.Plugin.LogInfo("Disconnecting: "+receivedToken)
            self.Cinema4DSocket.Disconnect( False )
        self.Plugin.LogInfo("Received Token: "+receivedToken)

        if receivedToken != self.AuthenticationToken:
            self.Plugin.FailRender( "%s: Did not receive expected token from Cinema4d (got \"%s\") - an unexpected error may have occurred during initialization" % (errorMessageOperation, receivedToken) )
    
######################################################################
## This is the class that starts up the Cinema4D process.
######################################################################
class Cinema4DProcess( ManagedProcess ):
    
    Cinema4DController = None
    
    def __init__( self, cinema4DController ):
        if sys.version_info.major == 3:
            super().__init__()
        self.Cinema4DController = cinema4DController
        self.InitializeProcessCallback += self.InitializeProcess
        self.RenderExecutableCallback += self.RenderExecutable
        self.RenderArgumentCallback += self.RenderArgument
        self.StartupDirectoryCallback += self.StartupDirectory
    
    def Cleanup( self ):
        for stdoutHandler in self.StdoutHandlers:
            del stdoutHandler.HandleCallback
        
        del self.InitializeProcessCallback
        del self.RenderExecutableCallback
        del self.RenderArgumentCallback
        del self.StartupDirectoryCallback
    
    def InitializeProcess( self ):
        self.ProcessPriority = ProcessPriorityClass.BelowNormal
        self.UseProcessTree = True
        self.SingleFramesOnly = False
        self.StdoutHandling = True
        self.PopupHandling = True
        
        self.FinishedFrameCount = 0
        self.CheckProgress = False
        self.CurrentRenderPhase = ""
        self.currFrame = None
        self.prevFrame = self.Cinema4DController.Plugin.GetStartFrame()
        
        #self.AddStdoutHandlerCallback("Error:.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Document not found.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Project not found.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Error rendering project.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Error loading project.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Error rendering document.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Error loading document.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Rendering failed.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Asset missing.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Asset Error.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Invalid License.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*License Check error.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Files cannot be written.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*Enter Registration Data.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*The output resolution is too high for the selected render engine.*").HandleCallback += self.HandleOutputResolutionError
        self.AddStdoutHandlerCallback(".*Unable to write file.*").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(".*RenderDocument failed with return code.*").HandleCallback += self.HandleStdoutError

        self.AddStdoutHandlerCallback(".*Warning: Unknown arguments: -DeadlineConnect.*").HandleCallback += self.HandlePluginEnvironment
        
        self.AddStdoutHandlerCallback(".*Rendering frame ([0-9]+) at.*").HandleCallback +=  self.HandleStdoutProgress
        self.AddStdoutHandlerCallback(".*Rendering Phase: Setup.*").HandleCallback +=  self.HandleSetupProgress
        self.AddStdoutHandlerCallback(".*Rendering Phase: Main Render.*").HandleCallback +=  self.HandleProgressCheck
        self.AddStdoutHandlerCallback(".*Progress: (\d+)%.*").HandleCallback += self.HandleTaskProgress 
        self.AddStdoutHandlerCallback(".*Rendering successful.*").HandleCallback +=  self.HandleProgress2
        self.AddStdoutHandlerCallback(".*Rendering Phase: Finalize.*").HandleCallback +=  self.HandleFrameProgress

        # Redshift progress handling
        self.AddStdoutHandlerCallback(r"Frame rendering aborted.").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(r"Rendering was internally aborted").HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(r'Cannot find procedure "rsPreference"').HandleCallback += self.HandleStdoutError
        self.AddStdoutHandlerCallback(
            r"Rendering frame \d+ \((\d+)/(\d+)\)").HandleCallback += self.HandleRedshiftNewFrameProgress
        self.AddStdoutHandlerCallback(
            r"Block (\d+)/(\d+) .+ rendered").HandleCallback += self.HandleRedshiftBlockRendered

        self.AddStdoutHandlerCallback( ".*ImportError: No module named site.*" ).HandleCallback += self.HandleNoSite
        self.AddStdoutHandlerCallback( ".*code for hash .* was not found." ).HandleCallback += self.HandleHashNotFound

        # Handle QuickTime popup dialog
        # "QuickTime does not support the current Display Setting.  Please change it and restart this application."
        self.AddPopupHandler( "Unsupported Display", "OK" )
        self.AddPopupHandler( "Nicht.*", "OK" )

        self.AddPopupHandler( ".*Render history settings.*", "OK" )

    def RenderExecutable( self ):
        return self.Cinema4DController.ManagedCinema4DProcessRenderExecutable
    
    def RenderArgument( self ):
        return self.Cinema4DController.ManagedCinema4DProcessRenderArgument
    
    def StartupDirectory( self ):
        return self.Cinema4DController.ManagedCinema4DProcessStartupDirectory

    def HandleNoSite( self ):
        self.Cinema4DController.Plugin.FailRender( "Failed to import the following modules: site\nPlease ensure that your environment is set correctly or that you are allowing Deadline to set the render environment.\nPlease go to the C4D FAQ in the Deadline documentation for more information." )

    def HandleHashNotFound( self ):
        self.Cinema4DController.Plugin.LogInfo( "OpenSSL has not been set up to work properly with C4D Batch, this is a non-blocking issue.\nPlease go to the C4D FAQ in the Deadline documentation for more information." )

    def HandleStdoutProgress( self ):
        startFrame = self.Cinema4DController.Plugin.GetStartFrame()
        endFrame = self.Cinema4DController.Plugin.GetEndFrame()

        currFrame = int( self.GetRegexMatch(1) )
        frameCount = abs( endFrame - startFrame ) + 1
        progress = 100 * ( currFrame - startFrame ) // frameCount

        self.Cinema4DController.Plugin.SetProgress( progress )
        self.Cinema4DController.Plugin.SetStatusMessage( self.GetRegexMatch(0) )
        
    def HandleProgress2( self ):
        self.SetProgress( 100 )
        self.SetStatusMessage( self.GetRegexMatch(0) )

    def HandleOutputResolutionError( self ):
        errorMsg = self.GetRegexMatch( 0 )
        if not self.Cinema4DController.loadOpenGL:
            errorMsg = "This job was configured to not load OpenGL. If you are using the Hardware OpenGL renderer, resubmit without the \"Don't Load OpenGL\" option checked. "
        self.Cinema4DController.Plugin.FailRender( errorMsg )

    def HandleStdoutError( self ):
        self.Cinema4DController.Plugin.FailRender(self.GetRegexMatch(0))

    def HandlePluginEnvironment( self ):
        self.Cinema4DController.Plugin.FailRender( self.GetRegexMatch(0) + "\nC4D was unable to locate DeadlineConnect.pyp. This is a known issue in R18 and R19 for Cinema4DBatch, please go to the C4D FAQ in the Deadline documentation for a workaround." )
        
    def HandleSetupProgress( self ):
        #If frame number is given update the Render status with the current frame
        if self.currFrame is not None:
            self.CurrentRenderPhase = "Frame: "+str(self.currFrame)+",  Rendering Phase: Setup"
        else:
            self.CurrentRenderPhase = "Rendering Phase: Setup"

    def HandleProgressCheck( self ):
        self.CheckProgress = True

        #If frame number is given update the Render status with the current frame
        if self.currFrame != None:
            self.CurrentRenderPhase = "Frame: "+str(self.currFrame)+",  Rendering Phase: Main Render"
        else:
            self.CurrentRenderPhase = "Rendering Phase: Main Render"
            
    def HandleTaskProgress( self ):
        startFrame = self.Cinema4DController.Plugin.GetStartFrame()
        endFrame = self.Cinema4DController.Plugin.GetEndFrame()
        frameCount = abs( endFrame - startFrame ) + 1

        # Sometimes progress is reported as over 100%. We don't know why, but we're handling it here.
        subProgress = 1
        if float(self.GetRegexMatch(1)) <= 100:
            subProgress = float(self.GetRegexMatch(1))/100
        
        if self.currFrame is not None and self.CheckProgress:
            if self.prevFrame + subProgress < self.currFrame:
                self.prevFrame = self.currFrame
                progress = 100 * ( self.currFrame - startFrame ) // frameCount
                self.Cinema4DController.Plugin.SetProgress( progress )
            else:
                progress = int( 100 * float( self.currFrame + subProgress - startFrame ) / float( frameCount ) )
                self.Cinema4DController.Plugin.SetProgress( progress )
        
        #Update the 'Task Render Status' with the progress of each Render Phase
        self.Cinema4DController.Plugin.SetStatusMessage( str(self.CurrentRenderPhase)+" - Progress: "+str(self.GetRegexMatch(1))+"%" )
        
    def HandleFrameProgress( self ):
        self.FinishedFrameCount += 1
        self.CheckProgress = False

        #If frame number is given update the Render status with the current frame
        if self.currFrame is not None:
            self.CurrentRenderPhase = "Frame: "+str(self.currFrame)+",  Rendering Phase: Finalize"
        else:
            self.CurrentRenderPhase = "Rendering Phase: Finalize"
        
        startFrame = self.Cinema4DController.Plugin.GetStartFrame()
        endFrame = self.Cinema4DController.Plugin.GetEndFrame()
        frameCount = abs( endFrame - startFrame ) + 1
        progress = 100 * self.FinishedFrameCount / frameCount

        self.Cinema4DController.Plugin.SetProgress( progress )
        self.Cinema4DController.Plugin.LogInfo( "Task Overall Progress: " + str(progress)+"%")

    def HandleRedshiftNewFrameProgress(self):
        self.FinishedFrameCount = float(self.GetRegexMatch(1)) - 1
        startFrame = self.Cinema4DController.Plugin.GetStartFrame()
        endFrame = self.Cinema4DController.Plugin.GetEndFrame()
        frameCount = abs( endFrame - startFrame ) + 1

        progress = 100 * self.FinishedFrameCount / frameCount
        self.Cinema4DController.Plugin.SetProgress( progress )

    def HandleRedshiftBlockRendered(self):
        startFrame = self.Cinema4DController.Plugin.GetStartFrame()
        endFrame = self.Cinema4DController.Plugin.GetEndFrame()
        frameCount = abs( endFrame - startFrame ) + 1

        completedBlockNumber = float(self.GetRegexMatch(1))
        totalBlockCount = float(self.GetRegexMatch(2))
        finishedFrames = completedBlockNumber / totalBlockCount
        finishedFrames = finishedFrames + self.FinishedFrameCount

        progress = 100 * finishedFrames / frameCount
        self.Cinema4DController.Plugin.SetProgress( progress )