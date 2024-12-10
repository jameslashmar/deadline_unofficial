from __future__ import absolute_import
import re
import imp  # For Integration UI
import os
from typing import Any

from System import *
from System.Collections.Specialized import StringCollection
from System.IO import Path, StreamWriter, File, Directory
from System.Text import Encoding

from Deadline.Scripting import RepositoryUtils, ClientUtils, FrameUtils, PathUtils, StringUtils

from DeadlineUI.Controls.Scripting.DeadlineScriptDialog import DeadlineScriptDialog
from ThinkboxUI.Controls.Scripting.RangeControl import RangeControl
from ThinkboxUI.Controls.Scripting.ButtonControl import ButtonControl
imp.load_source( 'IntegrationUI', RepositoryUtils.GetRepositoryFilePath( "submission/Integration/Main/IntegrationUI.py", True ) )
import IntegrationUI

########################################################################
## Globals
########################################################################
scriptDialog = None  # type: DeadlineScriptDialog
settings = None
integration_dialog = None

ProjectManagementOptions = ["Shotgun","FTrack","NIM"]
DraftRequested = False

SUPPORTED_VERSIONS = ["12", "13", "14", "15", "16", "17", "18", "19", "20", "21", "22", "23", "24", "25", "26", "2023", "2024", "2025"]

########################################################################
## Main Function Called By Deadline
########################################################################
def __main__():
    # type: () -> None
    global scriptDialog
    global settings
    global ProjectManagementOptions
    global DraftRequested
    global integration_dialog
    
    scriptDialog = DeadlineScriptDialog()
    scriptDialog.SetTitle( "Submit Cinema 4D Job To Deadline" )
    scriptDialog.SetIcon( scriptDialog.GetIcon( 'Cinema4D' ) )
    
    scriptDialog.AddTabControl("Tabs", 0, 0)
    
    scriptDialog.AddTabPage("Job Options")
    scriptDialog.AddGrid()
    scriptDialog.AddControlToGrid( "Separator1", "SeparatorControl", "Job Description", 0, 0, colSpan=2 )

    scriptDialog.AddControlToGrid( "NameLabel", "LabelControl", "Job Name", 1, 0, "The name of your job. This is optional, and if left blank, it will default to 'Untitled'.", False )
    scriptDialog.AddControlToGrid( "NameBox", "TextControl", "Untitled", 1, 1 )

    scriptDialog.AddControlToGrid( "CommentLabel", "LabelControl", "Comment", 2, 0, "A simple description of your job. This is optional and can be left blank.", False )
    scriptDialog.AddControlToGrid( "CommentBox", "TextControl", "", 2, 1 )

    scriptDialog.AddControlToGrid( "DepartmentLabel", "LabelControl", "Department", 3, 0, "The department you belong to. This is optional and can be left blank.", False )
    scriptDialog.AddControlToGrid( "DepartmentBox", "TextControl", "", 3, 1 )
    scriptDialog.EndGrid()

    scriptDialog.AddGrid()
    scriptDialog.AddControlToGrid( "Separator2", "SeparatorControl", "Job Options", 0, 0, colSpan=3 )

    scriptDialog.AddControlToGrid( "PoolLabel", "LabelControl", "Pool", 1, 0, "The pool that your job will be submitted to.", False )
    scriptDialog.AddControlToGrid( "PoolBox", "PoolComboControl", "none", 1, 1 )

    scriptDialog.AddControlToGrid( "SecondaryPoolLabel", "LabelControl", "Secondary Pool", 2, 0, "The secondary pool lets you specify a Pool to use if the primary Pool does not have any available Workers.", False )
    scriptDialog.AddControlToGrid( "SecondaryPoolBox", "SecondaryPoolComboControl", "", 2, 1 )

    scriptDialog.AddControlToGrid( "GroupLabel", "LabelControl", "Group", 3, 0, "The group that your job will be submitted to.", False )
    scriptDialog.AddControlToGrid( "GroupBox", "GroupComboControl", "none", 3, 1 )

    scriptDialog.AddControlToGrid( "PriorityLabel", "LabelControl", "Priority", 4, 0, "A job can have a numeric priority ranging from 0 to 100, where 0 is the lowest priority and 100 is the highest priority.", False )
    scriptDialog.AddRangeControlToGrid( "PriorityBox", "RangeControl", RepositoryUtils.GetMaximumPriority() // 2, 0, RepositoryUtils.GetMaximumPriority(), 0, 1, 4, 1 )

    scriptDialog.AddControlToGrid( "TaskTimeoutLabel", "LabelControl", "Task Timeout", 5, 0, "The number of minutes a Worker has to render a task for this job before it requeues it. Specify 0 for no limit.", False )
    scriptDialog.AddRangeControlToGrid( "TaskTimeoutBox", "RangeControl", 0, 0, 1000000, 0, 1, 5, 1 )
    scriptDialog.AddSelectionControlToGrid( "AutoTimeoutBox", "CheckBoxControl", False, "Enable Auto Task Timeout", 5, 2, "If the Auto Task Timeout is properly configured in the Repository Options, then enabling this will allow a task timeout to be automatically calculated based on the render times of previous frames for the job. " )

    scriptDialog.AddControlToGrid( "ConcurrentTasksLabel", "LabelControl", "Concurrent Tasks", 6, 0, "The number of tasks that can render concurrently on a single Worker. This is useful if the rendering application only uses one thread to render and your Workers have multiple CPUs.", False )
    scriptDialog.AddRangeControlToGrid( "ConcurrentTasksBox", "RangeControl", 1, 1, 16, 0, 1, 6, 1 )
    scriptDialog.AddSelectionControlToGrid( "LimitConcurrentTasksBox", "CheckBoxControl", True, "Limit Tasks To Worker's Task Limit", 6, 2, "If you limit the tasks to a Worker's task limit, then by default, the Worker won't dequeue more tasks then it has CPUs. This task limit can be overridden for individual Workers by an administrator." )

    scriptDialog.AddControlToGrid( "MachineLimitLabel", "LabelControl", "Machine Limit", 7, 0, "Use the Machine Limit to specify the maximum number of machines that can render your job at one time. Specify 0 for no limit.", False )
    scriptDialog.AddRangeControlToGrid( "MachineLimitBox", "RangeControl", 0, 0, 1000000, 0, 1, 7, 1 )
    scriptDialog.AddSelectionControlToGrid( "IsBlacklistBox", "CheckBoxControl", False, "Machine List Is A Deny List", 7, 2, "You can force the job to render on specific machines by using an allow list, or you can avoid specific machines by using a deny list." )

    scriptDialog.AddControlToGrid( "MachineListLabel", "LabelControl", "Machine List", 8, 0, "The list of machines on the deny list or allow list.", False )
    scriptDialog.AddControlToGrid( "MachineListBox", "MachineListControl", "", 8, 1, colSpan=2 )

    scriptDialog.AddControlToGrid( "LimitGroupLabel", "LabelControl", "Limits", 9, 0, "The Limits that your job requires.", False )
    scriptDialog.AddControlToGrid( "LimitGroupBox", "LimitGroupControl", "", 9, 1, colSpan=2 )

    scriptDialog.AddControlToGrid( "DependencyLabel", "LabelControl", "Dependencies", 10, 0, "Specify existing jobs that this job will be dependent on. This job will not start until the specified dependencies finish rendering.", False )
    scriptDialog.AddControlToGrid( "DependencyBox", "DependencyControl", "", 10, 1, colSpan=2 )

    scriptDialog.AddControlToGrid( "OnJobCompleteLabel", "LabelControl", "On Job Complete", 11, 0, "If desired, you can automatically archive or delete the job when it completes.", False )
    scriptDialog.AddControlToGrid( "OnJobCompleteBox", "OnJobCompleteControl", "Nothing", 11, 1 )
    scriptDialog.AddSelectionControlToGrid( "SubmitSuspendedBox", "CheckBoxControl", False, "Submit Job As Suspended", 11, 2, "If enabled, the job will submit in the suspended state. This is useful if you don't want the job to start rendering right away. Just resume it from the Monitor when you want it to render." )
    scriptDialog.EndGrid()
    
    scriptDialog.AddGrid()
    scriptDialog.AddControlToGrid( "Separator3", "SeparatorControl", "Cinema 4D Options", 0, 0, colSpan=4 )

    scriptDialog.AddControlToGrid( "SceneLabel", "LabelControl", "Cinema 4D File", 1, 0, "The scene file to be rendered.", False )
    scriptDialog.AddSelectionControlToGrid( "SceneBox", "MultiFileBrowserControl", "", "Cinema 4D Files (*.c4d)", 1, 1, colSpan=3 )
    
    scriptDialog.AddControlToGrid( "TakeLabel", "LabelControl", "Take Name", 2, 0, "The name of the take to render. This is optional, and if left blank, it will default to the current take.", False )
    scriptDialog.AddControlToGrid( "TakeBox", "TextControl", "", 2, 1 )
    scriptDialog.AddControlToGrid("ThreadsLabel","LabelControl","Threads", 2, 2, "The number of threads to use for rendering.", False )
    scriptDialog.AddRangeControlToGrid("ThreadsBox","RangeControl",0,0,16,0,1, 2, 3 )
    
    scriptDialog.AddControlToGrid( "FramesLabel", "LabelControl", "Frame List", 3, 0, "The list of frames to render.", False )
    scriptDialog.AddControlToGrid( "FramesBox", "TextControl", "", 3, 1 )
    scriptDialog.AddControlToGrid( "ChunkSizeLabel", "LabelControl", "Frames Per Task", 3, 2, "This is the number of frames that will be rendered at a time for each job task. ", False )
    scriptDialog.AddRangeControlToGrid( "ChunkSizeBox", "RangeControl", 1, 1, 1000000, 0, 1, 3, 3 )
    
    scriptDialog.AddControlToGrid("VersionLabel","LabelControl","Version", 4, 0, "The version of Cinema 4D to render with.", False )
    versionBox = scriptDialog.AddComboControlToGrid("VersionBox", "ComboControl", SUPPORTED_VERSIONS[-1], SUPPORTED_VERSIONS, 4, 1)
    versionBox.ValueModified.connect(VersionBoxChanged)
    scriptDialog.AddSelectionControlToGrid( "UseBatchPluginBox", "CheckBoxControl", True, "Use Batch Plugin", 4, 2, "If checked, the Cinema 4D batch plugin will be used to render Cinema 4D jobs, which keeps the scene file loaded in memory between tasks.", colSpan=1 )
    scriptDialog.AddSelectionControlToGrid( "NoOpenGLBox", "CheckBoxControl", False, "Don't Load OpenGL", 4, 3, "If you are not using the Hardware OpenGL renderer, checking this option reduces the Cinema 4D startup time.", colSpan=1 )

    scriptDialog.AddControlToGrid("BuildLabel","LabelControl","Build To Force", 5, 0, "You can force 32 or 64 bit rendering with this option.", False )
    scriptDialog.AddComboControlToGrid("BuildBox","ComboControl","None",("None","32bit","64bit"), 5, 1 )
    scriptDialog.AddSelectionControlToGrid("SubmitSceneBox","CheckBoxControl",False,"Submit Cinema 4D Scene", 5, 2, "If this option is enabled, the scene file will be submitted with the job, and then copied locally to the Worker machine during rendering.", colSpan=2)
    
    scriptDialog.EndGrid()
    scriptDialog.EndTabPage()
    
    scriptDialog.AddTabPage("Advanced Options")
    scriptDialog.AddGrid()
    scriptDialog.AddControlToGrid( "Separator4", "SeparatorControl", "Cinema 4D Output Options", 0, 0, colSpan=5 )

    useDefaultBox = scriptDialog.AddSelectionControlToGrid("UseDefaultOutputBox","CheckBoxControl",True,"Use Default Output From Scene", 1, 0, "Enable this option to use the output path defined in the scene file.", False, colSpan=2)
    useDefaultBox.ValueModified.connect(UseDefaultOutputChanged)

    scriptDialog.AddControlToGrid("OutputPrefixLabel","LabelControl","Filename Prefix", 1, 2, "If overriding the output, this is the file name prefix.", False)
    scriptDialog.AddControlToGrid("OutputPrefixBox","TextControl","", 1, 3, colSpan=2)

    scriptDialog.AddControlToGrid("OutputFolderLabel","LabelControl","Output Folder", 2, 0, "If overriding the output, this is the folder that the frames will be saved to.", False)
    scriptDialog.AddSelectionControlToGrid("OutputFolderBox","FolderBrowserControl","","", 2, 1, colSpan=4)

    useDefaultMPBox = scriptDialog.AddSelectionControlToGrid("UseDefaultMPOutputBox","CheckBoxControl",True,"Use Default Multipass Output From Scene", 4, 0, "Enable this option to use the multipass output path defined in the scene file.", False, colSpan=2)
    useDefaultMPBox.ValueModified.connect(UseDefaultMPOutputChanged)

    scriptDialog.AddControlToGrid("OutputMPPrefixLabel","LabelControl","MP Filename Prefix", 4, 2, "If overriding the multipass output, this is the file name prefix.", False)
    scriptDialog.AddControlToGrid("OutputMPPrefixBox","TextControl","", 4, 3, colSpan=2)

    scriptDialog.AddControlToGrid("OutputMPFolderLabel","LabelControl","MP Output Folder", 5, 0, "If overriding the multipass output, this is the folder that the frames will be saved to.", False)
    scriptDialog.AddSelectionControlToGrid("OutputMPFolderBox","FolderBrowserControl","","", 5, 1, colSpan=4)

    scriptDialog.AddSelectionControlToGrid( "LocalRenderingBox", "CheckBoxControl", False, "Enable Local Rendering", 6, 0, "If enabled, the frames will be rendered locally, and then copied to their final network location.", False )
    scriptDialog.EndGrid()
    
    scriptDialog.AddGrid()
    scriptDialog.AddControlToGrid( "Separator7", "SeparatorControl", "Script Job Options", 7, 0, colSpan=4 )
    scriptDialog.AddControlToGrid( "ScriptJobLabel1", "LabelControl", "Script Jobs use the Cinema 4D Batch plugin, and do not force a particular render.", 8, 0, colSpan=2 )
    scriptJobBox = scriptDialog.AddSelectionControlToGrid( "ScriptJobBox", "CheckBoxControl", False, "Submit A Cinema4D Script Job (Python)", 9, 0, "Enable this option to submit a custom Python script job. This script will be applied to the scene file that is specified.", colSpan=2 )
    scriptJobBox.ValueModified.connect(ScriptJobChanged)
    
    scriptDialog.AddControlToGrid( "ScriptFileLabel", "LabelControl", "Python Script File", 10, 0, "The Python script file to use.", False )
    scriptDialog.AddSelectionControlToGrid( "ScriptFileBox", "FileBrowserControl", "", "Python Script Files (*.py)", 10, 1, colSpan=3 )
    scriptDialog.EndGrid()

    scriptDialog.AddGrid()
    scriptDialog.AddControlToGrid( "GPUSeparator", "SeparatorControl", "Redshift GPU Options", 11, 0, colSpan=3 )
    
    scriptDialog.AddControlToGrid( "GPUsPerTaskLabel", "LabelControl", "GPUs Per Task", 12, 0, "The number of GPUs to use per task. If set to 0, the default number of GPUs will be used, unless 'Select GPU Devices' Id's have been defined.", False )
    GPUsPerTaskBox = scriptDialog.AddRangeControlToGrid( "GPUsPerTaskBox", "RangeControl", 0, 0, 1024, 0, 1, 12, 1 )
    GPUsPerTaskBox.ValueModified.connect( GPUsPerTaskChanged )

    scriptDialog.AddControlToGrid( "GPUsSelectDevicesLabel", "LabelControl", "Select GPU Devices", 13, 0, "A comma separated list of the GPU devices to use specified by device Id. 'GPUs Per Task' will be ignored.", False )
    GPUsSelectDevicesBox = scriptDialog.AddControlToGrid( "GPUsSelectDevicesBox", "TextControl", "", 13, 1 )
    GPUsSelectDevicesBox.ValueModified.connect( GPUsSelectDevicesChanged )
    scriptDialog.EndGrid()
    scriptDialog.EndTabPage()
    
    integration_dialog = IntegrationUI.IntegrationDialog()
    integration_dialog.AddIntegrationTabs( scriptDialog, "Cinema4DMonitor", DraftRequested, ProjectManagementOptions, failOnNoTabs=False )
    
    scriptDialog.EndTabControl()
    
    scriptDialog.AddGrid()
    scriptDialog.AddHorizontalSpacerToGrid("HSpacer1", 0, 0 )

    submitButton = scriptDialog.AddControlToGrid( "SubmitButton", "ButtonControl", "Submit", 0, 1, expand=False )
    submitButton.ValueModified.connect(SubmitButtonPressed)

    closeButton = scriptDialog.AddControlToGrid( "CloseButton", "ButtonControl", "Close", 0, 2, expand=False )
    # Make sure all the project management connections are closed properly
    closeButton.ValueModified.connect(integration_dialog.CloseProjectManagementConnections)
    closeButton.ValueModified.connect(CloseButtonPressed)

    scriptDialog.EndGrid()
    
    #Application Box must be listed before version box or else the application changed event will change the version
    settings = ("DepartmentBox","CategoryBox","PoolBox","SecondaryPoolBox","GroupBox","PriorityBox","MachineLimitBox","IsBlacklistBox","MachineListBox","LimitGroupBox","SceneBox","FramesBox","ChunkSizeBox","ThreadsBox","VersionBox","BuildBox","SubmitSceneBox","UseDefaultOutputBox","OutputFolderBox","OutputPrefixBox","UseDefaultMPOutputBox","OutputMPFolderBox","OutputMPPrefixBox","LocalRenderingBox","UseBatchPluginBox","NoOpenGLBox")
    scriptDialog.LoadSettings( GetSettingsFilename(), settings )
    scriptDialog.EnabledStickySaving( settings, GetSettingsFilename() )
    
    VersionBoxChanged()
    UseDefaultOutputChanged(None)
    UseDefaultMPOutputChanged(None)
    ScriptJobChanged(None)
    GPUsPerTaskChanged()
    GPUsSelectDevicesChanged()
    
    scriptDialog.ShowDialog( False )
    
def GetSettingsFilename():
    # type: () -> str
    return Path.Combine( ClientUtils.GetUsersSettingsDirectory(), "Cinema4DSettings.ini" )

def VersionBoxChanged():
    # type: () -> None
    global scriptDialog
    version = scriptDialog.GetValue("VersionBox")
    scriptDialog.SetEnabled("TakeBox", int(version) >= 17 )
    scriptDialog.SetEnabled("UseBatchPluginBox", int(version) >= 15 )
    
def ScriptJobChanged( *args ):
    # type: (*Any) -> None
    global scriptDialog
    
    enabled = scriptDialog.GetValue( "ScriptJobBox" )
    scriptDialog.SetEnabled( "ScriptFileLabel", enabled )
    scriptDialog.SetEnabled( "ScriptFileBox", enabled )

def GPUsPerTaskChanged( *args ):
    # type: (*RangeControl) -> None
    global scriptDialog

    perTaskEnabled = ( scriptDialog.GetValue( "GPUsPerTaskBox" ) == 0 )

    scriptDialog.SetEnabled( "GPUsSelectDevicesLabel", perTaskEnabled )
    scriptDialog.SetEnabled( "GPUsSelectDevicesBox", perTaskEnabled )

def GPUsSelectDevicesChanged( *args ):
    # type: (*Any) -> None
    global scriptDialog

    selectDeviceEnabled = ( scriptDialog.GetValue( "GPUsSelectDevicesBox" ) == "" )

    scriptDialog.SetEnabled( "GPUsPerTaskLabel", selectDeviceEnabled )
    scriptDialog.SetEnabled( "GPUsPerTaskBox", selectDeviceEnabled )
            
def CloseDialog():
    # type: () -> None
    global scriptDialog
    global settings
    
    scriptDialog.SaveSettings(GetSettingsFilename(),settings)
    scriptDialog.CloseDialog()
    
def UseDefaultOutputChanged(*args):
    # type: (*Any) -> None
    global scriptDialog
    useDefault = scriptDialog.GetValue("UseDefaultOutputBox")
    
    scriptDialog.SetEnabled("OutputFolderBox",not useDefault)
    scriptDialog.SetEnabled("OutputFolderLabel",not useDefault)
    scriptDialog.SetEnabled("OutputPrefixBox",not useDefault)
    scriptDialog.SetEnabled("OutputPrefixLabel",not useDefault)

def UseDefaultMPOutputChanged(*args):
    # type: (*Any) -> None
    global scriptDialog
    useDefault = scriptDialog.GetValue("UseDefaultMPOutputBox")
    
    scriptDialog.SetEnabled("OutputMPFolderBox",not useDefault)
    scriptDialog.SetEnabled("OutputMPFolderLabel",not useDefault)
    scriptDialog.SetEnabled("OutputMPPrefixBox",not useDefault)
    scriptDialog.SetEnabled("OutputMPPrefixLabel",not useDefault)

def CloseButtonPressed(*args):
    # type: (*ButtonControl) -> None
    CloseDialog()
    
def SubmitButtonPressed(*args):
    global scriptDialog
    global integration_dialog
    global settings
    
    # Check if cinema 4d files exist.
    sceneFiles = StringUtils.FromSemicolonSeparatedString( scriptDialog.GetValue( "SceneBox" ), False )
    if( len( sceneFiles ) == 0 ):
        scriptDialog.ShowMessageBox( "No Cinema 4D file specified", "Error" )
        return
    
    for sceneFile in sceneFiles:
        if( not File.Exists( sceneFile ) ):
            scriptDialog.ShowMessageBox( "Cinema 4D file %s does not exist" % sceneFile, "Error" )
            return
        elif (not scriptDialog.GetValue("SubmitSceneBox") and PathUtils.IsPathLocal(sceneFile)):
            result = scriptDialog.ShowMessageBox( "Cinema 4D file %s is local.  Are you sure you want to continue?" % sceneFile, "Warning", ("Yes","No") )
            if(result=="No"):
                return
                
    #Check the output folder
    outputFolder=""
    outputPrefix=""
    if(not scriptDialog.GetValue("UseDefaultOutputBox")):
        outputFolder = scriptDialog.GetValue("OutputFolderBox")
        if(outputFolder ==""):
            scriptDialog.ShowMessageBox("Please specify an output folder","Error")
            return
        elif(not Directory.Exists(outputFolder)):
            scriptDialog.ShowMessageBox("Output folder " + outputFolder + " does not exist","Error")
            return
        elif(PathUtils.IsPathLocal(outputFolder)):
            result = scriptDialog.ShowMessageBox("Output folder " + outputFolder + " is local, do you still want to continue?","Warning",("Yes","No"))
            if(result=="No"):
                return
                
        outputPrefix=scriptDialog.GetValue("OutputPrefixBox")
        if(outputPrefix==""):
            scriptDialog.ShowMessageBox("Please specify an output prefix","Error")
            return
    
    #Check the MP output folder
    outputMPFolder=""
    outputMPPrefix=""
    if(not scriptDialog.GetValue("UseDefaultMPOutputBox")):
        outputMPFolder = scriptDialog.GetValue("OutputMPFolderBox")
        if(outputMPFolder ==""):
            scriptDialog.ShowMessageBox("Please specify a multipass output folder","Error")
            return
        elif(not Directory.Exists(outputMPFolder)):
            scriptDialog.ShowMessageBox("Multipass output folder " + outputMPFolder + " does not exist","Error")
            return
        elif(PathUtils.IsPathLocal(outputMPFolder)):
            result = scriptDialog.ShowMessageBox("Multipass output folder " + outputMPFolder + " is local, do you still want to continue?","Warning",("Yes","No"))
            if(result=="No"):
                return
                
        outputMPPrefix=scriptDialog.GetValue("OutputMPPrefixBox")
        if(outputMPPrefix==""):
            scriptDialog.ShowMessageBox("Please specify a multipass output prefix","Error")
            return
    
    # Check if a valid frame range has been specified.
    frames = scriptDialog.GetValue( "FramesBox" )
    if( not FrameUtils.FrameRangeValid( frames ) ):
        scriptDialog.ShowMessageBox( "Frame range %s is not valid" % frames, "Error" )
        return
    
    scriptJob = scriptDialog.GetValue( "ScriptJobBox" )
    # Check script
    scriptFile = (scriptDialog.GetValue( "ScriptFileBox" )).strip()
    if( scriptJob ):
        if( not File.Exists( scriptFile ) ):
            scriptDialog.ShowMessageBox( "Script file %s does not exist" % scriptFile, "Error" )
            return
        if not scriptDialog.GetEnabled( "UseBatchPluginBox" ):
            scriptDialog.ShowMessageBox( "Script jobs are only supported for Cinema 4D 15 and beyond.", "Error" )
            return

    # Gpu Options
    regex = re.compile( "^(\d{1,2}(,\d{1,2})*)?$" )
    selectDevices = scriptDialog.GetValue( "GPUsSelectDevicesBox" )
    validSyntax = regex.match( selectDevices )
    if not validSyntax:
        scriptDialog.ShowMessageBox( "'Select GPU Devices' syntax is invalid!\n\nTrailing 'commas' if present, should be removed.\n\nValid Examples: 0 or 2 or 0,1,2 or 0,3,4 etc", "Error" )
        return

    # Check if concurrent threads > 1
    if scriptDialog.GetValue( "ConcurrentTasksBox" ) > 1 and selectDevices != "" :
        scriptDialog.ShowMessageBox( "If using 'Select GPU Devices', then 'Concurrent Tasks' must be set to 1", "Error" )
        return
    
    # Check if Integration options are valid
    if integration_dialog is not None and not integration_dialog.CheckIntegrationSanity( ):
        return
    
    successes = 0
    failures = 0
    
    # Submit each scene file separately.
    for sceneFile in sceneFiles:
        jobName = scriptDialog.GetValue( "NameBox" )
        if len(sceneFiles) > 1:
            jobName = jobName + " [" + Path.GetFileName( sceneFile ) + "]"
            
        if scriptJob:
            jobName = jobName + " [Script Job]"
                
        # Create job info file.
        jobInfoFilename = Path.Combine( ClientUtils.GetDeadlineTempPath(), "cinema4d_job_info.job" )
        writer = StreamWriter( jobInfoFilename, False, Encoding.Unicode )
        if scriptDialog.GetEnabled( "UseBatchPluginBox" ) and ( scriptDialog.GetValue( "UseBatchPluginBox" ) or scriptJob ):
            writer.WriteLine( "Plugin=Cinema4DBatch" )
        else:
            writer.WriteLine( "Plugin=Cinema4D" )
        
        writer.WriteLine( "Name=%s" % jobName )
        writer.WriteLine( "Comment=%s" % scriptDialog.GetValue( "CommentBox" ) )
        writer.WriteLine( "Department=%s" % scriptDialog.GetValue( "DepartmentBox" ) )
        writer.WriteLine( "Pool=%s" % scriptDialog.GetValue( "PoolBox" ) )
        writer.WriteLine( "SecondaryPool=%s" % scriptDialog.GetValue( "SecondaryPoolBox" ) )
        writer.WriteLine( "Group=%s" % scriptDialog.GetValue( "GroupBox" ) )
        writer.WriteLine( "Priority=%s" % scriptDialog.GetValue( "PriorityBox" ) )
        writer.WriteLine( "TaskTimeoutMinutes=%s" % scriptDialog.GetValue( "TaskTimeoutBox" ) )
        writer.WriteLine( "EnableAutoTimeout=%s" % scriptDialog.GetValue( "AutoTimeoutBox" ) )
        writer.WriteLine( "ConcurrentTasks=%s" % scriptDialog.GetValue( "ConcurrentTasksBox" ) )
        writer.WriteLine( "LimitConcurrentTasksToNumberOfCpus=%s" % scriptDialog.GetValue( "LimitConcurrentTasksBox" ) )
        
        writer.WriteLine( "MachineLimit=%s" % scriptDialog.GetValue( "MachineLimitBox" ) )
        if( bool(scriptDialog.GetValue( "IsBlacklistBox" )) ):
            writer.WriteLine( "Blacklist=%s" % scriptDialog.GetValue( "MachineListBox" ) )
        else:
            writer.WriteLine( "Whitelist=%s" % scriptDialog.GetValue( "MachineListBox" ) )
        
        writer.WriteLine( "LimitGroups=%s" % scriptDialog.GetValue( "LimitGroupBox" ) )
        writer.WriteLine( "JobDependencies=%s" % scriptDialog.GetValue( "DependencyBox" ) )
        writer.WriteLine( "OnJobComplete=%s" % scriptDialog.GetValue( "OnJobCompleteBox" ) )
        
        if( bool(scriptDialog.GetValue( "SubmitSuspendedBox" )) ):
            writer.WriteLine( "InitialStatus=Suspended" )
        
        writer.WriteLine( "Frames=%s" % frames )
        writer.WriteLine( "ChunkSize=%s" % scriptDialog.GetValue( "ChunkSizeBox" ) )
        
        if not scriptJob:
            outputCount = 0
            if outputFolder != "":
                writer.WriteLine( "OutputDirectory" + str(outputCount) + "=" + outputFolder )
                outputCount = outputCount + 1
            
            if outputMPFolder != "":
                writer.WriteLine( "OutputDirectory" + str(outputCount) + "=" + outputMPFolder )
                outputCount = outputCount + 1
        
        # Integration
        extraKVPIndex = 0
        groupBatch = False
        if integration_dialog is not None and integration_dialog.IntegrationProcessingRequested():
            extraKVPIndex = integration_dialog.WriteIntegrationInfo( writer, extraKVPIndex )
            groupBatch = groupBatch or integration_dialog.IntegrationGroupBatchRequested()
            
        if groupBatch:
            writer.WriteLine( "BatchName=%s\n" % ( jobName ) ) 
        writer.Close()
        
        # Create plugin info file.
        pluginInfoFilename = Path.Combine( ClientUtils.GetDeadlineTempPath(), "cinema4d_plugin_info.job" )
        writer = StreamWriter( pluginInfoFilename, False, Encoding.Unicode )
        
        if( not scriptDialog.GetValue( "SubmitSceneBox" ) ):
            writer.WriteLine( "SceneFile=" + sceneFile )

        writer.WriteLine( "Version=" + scriptDialog.GetValue( "VersionBox" ) )
        writer.WriteLine( "Build=" + scriptDialog.GetValue( "BuildBox" ) )
        writer.WriteLine( "NoOpenGL=" + str( scriptDialog.GetValue( "NoOpenGLBox" ) ) )
        if scriptJob:
            writer.WriteLine( "ScriptJob=True" )
            writer.WriteLine( "ScriptFilename=%s" % Path.GetFileName( scriptFile ) )
        else:
            writer.WriteLine( "Threads=" + str( scriptDialog.GetValue( "ThreadsBox" ) ) )
            writer.WriteLine( "Width=0" )
            writer.WriteLine( "Height=0" )
            writer.WriteLine( "LocalRendering=" + str( scriptDialog.GetValue( "LocalRenderingBox" ) ) )
            writer.WriteLine( "FilePath=" + outputFolder )
            writer.WriteLine( "FilePrefix=" + outputPrefix )
            writer.WriteLine( "MultiFilePath=" + outputMPFolder )
            writer.WriteLine( "MultiFilePrefix=" + outputMPPrefix )
            writer.WriteLine( "Take=" + str( scriptDialog.GetValue( "TakeBox" ) ) )

            # Gpu Options - Only affects when using Redshift
            writer.WriteLine( "GPUsPerTask=%s" % scriptDialog.GetValue( "GPUsPerTaskBox" ) )
            writer.WriteLine( "GPUsSelectDevices=%s" % selectDevices )
        
        writer.Close()
        
        # Setup the command line arguments.
        arguments = StringCollection()
        
        arguments.Add( jobInfoFilename )
        arguments.Add( pluginInfoFilename )
        
        if scriptDialog.GetValue( "SubmitSceneBox" ):
            arguments.Add( sceneFile )

        if scriptJob:
            arguments.Add( scriptFile )
        
        if( len( sceneFiles ) == 1 ):
            results = ClientUtils.ExecuteCommandAndGetOutput( arguments )
            scriptDialog.ShowMessageBox( results, "Submission Results" )
        else:
            # Now submit the job.
            exitCode = ClientUtils.ExecuteCommand( arguments )
            if( exitCode == 0 ):
                successes = successes + 1
            else:
                failures = failures + 1
        
    if( len( sceneFiles ) > 1 ):
        scriptDialog.ShowMessageBox( "Jobs submitted successfully: %d\nJobs not submitted: %d" % (successes, failures), "Submission Results" )
    
    if successes > 0:
        scriptDialog.SaveSettings( GetSettingsFilename(), settings )
