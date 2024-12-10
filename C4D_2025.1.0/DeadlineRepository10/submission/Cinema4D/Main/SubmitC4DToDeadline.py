#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function

import io
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
import time
import traceback
from collections import namedtuple
from functools import partial

try:
    import ConfigParser
except ImportError:
    try:
        import configparser as ConfigParser
    except ImportError:
        print( "Could not load ConfigParser module, sticky settings will not be loaded/saved" )
    
import c4d
from c4d import documents
from c4d import gui
from c4d import plugins

try:
    unicode_type = unicode
except:
    unicode_type = str    
    
useTakes = False
try:
    from c4d.modules import takesystem
    useTakes = True
except ImportError:
    print( "Could not load takesystem module, modules will not be used." )

useTokens = False
try:
    from c4d.modules import tokensystem
    useTokens = True
except ImportError:
    print( "Could not load tokensystem module, module will not be used." )

import deadlinec4d

# A rectangular region
Region = namedtuple( "Region", [ "left", "top", "right", "bottom" ] )


## The submission dialog class.
class SubmitC4DToDeadlineDialog( gui.GeDialog ):
    
    LabelWidth = 200
    TextBoxWidth = 600
    ComboBoxWidth = 180
    RangeBoxWidth = 190
    SliderLabelWidth = 180

    renderersDict = {
        # third-party
        1029988 : "arnold",
        1034128 : "iray", #NVIDIA IRAY
        1036219 : "redshift",
        1019782 : "vray",
        1053272 : 'vray_5', # V-ray 5+ uses a different plugin that acts different then normal
        1029525 : "octane",

        # OpenGL
        300001061 : "ogl_hardware",
        1 : "ogl_software",

        # Built-in
        0 : "standard",
        1023342 : "physical",
        1037639 : "prorender",
        1016630 : "cineman"
    }

    gpuRenderers = [ "redshift" ]

    mPassTypePrefixDict ={
        c4d.VPBUFFER_AMBIENT : "ambient",               # Ambient
        c4d.VPBUFFER_AMBIENTOCCLUSION : "ao",           # Ambient Occlusion
        c4d.VPBUFFER_ATMOSPHERE : "atmos",              # Atmosphere
        c4d.VPBUFFER_ATMOSPHERE_MUL : "atmosmul",       # Atmosphere (Multiply)
        c4d.VPBUFFER_CAUSTICS : "caustics",             # Caustics
        c4d.VPBUFFER_DEPTH : "depth",                   # Depth
        c4d.VPBUFFER_DIFFUSE : "diffuse",               # Diffuse
        c4d.VPBUFFER_RADIOSITY : "gi",                  # Global Illumination
        c4d.VPBUFFER_ILLUMINATION : "illum",            # Illumination
        c4d.VPBUFFER_MAT_COLOR : "matcolor",            # Material Colour
        c4d.VPBUFFER_MAT_DIFFUSION : "matdif",          # Material Diffusion
        c4d.VPBUFFER_MAT_ENVIRONMENT : "matenv",        # Material Environment
        c4d.VPBUFFER_MAT_LUMINANCE : "matlum",          # Material Luminance
        c4d.VPBUFFER_MAT_NORMAL : "normal",             # Material Normal
        c4d.VPBUFFER_MAT_REFLECTION : "matrefl",        # Material Reflection
        c4d.VPBUFFER_MAT_SPECULAR : "matspec",          # Material Specular
        c4d.VPBUFFER_MAT_SPECULARCOLOR : "matspeccol",  # Material Specular Colour
        c4d.VPBUFFER_MAT_TRANSPARENCY : "mattrans",     # Material Transparency
        c4d.VPBUFFER_MAT_UV : "uv",                     # Material UVW
        c4d.VPBUFFER_MOTIONVECTOR : "motion",           # Motion Vector
        c4d.VPBUFFER_REFLECTION : "refl",               # Reflection
        c4d.VPBUFFER_TRANSPARENCY : "refr",             # Refraction
        c4d.VPBUFFER_RGBA : "rgb",                      # RGBA Image
        c4d.VPBUFFER_SHADOW : "shadow",                 # Shadow
        c4d.VPBUFFER_SPECULAR : "specular"              # Specular
    }

    exportFileTypeDict = {
        "Arnold" : "Arnold Scene Source File (*.ass)",
        "Octane" : "Octane ORBX Scene File (*.orbx)",
        "Redshift" : "Redshift Proxy File (*.rs)"
    }
    
    ARNOLD_PLUGIN_ID = 1029988
    ARNOLD_ASS_EXPORT = 1029993
    ARNOLD_C4D_DISPLAY_DRIVER_TYPE = 1927516736
    ARNOLD_DRIVER = 1030141
    
    REDSHIFT_PLUGIN_ID = 1036219
    REDSHIFT_EXPORT_PLUGIN_ID = 1038650

    OCTANE_PLUGIN_ID = 1029525
    OCTANE_ORBX_EXPORT = 1037665
    OCTANE_LIVEPLUGIN_ID = 1029499

    # V-Ray 3.7
    VRAY_MULTIPASS_PLUGIN_ID = 1028268

    # V-Ray 5
    VRAY_RENDER_ELEMENT_HOOK_ID = 1054363
    VRAY5_RENDER_ELEMENTS_ID = 1054149
    
    FRAME_TOKEN = "$frame"
    PASS_TOKEN = "$pass"
    USER_PASS_TOKEN = "$userpass"
    FRAME_PLACEHOLDER = "####"

    def __init__( self ):
        c4d.StatusSetBar( 25 )
        stdout = None
        self.c4dMajorVersion = c4d.GetC4DVersion() // 1000
        
        print( "Grabbing submitter info..." )
        try:
            dcOutput = CallDeadlineCommand( [ "-prettyJSON", "-GetSubmissionInfo", "Pools", "Groups", "MaxPriority", "TaskLimit", "UserHomeDir", "RepoDir:submission/Cinema4D/Main", "RepoDir:submission/Integration/Main", ], useDeadlineBg=True )
            output = json.loads( dcOutput )
        except:
            gui.MessageDialog( "Unable to get submitter info from Deadline:\n\n" + traceback.format_exc() )
            raise
        
        if output[ "ok" ]:
            self.SubmissionInfo = output[ "result" ]
        else:
            gui.MessageDialog( "DeadlineCommand returned a bad result and was unable to grab the submitter info.\n\n" + output[ "result" ] )
            c4d.StatusClear()
            raise Exception( output[ "result" ] )
        
        c4d.StatusSetBar( 70 )
        
        # Pools
        self.Pools = []
        self.SecondaryPools = [ " " ] # Need to have a space, since empty strings don't seem to show up.
        for pool in self.SubmissionInfo[ "Pools" ]:
            pool = pool.strip()
            self.Pools.append( pool )
            self.SecondaryPools.append( pool ) 
            
        if not self.Pools:
            self.Pools.append( "none" )
            self.SecondaryPools.append( "none" ) 
        
        c4d.StatusSetBar( 75 )
        
        # Groups
        self.Groups = []
        for group in self.SubmissionInfo[ "Groups" ]:
            self.Groups.append( group.strip() )
        
        if not self.Groups:
            self.Groups.append( "none" )
            
        c4d.StatusSetBar( 80 )
        
        # Maximum Priority / Task Limit
        self.MaximumPriority = int( self.SubmissionInfo.get( "MaxPriority", 100 ) )
        self.TaskLimit = int( self.SubmissionInfo.get( "TaskLimit", 5000 ) )
        
        c4d.StatusSetBar( 85 )
        
        # User Home Deadline Directory
        self.DeadlineHome = self.SubmissionInfo[ "UserHomeDir" ].strip()
        self.DeadlineSettings = os.path.join( self.DeadlineHome, "settings" )
        self.DeadlineTemp = os.path.join( self.DeadlineHome, "temp" )
        
        c4d.StatusSetBar( 90 )
        
        # Repository Directories
        self.C4DSubmissionDir = self.SubmissionInfo[ "RepoDirs" ][ "submission/Cinema4D/Main" ].strip()
        self.IntegrationDir = self.SubmissionInfo[ "RepoDirs" ][ "submission/Integration/Main" ].strip()
        
        c4d.StatusSetBar( 100 )
        
        # Set On Job Complete settings.
        self.OnComplete = ( "Archive", "Delete", "Nothing" )
        
        # Set Build settings.
        self.Builds = ( "None", "32bit", "64bit" )
        
        self.Exporters = []
        if plugins.FindPlugin( SubmitC4DToDeadlineDialog.ARNOLD_PLUGIN_ID ) is not None:
            self.Exporters.append( "Arnold" )
        if plugins.FindPlugin( SubmitC4DToDeadlineDialog.OCTANE_PLUGIN_ID ) is not None:
            self.Exporters.append( "Octane" )
        if plugins.FindPlugin( SubmitC4DToDeadlineDialog.REDSHIFT_PLUGIN_ID ) is not None:
            self.Exporters.append( "Redshift" )

        self.Takes = []
        if useTakes:
            self.Takes = ["Active", "All"]
            if deadlinec4d.takes.can_takes_be_checked():
                self.Takes.append("Marked")
        
        self.AssembleOver = [ "Blank Image", "Previous Output", "Selected Image" ]
        
        self.dialogIDs = {
            # Job Options
            "NameBoxID" : 0,
            "CommentBoxID" : 0,
            "DepartmentBoxID" : 0,
            "PoolBoxID" : 0,
            "SecondaryPoolBoxID" : 0,
            "GroupBoxID" : 0,
            "PriorityBoxID" : 0,
            "UseBatchBoxID" : 0,
            "AutoTimeoutBoxID" : 0,
            "TaskTimeoutBoxID" : 0,
            "ConcurrentTasksBoxID" : 0,
            "LimitConcurrentTasksBoxID" : 0,
            "MachineLimitBoxID" : 0,
            "IsBlacklistBoxID" : 0,
            "MachineListBoxID" :0,
            "MachineListButtonID" : 0,
            "LimitGroupsBoxID" : 0,
            "LimitGroupsButtonID" : 0,
            "DependenciesBoxID" : 0,
            "DependenciesButtonID" : 0,
            "OnCompleteBoxID" : 0,
            "SubmitSuspendedBoxID" : 0,
            "FramesBoxID" : 0,
            "EnableFrameStepBoxID" : 0,
            "TakeFramesBoxID" : 0,

            # Cinema4D Options
            "ChunkSizeBoxID" : 0,
            "ThreadsBoxID" : 0,
            "TakesBoxID" : 0,
            "IncludeMainBoxID" : 0,
            "BuildBoxID" : 0,
            "LocalRenderingBoxID" : 0,
            "SubmitSceneBoxID" : 0,
            "ExportProjectBoxID" : 0,
            "CloseOnSubmissionID" : 0,
            "OpenGLBoxID" : 0,
            
            # Output Override Options
            "OutputOverrideID" : 0,
            "OutputOverrideButtonID" : 0,
            "OutputMultipassOverrideID" : 0,
            "OutputMultipassOverrideButtonID" : 0,

            # Gpu Override Options
            "GPUsPerTaskID" : 0,
            "SelectGPUDevicesID" : 0,

            # AWS Portal Options
            "EnableAssetServerPrecachingID": 0,

            # Export Options
            "ExportJobID" : 0,
            "ExportJobTypesID" : 0,
            "ExportLocalID" : 0,
            "ExportDependentJobBoxID" : 0,

            # General Export Options 
            "ExportPoolBoxID" : 0,
            "ExportSecondaryPoolBoxID" : 0,
            "ExportGroupBoxID" : 0,
            "ExportPriorityBoxID" : 0,
            "ExportMachineLimitBoxID" : 0,
            "ExportConcurrentTasksBoxID" : 0,
            "ExportTaskTimeoutBoxID" : 0,
            "ExportLimitGroupsBoxID" : 0,
            "ExportLimitGroupsButtonID" : 0,
            "ExportMachineListBoxID" : 0,
            "ExportMachineListButtonID" : 0,
            "ExportOnCompleteBoxID" : 0,
            "ExportIsBlacklistBoxID" : 0,
            "ExportThreadsBoxID" : 0,
            "ExportSubmitSuspendedBoxID" : 0,
            "ExportLimitConcurrentTasksBoxID" : 0,
            "ExportAutoTimeoutBoxID" : 0,
            "ExportLocationBoxID" : 0,
            "ExportLocationButtonID" : 0,

            # Region Rendering Options
            "RegionRenderTypeID" : 0,
            "EnableRegionRenderingID" : 0,
            "TilesInXID" : 0,
            "TilesInYID" : 0,
            "SingleFrameTileJobID" : 0,
            "SingleFrameJobFrameID" : 0,
            "SubmitDependentAssemblyID" : 0,
            "CleanupTilesID" : 0,
            "ErrorOnMissingTilesID" : 0,
            "AssembleTilesOverID" : 0,
            "BackgroundImageID" : 0,
            "BackgroundImageButtonID" : 0,
            "ErrorOnMissingBackgroundID" : 0,

            # Generic Dialog Buttons
            "PipelineToolStatusID" : 0,
            "SubmitButtonID" : 0,
            "CancelButtonID" : 0,
            "UnifiedIntegrationButtonID" : 0
        }

        # Set all the IDs for the dialog
        self.NextID = 0
        for dialogID in self.dialogIDs.keys():
            self.dialogIDs[ dialogID ] = self.GetNextID()
        
        c4d.StatusClear()
    
    def GetNextID( self ):
        self.NextID += 1
        return self.NextID
    
    def StartGroup( self, label ):
        self.GroupBegin( self.GetNextID(), 0, 0, 20, label, 0 )
        self.GroupBorder( c4d.BORDER_THIN_IN )
        self.GroupBorderSpace( 4, 4, 4, 4 )
    
    def EndGroup( self ):
        self.GroupEnd()
    
    def AddTextBoxGroup( self, id, label ):
        self.GroupBegin( self.GetNextID(), 0, 2, 1, "", 0 )
        self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, label, 0 )
        self.AddEditText( id, 0, SubmitC4DToDeadlineDialog.TextBoxWidth, 0 )
        self.GroupEnd()
    
    def AddComboBoxGroup( self, id, label, checkboxID=-1, checkboxLabel="" ):
        self.GroupBegin( self.GetNextID(), 0, 3, 1, "", 0 )
        self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, label, 0 )
        self.AddComboBox( id, 0, SubmitC4DToDeadlineDialog.ComboBoxWidth, 0 )
        if checkboxID >= 0 and checkboxLabel != "":
            self.AddCheckbox( checkboxID, 0, SubmitC4DToDeadlineDialog.LabelWidth + SubmitC4DToDeadlineDialog.ComboBoxWidth + 12, 0, checkboxLabel )
        elif checkboxID > -2:
            self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth + SubmitC4DToDeadlineDialog.ComboBoxWidth + 12, 0, "", 0 )
        self.GroupEnd()
    
    def AddRangeBoxGroup( self, id, label, min, max, inc, checkboxID=-1, checkboxLabel="" ):
        self.GroupBegin( self.GetNextID(), 0, 3, 1, "", 0 )
        self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, label, 0 )
        self.AddEditNumberArrows( id, 0, SubmitC4DToDeadlineDialog.RangeBoxWidth, 0 )
        if checkboxID >= 0 and checkboxLabel != "":
            self.AddCheckbox( checkboxID, 0, SubmitC4DToDeadlineDialog.LabelWidth + SubmitC4DToDeadlineDialog.ComboBoxWidth + 12, 0, checkboxLabel )
        else:
            self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth + SubmitC4DToDeadlineDialog.RangeBoxWidth + 4, 0, "", 0 )
        self.SetLong( id, min, min, max, inc )
        self.GroupEnd()
    
    def AddSelectionBoxGroup( self, id, label, buttonID ):
        self.GroupBegin( self.GetNextID(), 0, 3, 1, "", 0 )
        self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, label, 0 )
        self.AddEditText( id, 0, SubmitC4DToDeadlineDialog.TextBoxWidth - 56, 0 )
        self.AddButton( buttonID, 0, 8, 0, "..." )
        self.GroupEnd()
    
    def AddCheckboxGroup( self, checkboxID, checkboxLabel, textID, buttonID ):
        self.GroupBegin( self.GetNextID(), 0, 3, 1, "", 0 )
        self.AddCheckbox( checkboxID, 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, checkboxLabel )
        self.AddEditText( textID, 0, SubmitC4DToDeadlineDialog.TextBoxWidth - 56, 0 )
        self.AddButton( buttonID, 0, 8, 0, "..." )
        self.GroupEnd()
    
    ## This is called when the dialog is initialized.
    def CreateLayout( self ):
        self.SetTitle( "Submit To Deadline" )
        
        self.TabGroupBegin( self.GetNextID(), 0 )
        #General Options Tab
        self.GroupBegin( self.GetNextID(), c4d.BFH_LEFT, 0, 20, "General Options", 0 )
        self.GroupBorderNoTitle( c4d.BORDER_NONE )
        
        self.StartGroup( "Job Description" )
        self.AddTextBoxGroup( self.dialogIDs[ "NameBoxID" ], "Job Name" )
        self.AddTextBoxGroup( self.dialogIDs[ "CommentBoxID" ], "Comment" )
        self.AddTextBoxGroup( self.dialogIDs[ "DepartmentBoxID" ], "Department" )
        self.EndGroup()
        
        self.StartGroup( "Job Options" )
        self.AddComboBoxGroup( self.dialogIDs[ "PoolBoxID" ], "Pool" )
        self.AddComboBoxGroup( self.dialogIDs[ "SecondaryPoolBoxID" ], "Secondary Pool" )
        self.AddComboBoxGroup( self.dialogIDs[ "GroupBoxID" ], "Group" )
        self.AddRangeBoxGroup( self.dialogIDs[ "PriorityBoxID" ], "Priority", 0, 100, 1 )
        self.AddRangeBoxGroup( self.dialogIDs[ "TaskTimeoutBoxID" ], "Task Timeout", 0, 999999, 1, self.dialogIDs[ "AutoTimeoutBoxID" ], "Enable Auto Task Timeout" )
        self.AddRangeBoxGroup( self.dialogIDs[ "ConcurrentTasksBoxID" ], "Concurrent Tasks", 1, 16, 1, self.dialogIDs[ "LimitConcurrentTasksBoxID" ], "Limit Tasks To Worker's Task Limit" )
        self.AddRangeBoxGroup( self.dialogIDs[ "MachineLimitBoxID" ], "Machine Limit", 0, 999999, 1, self.dialogIDs[ "IsBlacklistBoxID" ], "Machine List Is A Deny List" )
        self.AddSelectionBoxGroup( self.dialogIDs[ "MachineListBoxID" ], "Machine List", self.dialogIDs[ "MachineListButtonID" ] )
        self.AddSelectionBoxGroup( self.dialogIDs[ "LimitGroupsBoxID" ], "Limit Groups", self.dialogIDs[ "LimitGroupsButtonID" ] )
        self.AddSelectionBoxGroup( self.dialogIDs[ "DependenciesBoxID" ], "Dependencies", self.dialogIDs[ "DependenciesButtonID" ] )
        self.AddComboBoxGroup( self.dialogIDs[ "OnCompleteBoxID" ], "On Job Complete", self.dialogIDs[ "SubmitSuspendedBoxID" ], "Submit Job As Suspended" )
        self.EndGroup()
        
        self.StartGroup( "Cinema 4D Options" )

        self.AddComboBoxGroup( self.dialogIDs[ "TakesBoxID" ], "Take List", self.dialogIDs[ "IncludeMainBoxID" ], "Include Main take in All takes" )

        self.AddTextBoxGroup( self.dialogIDs[ "FramesBoxID" ], "Frame List" )

        self.GroupBegin( self.GetNextID(), c4d.BFH_LEFT, 4, 1, "", 0 )
        self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, "", 0 )
        self.AddCheckbox( self.dialogIDs[ "TakeFramesBoxID" ], 0, SubmitC4DToDeadlineDialog.LabelWidth + 23, 0, "Use Take Frame Range" )
        self.AddCheckbox( self.dialogIDs[ "EnableFrameStepBoxID" ], 0, 0, 0, "Submit all frames as single task" )
        self.GroupEnd()
        
        self.AddRangeBoxGroup( self.dialogIDs[ "ChunkSizeBoxID" ], "Frames Per Task", 1, 999999, 1, self.dialogIDs[ "SubmitSceneBoxID" ], "Submit Cinema 4D Scene File" )
        self.AddRangeBoxGroup( self.dialogIDs[ "ThreadsBoxID" ], "Threads To Use", 0, 256, 1, self.dialogIDs[ "ExportProjectBoxID" ], "Export Project Before Submission" )
        self.AddComboBoxGroup( self.dialogIDs[ "BuildBoxID" ], "Build To Force", self.dialogIDs[ "LocalRenderingBoxID" ], "Enable Local Rendering" )
        
        self.GroupBegin( self.GetNextID(), c4d.BFH_LEFT, 4, 1, "", 0 )
        self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, "", 0 )
        self.AddCheckbox( self.dialogIDs[ "CloseOnSubmissionID" ], 0, SubmitC4DToDeadlineDialog.LabelWidth + 23, 0, "Close On Submission" )
        self.AddCheckbox( self.dialogIDs[ "UseBatchBoxID" ], 0, 0, 0, "Use Batch Plugin" )
        self.AddCheckbox( self.dialogIDs[ "OpenGLBoxID" ], 0, 0, 0, "Disable OpenGL" )
        self.GroupEnd()

        self.GroupBegin( self.GetNextID(), c4d.BFH_LEFT, 4, 1, "", 0 )
        self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, "", 0 )
        self.AddButton( self.dialogIDs[ "UnifiedIntegrationButtonID" ], c4d.BFH_CENTER, 183, 0, "Pipeline Tools" )
        self.AddStaticText( self.dialogIDs[ "PipelineToolStatusID" ], c4d.BFH_CENTER, 380, 0, "No Tools Set", 0 )
        self.EndGroup()
        
        self.EndGroup()

        self.GroupEnd() #General Options Tab
        
        # Advanced Options Tab
        self.GroupBegin( self.GetNextID(), c4d.BFV_TOP, 0, 20, "Advanced Options", 0 )
        self.GroupBorderNoTitle( c4d.BORDER_NONE )

        # Output Overrides
        self.StartGroup( "Output Overrides" )
        self.AddSelectionBoxGroup( self.dialogIDs[ "OutputOverrideID" ], "Output File", self.dialogIDs[ "OutputOverrideButtonID" ] )
        self.AddSelectionBoxGroup( self.dialogIDs[ "OutputMultipassOverrideID" ], "Multipass File", self.dialogIDs[ "OutputMultipassOverrideButtonID" ] )
        self.EndGroup()
        
        # GPU AFFINITY
        self.StartGroup( "GPU Affinity Overrides" )
        self.AddRangeBoxGroup( self.dialogIDs[ "GPUsPerTaskID" ], "GPUs Per Task", 0, 16, 1 )
        self.AddTextBoxGroup( self.dialogIDs[ "SelectGPUDevicesID" ], "Select GPU Devices" )
        self.EndGroup()
        
        self.StartGroup( "Region Rendering" )
        self.AddCheckbox( self.dialogIDs[ "EnableRegionRenderingID" ], 0, SubmitC4DToDeadlineDialog.LabelWidth+SubmitC4DToDeadlineDialog.ComboBoxWidth + 12, 0, "Enable Region Rendering" )
        self.AddRangeBoxGroup( self.dialogIDs[ "TilesInXID" ], "Tiles In X", 1, 100, 1 )
        self.AddRangeBoxGroup( self.dialogIDs[ "TilesInYID" ], "Tiles In Y", 1, 100, 1 )
        
        self.GroupBegin( self.GetNextID(), 0, 3, 1, "", 0 )
        self.AddRangeBoxGroup( self.dialogIDs[ "SingleFrameJobFrameID" ], "Frame to Render", 0, 9999999, 1, self.dialogIDs[ "SingleFrameTileJobID" ], "Submit All Tiles as a Single Job." )
        self.GroupEnd() 
        self.AddCheckbox( self.dialogIDs[ "SubmitDependentAssemblyID" ], 0, SubmitC4DToDeadlineDialog.LabelWidth+SubmitC4DToDeadlineDialog.ComboBoxWidth + 12, 0, "Submit Dependent Assembly Job" )
        self.AddCheckbox( self.dialogIDs[ "CleanupTilesID" ], 0, SubmitC4DToDeadlineDialog.LabelWidth+SubmitC4DToDeadlineDialog.ComboBoxWidth + 12, 0, "Cleanup Tiles After Assembly" )
        self.AddCheckbox( self.dialogIDs[ "ErrorOnMissingTilesID" ], 0, SubmitC4DToDeadlineDialog.LabelWidth+SubmitC4DToDeadlineDialog.ComboBoxWidth + 12, 0, "Error on Missing Tiles" )
        self.AddComboBoxGroup( self.dialogIDs[ "AssembleTilesOverID" ], "Assemble Tiles Over" )
        
        self.AddSelectionBoxGroup( self.dialogIDs[ "BackgroundImageID" ], "Background Image", self.dialogIDs[ "BackgroundImageButtonID" ] )
        self.AddCheckbox( self.dialogIDs[ "ErrorOnMissingBackgroundID" ], 0, SubmitC4DToDeadlineDialog.LabelWidth+SubmitC4DToDeadlineDialog.ComboBoxWidth + 12, 0, "Error on Missing Background" )
        self.EndGroup()

        # AWSPortal 
        self.StartGroup( "AWSPortal Options" )
        self.AddCheckbox( self.dialogIDs[ "EnableAssetServerPrecachingID" ], 0, SubmitC4DToDeadlineDialog.LabelWidth+SubmitC4DToDeadlineDialog.TextBoxWidth + 30, 0, "Precache assets for AWS" )
        self.EndGroup()

        self.GroupEnd() #Region Rendering Tab

        #Export Jobs Tab
        self.GroupBegin( self.GetNextID(), c4d.BFV_TOP, 0, 40, "Export Jobs", 0 )
        self.StartGroup( "Export Jobs" )
        self.GroupBegin( self.GetNextID(), c4d.BFH_LEFT, 4, 1, "", 0 )
        self.AddCheckbox( self.dialogIDs[ "ExportJobID" ], 0, 624, 0, "Submit Export Job" )
        self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, "", 0 )
        self.GroupEnd()
        self.AddComboBoxGroup( self.dialogIDs[ "ExportJobTypesID" ], "Export Type" )
        self.AddSelectionBoxGroup( self.dialogIDs[ "ExportLocationBoxID" ], "Export File Location", self.dialogIDs[ "ExportLocationButtonID" ] )
        self.EndGroup()#Export Group

        self.StartGroup( "Dependent Job Options" )
        self.GroupBegin( self.GetNextID(), c4d.BFH_LEFT, 4, 1, "", 0 )
        self.AddCheckbox( self.dialogIDs[ "ExportDependentJobBoxID" ], 0, 0, 0, "Submit Dependent Job" )
        self.AddCheckbox( self.dialogIDs[ "ExportLocalID" ], 0, 0, 0, "Export Locally" )
        self.GroupEnd()

        self.GroupBegin( self.GetNextID(), c4d.BFH_LEFT, 4, 1, "", 0 )
        self.AddStaticText( self.GetNextID(), 0, SubmitC4DToDeadlineDialog.LabelWidth, 0, "", 0 )
        self.GroupEnd()

        self.AddComboBoxGroup( self.dialogIDs[ "ExportPoolBoxID" ], "Pool" )
        self.AddComboBoxGroup( self.dialogIDs[ "ExportSecondaryPoolBoxID" ], "Secondary Pool" )
        self.AddComboBoxGroup( self.dialogIDs[ "ExportGroupBoxID" ], "Group" )
        self.AddRangeBoxGroup( self.dialogIDs[ "ExportPriorityBoxID" ], "Priority", 0, 100, 1 )
        self.AddRangeBoxGroup( self.dialogIDs[ "ExportThreadsBoxID" ], "Threads To Use", 0, 256, 1 )
        self.AddRangeBoxGroup( self.dialogIDs[ "ExportTaskTimeoutBoxID" ], "Task Timeout", 0, 999999, 1, self.dialogIDs[ "ExportAutoTimeoutBoxID" ], "Enable Auto Task Timeout" )
        self.AddRangeBoxGroup( self.dialogIDs[ "ExportConcurrentTasksBoxID" ], "Concurrent Tasks", 1, 16, 1, self.dialogIDs[ "ExportLimitConcurrentTasksBoxID" ], "Limit Tasks To Worker's Task Limit" )
        self.AddRangeBoxGroup( self.dialogIDs[ "ExportMachineLimitBoxID" ], "Machine Limit", 0, 999999, 1, self.dialogIDs[ "ExportIsBlacklistBoxID" ], "Machine List Is A Deny List" )
        self.AddSelectionBoxGroup( self.dialogIDs[ "ExportMachineListBoxID" ], "Machine List", self.dialogIDs[ "ExportMachineListButtonID" ] )
        self.AddSelectionBoxGroup( self.dialogIDs[ "ExportLimitGroupsBoxID" ], "Limit Groups", self.dialogIDs[ "ExportLimitGroupsButtonID" ] )
        self.AddComboBoxGroup( self.dialogIDs[ "ExportOnCompleteBoxID" ], "On Job Complete", self.dialogIDs[ "ExportSubmitSuspendedBoxID" ], "Submit Job As Suspended" )
        self.EndGroup()#Job Options Group

        self.GroupEnd() #Export Jobs tab
        self.GroupEnd() #Tab group
        
        self.GroupBegin( self.GetNextID(), c4d.BFH_SCALE, 0, 1, "", 0 )
        self.AddButton( self.dialogIDs[ "SubmitButtonID" ], 0, 100, 0, "Submit" )
        self.AddButton( self.dialogIDs[ "CancelButtonID" ], 0, 100, 0, "Cancel" )
        self.GroupEnd()
        
        return True
    
    ## This is called after the dialog has been initialized.
    def InitValues( self ):
        scene = documents.GetActiveDocument()
        frameRate = scene.GetFps()
        
        startFrame = 0
        endFrame = 0
        stepFrame = 0
        
        renderData = scene.GetActiveRenderData().GetDataInstance()
        frameMode = renderData.GetLong( c4d.RDATA_FRAMESEQUENCE )
        if frameMode == c4d.RDATA_FRAMESEQUENCE_MANUAL:
            startFrame = renderData.GetTime( c4d.RDATA_FRAMEFROM ).GetFrame( frameRate )
            endFrame = renderData.GetTime( c4d.RDATA_FRAMETO ).GetFrame( frameRate )
            stepFrame = renderData.GetLong( c4d.RDATA_FRAMESTEP )
        elif frameMode == c4d.RDATA_FRAMESEQUENCE_CURRENTFRAME:
            startFrame = scene.GetTime().GetFrame( frameRate )
            endFrame = startFrame
            stepFrame = 1
        elif frameMode == c4d.RDATA_FRAMESEQUENCE_ALLFRAMES:
            startFrame = scene.GetMinTime().GetFrame( frameRate )
            endFrame = scene.GetMaxTime().GetFrame( frameRate )
            stepFrame = renderData.GetLong( c4d.RDATA_FRAMESTEP )
        elif frameMode == c4d.RDATA_FRAMESEQUENCE_PREVIEWRANGE:
            startFrame = scene.GetLoopMinTime().GetFrame( frameRate )
            endFrame = scene.GetLoopMaxTime().GetFrame( frameRate )
            stepFrame = renderData.GetLong( c4d.RDATA_FRAMESTEP )
        
        frameList = str( startFrame )
        if startFrame != endFrame:
            frameList = frameList + "-" + str( endFrame )
        if stepFrame > 1:
            frameList = frameList + "x" + str( stepFrame )
        
        initName = os.path.splitext( scene.GetDocumentName() )[0]
        initComment = ""
        initDepartment = ""
        
        initPool = "none"
        initSecondaryPool = " " # Needs to have a space
        initGroup = "none"
        initPriority = 50
        initMachineLimit = 0
        initTaskTimeout = 0
        initAutoTaskTimeout = False
        initConcurrentTasks = 1
        initLimitConcurrentTasks = True
        initIsBlacklist = False
        initMachineList = ""
        initLimitGroups = ""
        initDependencies = ""
        initOnComplete = "Nothing"
        initSubmitSuspended = False
        
        initUseTakeFrames = False
        initIncludeMainTake = False
        initFrames = frameList
        initChunkSize = 1
        initThreads = 0
        initBuild = "None"
        initSubmitScene = False
        initExportProject = False
        initLocalRendering = False
        initCloseOnSubmission = True
        initUseBatch = True

        initExporter = ""

        initExportJob = False
        initExportJobLocal = False
        initExportDependentJob = False

        initExportLocation = ""
        initExportPool = "none"
        initExportSecondaryPool = " " # Needs to have a space
        initExportGroup = "none"
        initExportPriority = 50
        initExportThreads = 0
        initExportTaskTimeout = 0
        initExportAutoTaskTimeout = False
        initExportConcurrentTasks = 1
        initExportLimitConcurrentTasks = True
        initExportMachineLimit = 0
        initExportMachineList = ""
        initExportIsBlacklist = False
        initExportLimitGroups = ""
        initExportOnComplete = "Nothing"
        initExportSubmitSuspended = False
        initExportDependencies = ""

        initEnableRegionRendering = False
        initTilesInX = 2
        initTilesInY = 2
        initSingleFrameTileJob = True
        initSingleFrameJobFrame = 0
        initSubmitDependentAssembly = True
        initCleanupTiles = False
        initErrorOnMissingTiles = True
        initAssembleTilesOver = "Blank Image"
        initBackgroundImage = ""
        initErrorOnMissingBackground = True
        initSelectedAssembleOver = 0

        initOutputOverride = ""
        initOutputMultipassOverride = ""

        initGPUsPerTask = 0
        initGPUsSelectDevices = ""

        initEnableAssetServerPrecaching = False
        
        # Read in sticky settings
        self.ConfigFile = os.path.join( self.DeadlineSettings, "c4d_py_submission.ini" )
        try:
            if os.path.isfile( self.ConfigFile ):
                config = ConfigParser.ConfigParser()
                config.read( self.ConfigFile )
                
                if config.has_section( "Sticky" ):
                    if config.has_option( "Sticky", "Department" ):
                        initDepartment = config.get( "Sticky", "Department" )
                    if config.has_option( "Sticky", "Pool" ):
                        initPool = config.get( "Sticky", "Pool" )
                    if config.has_option( "Sticky", "SecondaryPool" ):
                        initSecondaryPool = config.get( "Sticky", "SecondaryPool" )
                    if config.has_option( "Sticky", "Group" ):
                        initGroup = config.get( "Sticky", "Group" )
                    if config.has_option( "Sticky", "Priority" ):
                        initPriority = config.getint( "Sticky", "Priority" )
                    if config.has_option( "Sticky", "MachineLimit" ):
                        initMachineLimit = config.getint( "Sticky", "MachineLimit" )
                    if config.has_option( "Sticky", "LimitGroups" ):
                        initLimitGroups = config.get( "Sticky", "LimitGroups" )
                    if config.has_option( "Sticky", "ConcurrentTasks" ):
                        initConcurrentTasks = config.getint( "Sticky", "ConcurrentTasks" )
                    if config.has_option( "Sticky", "IsBlacklist" ):
                        initIsBlacklist = config.getboolean( "Sticky", "IsBlacklist" )
                    if config.has_option( "Sticky", "MachineList" ):
                        initMachineList = config.get( "Sticky", "MachineList" )
                    if config.has_option( "Sticky", "SubmitSuspended" ):
                        initSubmitSuspended = config.getboolean( "Sticky", "SubmitSuspended" )
                    if config.has_option( "Sticky", "ChunkSize" ):
                        initChunkSize = config.getint( "Sticky", "ChunkSize" )

                    if config.has_option( "Sticky", "IncludeMainTake" ):
                        initIncludeMainTake = config.getboolean( "Sticky", "IncludeMainTake" )
                    if config.has_option( "Sticky", "OutputOverride" ):
                        initOutputOverride = config.get( "Sticky", "OutputOverride" )
                    if config.has_option( "Sticky", "OutputMultipassOverride" ):
                        initOutputMultipassOverride = config.get( "Sticky", "OutputMultipassOverride" )
                    if config.has_option( "Sticky", "UseTakeFrames" ):
                        initUseTakeFrames = config.getboolean( "Sticky", "UseTakeFrames" )
                    if config.has_option( "Sticky", "SubmitScene" ):
                        initSubmitScene = config.getboolean( "Sticky", "SubmitScene" )
                    if config.has_option( "Sticky", "Threads" ):
                        initThreads = config.getint( "Sticky", "Threads" )
                    if config.has_option( "Sticky", "ExportProject" ):
                        initExportProject = config.getboolean( "Sticky", "ExportProject" )
                    if config.has_option( "Sticky", "Build" ):
                        initBuild = config.get( "Sticky", "Build" )
                    if config.has_option( "Sticky", "LocalRendering" ):
                        initLocalRendering = config.getboolean( "Sticky", "LocalRendering" )
                    if config.has_option( "Sticky", "CloseOnSubmission" ):
                        initCloseOnSubmission = config.getboolean( "Sticky", "CloseOnSubmission" )
                    if config.has_option( "Sticky", "UseBatchPlugin" ):
                        initUseBatch = config.getboolean( "Sticky", "UseBatchPlugin" )

                    if config.has_option( "Sticky", "ExportJob" ):
                        initExportJob = config.getboolean( "Sticky", "ExportJob" )
                    if config.has_option( "Sticky", "ExportDependentJob" ):
                        initExportDependentJob = config.getboolean( "Sticky", "ExportDependentJob" )
                    if config.has_option( "Sticky", "LocalExport" ):
                        initExportJobLocal = config.getboolean( "Sticky", "LocalExport" )
                    if config.has_option( "Sticky", "ExportPool" ):
                        initExportPool = config.get( "Sticky", "ExportPool" )
                    if config.has_option( "Sticky", "ExportSecondaryPool" ):
                        initExportSecondaryPool = config.get( "Sticky", "ExportSecondaryPool" )
                    if config.has_option( "Sticky", "ExportGroup" ):
                        initExportGroup = config.get( "Sticky", "ExportGroup" )
                    if config.has_option( "Sticky", "ExportPriority" ):
                        initExportPriority = config.getint( "Sticky", "ExportPriority" )
                    if config.has_option( "Sticky", "ExportMachineLimit" ):
                        initExportMachineLimit = config.getint( "Sticky", "ExportMachineLimit" )
                    if config.has_option( "Sticky", "ExportLimitGroups" ):
                        initExportLimitGroups = config.get( "Sticky", "ExportLimitGroups" )
                    if config.has_option( "Sticky", "ExportIsBlacklist" ):
                        initExportIsBlacklist = config.getboolean( "Sticky", "ExportIsBlacklist" )
                    if config.has_option( "Sticky", "ExportMachineList" ):
                        initExportMachineList = config.get( "Sticky", "ExportMachineList" )
                    if config.has_option( "Sticky", "ExportSubmitSuspended" ):
                        initExportSubmitSuspended = config.getboolean( "Sticky", "ExportSubmitSuspended" )
                    if config.has_option( "Sticky", "ExportThreads" ):
                        initExportThreads = config.getint( "Sticky", "ExportThreads" )
                    if config.has_option( "Sticky", "ExportOutputLocation" ):
                        initExportLocation = config.get( "Sticky", "ExportOutputLocation" )    

                    if config.has_option( "Sticky", "EnableRegionRendering" ):
                        initEnableRegionRendering = config.getboolean( "Sticky", "EnableRegionRendering" )
                    if config.has_option( "Sticky", "TilesInX" ):
                        initTilesInX = config.getint( "Sticky", "TilesInX" )
                    if config.has_option( "Sticky", "TilesInY" ):
                        initTilesInY = config.getint( "Sticky", "TilesInY" )
                    if config.has_option( "Sticky", "SingleFrameTileJob" ):
                        initSingleFrameTileJob = config.getboolean( "Sticky", "SingleFrameTileJob" )
                    if config.has_option( "Sticky", "SingleFrameJobFrame" ):
                        initSingleFrameJobFrame = config.getint( "Sticky", "SingleFrameJobFrame" )
                    if config.has_option( "Sticky", "SubmitDependentAssembly" ):
                        initSubmitDependentAssembly = config.getboolean( "Sticky", "SubmitDependentAssembly" )
                    if config.has_option( "Sticky", "CleanupTiles" ):
                        initCleanupTiles = config.getboolean( "Sticky", "CleanupTiles" )
                    if config.has_option( "Sticky", "ErrorOnMissingTiles" ):
                        initErrorOnMissingTiles = config.getboolean( "Sticky", "ErrorOnMissingTiles" )
                    if config.has_option( "Sticky", "AssembleTilesOver" ):
                        initAssembleTilesOver = config.get( "Sticky", "AssembleTilesOver" )
                    if config.has_option( "Sticky", "BackgroundImage" ):
                        initBackgroundImage = config.get( "Sticky", "BackgroundImage" )
                    if config.has_option( "Sticky", "ErrorOnMissingBackground" ):
                        initErrorOnMissingBackground = config.getboolean( "Sticky", "ErrorOnMissingBackground" )
                    if config.has_option( "Sticky", "SelectedAssembleOver" ):
                        initSelectedAssembleOver = config.getint( "Sticky", "SelectedAssembleOver" )    

                    if config.has_option( "Sticky", "GPUsPerTask" ):
                        initGPUsPerTask = config.getint( "Sticky", "GPUsPerTask" )
                    if config.has_option( "Sticky", "GPUsSelectDevices" ):
                        initGPUsSelectDevices = config.get( "Sticky", "GPUsSelectDevices" )

                    if config.has_option( "Sticky", "EnableAssetServerPrecaching" ):
                        initEnableAssetServerPrecaching = config.getboolean( "Sticky", "EnableAssetServerPrecaching" )
        except:
            print( "Could not read sticky settings:\n" + traceback.format_exc() )
        
        if initPriority > self.MaximumPriority:
            initPriority = self.MaximumPriority // 2
       
        # Populate the combo boxes, and figure out the default selected index if necessary.       
        selectedPoolID = self.setComboBoxOptions( self.Pools, self.dialogIDs[ "PoolBoxID" ], initPool )
        selectedSecondaryPoolID = self.setComboBoxOptions( self.SecondaryPools, self.dialogIDs[ "SecondaryPoolBoxID" ], initSecondaryPool )
        selectedGroupID = self.setComboBoxOptions( self.Groups, self.dialogIDs[ "GroupBoxID" ], initGroup )
        selectedOnCompleteID = self.setComboBoxOptions( self.OnComplete, self.dialogIDs[ "OnCompleteBoxID" ], initOnComplete )
        selectedBuildID = self.setComboBoxOptions( self.Builds, self.dialogIDs[ "BuildBoxID" ], initBuild )
        self.setComboBoxOptions( self.Takes, self.dialogIDs[ "TakesBoxID" ], "Active" )

        # Populate the Export combo boxes, and figure out the default selected index if necessary.
        selectExportJobTypeID = self.setComboBoxOptions( self.Exporters, self.dialogIDs[ "ExportJobTypesID" ], initExporter )
        selectedExportPoolID = self.setComboBoxOptions( self.Pools, self.dialogIDs[ "ExportPoolBoxID" ], initExportPool )
        selectedExportSecondaryPoolID = self.setComboBoxOptions( self.SecondaryPools, self.dialogIDs[ "ExportSecondaryPoolBoxID" ], initExportSecondaryPool )
        selectedExportGroupID = self.setComboBoxOptions( self.Groups, self.dialogIDs[ "ExportGroupBoxID" ], initExportGroup )
        selectedExportOnCompleteID = self.setComboBoxOptions( self.OnComplete, self.dialogIDs[ "ExportOnCompleteBoxID" ], initExportOnComplete )
        
        selectedAssembleOverID = self.setComboBoxOptions( self.AssembleOver, self.dialogIDs[ "AssembleTilesOverID" ], initSelectedAssembleOver )

        self.Enable( self.dialogIDs[ "TakesBoxID" ], useTakes )
        self.Enable( self.dialogIDs[ "IncludeMainBoxID" ], useTakes )
        self.Enable( self.dialogIDs[ "TakeFramesBoxID" ], useTakes )

        # Set the default settings.
        self.SetString( self.dialogIDs[ "NameBoxID" ], initName )
        self.SetString( self.dialogIDs[ "CommentBoxID" ], initComment )
        self.SetString( self.dialogIDs[ "DepartmentBoxID" ], initDepartment )

        self.SetLong( self.dialogIDs[ "PoolBoxID" ], selectedPoolID )
        self.SetLong( self.dialogIDs[ "SecondaryPoolBoxID" ], selectedSecondaryPoolID )
        self.SetLong( self.dialogIDs[ "GroupBoxID" ], selectedGroupID )
        self.SetLong( self.dialogIDs[ "PriorityBoxID" ], initPriority, 0, self.MaximumPriority, 1 )
        self.SetLong( self.dialogIDs[ "MachineLimitBoxID" ], initMachineLimit )
        self.SetLong( self.dialogIDs[ "TaskTimeoutBoxID" ], initTaskTimeout )
        self.SetBool( self.dialogIDs[ "AutoTimeoutBoxID" ], initAutoTaskTimeout )
        self.SetLong( self.dialogIDs[ "ConcurrentTasksBoxID" ], initConcurrentTasks )
        self.SetBool( self.dialogIDs[ "LimitConcurrentTasksBoxID" ], initLimitConcurrentTasks )
        self.SetBool( self.dialogIDs[ "IsBlacklistBoxID" ], initIsBlacklist )
        self.SetString( self.dialogIDs[ "MachineListBoxID" ], initMachineList )
        self.SetString( self.dialogIDs[ "LimitGroupsBoxID" ], initLimitGroups )
        self.SetString( self.dialogIDs[ "DependenciesBoxID" ], initDependencies )
        self.SetLong( self.dialogIDs[ "OnCompleteBoxID" ], selectedOnCompleteID )
        self.SetBool( self.dialogIDs[ "SubmitSuspendedBoxID" ], initSubmitSuspended )
        self.SetLong( self.dialogIDs[ "ChunkSizeBoxID" ], initChunkSize )

        # Find current take in list of all takes
        self.SetLong( self.dialogIDs[ "TakesBoxID" ], 0 )
        self.SetBool( self.dialogIDs[ "IncludeMainBoxID" ], initIncludeMainTake )
        self.SetString( self.dialogIDs[ "FramesBoxID" ], initFrames )
        self.SetBool( self.dialogIDs[ "TakeFramesBoxID" ], initUseTakeFrames )
        self.SetBool( self.dialogIDs[ "SubmitSceneBoxID" ], initSubmitScene )
        self.SetLong( self.dialogIDs[ "ThreadsBoxID" ], initThreads )
        self.SetBool( self.dialogIDs[ "ExportProjectBoxID" ], initExportProject )
        self.SetLong( self.dialogIDs[ "BuildBoxID" ], selectedBuildID )
        self.SetBool( self.dialogIDs[ "LocalRenderingBoxID" ], initLocalRendering )
        self.SetBool( self.dialogIDs[ "CloseOnSubmissionID" ], initCloseOnSubmission )
        self.SetBool( self.dialogIDs[ "UseBatchBoxID" ], initUseBatch )

        self.SetBool( self.dialogIDs[ "EnableFrameStepBoxID" ], False )
        self.EnableFrameStep()
        self.Enable( self.dialogIDs[ "SubmitSceneBoxID" ], not initExportProject )
        self.Enable( self.dialogIDs[ "UseBatchBoxID" ], ( c4d.GetC4DVersion() / 1000 ) >= 15 )

        self.SetBool( self.dialogIDs[ "EnableRegionRenderingID" ], initEnableRegionRendering )
        self.SetLong( self.dialogIDs[ "TilesInXID" ], initTilesInX )
        self.SetLong( self.dialogIDs[ "TilesInYID" ], initTilesInY )
        self.SetBool( self.dialogIDs[ "SingleFrameTileJobID" ], initSingleFrameTileJob )
        self.SetLong( self.dialogIDs[ "SingleFrameJobFrameID" ], initSingleFrameJobFrame )
        self.SetBool( self.dialogIDs[ "SubmitDependentAssemblyID" ], initSubmitDependentAssembly )
        self.SetBool( self.dialogIDs[ "CleanupTilesID" ], initCleanupTiles )
        self.SetBool( self.dialogIDs[ "ErrorOnMissingTilesID" ], initErrorOnMissingTiles )
        self.SetLong( self.dialogIDs[ "AssembleTilesOverID" ], selectedAssembleOverID)
        self.SetString( self.dialogIDs[ "BackgroundImageID" ], initBackgroundImage )
        self.SetBool( self.dialogIDs[ "ErrorOnMissingBackgroundID" ], initErrorOnMissingBackground )

        self.EnableRegionRendering()

        self.SetString( self.dialogIDs[ "OutputOverrideID" ], initOutputOverride )
        self.SetString( self.dialogIDs[ "OutputMultipassOverrideID" ], initOutputMultipassOverride )

        self.SetLong( self.dialogIDs[ "GPUsPerTaskID" ], initGPUsPerTask )
        self.SetString( self.dialogIDs[ "SelectGPUDevicesID" ], initGPUsSelectDevices )

        self.SetBool( self.dialogIDs[ "EnableAssetServerPrecachingID" ], initEnableAssetServerPrecaching )

        self.EnableGPUAffinityOverride()

        self.SetString( self.dialogIDs[ "ExportLocationBoxID" ], initExportLocation )
        self.SetBool( self.dialogIDs[ "ExportJobID" ], initExportJob )
        if len( self.Exporters ) == 0:
            self.SetBool( self.dialogIDs[ "ExportJobID" ], False )
            self.Enable( self.dialogIDs[ "ExportJobID" ], False )
        self.EnableExportFields()

        self.SetBool( self.dialogIDs[ "ExportLocalID" ], initExportJobLocal )
        self.SetBool( self.dialogIDs[ "ExportDependentJobBoxID" ], initExportDependentJob )
        self.EnableDependentExportFields()

        self.SetLong( self.dialogIDs[ "ExportPoolBoxID" ], selectedExportPoolID )
        self.SetLong( self.dialogIDs[ "ExportSecondaryPoolBoxID" ], selectedExportSecondaryPoolID )
        self.SetLong( self.dialogIDs[ "ExportGroupBoxID" ], selectedExportGroupID )
        self.SetLong( self.dialogIDs[ "ExportPriorityBoxID" ], initExportPriority, 0, self.MaximumPriority, 1 )
        self.SetLong( self.dialogIDs[ "ExportThreadsBoxID" ], initExportThreads )
        self.SetLong( self.dialogIDs[ "ExportTaskTimeoutBoxID" ], initExportTaskTimeout )
        self.SetBool( self.dialogIDs[ "ExportAutoTimeoutBoxID" ], initExportAutoTaskTimeout )
        self.SetLong( self.dialogIDs[ "ExportConcurrentTasksBoxID" ], initExportConcurrentTasks )
        self.SetBool( self.dialogIDs[ "ExportLimitConcurrentTasksBoxID" ], initExportLimitConcurrentTasks )
        self.SetLong( self.dialogIDs[ "ExportMachineLimitBoxID" ], initExportMachineLimit )
        self.SetBool( self.dialogIDs[ "ExportIsBlacklistBoxID" ], initExportIsBlacklist )
        self.SetString( self.dialogIDs[ "ExportMachineListBoxID" ], initExportMachineList )
        self.SetString( self.dialogIDs[ "ExportLimitGroupsBoxID" ], initExportLimitGroups )
        self.SetLong( self.dialogIDs[ "ExportOnCompleteBoxID" ], selectedExportOnCompleteID )
        self.SetBool( self.dialogIDs[ "ExportSubmitSuspendedBoxID" ], initExportSubmitSuspended )

        #If 'CustomSanityChecks.py' exists, then it executes. This gives the user the ability to change default values
        self.SanityCheckFile = os.path.join( self.C4DSubmissionDir, "CustomSanityChecks.py" )
        if os.path.isfile( self.SanityCheckFile ):
            print( "Running sanity check script: " + self.SanityCheckFile )
            try:
                import CustomSanityChecks
                sanityResult = CustomSanityChecks.RunSanityCheck( self )
                if not sanityResult:
                    print( "Sanity check returned False, exiting" )
                    self.Close()
            except:
                gui.MessageDialog( "Could not run CustomSanityChecks.py script:\n" + traceback.format_exc() )

        statusMessage = self.retrievePipelineToolStatus()
        self.updatePipelineToolStatusLabel( statusMessage )

        self.EnableOutputOverrides()

        return True

    def setComboBoxOptions( self, options, dialogID, stickyValue ):
        selectedID = 0
        for i, option in enumerate( options ):
            self.AddChild( dialogID, i, option )
            if stickyValue == option:
                selectedID = i

        return selectedID

    def EnableExportFields( self ):
        exportEnabled = self.GetBool( self.dialogIDs[ "ExportJobID" ] )

        self.Enable( self.dialogIDs[ "ExportDependentJobBoxID" ], exportEnabled )
        self.Enable( self.dialogIDs[ "ExportJobTypesID" ], exportEnabled )
        self.Enable( self.dialogIDs[ "ExportLocationButtonID" ], exportEnabled )
        self.Enable( self.dialogIDs[ "ExportLocationBoxID" ], exportEnabled )

        self.EnableDependentExportFields()

    def EnableDependentExportFields( self ):
        dependentExportEnabled = self.GetBool( self.dialogIDs[ "ExportDependentJobBoxID" ] )
        exportJobEnabled = self.GetBool( self.dialogIDs[ "ExportJobID" ] )

        self.Enable( self.dialogIDs[ "ExportPoolBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportSecondaryPoolBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportGroupBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportPriorityBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportThreadsBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportTaskTimeoutBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportAutoTimeoutBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportConcurrentTasksBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportLimitConcurrentTasksBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportMachineLimitBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportIsBlacklistBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportMachineListBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportMachineListButtonID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportLimitGroupsBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportLimitGroupsButtonID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportOnCompleteBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportSubmitSuspendedBoxID" ], ( dependentExportEnabled and exportJobEnabled ) )
        self.Enable( self.dialogIDs[ "ExportLocalID" ], ( dependentExportEnabled and exportJobEnabled ) )

    def EnableFrameStep( self ):
        frameStepEnabled = self.GetBool( self.dialogIDs[ "EnableFrameStepBoxID" ] )
        
        isSingleTileJob = self.GetBool( self.dialogIDs[ "SingleFrameTileJobID" ] ) and self.IsRegionRenderingEnabled()
        self.Enable( self.dialogIDs[ "ChunkSizeBoxID" ], not frameStepEnabled and not isSingleTileJob )

    def IsGPUAffinityOverrideEnabled( self ):
        """
        A utility function to determine if the current renderer supports GPU Affinity Overrides
        :return: Whether or not any renderable take allows for gpu overrides.
        """
        return any(self.take_uses_gpu_renderer(t) for t in self.takes_to_render())

    def take_uses_gpu_renderer(self, take):
        """
        Determines if the the specified take uses a renderer that support gpu affinity.
        """

        rdata = deadlinec4d.takes.get_effective_renderdata(take)
        renderer_name = self.GetRendererName( rdata[c4d.RDATA_RENDERENGINE] )
        return renderer_name in self.gpuRenderers

    def EnableGPUAffinityOverride( self ):
        enabled = self.IsGPUAffinityOverrideEnabled()

        self.Enable( self.dialogIDs[ "GPUsPerTaskID" ], enabled )
        self.Enable( self.dialogIDs[ "SelectGPUDevicesID" ], enabled )

    def IsRegionRenderingEnabled( self ):
        return self.GetBool( self.dialogIDs[ "EnableRegionRenderingID" ] ) and self.GetBool( self.dialogIDs[ "UseBatchBoxID" ] )
    
    def EnableRegionRendering( self ):
        self.Enable( self.dialogIDs[ "EnableRegionRenderingID" ], self.GetBool( self.dialogIDs[ "UseBatchBoxID" ] ) )

        enable = self.IsRegionRenderingEnabled()
            
        self.Enable( self.dialogIDs[ "TilesInXID" ], enable )
        self.Enable( self.dialogIDs[ "TilesInYID" ], enable )
        self.Enable( self.dialogIDs[ "SingleFrameTileJobID" ], enable )
        self.Enable( self.dialogIDs[ "SubmitDependentAssemblyID" ], enable )
        self.Enable( self.dialogIDs[ "CleanupTilesID" ], enable )
        self.Enable( self.dialogIDs[ "ErrorOnMissingTilesID" ], enable )
        self.Enable( self.dialogIDs[ "AssembleTilesOverID" ], enable )
        
        self.IsSingleFrameTileJob()
        self.AssembleOverChanged()
        self.EnableOutputOverrides()

    def IsOutputOverrideEnabled( self ):
        return not self.GetBool( self.dialogIDs[ "ExportJobID" ] )
    
    def EnableOutputOverrides( self ):
        enable = self.IsOutputOverrideEnabled()

        self.Enable( self.dialogIDs[ "OutputOverrideID" ], enable )
        self.Enable( self.dialogIDs[ "OutputMultipassOverrideID" ], enable )

    def IsSingleFrameTileJob( self ):
        isSingleJob = self.GetBool( self.dialogIDs[ "SingleFrameTileJobID" ] ) and self.IsRegionRenderingEnabled()
            
        self.Enable( self.dialogIDs[ "SingleFrameJobFrameID" ], isSingleJob )
        self.Enable( self.dialogIDs[ "EnableFrameStepBoxID" ], not isSingleJob )
        self.Enable( self.dialogIDs[ "FramesBoxID" ], not isSingleJob )
        
        self.EnableFrameStep()
    
    def AssembleOverChanged( self ):
        assembleOver = self.GetLong( self.dialogIDs[ "AssembleTilesOverID" ] )
        if assembleOver == 0:
            self.Enable( self.dialogIDs[ "BackgroundImageID" ], False )
            self.Enable( self.dialogIDs[ "BackgroundImageButtonID" ], False )
            self.Enable( self.dialogIDs[ "ErrorOnMissingBackgroundID" ], False )
        elif assembleOver == 1:
            self.Enable( self.dialogIDs[ "BackgroundImageID" ], False )
            self.Enable( self.dialogIDs[ "BackgroundImageButtonID" ], False )
            self.Enable( self.dialogIDs[ "ErrorOnMissingBackgroundID" ], True )
        elif assembleOver == 2:
            self.Enable( self.dialogIDs[ "BackgroundImageID" ], True )
            self.Enable( self.dialogIDs[ "BackgroundImageButtonID" ], True )
            self.Enable( self.dialogIDs[ "ErrorOnMissingBackgroundID" ], True )
    
    def retrievePipelineToolStatus( self ):
        """
        Grabs a status message from the JobWriter that indicates which pipeline tools have settings enabled for the current scene.
        :return: A string representing the status of the pipeline tools for the current scene.
        """
        jobWriterPath = os.path.join( self.IntegrationDir, "JobWriter.py" )
        scenePath = documents.GetActiveDocument().GetDocumentPath()
        args = [ "-ExecuteScript", jobWriterPath, "Cinema4D", "--status", "--scene-path", scenePath ]
        statusMessage = CallDeadlineCommand( args )

        return statusMessage

    def updatePipelineToolStatusLabel( self, statusMessage ):
        """
        Updates the pipeline tools status label with a non-empty status message as there's always a status associated with the pipeline tools.
        :param statusMessage: A non-empty string representing the status of the pipeline tools for the current scene.
        :return: None
        """
        if not statusMessage:
            raise ValueError( 'The status message for the pipeline tools label is not allowed to be empty.' )

        if statusMessage.startswith( "Error" ):
            self.SetString( self.dialogIDs[ "PipelineToolStatusID" ], "Pipeline Tools Error" )
            print( statusMessage )
        else:
            self.SetString( self.dialogIDs[ "PipelineToolStatusID" ], statusMessage )

    def OpenIntegrationWindow( self ):
        """
        Launches a graphical interface for the pipeline tools, attempts to grab local project management info from the scene, and updates the
        Pipeline Tools status label indicating which project management tools are being used.
        :return: None
        """
        if self.IntegrationDir not in sys.path:
            sys.path.append( self.IntegrationDir )

        try:
            import GetPipelineToolsInfo
            GetPipelineToolsInfo.getInfo( self.DeadlineTemp )
        except ImportError:
            print( "Failed to import GetPipelineToolsInfo.py." )
            print( traceback.format_exc() )

        print( "\nOpening Integration window" )
        integrationPath = os.path.join( self.IntegrationDir, "IntegrationUIStandAlone.py" )
        scenePath = documents.GetActiveDocument().GetDocumentPath()
        args = [ "-ExecuteScript", integrationPath, "-v", "2", "Cinema4D", "-d", "Shotgun", "FTrack", "NIM", "--path", scenePath ]
        statusMessage = CallDeadlineCommand( args, hideWindow=False, useArgFile=True )
        self.updatePipelineToolStatusLabel( statusMessage )

    def ConcatenatePipelineSettingsToJob( self, jobInfoPath, batchName ):
        """
        Concatenate pipeline tool settings for the scene to the .job file.
        :param jobInfoPath: Path to the .job file.
        :param batchName: Value of the 'batchName' job info entry, if it is required.
        :return: None
        """

        jobWriterPath = os.path.join( self.IntegrationDir, "JobWriter.py" )
        scenePath = documents.GetActiveDocument().GetDocumentPath()
        argArray = [ "-ExecuteScript", jobWriterPath, "Cinema4D", "--write", "--scene-path", scenePath, "--job-path",
                    jobInfoPath, "--batch-name", batchName ]
        CallDeadlineCommand( argArray, hideWindow=False, useArgFile=True )

    def SubmitDependentExportJob( self, renderer, jobIds, groupBatch, take ):
        """
        Submits the dependent render job for the current renderer following the export process
        :param renderer: string representation of the current renderer
        :param jobIds: a list of dependent job IDs
        :param groupBatch: boolean used to determine if we should batch the jobs
        :param take: the current take to render
        :return: the results from submitting the job via deadlinecommand
        """
        scene = documents.GetActiveDocument()
        jobName = self.GetString( self.dialogIDs[ "NameBoxID" ] )

        exportDependencies = ",".join( jobIds )

        renderInfo = self.GetRenderInfo( scene, take )
        renderData = renderInfo.GetDataInstance()

        if take:
            jobName += " - %s" % take.GetName()

        jobName += " - %s Standalone" % renderer

        scenePath = scene.GetDocumentPath()
        outputPath = self.getOutputPath( renderData, scenePath )

        outputFormat = renderData.GetLong( c4d.RDATA_FORMAT )
        outputDepth = renderData.GetLong( c4d.RDATA_FORMATDEPTH )
        outputNameFormat = renderData.GetLong( c4d.RDATA_NAMEFORMAT )

        print( "\nCreating %s standalone job info file" % renderer )
        exportJobInfoFile = os.path.join( self.DeadlineTemp, "%s_submit_info.job" % renderer.lower() )

        jobContents = {
            "Plugin" : renderer,
            "Name" : jobName,
            "Pool" : self.Pools[ self.GetLong( self.dialogIDs[ "ExportPoolBoxID" ] ) ],
            "SecondaryPool" : "",
            "Group" : self.Groups[ self.GetLong( self.dialogIDs[ "ExportGroupBoxID" ] ) ],
            "Priority" : self.GetLong( self.dialogIDs[ "ExportPriorityBoxID" ] ),
            "MachineLimit" : self.GetLong( self.dialogIDs[ "ExportMachineLimitBoxID" ] ),
            "TaskTimeoutMinutes" : self.GetLong( self.dialogIDs[ "ExportTaskTimeoutBoxID" ] ),
            "EnableAutoTimeout" : self.GetBool( self.dialogIDs[ "ExportAutoTimeoutBoxID" ] ),
            "ConcurrentTasks" : self.GetLong( self.dialogIDs[ "ExportConcurrentTasksBoxID" ] ),
            "LimitConcurrentTasksToNumberOfCpus" : self.GetBool( self.dialogIDs[ "ExportLimitConcurrentTasksBoxID" ] ),
            "LimitGroups" : self.GetString( self.dialogIDs[ "ExportLimitGroupsBoxID" ] ),
            "JobDependencies" : exportDependencies,
            "OnJobComplete" : self.OnComplete[ self.GetLong( self.dialogIDs[ "ExportOnCompleteBoxID" ] ) ],
            "IsFrameDependent" : True,
            "ChunkSize" : 1,
        }

        if groupBatch:
            jobContents[ "BatchName" ] = self.GetString( self.dialogIDs[ "NameBoxID" ] )

        # If it's not a space, then a secondary pool was selected.
        if self.SecondaryPools[ self.GetLong( self.dialogIDs[ "ExportSecondaryPoolBoxID" ] ) ] != " ":
            jobContents[ "SecondaryPool" ] = self.SecondaryPools[ self.GetLong( self.dialogIDs[ "ExportSecondaryPoolBoxID" ] ) ]

        if self.GetBool( self.dialogIDs[ "TakeFramesBoxID" ] ):
            framesPerSecond = renderData.GetReal( c4d.RDATA_FRAMERATE )
            startFrame = renderData.GetTime( c4d.RDATA_FRAMEFROM ).GetFrame( framesPerSecond )
            endFrame = renderData.GetTime( c4d.RDATA_FRAMETO ).GetFrame( framesPerSecond )
            frames = "%s-%s" % ( startFrame, endFrame )
        else:
            frames  = self.GetString( self.dialogIDs[ "FramesBoxID" ] )
        jobContents[ "Frames" ] = frames

        if self.GetBool( self.dialogIDs[ "ExportSubmitSuspendedBoxID" ] ):
            jobContents[ "InitialStatus" ] = "Suspended"

        if self.GetBool( self.dialogIDs[ "ExportIsBlacklistBoxID" ] ):
            jobContents[ "Blacklist" ] = self.GetString( self.dialogIDs[ "ExportMachineListBoxID" ] )
        else:
            jobContents[ "Whitelist" ] = self.GetString( self.dialogIDs[ "ExportMachineListBoxID" ] )

        outputFilename = self.GetOutputFileName( outputPath, outputFormat, outputNameFormat, take )
        if outputFilename:
            jobContents[ "OutputFilename0" ] = outputFilename

        self.writeInfoFile( exportJobInfoFile, jobContents )
        self.ConcatenatePipelineSettingsToJob( exportJobInfoFile, self.GetString( self.dialogIDs[ "NameBoxID" ] ) )

        print( "Creating %s standalone plugin info file" % renderer )
        exportPluginInfoFile = os.path.join( self.DeadlineTemp, "%s_plugin_info.job" % renderer.lower() )
        pluginContents = {}

        exportFilename = self.getExportFilename( renderer, take )

        if renderer == "Redshift":
            pluginContents[ "SceneFile" ] = exportFilename

        elif renderer == "Octane":
            octaneVideoPost = renderInfo.GetFirstVideoPost()
            while octaneVideoPost is not None and not self.GetRendererName( octaneVideoPost.GetType() ) == "octane":
                octaneVideoPost = octaneVideoPost.GetNext()

            # This shouldn't happen as we check all the settings before the submission.
            if not octaneVideoPost:
                errorMessage = "Failed to retrieve Octane Renderer Settings. Check if Octane Plugin was installed correctly."
                print( errorMessage )
                return errorMessage

            pluginContents[ "Version" ] = self.getOctaneVersion( scene )
            pluginContents[ "SceneFile" ] = exportFilename
            if outputPath:
                pluginContents[ "OutputFolder" ] = os.path.dirname( outputPath )

            outputExtension = self.GetExtensionFromFormat( outputFormat )
            pluginContents[ "FileFormat" ] = self.createOctaneFileFormat( outputExtension, outputDepth, octaneVideoPost[ c4d.VP_BUFFER_TYPE ] )

            pluginContents[ "SaveDeepImage" ] = bool( octaneVideoPost[ c4d.SET_PASSES_SAVE_DEEPIMAGE ] )
            pluginContents[ "SaveDenoisedMainPass" ] = octaneVideoPost[ c4d.VP_USE_DENOISED_BEAUTY ]

            saveRenderPasses = False
            if octaneVideoPost[ c4d.SET_PASSES_ENABLED ]:
                saveRenderPasses = True
                pluginContents[ "SaveAllPasses" ] = saveRenderPasses

                if outputExtension == "exr":
                    pluginContents[ "ExrCompressionType" ] = self.getOctaneCompression( octaneVideoPost[ c4d.SET_PASSES_EXR_COMPR ] )
                    pluginContents[ "SaveLayeredEXR" ] = bool( octaneVideoPost[ c4d.SET_PASSES_MULTILAYER ] )

            pluginContents[ "FilenameTemplate" ] = self.getFilenameTemplate( outputFilename, saveRenderPasses )

        else:
            pluginContents[ "InputFile" ] = exportFilename

        if renderer == "Arnold":
            pluginContents[ "Threads" ] = self.GetLong( self.dialogIDs[ "ExportThreadsBoxID" ] )
            pluginContents[ "CommandLineOptions" ] = ""
            pluginContents[ "Verbose" ] = 4

        self.writeInfoFile( exportPluginInfoFile, pluginContents )

        print( "Submitting %s standalone job" % renderer )
        c4d.StatusSetSpin()
        args = [ exportJobInfoFile, exportPluginInfoFile ]

        results = ""
        try:
            results = CallDeadlineCommand( args, useArgFile=True )
        except:
            results = "An error occurred while submitting the job to Deadline."
        
        print( results )
        return results

    def getOutputPath( self, renderData, scenePath ):
        """
        Returns the full path to the output. By default the path is taken from RenderData,
        but can be overridden if Output Override is enabled in the dialog UI.
        :param renderData: A C4D render data.
        :param scenePath: A full path to the scene.
        :return: A string that contains the full path to the output.
        """
        outputPath = renderData.GetFilename( c4d.RDATA_PATH )
        outputOverride = self.GetString( self.dialogIDs[ "OutputOverrideID" ] ).strip()
        if self.IsOutputOverrideEnabled() and len( outputOverride ) > 0:
            outputPath = outputOverride

        if not os.path.isabs( outputPath ):
            outputPath = os.path.join( scenePath, outputPath )
        
        return outputPath

    def vray5_sanity_checks(self, scene, takes):
        """
        Check if the V-Ray output path doesn't include a frame token and if V-Ray scene export is not enabled.
        Returns a list of error messages if any. Otherwise, returns an empty list.
        """
        errors = []
        export_scene_takes = []

        for take in takes:
            render_info = self.GetRenderInfo(scene, take)
            video_post = self.vray5_get_video_post(render_info)
            if video_post and video_post[c4d.VRAY_VP_COMMON_EXPORT_STD_SCENE_ENABLED]:
                export_scene_takes.append(take.GetName())

        if len(export_scene_takes) > 0:
            message = ("Deadline does not support exporting to a .vrscene file. "
                       "Disable exporting in V-Ray settings for the following takes: {}").format( ", ".join( export_scene_takes ) )
            errors.append(message)

        return errors

    def vray5_get_output_paths(self, scene, take, output_path, region_prefix=""):
        """
        Creates a list of all output filenames if V-Ray output filesystem is enabled.
        The list contains the full paths to all enabled rendered elements, separately saved alpha channel, denoiser image, etc.
        :param scene: A hook to the current scene.
        :param take: The take that is being rendered.
        :param output_path: The V-Ray 5 and higher output path from UI.
        :param region_prefix: The prefix to be used if region rendering is enabled.
        :return: A list of all output filenames with frame numbers replaced with ####.
        """
        render_info = self.GetRenderInfo( scene, take )
        video_post = self.vray5_get_video_post(render_info)
        use_vray_output = self.vray5_get_use_output_system(video_post)

        if not use_vray_output or not output_path:
            return []

        output_format = self.vray5_get_output_format(video_post)
        output_prefix, temp_output_extension = os.path.splitext( output_path )

        output_prefix = insert_before_substring(output_prefix, self.FRAME_TOKEN, region_prefix)
        output_prefix = output_prefix.replace(self.FRAME_TOKEN, self.FRAME_PLACEHOLDER)

        paths = []
        # Get RGB (normal) channel output path
        rgb_path = self.vray5_get_rgb_path(video_post, output_prefix, output_format)
        if rgb_path:
            paths.append(rgb_path)

        if self.vray5_save_multiple_files(video_post, output_format):
            # Get output paths of all enabled render elements.
            render_elements = self.vray5_get_render_elements(scene, video_post)
            for render_element in render_elements:
                # Replace spaces and dashes with underscores to match the V-Ray behavior.
                render_element = re.sub(r"[\s-]", "_", render_element)
                render_element_path = output_prefix
                for token in (self.PASS_TOKEN, self.USER_PASS_TOKEN):
                    render_element_path = render_element_path.replace(token, render_element)
                render_element_path += "." + output_format
                paths.append(render_element_path)

        return self.vray5_eval_tokens(paths, scene, take)

    def vray5_get_modified_output(self, render_info):
        """
        When rendering a single frame, V-Ray will not add frame prefix to the output filename.
        This causes issues even when submitting multiple frames for rendering,
        because Deadline will create a separate task for each frame with equal start_frame and end_frame.
        As start_frame and end_frame are equal, V-Ray will not append the frame number to the filename,
        so each render task will create output files with the same names and overwrite the previous files.
        In this function we add a Cinema4D frame and pass/userpass tokens to the V-Ray output filename if they are not present.
        These tokens will be separated by dots to follow the behavior of V-Ray when rendering with DCC.
        Example: Original V-Ray output is "C:\Output\vray" and modified would be "C:\Output\vray.$pass.$frame.dummy".
        """
        output_path = self.vray5_get_output_path(render_info)
        if not output_path:
            return None

        modified_output, temp_output_extension = os.path.splitext( output_path )

        if not any(token in modified_output for token in (self.PASS_TOKEN, self.USER_PASS_TOKEN)):
            modified_output += "." + self.PASS_TOKEN

        if self.FRAME_TOKEN not in modified_output:
            modified_output += "." + self.FRAME_TOKEN

        # Output extension will be ignored by Cinema4D, so we just add here a dummy extension,
        # so Cinema4D doesn't throw away our frame suffix.
        if temp_output_extension:
            modified_output += temp_output_extension
        else:
            modified_output += ".dummy"

        return modified_output

    def vray5_get_rgb_path(self, video_post, output_prefix, output_format):
        """Returns the output filename for the main rgb pass if rgb pass should be saved. Otherwise, returns None."""
        rgb_path = None
        save_rgb = not bool(video_post[c4d.SETTINGSOUTPUT_IMG_DONTSAVERGBCHANNEL])
        # For exr and vrimg one file is always created. It will contain the main rgb pass and all the render elements.
        if output_format in ["exr", "vrimg"] or save_rgb:
            rgb_path = output_prefix
            # Remove pass or userpass tokens with an optional preceding dot.
            for token in (self.PASS_TOKEN, self.USER_PASS_TOKEN):
                rgb_path = re.sub(r"\.?%s" % re.escape(token), "", rgb_path)
            rgb_path += "." + output_format

        return rgb_path

    def vray5_save_multiple_files(self, video_post, output_format):
        """Returns false for multichannel exr or vrimg files. Otherwise, returns True."""
        if output_format == "vrimg":
            return False
        elif output_format == "exr" and video_post[c4d.SETTINGSEXR_OUTPUT_TYPE] == c4d.SETTINGSEXR_OUTPUT_TYPE_MULTICHANNEL:
            return False
        else:
            return True
    
    def vray5_get_render_elements(self, scene, video_post):
        """
        Returns a list of the names of each render element enabled in settings of V-Ray 5 and higher.
        :param scene: A hook to the current scene.
        :return: A list of names of the render elements.
        """
        mp_scene_hook = scene.FindSceneHook( self.VRAY_RENDER_ELEMENT_HOOK_ID )
        try:
            for branch in mp_scene_hook.GetBranchInfo():
                if branch['id'] == self.VRAY5_RENDER_ELEMENTS_ID:
                    head = branch['head']
                    break
            else:
                return []
        except AttributeError:
            # GetBranchInfo was exposed to python C4D R19
            return []

        VRAY5_MP_NODE_ISENABLED = 160011

        # Add all enabled V-Ray render elements
        channels = []
        channel_node = head.GetFirst()
        while channel_node:
            channel_data = channel_node.GetDataInstance()
            if channel_data[ VRAY5_MP_NODE_ISENABLED ]:
                channels.append( channel_node.GetName() )

            channel_node = channel_node.GetNext()

        # Add Alpha channel if saving Alpha as a separate file is enabled
        if video_post[c4d.SETTINGSOUTPUT_IMG_SEPARATEALPHA]:
            channels.append("Alpha")

        # Add denoiser and effectsResult if Denoiser is enabled
        if video_post[c4d.RENDERCHANNELDENOISER_ENABLED]:
            channels.append("denoiser")
            channels.append("effectsResult")

            # Add bumpNormals if NVIDIA AI Denoiser is selected
            if video_post[c4d.RENDERCHANNELDENOISER_ENGINE] == c4d.RENDERCHANNELDENOISER_ENGINE_NVIDIA_AI_DENOISER:
                channels.append("bumpNormals")

        return channels

    def vray5_eval_tokens(self, paths, doc, take):
        """Replace Cinema4D tokens (resolution, date, etc.) in V-Ray 5 output paths."""
        evaluated_paths = []
        if useTokens:
            rp_data = self.get_general_render_path_data( doc, take )
            evaluated_paths = [self.tokenSystem_eval( path, rp_data ) for path in paths]
        else:
            context = self.get_general_token_context( doc, take )
            evaluated_paths = [self.token_eval( path, context ) for path in paths]

        return evaluated_paths

    def vray5_get_video_post(self, render_info):
        """Return video post object for V-Ray 5 if available. Otherwise, return None."""
        video_post = render_info.GetFirstVideoPost()

        while video_post is not None and not self.GetRendererName( video_post.GetType() ) == "vray_5":
           video_post = video_post.GetNext()

        return video_post

    def vray5_get_use_output_system(self, video_post):
        """Return True if V-Ray output system is enabled. Otherwise, return False."""
        if video_post is not None:
            return video_post[c4d.VRAY_VP_OUTPUT_SETTINGS_USE_VRAY_VFB_OUTPUT]
        return False

    def vray5_get_output_path(self, render_info):
        """Return V-Ray output path if V-Ray output system is enabled. Otherwise, return None."""
        video_post = self.vray5_get_video_post(render_info)

        if self.vray5_get_use_output_system(video_post):
            return video_post[c4d.VRAY_VP_OUTPUT_SETTINGS_FILENAME]

        return None

    def vray5_get_output_format(self, video_post):
        """Return a string representation of V-Ray output format if V-Ray output system is enabled. Otherwise, return None."""
        if self.vray5_get_use_output_system(video_post):
            return self.vray5_get_format(video_post[c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT])

        return None

    def vray5_get_format(self, c4d_id, default_return="png"):
        """Converts Cinema4D ID for V-Ray file format into a readable string displayed in UI."""
        switcher = {
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_PNG: "png",
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_JPG: "jpg",
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_VRIMG: "vrimg",
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_HDR: "hdr",
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_EXR: "exr",
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_TGA: "tga",
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_BMP: "bmp",
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_SGI: "sgi",
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_TIF: "tif",
            c4d.VRAY_VP_OUTPUT_SETTINGS_FORMAT_VRST: "vrst",
        }

        return switcher.get(c4d_id, default_return)

    def vray5_create_dta_config_file(self, frame, render_data, output_name):
        """
        Creates a DTA config file used by tile rendering assembly jobs if V-Ray output system is used.
        :param frame: The frame number for which a config file will be created.
        :param render_data: The render settings object that we are pulling information from.
        :param output_name: The full path to the output file with #### instead of a frame number.
        :return: A name of the created config file.
        """
        # Partial function, that requires region prefix to be passed when called.
        get_region_output_filename_function = partial(insert_before_substring, output_name, self.FRAME_PLACEHOLDER)
        return self.create_dta_config_file(frame, render_data, output_name, get_region_output_filename_function)

    def create_dta_config_file(self, frame, render_data, output_name, get_region_output_filename_function):
        """
        Creates a tile rendering config file for the given frame.
        :param frame: The frame number for which a config file will be created.
        :param render_data: The render settings object that we are pulling information from.
        :param output_name: The full path to the output file with #### instead of a frame number.
        :param get_region_output_filename_function: The function called for each tile to retreive output filename.
        :return: A name of the created config file.
        """
        padded_frame = str(frame).zfill(4)

        padded_output_name = output_name.replace(self.FRAME_PLACEHOLDER, padded_frame)

        width = render_data.GetLong( c4d.RDATA_XRES )
        height = render_data.GetLong( c4d.RDATA_YRES )
        tiles_in_x = self.GetLong( self.dialogIDs[ "TilesInXID" ] )
        tiles_in_y = self.GetLong( self.dialogIDs[ "TilesInYID" ] )

        file_name, fileExtension = os.path.splitext( padded_output_name )
        
        date = time.strftime( "%Y_%m_%d_%H_%M_%S" )
        config_filename = "%s_%s_config_%s.txt" % ( file_name, frame, date )
        config_contents = {
            "ImageFileName" : padded_output_name,
            "ImageHeight" : height,
            "ImageWidth" : width,
            "TilesCropped" : False,
            "TileCount" : tiles_in_x * tiles_in_y,
        }

        background_type = self.AssembleOver[ self.GetLong( self.dialogIDs[ "AssembleTilesOverID" ] ) ]
        if background_type == "Previous Output":
            config_contents[ "BackgroundSource" ] = padded_output_name
        elif background_type == "Selected Image":
            background_image = self.GetString( self.dialogIDs[ "BackgroundImageID" ] )
            config_contents[ "BackgroundSource" ] = background_image

        curr_tile = 0
        region_num = 0
        for y in range( tiles_in_y ):
            for x in range( tiles_in_x ):
                left = ( float( x ) /tiles_in_x ) * width
                left = int( left + 0.5 )

                right = ( float( x + 1.0 ) /tiles_in_x ) * width
                right = int( right + 0.5 )
                tile_width = right - left

                top = ( float( y + 1 ) /tiles_in_y ) * height
                top = height - int( top + 0.5 )

                tile_height = int ( ( float( y + 1 ) /tiles_in_y ) * height +0.5 ) - int ( ( float( y ) /tiles_in_y ) * height +0.5 )

                region_prefix = "_region_%s_" % region_num
                region_output_filename = get_region_output_filename_function(region_prefix)
                region_output_filename = region_output_filename.replace( self.FRAME_PLACEHOLDER, padded_frame )

                config_contents["Tile%iFileName" % curr_tile] = region_output_filename
                config_contents["Tile%iX" % curr_tile] = left
                config_contents["Tile%iY" % curr_tile] = top
                config_contents["Tile%iWidth" % curr_tile] = tile_width
                config_contents["Tile%iHeight" % curr_tile] = tile_height

                curr_tile += 1
                region_num += 1

        self.writeInfoFile( config_filename, config_contents )

        return config_filename

    def getOctaneVersion( self, scene ):
        """
        Determines which version of Octane is used based on the installed Octane Live Plugin for Cinema4D.
        Also, it converts Octane version obtained from C4D into the version used by Deadline (e.g., 5 -> 2018).
        :param scene: C4D scene.
        :return: A single digit major version of Octane.
        """
        dataInstance = scene.GetDataInstance()
        containerInstance = dataInstance.GetContainerInstance( SubmitC4DToDeadlineDialog.OCTANE_LIVEPLUGIN_ID )
        # Job export from Cinema4D for Octane is supported only from version 4, that's why 4000000 is used as default.
        octaneVersion = containerInstance.GetLong( c4d.SET_OCTANE_VERSION, 4000000 )
        versionInC4D = str( octaneVersion // 1000000 )

        C4D_TO_DEADLINE_VERSION = { "5":"2018", "6":"2019", "10":"2020" }
        # Try to find the mapping in the dictionary. If there is no mapping, use version as is by default.
        versionInDeadline = C4D_TO_DEADLINE_VERSION.get(versionInC4D, versionInC4D)

        return versionInDeadline

    def getFilenameTemplate( self, outputFilename, saveRenderPasses ):
        """
        Constructs the filename template from the filename. The template is in the format used by Octane scripting.
        :param outputFilename: Output filename in any format: raw filename or full path, with or without an extension.
        :param saveRenderPasses: Determines if pass name should be added to the template.
        :return:
        """
        if not outputFilename:
            return "%n_%p_%f_%s.%e"

        outputFilename = re.sub( r"#{3,4}", "%F", outputFilename )
        template = ".%e"

        passPlaceholder = "%p"
        if saveRenderPasses and passPlaceholder not in outputFilename:
            template = "_" + passPlaceholder + template

        fullFilename = os.path.split( outputFilename )[ 1 ]
        return  os.path.splitext( fullFilename )[ 0 ] + template

    def getOctaneCompression( self, argument, defaultReturn="ZIP (lossless)" ):
        """Converts Cinema4D ID of selected compression into a string supported by Deadline Submitter."""
        switcher = {
            0: "Uncompressed",
            1: "RLE (lossless)",
            2: "ZIPS (lossless)",
            3: "ZIP (lossless)",
            4: "PIZ (lossless)",
            5: "PXR24 (lossy)",
            6: "B44 (lossy)",
            7: "B44A (lossy)",
            8: "DWAA (lossy)",
            9: "DWAB (lossy)"
        }

        return switcher.get(argument, defaultReturn)

    def createOctaneFileFormat( self, extension, depth, tonemap=3 ):
        """
        Create a string that is compatible with file formats used in Octane lua files.
        :param extension: Octane currently supports only "png" or "exr" formats. If the extension is not 'exr' - defaults to PNG.
        :param depth: Image depth in Cinema4d. 0 is 8 bit, 1 is 16 bit, 2 is 32 bit.
        :param tonemap: Should the output be tonemapped (tonemap==2) or not (other values). Used only if extension is "exr".
        :return: A string which represents the format supported by Octane LUA script. E.g., 'EXR (16-bit) Tonemapped'
        """
        if extension == "exr":
            if depth == 2:
                octaneFileFormat = "EXR (32-bit)"
            else:
                octaneFileFormat = "EXR (16-bit)"
            octaneFileFormat += " Tonemapped" if tonemap == 2 else " Untonemapped"
        else:
            if depth == 1:
                octaneFileFormat = "PNG (16-bit)"
            else:
                octaneFileFormat = "PNG (8-bit)"

        return octaneFileFormat

    def writeInfoFile( self, filename, fileContents ):
        """
        Creates a Deadline info file (job or plugin) at a specified filename using a dict containing the submission parameters
        :param filename: The path to the info file
        :param fileContents: A dictionary of submission key-value pairs to be written to the info file
        :return: None
        """
        # A list comprehension with a join statement on a newline doesn't work here, since we're mixing and matches types which
        # causes unicode decode issues. As such, iterating over the  items is the cleanest method that works in python 2 and 3.

        with open( filename, "wb" ) as fileHandle:
            for key, value in fileContents.items():
                line = "%s=%s\n" % ( key, value )
                if isinstance(line, unicode_type):
                    line = line.encode("utf-8")
                fileHandle.write( line )

    def getExportFilename( self, renderer, take ):
        """
        Builds up the export filename based on the renderer and the current take
        :param renderer: The renderer used for the render
        :param take: The current take
        :return: A string containing the resulting filename
        """
        exportFilename = self.GetString( self.dialogIDs[ "ExportLocationBoxID" ] )

        if not os.path.isabs( exportFilename ):
            scene = documents.GetActiveDocument()
            scenePath = scene.GetDocumentPath()
            exportFilename = os.path.join( scenePath, exportFilename )

        exportFilename, extension = os.path.splitext( exportFilename )

        exportFilename = "%s_%s" % ( exportFilename, take.GetName() )

        if renderer not in [ "Octane", "Redshift" ]:
            exportFilename += "."

        if renderer != "Octane":
            exportFilename += "0000"
        
        exportFilename += extension

        return exportFilename

    def WriteStickySettings( self ):
        print( "Writing sticky settings" )
        # Save sticky settings
        try:
            config = ConfigParser.ConfigParser()
            config.add_section( "Sticky" )

            config.set( "Sticky", "Department", self.GetString( self.dialogIDs[ "DepartmentBoxID" ] ) )
            config.set( "Sticky", "Pool", self.Pools[ self.GetLong( self.dialogIDs[ "PoolBoxID" ] ) ] )
            config.set( "Sticky", "SecondaryPool", self.SecondaryPools[ self.GetLong( self.dialogIDs[ "SecondaryPoolBoxID" ] ) ] )
            config.set( "Sticky", "Group", self.Groups[ self.GetLong( self.dialogIDs[ "GroupBoxID" ] ) ] )
            config.set( "Sticky", "Priority", str( self.GetLong( self.dialogIDs[ "PriorityBoxID" ] ) ) )
            config.set( "Sticky", "MachineLimit", str( self.GetLong( self.dialogIDs[ "MachineLimitBoxID" ] ) ) )
            config.set( "Sticky", "IsBlacklist", str( self.GetBool( self.dialogIDs[ "IsBlacklistBoxID" ] ) ) )
            config.set( "Sticky", "MachineList", self.GetString( self.dialogIDs[ "MachineListBoxID" ] ) )
            config.set( "Sticky", "ConcurrentTasks", str( self.GetLong( self.dialogIDs[ "ConcurrentTasksBoxID" ] ) ) )
            config.set( "Sticky", "LimitGroups", self.GetString( self.dialogIDs[ "LimitGroupsBoxID" ] ) )
            config.set( "Sticky", "SubmitSuspended", str( self.GetBool( self.dialogIDs[ "SubmitSuspendedBoxID" ] ) ) )
            config.set( "Sticky", "ChunkSize", str( self.GetLong( self.dialogIDs[ "ChunkSizeBoxID" ] ) ) )

            config.set( "Sticky", "IncludeMainTake", str( self.GetBool( self.dialogIDs[ "IncludeMainBoxID" ] ) ) )
            config.set( "Sticky", "UseTakeFrames", str( self.GetBool( self.dialogIDs[ "TakeFramesBoxID" ] ) ) )
            config.set( "Sticky", "SubmitScene", str( self.GetBool( self.dialogIDs[ "SubmitSceneBoxID" ] ) ) )
            config.set( "Sticky", "Threads", str( self.GetLong( self.dialogIDs[ "ThreadsBoxID" ] ) ) )
            config.set( "Sticky", "ExportProject", str( self.GetBool( self.dialogIDs[ "ExportProjectBoxID" ] ) ) )
            config.set( "Sticky", "Build", self.Builds[ self.GetLong( self.dialogIDs[ "BuildBoxID" ] ) ] )
            config.set( "Sticky", "LocalRendering", str( self.GetBool( self.dialogIDs[ "LocalRenderingBoxID" ] ) ) )
            config.set( "Sticky", "CloseOnSubmission", str( self.GetBool( self.dialogIDs[ "CloseOnSubmissionID" ] ) ) )
            config.set( "Sticky", "UseBatchPlugin", str( self.GetBool( self.dialogIDs[ "UseBatchBoxID" ] ) ) )

            config.set( "Sticky", "ExportJob", str( self.GetBool( self.dialogIDs[ "ExportJobID" ] ) ) )
            config.set( "Sticky", "ExportDependentJob", str( self.GetBool( self.dialogIDs[ "ExportDependentJobBoxID" ] ) ) )
            config.set( "Sticky", "LocalExport", str(self.GetBool( self.dialogIDs[ "ExportLocalID" ] ) ))
            config.set( "Sticky", "ExportPool", self.Pools[ self.GetLong( self.dialogIDs[ "ExportPoolBoxID" ] ) ] )
            config.set( "Sticky", "ExportSecondaryPool", self.SecondaryPools[ self.GetLong( self.dialogIDs[ "ExportSecondaryPoolBoxID" ] ) ] )
            config.set( "Sticky", "ExportGroup", self.Groups[ self.GetLong( self.dialogIDs[ "ExportGroupBoxID" ] ) ] )
            config.set( "Sticky", "ExportPriority", str( self.GetLong( self.dialogIDs[ "ExportPriorityBoxID" ] ) ) )
            config.set( "Sticky", "ExportMachineLimit", str( self.GetLong( self.dialogIDs[ "ExportMachineLimitBoxID" ] ) ) )
            config.set( "Sticky", "ExportIsBlacklist", str( self.GetBool( self.dialogIDs[ "ExportIsBlacklistBoxID" ] ) ) )
            config.set( "Sticky", "ExportMachineList", self.GetString( self.dialogIDs[ "ExportMachineListBoxID" ] ) )
            config.set( "Sticky", "ExportLimitGroups", self.GetString( self.dialogIDs[ "ExportLimitGroupsBoxID" ] ) )
            config.set( "Sticky", "ExportSubmitSuspended", str( self.GetBool( self.dialogIDs[ "ExportSubmitSuspendedBoxID" ] ) ) )
            config.set( "Sticky", "ExportThreads", str( self.GetLong( self.dialogIDs[ "ExportThreadsBoxID" ] ) ) )
            config.set( "Sticky", "ExportOutputLocation", self.GetString( self.dialogIDs[ "ExportLocationBoxID" ] ) )

            config.set( "Sticky", "EnableRegionRendering", str(self.GetBool( self.dialogIDs[ "EnableRegionRenderingID" ] ) ))
            config.set( "Sticky", "TilesInX", str( self.GetLong( self.dialogIDs[ "TilesInXID" ] ) ) )
            config.set( "Sticky", "TilesInY", str( self.GetLong( self.dialogIDs[ "TilesInYID" ] ) ) )
            config.set( "Sticky", "SingleFrameTileJob", str(self.GetBool( self.dialogIDs[ "SingleFrameTileJobID" ] ) ))
            config.set( "Sticky", "SingleFrameJobFrame", str( self.GetLong( self.dialogIDs[ "SingleFrameJobFrameID" ] ) ) )
            config.set( "Sticky", "SubmitDependentAssembly", str(self.GetBool( self.dialogIDs[ "SubmitDependentAssemblyID" ] ) ))
            config.set( "Sticky", "CleanupTiles", str(self.GetBool( self.dialogIDs[ "CleanupTilesID" ] ) ))
            config.set( "Sticky", "ErrorOnMissingTiles", str(self.GetBool( self.dialogIDs[ "ErrorOnMissingTilesID" ] ) ))
            config.set( "Sticky", "AssembleTilesOver", self.AssembleOver[ self.GetLong( self.dialogIDs[ "AssembleTilesOverID" ] ) ] )
            config.set( "Sticky", "BackgroundImage", self.GetString( self.dialogIDs[ "BackgroundImageID" ] ) )
            config.set( "Sticky", "ErrorOnMissingBackground", str(self.GetBool( self.dialogIDs[ "ErrorOnMissingBackgroundID" ] ) ))

            config.set( "Sticky", "OutputOverride", self.GetString( self.dialogIDs[ "OutputOverrideID" ] ) )
            config.set( "Sticky", "OutputMultipassOverride", self.GetString( self.dialogIDs[ "OutputMultipassOverrideID" ] ) )

            config.set( "Sticky" ,"GPUsPerTask", str( self.GetLong( self.dialogIDs[ "GPUsPerTaskID" ] ) ) )
            config.set( "Sticky", "GPUsSelectDevices", self.GetString( self.dialogIDs[ "SelectGPUDevicesID" ] ) )

            config.set( "Sticky", "EnableAssetServerPrecaching", str(self.GetBool( self.dialogIDs[ "EnableAssetServerPrecachingID" ] ) ))
            
            with open( self.ConfigFile, "w" ) as fileHandle:
                config.write( fileHandle )
        except:
            print( "Could not write sticky settings:\n" + traceback.format_exc() )

    def renderOutputSanityCheck( self, scene, takes ):
        """
        Make sure that render output is being saved and has a output defined. If multi-pass is enabled ensure it has
        output too.
        Check the following:
        If the output is set to be saved
        If the output has an output path set
        If there is an output path set, is the output path local

        If multi-pass is enabled do the same as above, but for the multi-pass output.

        Return a list of what's wrong.
        :param c4d.documents.BaseDocument -- scene: The scene to be submitted to Deadline
        :param String -- takes: The Cinema4D takes in the scene
        :return List: A list of warning messages related to render output
        """
        message = []

        def check_output_settings( save_image_container_id, output_path_container_id, is_multipass, take_name ):
            """
            Check if the render output settings are in a good state and add any issues to the list of warning messages.

            Container ids can be found here (https://developers.maxon.net/docs/Cinema4DPythonSDK/html/modules/c4d.documents/RenderData/index.html)
            :param int -- save_image_container_id:
            :param int -- output_path_container_id:
            :param bool -- is_multipass: Whether or not we are checking multipass output
            :param String -- take_name: The name the take to check
            """
            # If the takes name is "" or None it's because takes aren't being used. No need to include takes in the
            # messaging at that point.
            take_message = ' in the "{}" take'.format( take_name ) if take_name else ""
            message_prefix = ' multipass' if is_multipass else ""

            if not render_data.GetBool( save_image_container_id ):
                message.append( "The{} output image is not set to be saved{}.".format( message_prefix, take_message ) )
            else:
                output_path = render_data.GetFilename( output_path_container_id )

                if not output_path:
                    message.append( "The{} output image does not have a path set{}.".format( message_prefix, take_message ) )
                elif deadlinec4d.utils.is_path_local(output_path):
                    message.append(
                        "The{} output image path '{}'{} is local and may not be accessible by your render nodes.".format( message_prefix, output_path, take_message )
                    )

        for take in takes:
            render_data = self.GetRenderInfo( scene, take ).GetDataInstance()
            check_output_settings( save_image_container_id=c4d.RDATA_SAVEIMAGE, output_path_container_id=c4d.RDATA_PATH,
                                  is_multipass=False, take_name=take.GetName() )

            if render_data.GetBool( c4d.RDATA_MULTIPASS_ENABLE ):
                check_output_settings( save_image_container_id=c4d.RDATA_MULTIPASS_SAVEIMAGE,
                                      output_path_container_id=c4d.RDATA_MULTIPASS_FILENAME, is_multipass=True,
                                      take_name=take.GetName() )

        return message

    def SubmitJob( self ):

        takesToRender = self.takes_to_render()

        jobName = self.GetString( self.dialogIDs[ "NameBoxID" ] )
        comment = self.GetString( self.dialogIDs[ "CommentBoxID" ] )
        department = self.GetString( self.dialogIDs[ "DepartmentBoxID" ] )
        
        pool = self.Pools[ self.GetLong( self.dialogIDs[ "PoolBoxID" ] ) ]
        secondaryPool = self.SecondaryPools[ self.GetLong( self.dialogIDs[ "SecondaryPoolBoxID" ] ) ]
        group = self.Groups[ self.GetLong( self.dialogIDs[ "GroupBoxID" ] ) ]
        priority = self.GetLong( self.dialogIDs[ "PriorityBoxID" ] )
        machineLimit = self.GetLong( self.dialogIDs[ "MachineLimitBoxID" ] )
        taskTimeout = self.GetLong( self.dialogIDs[ "TaskTimeoutBoxID" ] )
        autoTaskTimeout = self.GetBool( self.dialogIDs[ "AutoTimeoutBoxID" ] )
        concurrentTasks = self.GetLong( self.dialogIDs[ "ConcurrentTasksBoxID" ] )
        limitConcurrentTasks = self.GetBool( self.dialogIDs[ "LimitConcurrentTasksBoxID" ] )
        isBlacklist = self.GetBool( self.dialogIDs[ "IsBlacklistBoxID" ] )
        machineList = self.GetString( self.dialogIDs[ "MachineListBoxID" ] )
        limitGroups = self.GetString( self.dialogIDs[ "LimitGroupsBoxID" ] )
        dependencies = self.GetString( self.dialogIDs[ "DependenciesBoxID" ] )
        onComplete = self.OnComplete[ self.GetLong( self.dialogIDs[ "OnCompleteBoxID" ] ) ]
        submitSuspended = self.GetBool( self.dialogIDs[ "SubmitSuspendedBoxID" ] )
        IncludeMainTake = self.GetBool( self.dialogIDs[ "IncludeMainBoxID" ] )

        frames = self.GetString( self.dialogIDs[ "FramesBoxID" ] )
        useTakeFrames = self.GetBool( self.dialogIDs[ "TakeFramesBoxID" ] )
        frameStepEnabled = self.GetBool( self.dialogIDs[ "EnableFrameStepBoxID" ] )
        frameStep = 1
        chunkSize = self.GetLong( self.dialogIDs[ "ChunkSizeBoxID" ] )
        threads = self.GetLong( self.dialogIDs[ "ThreadsBoxID" ] )
        build = self.Builds[ self.GetLong( self.dialogIDs[ "BuildBoxID" ] ) ]
        submitScene = self.GetBool( self.dialogIDs[ "SubmitSceneBoxID" ] )
        exportProject = self.GetBool( self.dialogIDs[ "ExportProjectBoxID" ] )
        localRendering = self.GetBool( self.dialogIDs[ "LocalRenderingBoxID" ] )
        useBatchPlugin = self.GetBool( self.dialogIDs[ "UseBatchBoxID" ] )
        disableOpenGl = self.GetBool( self.dialogIDs[ "OpenGLBoxID" ] )

        exportJob = self.GetBool( self.dialogIDs[ "ExportJobID" ] )
        if self.Exporters:
            exporter = self.Exporters[ self.GetLong( self.dialogIDs[ "ExportJobTypesID" ] ) ]
        dependentExport = self.GetBool( self.dialogIDs[ "ExportDependentJobBoxID" ] ) and exportJob
        localExport = self.GetBool( self.dialogIDs[ "ExportLocalID" ] ) and dependentExport
        exportFilename = self.GetString( self.dialogIDs[ "ExportLocationBoxID" ] )

        GPUsPerTask = self.GetLong( self.dialogIDs[ "GPUsPerTaskID" ] )
        GPUsSelectDevices = self.GetString( self.dialogIDs[ "SelectGPUDevicesID" ] )

        EnableRegionRendering = self.IsRegionRenderingEnabled()
        TilesInX = self.GetLong( self.dialogIDs[ "TilesInXID" ] )
        TilesInY = self.GetLong( self.dialogIDs[ "TilesInYID" ] )
        SingleFrameTileJob = self.GetBool( self.dialogIDs[ "SingleFrameTileJobID" ] )
        SingleFrameJobFrame = self.GetLong( self.dialogIDs[ "SingleFrameJobFrameID" ] )
        SubmitDependentAssembly = self.GetBool( self.dialogIDs[ "SubmitDependentAssemblyID" ] )
        CleanupTiles = self.GetBool( self.dialogIDs[ "CleanupTilesID" ] )
        ErrorOnMissingTiles = self.GetBool( self.dialogIDs[ "ErrorOnMissingTilesID" ] )
        AssembleTilesOver = self.AssembleOver[ self.GetLong( self.dialogIDs[ "AssembleTilesOverID" ] ) ]
        BackgroundImage = self.GetString( self.dialogIDs[ "BackgroundImageID" ] )
        ErrorOnMissingBackground = self.GetBool( self.dialogIDs[ "ErrorOnMissingBackgroundID" ] )

        EnableAssetServerPrecaching = self.GetBool( self.dialogIDs[ "EnableAssetServerPrecachingID" ] )

        regionJobCount = 1
        regionOutputCount = 1
        if EnableRegionRendering and not SingleFrameTileJob:
            regionJobCount = TilesInX * TilesInY
        if EnableRegionRendering and SingleFrameTileJob:
            regionOutputCount = TilesInX * TilesInY
        
        warningMessages = []
        errorMessages = []
        
        scene = documents.GetActiveDocument()
        sceneName = scene.GetDocumentName()
        scenePath = scene.GetDocumentPath()
        
        if exportProject:
            document = documents.GetActiveDocument()
            export_dir = deadlinec4d.utils.export_project(scene)
            if export_dir is None:
                return

            scenePath = export_dir
            submitScene = False

        sceneFilename = os.path.join( scenePath, sceneName )

        if deadlinec4d.utils.is_path_local( sceneFilename ) and not submitScene:
            warningMessages.append( "The c4d file %s is local and is not being submitted with the Job." %sceneFilename )

        warningMessages.extend( self.renderOutputSanityCheck( scene, takesToRender ) )
        errorMessages.extend( self.vray5_sanity_checks( scene, takesToRender ) )

        if exportJob:
            if exportFilename == "":
                errorMessages.append( "Export file location is blank. No scene files will be exported." )
            if exporter == "Arnold":
                if not hasArnoldDriver():
                    warningMessages.append( "The scene file does not contain an Arnold Driver node. The Arnold Scene created will not produce any Output." )
            if exporter == "Octane":
                if localExport:
                    errorMessages.append( "Local export is not supported when exporting to Octane Orbx. Uncheck 'Export Locally' to resolve this error." )
                if useBatchPlugin:
                    errorMessages.append( "The batch plugin does not support exporting to Octane Orbx. Disable 'Use Batch Plugin' to resolve this error." )

                warningsFromTakes, errorsFromTakes = self.checkOctaneSettingsForTakes( takesToRender, scene )
                warningMessages.extend( warningsFromTakes )
                errorMessages.extend( errorsFromTakes )

        if EnableRegionRendering and TilesInX * TilesInY > self.TaskLimit and SingleFrameTileJob:
            errorMessages.append( "Unable to submit a job with more tasks (%s) than the task limit (%s). Adjust 'Tiles In X' and 'Tiles In Y' so that their product is less than or equal to the task limit." % ( TilesInX * TilesInY, self.TaskLimit ) )

        if frameStepEnabled and not ( EnableRegionRendering and SingleFrameTileJob ):
            if "," in frames:
                errorMessages.append( "Unable to submit non contiguous frame ranges when submitting all frames as a single task." )
            else:
                match = re.search( r"x(\d+)", frames )
                if match is not None:
                    frameStep = int( match.group( 1 ) )
                    frames = re.sub( r"x\d+", "", frames )
        
        if errorMessages:
            errorMessages.insert( 0, "The following errors were detected:\n" )
            errorMessages.append( "\nPlease fix these issues and submit again." )
            gui.MessageDialog( "\n\n".join( errorMessages ) )
            return False
        
        if warningMessages:
            warningMessages.insert( 0, "The following warnings were detected:\n" )
            warningMessages.append( "\nDo you still wish to submit this job to Deadline?" )
            if not gui.QuestionDialog( "\n\n".join( warningMessages ) ):
                return False
        
        groupBatch = ( ( EnableRegionRendering and SubmitDependentAssembly ) or
                      ( dependentExport and not localExport ) or
                      ( len( takesToRender ) > 1 ) )
        
        renderData = scene.GetActiveRenderData().GetDataInstance()
        framesPerSecond = renderData.GetReal( c4d.RDATA_FRAMERATE )
        successes = 0
        failures = 0
        # Loop through the list of takes and submit them all
        for take in takesToRender:
            jobIds = []
            submissionSuccess = 0
            exportFilename = ""
            if exportJob:
                exportFilename = self.GetString( self.dialogIDs[ "ExportLocationBoxID" ] )
                exportFilename, extension = os.path.splitext( exportFilename )
                exportFilename = "%s_%s" % ( exportFilename, take.GetName() )
                
                if exporter == "Arnold":
                    exportFilename += "." + self.FRAME_PLACEHOLDER
                
                exportFilename += extension

            for jobRegNum in range( regionJobCount ):

                renderInfo = self.GetRenderInfo( scene, take )
                renderData = renderInfo.GetDataInstance()
                
                saveOutput = renderData.GetBool( c4d.RDATA_SAVEIMAGE )
                outputPath = self.getOutputPath( renderData, scenePath )

                outputFormat = renderData.GetLong( c4d.RDATA_FORMAT )
                outputNameFormat = renderData.GetLong( c4d.RDATA_NAMEFORMAT )
                alphaEnabled = renderData.GetBool( c4d.RDATA_ALPHACHANNEL )
                separateAlpha = renderData.GetBool( c4d.RDATA_SEPARATEALPHA )

                saveMP = renderData.GetBool( c4d.RDATA_MULTIPASS_ENABLE ) and renderData.GetBool( c4d.RDATA_MULTIPASS_SAVEIMAGE )
                mpPath = renderData.GetFilename( c4d.RDATA_MULTIPASS_FILENAME )
                outputMultipassOverride = self.GetString( self.dialogIDs[ "OutputMultipassOverrideID" ] ).strip()
                if len( outputMultipassOverride ) > 0:
                    mpPath = outputMultipassOverride

                if not os.path.isabs( mpPath ):
                    mpPath = os.path.join( scenePath, mpPath )

                mpFormat = renderData.GetLong( c4d.RDATA_MULTIPASS_SAVEFORMAT )
                mpSuffix = renderData.GetBool( c4d.RDATA_MULTIPASS_SUFFIX )
                mpUsers = False
                try:
                    mpUsers = renderData.GetBool( c4d.RDATA_MULTIPASS_USERNAMES )
                except:
                    pass
                width = renderData.GetLong( c4d.RDATA_XRES )
                height = renderData.GetLong( c4d.RDATA_YRES )
                
                if not localExport:
                    print( "Creating C4D submit info file" )
                    jobInfoFile = os.path.join( self.DeadlineTemp, "c4d_submit_info.job" )

                    tempJobName = jobName
                    take_name = take.GetName()
                    if not take_name == "Main":
                        tempJobName += " - " + take_name

                    if EnableRegionRendering and not SingleFrameTileJob:
                        tempJobName += " - Region " + str( jobRegNum )

                    jobContents = {
                        "Plugin" : "Cinema4D",
                        "Name" : tempJobName,
                        "Comment" : comment,
                        "Department" : department,
                        "Group" : group,
                        "Pool" : pool,
                        "SecondaryPool" : "",
                        "Priority" : priority,
                        "MachineLimit" : machineLimit,
                        "TaskTimeoutMinutes" : taskTimeout,
                        "EnableAutoTimeout" : autoTaskTimeout,
                        "ConcurrentTasks" : concurrentTasks,
                        "LimitConcurrentTasksToNumberOfCpus" : limitConcurrentTasks,
                        "LimitGroups" : limitGroups,
                        "JobDependencies" : dependencies,
                        "OnJobComplete" : onComplete,
                    }

                    if groupBatch:
                        jobContents[ "BatchName" ] = jobName

                    if useBatchPlugin and self.c4dMajorVersion >= 15:
                        jobContents[ "Plugin" ] = "Cinema4DBatch"

                    # If it's not a space, then a secondary pool was selected.
                    if secondaryPool != " ":
                        jobContents[ "SecondaryPool" ] = secondaryPool

                    if EnableRegionRendering and SingleFrameTileJob and not exportJob:
                        jobContents[ "TileJob" ] = True
                        jobContents[ "TileJobFrame" ] = SingleFrameJobFrame
                        jobContents[ "TileJobTilesInX" ] = TilesInX
                        jobContents[ "TileJobTilesInY" ] = TilesInY
                    else:
                        if useTakeFrames:
                            startFrame = renderData.GetTime( c4d.RDATA_FRAMEFROM ).GetFrame( int(framesPerSecond) )
                            endFrame = renderData.GetTime( c4d.RDATA_FRAMETO ).GetFrame( int(framesPerSecond) )
                            takeFrames = "%s-%s" % ( startFrame, endFrame )
                            jobContents[ "Frames" ] = takeFrames
                        else:
                            jobContents[ "Frames" ] = frames

                        if frameStepEnabled:
                            jobContents[ "ChunkSize" ] = 10000
                        else:
                            jobContents[ "ChunkSize" ] = chunkSize

                    if submitSuspended:
                        jobContents[ "InitialStatus" ] = "Suspended"

                    if isBlacklist:
                        jobContents[ "Blacklist" ] = machineList
                    else:
                        jobContents[ "Whitelist" ] = machineList

                    outputFilenameLine = False
                    outputDirectoryLine = False
                    outputFileCount = 0

                    vray5_output_path = self.vray5_get_modified_output(renderInfo)
                    if not exportJob:
                        for outputRegNum in range( regionOutputCount ):
                            regionPrefix = ""
                            if EnableRegionRendering:
                                if SingleFrameTileJob:
                                    regionPrefix = "_region_%s_" % outputRegNum
                                else:
                                    regionPrefix = "_region_%s_" % jobRegNum

                            if saveOutput and outputPath != "":
                                outputFilename = self.GetOutputFileName( outputPath, outputFormat, outputNameFormat, take, regionPrefix=regionPrefix )
                                if outputFilename:
                                    jobContents[ "OutputFilename%s" % outputFileCount ] = outputFilename
                                    outputFileCount += 1
                                    if alphaEnabled and separateAlpha:
                                        tempOutputFolder, tempOutputFile = os.path.split( outputFilename )

                                        jobContents[ "OutputFilename%s" % outputFileCount ] =  os.path.join( tempOutputFolder, "A_" + tempOutputFile )
                                        outputFileCount += 1
                                else:
                                    jobContents[ "OutputDirectory%s" % outputFileCount ] = os.path.dirname( outputPath )
                                    outputFileCount += 1

                            if saveMP and mpPath:
                                if self.isSingleMultipassFile( renderData ):
                                    mpFilename = self.GetOutputFileName( mpPath, mpFormat, outputNameFormat, take, isMulti = True, regionPrefix=regionPrefix )
                                    if mpFilename:
                                        jobContents["OutputFilename%s" % outputFileCount] = mpFilename
                                    else:
                                        jobContents[ "OutputDirectory%s" % outputFileCount ] = os.path.dirname( mpPath )

                                    outputFileCount += 1
                                else:
                                    for mPass, postEffect in self.getEachMultipass( take ):
                                        mpFilename = self.GetOutputFileName( mpPath, mpFormat, outputNameFormat, take, isMulti=True, mpass=mPass, mpassSuffix=mpSuffix, mpUsers=mpUsers,
                                                                             regionPrefix=regionPrefix, postEffect=postEffect )
                                        if mpFilename:
                                            jobContents[ "OutputFilename%s" % outputFileCount ] = mpFilename
                                        else:
                                            jobContents[ "OutputDirectory%s" % outputFileCount ] = os.path.dirname( mpPath )
                                        outputFileCount += 1

                            # Get any Renderer Specific output paths for V-Ray 5 and higher
                            for output_filename in self.vray5_get_output_paths(scene, take, vray5_output_path, region_prefix=regionPrefix):
                                jobContents[ "OutputFilename%s" % outputFileCount ] = output_filename
                                outputFileCount += 1

                    else:
                        if not os.path.isabs( exportFilename ):
                            scenePath = scene.GetDocumentPath()
                            exportFilename = os.path.join( scenePath, exportFilename )

                        jobContents[ "OutputDirectory%s" % outputFileCount ] = os.path.dirname( exportFilename )

                    if EnableAssetServerPrecaching:
                        for index, asset in enumerate( self.GetAllAssets( submitScene, sceneFilename ) ):
                            jobContents[ "AWSAssetFile%d" % index ] = asset

                    self.writeInfoFile( jobInfoFile, jobContents )

                    if not ( EnableRegionRendering and SubmitDependentAssembly ):
                        self.ConcatenatePipelineSettingsToJob( jobInfoFile, jobName )

                    print( "Creating C4D plugin info file" )
                    renderer = self.getRenderer( scene, take )
                    pluginInfoFile = os.path.join( self.DeadlineTemp, "c4d_plugin_info.job" )

                    pluginContents = {
                        "Version" : self.c4dMajorVersion,
                        "Build" : build,
                        "Threads" : threads,
                        "Width" : width,
                        "Height" : height,
                        "LocalRendering" : localRendering,
                        "Take" : take.GetName(),
                        "RegionRendering" : EnableRegionRendering,
                        "HasTexturePaths" : True,
                        "NoOpenGL" : disableOpenGl,
                    }

                    if not submitScene:
                        pluginContents[ "SceneFile" ] = sceneFilename

                    if self.take_uses_gpu_renderer(take):
                        pluginContents[ "GPUsPerTask" ] = GPUsPerTask
                        pluginContents[ "GPUsSelectDevices" ] = GPUsSelectDevices

                    if exportJob:
                        pluginContents[ "Renderer" ] = "%sExport" % exporter
                        pluginContents[ "ExportFile" ] = exportFilename
                    else:
                        if renderer:
                            pluginContents[ "Renderer" ] = renderer
                        if EnableRegionRendering:
                            if SingleFrameTileJob:
                                for outputRegNum in range( regionOutputCount ):
                                    tile_region = compute_tile_region(outputRegNum,
                                                                      TilesInX,
                                                                      TilesInY,
                                                                      height,
                                                                      width,
                                                                      renderer)

                                    pluginContents[ "RegionLeft%s" % outputRegNum ] = tile_region.left
                                    pluginContents[ "RegionRight%s" % outputRegNum ] = tile_region.right
                                    pluginContents[ "RegionTop%s" % outputRegNum ] = tile_region.top
                                    pluginContents[ "RegionBottom%s" % outputRegNum ] = tile_region.bottom

                                    if saveOutput and outputPath:
                                        path, prefix = os.path.split( outputPath )
                                        extlessPrefix, tempOutputExtension = os.path.splitext( prefix )
                                        # When AWS Portal generates the path mapping rules, it expects a trailing slash.
                                        pluginContents[ "FilePath" ] = os.path.join( path, '' ) 
                                        pluginContents[ "RegionPrefix%s" % outputRegNum ] = "%s_region_%s_" % ( extlessPrefix, outputRegNum )

                                    if saveMP and mpPath:
                                        path, prefix = os.path.split( mpPath )
                                        extlessPrefix, tempOutputExtension = os.path.splitext( prefix )
                                        # When AWS Portal generates the path mapping rules, it expects a trailing slash.
                                        pluginContents[ "MultiFilePath" ] = os.path.join( path, '' ) 
                                        pluginContents[ "MultiFileRegionPrefix%s" % outputRegNum ] = "%s_region_%s_" % ( extlessPrefix, outputRegNum )

                                    if vray5_output_path:
                                        path, prefix = os.path.split( vray5_output_path )
                                        # When AWS Portal generates the path mapping rules, it expects a trailing slash.
                                        pluginContents[ "VRay5FilePath" ] = os.path.join( path, '' )
                                        pluginContents[ "VRay5RegionPrefix%s" % outputRegNum ] = insert_before_substring(prefix, self.FRAME_TOKEN, "_region_%s_" % outputRegNum)

                            else:
                                tile_region = compute_tile_region(jobRegNum,
                                                                  TilesInX,
                                                                  TilesInY,
                                                                  height,
                                                                  width,
                                                                  renderer)

                                pluginContents[ "RegionLeft" ] = tile_region.left
                                pluginContents[ "RegionRight" ] = tile_region.right
                                pluginContents[ "RegionTop" ] = tile_region.top
                                pluginContents[ "RegionBottom" ] = tile_region.bottom

                                if saveOutput and outputPath:
                                    path, prefix = os.path.split( outputPath )
                                    extlessPrefix, tempOutputExtension = os.path.splitext( prefix )
                                    # When AWS Portal generates the path mapping rules, it expects a trailing slash.
                                    pluginContents[ "FilePath" ] = os.path.join( path, '' ) 
                                    pluginContents[ "FilePrefix" ] = "%s_region_%s_" % ( extlessPrefix, jobRegNum )

                                if saveMP and mpPath:
                                    path, prefix = os.path.split( mpPath )
                                    extlessPrefix, tempOutputExtension = os.path.splitext( prefix )
                                    # When AWS Portal generates the path mapping rules, it expects a trailing slash.
                                    pluginContents[ "MultiFilePath" ] = os.path.join( path, '' ) 
                                    pluginContents[ "MultiFilePrefix" ] = "%s_region_%s_" % ( extlessPrefix, jobRegNum )
                                
                                if vray5_output_path:
                                    path, prefix = os.path.split( vray5_output_path )
                                    # When AWS Portal generates the path mapping rules, it expects a trailing slash.
                                    pluginContents[ "VRay5FilePath" ] = os.path.join( path, '' )
                                    pluginContents[ "VRay5FilePrefix" ] = insert_before_substring(prefix, self.FRAME_TOKEN, "_region_%s_" % jobRegNum)
                        else:
                            if saveOutput and outputPath:
                                head, tail = os.path.split( outputPath )
                                # When AWS Portal generates the path mapping rules, it expects a trailing slash.
                                pluginContents[ "FilePath" ] = os.path.join( head, '' ) 
                                pluginContents[ "FilePrefix" ] = tail

                            if saveMP and mpPath:
                                head, tail = os.path.split( mpPath )
                                # When AWS Portal generates the path mapping rules, it expects a trailing slash.
                                pluginContents[ "MultiFilePath" ] = os.path.join( head, '' ) 
                                pluginContents[ "MultiFilePrefix" ] = tail
                            
                            if vray5_output_path:
                                head, tail = os.path.split( vray5_output_path )
                                # When AWS Portal generates the path mapping rules, it expects a trailing slash.
                                pluginContents[ "VRay5FilePath" ] = os.path.join( head, '' )
                                pluginContents[ "VRay5FilePrefix" ] = tail

                    if frameStepEnabled:
                        pluginContents[ "EnableFrameStep" ] = True
                        pluginContents[ "FrameStep" ] = frameStep

                    # Add the texture search paths, if they exist
                    for index, path in enumerate( self.getTextureSearchPaths() ):
                        pluginContents[ "TexturePath%s" % index ] = path

                    self.writeInfoFile( pluginInfoFile, pluginContents )

                    print( "Submitting job" )
                    c4d.StatusSetSpin()

                    args = [ jobInfoFile, pluginInfoFile ]
                    if submitScene:
                        args.append( sceneFilename )
                    
                    results = ""
                    try:
                        results = CallDeadlineCommand( args, useArgFile=True )
                        submissionSuccess += 1
                    except:
                        results = "An error occurred while submitting the job to Deadline."
                    
                    print( results )
                    
                    successfulSubmission = ( results.find( "Result=Success" ) != -1 )
                    
                    if successfulSubmission:
                        successes += 1
                        jobId = ""
                        resultArray = results.split()
                        for line in resultArray:
                            if line.startswith( "JobID=" ):
                                jobId = line.replace( "JobID=", "" )
                                break
                        if not jobId == "":
                            jobIds.append( jobId )
                            if EnableAssetServerPrecaching:
                                print( CallDeadlineCommand( [ "-AWSPortalPrecacheJob", jobId ] ) )
                    else:
                        failures += 1
                # Local Export
                elif localExport:
                    scene.GetTakeData().SetCurrentTake( take )

                    numExports = 1

                    if useTakeFrames:
                        startFrame = renderData.GetTime( c4d.RDATA_FRAMEFROM ).GetFrame( framesPerSecond )
                        endFrame = renderData.GetTime( c4d.RDATA_FRAMETO ).GetFrame( framesPerSecond )
                    else:
                        parsedFrameList = CallDeadlineCommand( [ "-ParseFrameList", self.GetString( self.dialogIDs[ "FramesBoxID" ] ), "False" ] ).strip()
                        parsedFrameList = parsedFrameList.split( "," )
                        numExports = len( parsedFrameList )

                    for i in range( 0, numExports ):
                        if not useTakeFrames:
                            startFrame = int( parsedFrameList[ i ] )
                            endFrame = int ( parsedFrameList[ i ] )

                        if exporter == "Arnold":
                            options = c4d.BaseContainer()
                            options.SetInt32( 6, startFrame )
                            options.SetInt32( 7, endFrame )

                            options.SetFilename( 0, exportFilename )
                            
                            scene.GetSettingsInstance( c4d.DOCUMENTSETTINGS_DOCUMENT ).SetContainer( SubmitC4DToDeadlineDialog.ARNOLD_ASS_EXPORT, options )
                         
                            c4d.CallCommand( SubmitC4DToDeadlineDialog.ARNOLD_ASS_EXPORT )

                        elif exporter == "Redshift":
                            plug = c4d.plugins.FindPlugin( SubmitC4DToDeadlineDialog.REDSHIFT_EXPORT_PLUGIN_ID, c4d.PLUGINTYPE_SCENESAVER )

                            op = {}
                            plug.Message( c4d.MSG_RETRIEVEPRIVATEDATA, op )
                            imexporter = op[ "imexporter" ]
                            imexporter[ c4d.REDSHIFT_PROXYEXPORT_AUTOPROXY_CREATE ] = False
                            imexporter[ c4d.REDSHIFT_PROXYEXPORT_ANIMATION_RANGE ] = c4d.REDSHIFT_PROXYEXPORT_ANIMATION_RANGE_MANUAL
                            imexporter[ c4d.REDSHIFT_PROXYEXPORT_ANIMATION_FRAME_START ] = startFrame
                            imexporter[ c4d.REDSHIFT_PROXYEXPORT_ANIMATION_FRAME_END ] = endFrame
                            imexporter[ c4d.REDSHIFT_PROXYEXPORT_ANIMATION_FRAME_STEP ] = 1

                            documents.SaveDocument( scene, exportFilename, c4d.SAVEDOCUMENTFLAGS_0, SubmitC4DToDeadlineDialog.REDSHIFT_EXPORT_PLUGIN_ID )

                if dependentExport:
                    results = self.SubmitDependentExportJob( exporter, jobIds, groupBatch, take )

                    successfulSubmission = ( results.find( "Result=Success" ) != -1 )
                    if successfulSubmission:
                        successes += 1
                        jobId = ""
                        resultArray = results.split()
                        for line in resultArray:
                            if line.startswith( "JobID=" ):
                                jobId = line.replace( "JobID=", "" )
                                break
                        if not jobId == "":
                            jobIds.append( jobId )
                    else:
                        failures+=1

            if EnableRegionRendering and SubmitDependentAssembly:
                if SingleFrameTileJob:
                    
                    configFiles = []
                    outputFiles = []
                    
                    paddedFrame = str(SingleFrameJobFrame)
                    while len( paddedFrame ) < 4:
                        paddedFrame = "0" + paddedFrame
                    
                    if saveOutput and outputPath:
                        configFiles.append( self.createDTAConfigFile( SingleFrameJobFrame, renderData, outputPath, outputFormat, outputNameFormat, take )  )
                        outputFile = self.GetOutputFileName( outputPath, outputFormat, outputNameFormat, take )
                        outputFiles.append( outputFile.replace( self.FRAME_PLACEHOLDER, paddedFrame ) )
                        
                        if alphaEnabled and separateAlpha:
                            configFiles.append( self.createDTAConfigFile( SingleFrameJobFrame, renderData, outputPath, outputFormat, outputNameFormat, take, isAlpha=True )  )
                            outputFile = self.GetOutputFileName( outputPath, outputFormat, outputNameFormat, take )
                            tempOutputFolder, tempOutputFile = os.path.split( outputFile )
                            outputFile = os.path.join( tempOutputFolder, "A_" + tempOutputFile )
                            outputFiles.append( outputFile.replace( self.FRAME_PLACEHOLDER, paddedFrame ) )
                        
                    if saveMP and mpPath:
                        if self.isSingleMultipassFile( renderData ):
                            configFiles.append( self.createDTAConfigFile( SingleFrameJobFrame, renderData, mpPath, mpFormat, outputNameFormat, take, isMulti=True )  )
                            outputFile = self.GetOutputFileName( mpPath, mpFormat, outputNameFormat, take, isMulti=True )
                            outputFiles.append( outputFile.replace( self.FRAME_PLACEHOLDER, paddedFrame ) )
                        else:
                            for mPass, postEffect in self.getEachMultipass( take ):
                                configFiles.append(
                                    self.createDTAConfigFile( SingleFrameJobFrame, renderData, mpPath, mpFormat, outputNameFormat, take, isMulti=True, mpass=mPass, mpassSuffix=mpSuffix,
                                                              mpUsers=mpUsers, postEffect=postEffect ) )
                                outputFile = self.GetOutputFileName( mpPath, mpFormat, outputNameFormat, take, isMulti=True, mpass=mPass, mpassSuffix=mpSuffix, mpUsers=mpUsers, postEffect=postEffect )
                                outputFiles.append( outputFile.replace( self.FRAME_PLACEHOLDER, paddedFrame ) )
                    
                    if vray5_output_path:
                        for output_filename in self.vray5_get_output_paths(scene, take, vray5_output_path):
                            configFiles.append( self.vray5_create_dta_config_file( SingleFrameJobFrame, renderData, output_filename ) )
                            outputFiles.append( output_filename.replace( self.FRAME_PLACEHOLDER, paddedFrame ) )

                    if self.submitDependentAssemblyJob( outputFiles, configFiles, successes + failures, jobIds ):
                        successes +=1
                    else:
                        failures += 1
                else:
                    frameListString = CallDeadlineCommand( [ "-ParseFrameList", self.GetString( self.dialogIDs[ "FramesBoxID" ] ), "False" ] ).strip()
                    frameList = frameListString.split( "," )
                    
                    if saveOutput and outputPath:
                        configFiles = []
                        outputFiles = []
                        for frame in frameList:
                            configFiles.append( self.createDTAConfigFile( frame, renderData, outputPath, outputFormat, outputNameFormat, take )  )
                            
                        outputFile = self.GetOutputFileName( outputPath, outputFormat, outputNameFormat, take )
                        outputFiles.append( outputFile )
                        
                        if self.submitDependentAssemblyJob( outputFiles, configFiles, successes + failures, jobIds ):
                            successes +=1
                        else:
                            failures += 1
                                                        
                        if alphaEnabled and separateAlpha:
                            
                            configFiles = []
                            outputFiles = []
                            for frame in frameList:
                                configFiles.append( self.createDTAConfigFile( frame, renderData, outputPath, outputFormat, outputNameFormat, take, isAlpha=True ) )
                                
                            outputFile = self.GetOutputFileName( outputPath, outputFormat, outputNameFormat, take )
                            tempOutputFolder, tempOutputFile = os.path.split( outputFile )
                            outputFile = os.path.join( tempOutputFolder, "A_" + tempOutputFile )
                            outputFiles.append( outputFile )
                            
                            if self.submitDependentAssemblyJob( outputFiles, configFiles, successes + failures, jobIds ):
                                successes +=1
                            else:
                                failures += 1

                    if saveMP and mpPath:
                        if self.isSingleMultipassFile( renderData ):
                            configFiles = []
                            outputFiles = []
                            
                            for frame in frameList:
                                configFiles.append( self.createDTAConfigFile( frame, renderData, mpPath, mpFormat, outputNameFormat, take, isMulti = True )  )
                            outputFile = self.GetOutputFileName( mpPath, mpFormat, outputNameFormat, take, isMulti = True )
                            outputFiles.append( outputFile )
                            
                            if self.submitDependentAssemblyJob( outputFiles, configFiles, successes + failures, jobIds ):
                                successes +=1
                            else:
                                failures += 1
                        else:

                            for mPass, postEffect in self.getEachMultipass( take ):
                                configFiles = []
                                outputFiles = []
                                for frame in frameList:
                                    configFiles.append(
                                        self.createDTAConfigFile( frame, renderData, mpPath, mpFormat, outputNameFormat, take, isMulti=True, mpass=mPass, mpassSuffix=mpSuffix, mpUsers=mpUsers,
                                                                    postEffect=postEffect ) )
                                outputFile = self.GetOutputFileName( mpPath, mpFormat, outputNameFormat, take, isMulti=True, mpass=mPass, mpassSuffix=mpSuffix, mpUsers=mpUsers,
                                                                        postEffect=postEffect )
                                outputFiles.append( outputFile )

                                if self.submitDependentAssemblyJob( outputFiles, configFiles, successes + failures, jobIds ):
                                    successes += 1
                                else:
                                    failures += 1

                    if vray5_output_path:
                        for output_filename in self.vray5_get_output_paths(scene, take, vray5_output_path):
                            configFiles = []
                            outputFiles = []
                            for frame in frameList:
                                configFiles.append( self.vray5_create_dta_config_file( frame, renderData, output_filename ) )

                            outputFiles.append( output_filename )

                            if self.submitDependentAssemblyJob( outputFiles, configFiles, successes + failures, jobIds ):
                                successes += 1
                            else:
                                failures += 1

        c4d.StatusClear()
        if successes + failures == 1:
            gui.MessageDialog( results )
        elif successes + failures > 1:
            gui.MessageDialog( "Submission Results\n\nSuccesses: " + str( successes ) + "\nFailures: " + str( failures ) + "\n\nSee script console for more details" )
        else:
            gui.MessageDialog( "Submission Failed. No takes selected." )
            return False
        
        return True

    def checkOctaneSettingsForTakes( self, takesToRender, scene ):
        """
        Checks all the Octane parameters supported by Deadline for all the input takes.
        If any settings are invalid - produces a corresponding error message.
        If any setting is not fully supported but has a meaningful default value - produces a corresponding warning.
        :param takesToRender: A collection of takes for which the settings will be checked.
        :param scene: A C4D scene.
        :return: A pair of warning and error messages constructed during the check.
        """
        videoPostErrorTakes = []
        denoisedAndAllPassesErrorTakes = []

        invalidBufferTakes = []
        deepImageTakesAndDirs = []
        formatAffectedTakes = []

        renderPassEnabledTakes = []
        customRenderPassTakesAndDirs = []
        unusedCompressionTakes = []
        multilayerTakes = []
        invalidCompressionTakes = []

        for take in takesToRender:
            renderInfo = self.GetRenderInfo( scene, take )
            renderData = renderInfo.GetDataInstance()

            octaneVideoPost = renderInfo.GetFirstVideoPost()
            while octaneVideoPost is not None and not self.GetRendererName( octaneVideoPost.GetType() ) == "octane":
                octaneVideoPost = octaneVideoPost.GetNext()

            if not octaneVideoPost:
                videoPostErrorTakes.append( take )
                continue

            if not self.validBufferType( octaneVideoPost ):
                invalidBufferTakes.append( take )

            outputPath = self.getOutputPath( renderData, scene.GetDocumentPath() )
            outupDirectory = os.path.dirname( outputPath )

            if self.usingCustomDeepImageName( octaneVideoPost ):
                deepImageTakesAndDirs.append( (outupDirectory, take) )

            outputFormat = renderData.GetLong( c4d.RDATA_FORMAT )
            outputExtension = self.GetExtensionFromFormat( outputFormat )

            if outputExtension not in [ "png", "exr" ]:
                formatAffectedTakes.append( take )

            checkResults = self.checkOctaneRenderPassesSettings( octaneVideoPost, outputExtension )
            if checkResults.DenoisedBeautyAndAllPasses:
                denoisedAndAllPassesErrorTakes.append( take )
            if checkResults.RenderPassesEnabled:
                renderPassEnabledTakes.append( take )
            if checkResults.CustomRenderPassName:
                customRenderPassTakesAndDirs.append( ( outupDirectory, take ) )
            if checkResults.CompressionEnabled:
                unusedCompressionTakes.append( take )
            if checkResults.MultilayerEnabled:
                multilayerTakes.append( take )
            if checkResults.UnrecognizedCompression:
                invalidCompressionTakes.append( take )

        warningMessages = []
        errorMessages = []

        if videoPostErrorTakes:
            errorMessages.append( self.getVideoPostError( videoPostErrorTakes ) )
        if denoisedAndAllPassesErrorTakes:
            errorMessages.append( self.getDenoisedAndAllPassesError( denoisedAndAllPassesErrorTakes ) )

        if invalidBufferTakes:
            warningMessages.append( self.getInvalidBufferWarning( invalidBufferTakes ) )
        if deepImageTakesAndDirs:
            warningMessages.append( self.getCustomDeepImageWarning( deepImageTakesAndDirs ) )
        if formatAffectedTakes:
            warningMessages.append( self.getInvalidExtensionWarning( formatAffectedTakes ) )

        if renderPassEnabledTakes:
            warningMessages.append( self.getRenderPassesEnabledWarning( renderPassEnabledTakes ) )
        if customRenderPassTakesAndDirs:
            warningMessages.append( self.getCustomRenderPassWarning( customRenderPassTakesAndDirs ) )
        if unusedCompressionTakes:
            warningMessages.append( self.getUnusedCompressionWarning( unusedCompressionTakes ) )
        if multilayerTakes:
            warningMessages.append( self.getMultilayerEnabledWarning( multilayerTakes ) )
        if invalidCompressionTakes:
            warningMessages.append( self.getInvalidCompressionWarning( invalidCompressionTakes ) )

        return warningMessages, errorMessages

    def validBufferType( self, octaneVideoPost ):
        """
        Checks if currently selected buffer type for octane is valid for Deadline submission.
        :param octaneVideoPost: C4D VideoPost object for Octane.
        :return: Returns True if selected buffer type is supported by Deadline. Returns False otherwise.
        """
        renderBufferType = octaneVideoPost[ c4d.VP_BUFFER_TYPE ]
        # 2 is Float (tonemapped). 3 is Float (Linear).
        return renderBufferType in [ 2, 3 ]

    def usingCustomDeepImageName( self, octaneVideoPost ):
        """
        Checks if the custom path for saving deep image was set in Octane options.
        :param octaneVideoPost: C4D VideoPost object for Octane.
        :return: Returns True if Deep Image Path is not empty. NOTE: Returns False if Save Deep Image is not checked.
        """
        saveDeepImageChecked = octaneVideoPost[ c4d.SET_PASSES_SAVE_DEEPIMAGE ]
        customDeepImageFile = octaneVideoPost[ c4d.SET_PASSES_DEEPIMAGE_SAVEPATH ]
        return saveDeepImageChecked and customDeepImageFile

    def checkOctaneRenderPassesSettings( self, octaneVideoPost, outputExtension ):
        """
        Checks all Octane options related to render passes if they are valid and supported by Deadline.
        :param octaneVideoPost: C4D VideoPost object for Octane.
        :param outputExtension: File format selected in the Save tab of C4D Render options.
        :return: Object of type CheckRenderPassesResult.
        """
        result = CheckRenderPassesResult()

        if octaneVideoPost[ c4d.SET_PASSES_ENABLED ]:
            if octaneVideoPost[ c4d.VP_USE_DENOISED_BEAUTY ]:
                result.DenoisedBeautyAndAllPasses = True
            else:
                result.RenderPassesEnabled = True

                renderPassFile = octaneVideoPost[ c4d.SET_PASSES_SAVEPATH ]
                if renderPassFile:
                    result.CustomRenderPassName = True

                if outputExtension != "exr":
                    if self.isExrRenderPassFormatForOctane( octaneVideoPost ):
                        result.CompressionEnabled = True

                        if octaneVideoPost[ c4d.SET_PASSES_MULTILAYER ]:
                            result.MultilayerEnabled = True
                elif self.isExrRenderPassFormatForOctane( octaneVideoPost ):
                    defaultReturn = "Invalid"
                    compression = self.getOctaneCompression( octaneVideoPost[ c4d.SET_PASSES_FILEFORMAT ], defaultReturn )
                    if compression == defaultReturn:
                        result.UnrecognizedCompression = True
        return result

    def isExrRenderPassFormatForOctane( self, octaneVideoPost ):
        """
        Checks if the output format for render passes in Octane options is set to EXR.
        :param octaneVideoPost: C4D VideoPost object for Octane.
        :return: Returns True if selected format for render passes is EXR. Returns False otherwise.
        """
        renderPassFormat = octaneVideoPost[ c4d.SET_PASSES_FILEFORMAT ]
        # 3 is EXR. 8 is EXR(Octane).
        return renderPassFormat in [ 3, 8 ]

    def getVideoPostError( self, videoPostErrorTakes ):
        """
        Creates an error message caused by missing Octane VideoPost object for given takes.
        :param videoPostErrorTakes: A list of take names that don't have Octane VideoPost object.
        :return: A string with an error message.
        """
        message = ( "Failed to retrieve Octane Renderer settings for the following takes: {}. "
                    "Check if Octane Plugin is installed correctly." ).format( ', '.join( videoPostErrorTakes ) )
        return message

    def getDenoisedAndAllPassesError( self, denoisedAndAllPassesErrorTakes ):
        """
        Creates an error message caused by enabling both render passes and denoised main pass for given takes.
        :param denoisedAndAllPassesErrorTakes: A list of take names that have invalid options.
        :return: A string with an error message.
        """
        message = ( "Both Use denoised beauty pass and Render Passes are enabled for the following takes: {}. "
                    "Disable one of them in Render Settings." ).format( ', '.join( denoisedAndAllPassesErrorTakes ) )
        return message

    def getInvalidBufferWarning( self, invalidBufferTakes ):
        """
        Creates a warning message caused by setting invalid buffer type for given takes.
        :param invalidBufferTakes: A list of take names that have invalid options.
        :return: A string with a warning message.
        """
        invalid_take_names = [take.GetName() for take in invalidBufferTakes]
        message = ( "The following takes are using unsupported Render Buffer Types and will default to 'Float (Linear)': {}. "
                    "To change it go to the Main tab in Render Settings for Octane Renderer." ).format(', '.join(invalid_take_names))
        return message

    def getCustomDeepImageWarning( self, deepImageTakesAndDirs ):
        """
        Creates a warning message caused by setting custom deep image path for given takes.
        :param deepImageTakesAndDirs: A list of take names that have invalid options.
        :return: A string with a warning message.
        """
        deepImageWarning = "Custom name for deep image is not supported by Deadline submission.\n"
        takeWarnings = [ "Deep image will be saved at {} for the take {}.".format( *p ) for p in deepImageTakesAndDirs ]
        allWarnings = "\n".join( takeWarnings )
        message = deepImageWarning + allWarnings
        return message

    def getInvalidExtensionWarning( self, formatAffectedTakes ):
        """
        Creates a warning message caused by setting invalid format for given takes.
        :param formatAffectedTakes: A list of take names that have invalid options.
        :return: A string with a warning message.
        """
        message = ( "The following takes are using unsupported output file formats and will default to PNG: {}. "
                    "To change the format go to the Save tab in Render Settings." ).format( ', '.join( formatAffectedTakes ) )
        return message

    def getRenderPassesEnabledWarning( self, renderPassEnabledTakes ):
        """
        Creates a warning message caused by enabling render passes for given takes.
        :param renderPassEnabledTakes: A list of take names that have invalid options.
        :return: A string with a warning message.
        """
        message = ( "Separate Format, Depth and Tonemap type for Render Passes are not supported by Deadline submission. "
                    "Format and Depth from the Save tab of Render Settings and Render Buffer Type from the Main tab of "
                    "Octane Renderer Render Settings will be used instead for the following takes: "
                    "{}." ).format( ', '.join( renderPassEnabledTakes ) )
        return message

    def getCustomRenderPassWarning( self, customRenderPassTakesAndDirs ):
        """
        Creates a warning message caused by setting a custom render passes path for given takes.
        :param customRenderPassTakesAndDirs: A list of take names that have invalid options.
        :return: A string with a warning message.
        """
        renderPassWarning = "Custom name for render pass file is not supported by Deadline submission.\n"
        takeWarnings = [ "Render pass will be saved at {} for the take {}.".format( *p ) for p in customRenderPassTakesAndDirs ]
        allWarnings = "\n".join( takeWarnings )
        message = renderPassWarning + allWarnings
        return message

    def getUnusedCompressionWarning( self, unusedCompressionTakes ):
        """
        Creates a warning message caused by selecting compression type for given takes.
        :param unusedCompressionTakes: A list of take names that have invalid options.
        :return: A string with a warning message.
        """
        message = ( "Compression won't be used for render pass files, because the file format is not OpenEXR. "
                    "Separate format for render passes is not supported by Deadline submission and is ignored. "
                    "Change the format in the Save tab in Render Settings to OpenEXR to allow compression for the following takes: "
                    "{}." ).format( ', '.join( unusedCompressionTakes ) )
        return message

    def getMultilayerEnabledWarning( self, multilayerTakes ):
        """
        Creates a warning message caused by enabling multilayer EXR saving option for given takes.
        :param multilayerTakes: A list of take names that have invalid options.
        :return: A string with a warning message.
        """
        message = ( "Render passes won't be saved into a multilayer file, because the file format is not OpenEXR. "
                    "Separate format for render passes is not supported by Deadline submission and is ignored. "
                    "Change the format to OpenEXR in the Save tab in Render Settings to save passes into a multilayer file "
                    "for the following takes: {}." ).format( ', '.join( multilayerTakes ) )
        return message

    def getInvalidCompressionWarning( self, invalidCompressionTakes ):
        """
        Creates a warning message caused by selecting invalid compression method for given takes.
        :param invalidCompressionTakes: A list of take names that have invalid options.
        :return: A string with a warning message.
        """
        message = ( "Selected compression is not supported by Deadline submission. "
                    "To change the compression go to the Main tab in Render Settings for Octane Renderer. "
                    "ZIP (lossless) will be used instead for the following takes: "
                    "{}." ).format( ', '.join( invalidCompressionTakes ) )
        return message

    def takes_to_render(self):
        """
        Determine which takes in the scene to render.
        If 'All' is selected render all of the takes in the scene. 
        If 'Marked' is selected then render all of the checked of takes in the scene.
        :return List: A list of the takes to render.
        """

        take_selection = self.Takes[self.GetLong( self.dialogIDs[ "TakesBoxID" ] ) ]

        if take_selection == "Active":
            return [deadlinec4d.takes.get_active_take()]
        elif take_selection == "All":
            include_main = self.GetBool( self.dialogIDs[ "IncludeMainBoxID" ] )
            return [x for x in deadlinec4d.takes.get_all_takes(include_main=include_main)]
        elif take_selection == 'Marked':
            return [x for x in deadlinec4d.takes.get_checked_takes()]
        return []

    def isSingleMultipassFile( self, renderData ):
        """
        Determine whether or not multipass renders will be saved into a single multilayer file or multiple individual files.
        :param renderData: The render settings object that we are pulling information from.
        :return: Whether a single file will be rendered or not.
        """

        mpFormat = renderData.GetLong( c4d.RDATA_MULTIPASS_SAVEFORMAT )
        mpOneFile = renderData.GetBool( c4d.RDATA_MULTIPASS_SAVEONEFILE )

        #Only B3D, PSD, PSB, TIF, and EXR files can be saved as a single image.
        return mpOneFile and mpFormat in ( c4d.FILTER_B3D, c4d.FILTER_PSD, c4d.FILTER_PSB, c4d.FILTER_TIF_B3D, c4d.FILTER_TIF, c4d.FILTER_EXR )

    
    # This is called when a user clicks on a button or changes the value of a field.
    def Command( self, id, msg ):
        # The Limit Group browse button was pressed.
        if id == self.dialogIDs[ "LimitGroupsButtonID" ]:
            c4d.StatusSetSpin()
            
            currLimitGroups = self.GetString( self.dialogIDs[ "LimitGroupsBoxID" ] )
            result = CallDeadlineCommand( [ "-selectlimitgroups", currLimitGroups ], hideWindow=False )
            result = result.replace( "\n", "" ).replace( "\r", "" )
            
            if result != "Action was cancelled by user":
                self.SetString( self.dialogIDs[ "LimitGroupsBoxID" ], result )
            
            c4d.StatusClear()
        
        # The Dependencies browse button was pressed.
        elif id == self.dialogIDs[ "DependenciesButtonID" ]:
            c4d.StatusSetSpin()
            
            currDependencies = self.GetString( self.dialogIDs[ "DependenciesBoxID" ] )
            result = CallDeadlineCommand( [ "-selectdependencies", currDependencies ], hideWindow=False )
            result = result.replace( "\n", "" ).replace( "\r", "" )
            
            if result != "Action was cancelled by user":
                self.SetString( self.dialogIDs[ "DependenciesBoxID" ], result )
            
            c4d.StatusClear()
        
        elif id == self.dialogIDs[ "MachineListButtonID" ]:
            c4d.StatusSetSpin()
            
            currMachineList = self.GetString( self.dialogIDs[ "MachineListBoxID" ] )
            result = CallDeadlineCommand( [ "-selectmachinelist", currMachineList ], hideWindow=False )
            result = result.replace( "\n", "" ).replace( "\r", "" )
            
            if result != "Action was cancelled by user":
                self.SetString( self.dialogIDs[ "MachineListBoxID" ], result )
            
            c4d.StatusClear()
        
        elif id == self.dialogIDs[ "ExportProjectBoxID" ]:
            self.Enable( self.dialogIDs[ "SubmitSceneBoxID" ], not self.GetBool( self.dialogIDs[ "ExportProjectBoxID" ] ) )
        
        elif id == self.dialogIDs[ "EnableFrameStepBoxID" ]:
            self.EnableFrameStep()

        elif id == self.dialogIDs[ "OutputOverrideButtonID" ]:
            c4d.StatusSetSpin()
            try:
                currTemplate = self.GetString( self.dialogIDs[ "OutputOverrideID" ] )
                if not os.path.isabs( currTemplate ):
                    scenePath = documents.GetActiveDocument().GetDocumentPath()
                    currTemplate = os.path.join( scenePath, currTemplate )

                result = CallDeadlineCommand( [ "-SelectFilenameSave", currTemplate ] )
                if result != "Action was cancelled by user" and result != "":
                    self.SetString( self.dialogIDs[ "OutputOverrideID" ], result )
            finally:
                c4d.StatusClear()

        elif id == self.dialogIDs[ "OutputMultipassOverrideButtonID" ]:
            c4d.StatusSetSpin()
            try:
                currTemplate = self.GetString( self.dialogIDs[ "OutputMultipassOverrideID" ] )
                if not os.path.isabs( currTemplate ):
                    scenePath = documents.GetActiveDocument().GetDocumentPath()
                    currTemplate = os.path.join( scenePath, currTemplate )
                
                result = CallDeadlineCommand( [ "-SelectFilenameSave", currTemplate ] )
                if result != "Action was cancelled by user" and result != "":
                    self.SetString( self.dialogIDs[ "OutputMultipassOverrideID" ], result )
            finally:
                c4d.StatusClear()

        elif id == self.dialogIDs[ "UseBatchBoxID" ]:
            self.EnableRegionRendering()
        
        elif id == self.dialogIDs[ "EnableRegionRenderingID" ]:
            self.EnableRegionRendering()
        
        elif id == self.dialogIDs[ "SingleFrameTileJobID" ]:
            self.IsSingleFrameTileJob()
        
        elif id == self.dialogIDs[ "AssembleTilesOverID" ]:
            self.AssembleOverChanged()
        
        elif id == self.dialogIDs[ "BackgroundImageButtonID" ]:
            backgroundImage = c4d.storage.LoadDialog( type=c4d.FILESELECTTYPE_IMAGES, title="Background Image" )
            if backgroundImage is not None:
                self.SetString(self.dialogIDs[ "BackgroundImageID" ], backgroundImage )
                
        elif id == self.dialogIDs[ "ExportJobID" ]:
            self.EnableExportFields()
            self.EnableOutputOverrides()

        elif id == self.dialogIDs[ "ExportDependentJobBoxID" ]:
            self.EnableDependentExportFields()

        elif id == self.dialogIDs[ "ExportMachineListButtonID" ]:
            c4d.StatusSetSpin()
            
            currMachineList = self.GetString( self.dialogIDs[ "ExportMachineListBoxID" ] )
            result = CallDeadlineCommand( [ "-selectmachinelist", currMachineList ], hideWindow=False )
            result = result.replace( "\n", "" ).replace( "\r", "" )
            
            if result != "Action was cancelled by user":
                self.SetString( self.dialogIDs[ "ExportMachineListBoxID" ], result )
            
            c4d.StatusClear()

        elif id == self.dialogIDs[ "ExportLimitGroupsButtonID" ]:
            c4d.StatusSetSpin()
            
            currLimitGroups = self.GetString( self.dialogIDs[ "ExportLimitGroupsBoxID" ] )
            result = CallDeadlineCommand( [ "-selectlimitgroups", currLimitGroups ], hideWindow=False )
            result = result.replace( "\n", "" ).replace( "\r", "" )
            
            if result != "Action was cancelled by user":
                self.SetString( self.dialogIDs[ "ExportLimitGroupsBoxID" ], result )
            
            c4d.StatusClear()

        elif id == self.dialogIDs[ "ExportLocationButtonID" ]:
            c4d.StatusSetSpin()
            exporter = self.Exporters[ self.GetLong( self.dialogIDs[ "ExportJobTypesID" ] ) ]
            exportFileType = self.exportFileTypeDict[exporter]

            try:
                currTemplate = self.GetString( self.dialogIDs[ "ExportLocationBoxID" ] )
                result = CallDeadlineCommand( [ "-SelectFilenameSave", currTemplate, exportFileType ] )
                
                if result != "Action was cancelled by user" and result != "":
                    self.SetString( self.dialogIDs[ "ExportLocationBoxID" ], result )
            finally:
                c4d.StatusClear()
        
        elif id == self.dialogIDs[ "UnifiedIntegrationButtonID" ]:
            self.OpenIntegrationWindow()

        # The Submit or the Cancel button was pressed.
        elif id == self.dialogIDs[ "SubmitButtonID" ] or id == self.dialogIDs[ "CancelButtonID" ]:
            self.WriteStickySettings()

            # Close the dialog if the Cancel button was clicked
            if id == self.dialogIDs[ "SubmitButtonID" ]:
                if not self.SubmitJob():
                    return True

            if id == self.dialogIDs[ "CancelButtonID" ] or self.GetBool( self.dialogIDs[ "CloseOnSubmissionID" ] ):
                self.Close()

        elif id == self.dialogIDs["TakesBoxID"]:
            self.take_selection_changed()

        return True
    
    def take_selection_changed(self):
        """
        Updates the UI when the take selection changes.
        """
        
        self.EnableGPUAffinityOverride()

    def submitDependentAssemblyJob( self, outputFiles, configFiles, jobNum, dependentIDs ):
        jobName = self.GetString( self.dialogIDs[ "NameBoxID" ] )
        department = self.GetString( self.dialogIDs[ "DepartmentBoxID" ] )
            
        pool = self.Pools[ self.GetLong( self.dialogIDs[ "PoolBoxID" ] ) ]
        secondaryPool = self.SecondaryPools[ self.GetLong( self.dialogIDs[ "SecondaryPoolBoxID" ] ) ]
        group = self.Groups[ self.GetLong( self.dialogIDs[ "GroupBoxID" ] ) ]
        priority = self.GetLong( self.dialogIDs[ "PriorityBoxID" ] )
        machineLimit = self.GetLong( self.dialogIDs[ "MachineLimitBoxID" ] )
        taskTimeout = self.GetLong( self.dialogIDs[ "TaskTimeoutBoxID" ] )
        autoTaskTimeout = self.GetBool( self.dialogIDs[ "AutoTimeoutBoxID" ] )
        limitConcurrentTasks = self.GetBool( self.dialogIDs[ "LimitConcurrentTasksBoxID" ] )
        isBlacklist = self.GetBool( self.dialogIDs[ "IsBlacklistBoxID" ] )
        machineList = self.GetString( self.dialogIDs[ "MachineListBoxID" ] )
        limitGroups = self.GetString( self.dialogIDs[ "LimitGroupsBoxID" ] )
        onComplete = self.OnComplete[ self.GetLong( self.dialogIDs[ "OnCompleteBoxID" ] ) ]
        
        ErrorOnMissingTiles = self.GetBool( self.dialogIDs[ "ErrorOnMissingTilesID" ] )
        AssembleTilesOver = self.AssembleOver[ self.GetLong( self.dialogIDs[ "AssembleTilesOverID" ] ) ]
        BackgroundImage = self.GetString( self.dialogIDs[ "BackgroundImageID" ] )
        ErrorOnMissingBackground = self.GetBool( self.dialogIDs[ "ErrorOnMissingBackgroundID" ] )
        CleanupTiles = self.GetBool( self.dialogIDs[ "CleanupTilesID" ] )
        
        jobInfoFile = os.path.join( self.DeadlineTemp, "draft_submit_info%s.job" % jobNum )
        jobContents = {
            "Plugin" : "DraftTileAssembler",
            "BatchName" : jobName,
            "Name" : "%s - Assembly Job" % jobName,
            "Comment" : "Draft Tile Assembly Job",
            "Department" : department,
            "Pool" : pool,
            "SecondaryPool" : "",
            "Group" : group,
            "Priority" : priority,
            "MachineLimit" : machineLimit,
            "LimitGroups" : limitGroups,
            "JobDependencies" : ",".join( dependentIDs ),
            "OnJobComplete" : onComplete,
        }

        # If it's not a space, then a secondary pool was selected.
        if secondaryPool != " ":
            jobContents[ "SecondaryPool" ] = secondaryPool

        if isBlacklist:
            jobContents[ "Blacklist" ] = machineList
        else:
            jobContents[ "Whitelist" ] = machineList

        outputFileNum = 0
        for outputFile in outputFiles:
            jobContents[ "OutputFilename%s" % outputFileNum ] = outputFile
            outputFileNum += 1

        if not self.GetBool( self.dialogIDs[ "SingleFrameTileJobID" ] ):
            frames = self.GetString( self.dialogIDs[ "FramesBoxID" ] )
            jobContents["Frames"] = frames
        else:
            jobContents["Frames"] = "0-%s" % ( outputFileNum - 1 )

        self.writeInfoFile( jobInfoFile, jobContents )
        self.ConcatenatePipelineSettingsToJob( jobInfoFile, jobName )

        pluginInfoFile = os.path.join( self.DeadlineTemp, "draft_plugin_info%s.job" % jobNum )
        pluginContents = {
            "ErrorOnMissing" : ErrorOnMissingTiles,
            "ErrorOnMissingBackground" : ErrorOnMissingBackground,
            "CleanupTiles" : CleanupTiles,
            "MultipleConfigFiles" : len(configFiles) > 0,
        }
        self.writeInfoFile( pluginInfoFile, pluginContents )

        print( "Submitting Dependent Assembly Job..." )
        args = [ jobInfoFile, pluginInfoFile ]
        args.extend( configFiles )
        
        results = ""
        try:
            results = CallDeadlineCommand( args, useArgFile=True )
        except:
            results = "An error occurred while submitting the job to Deadline.\n" + traceback.format_exc()
            
        successfulSubmission = ( results.find( "Result=Success" ) != -1 )
        print( results )
       
        return successfulSubmission

    def get_region_output_filename(self, outputPath, outputFormat, outputNameFormat, take, isMulti=False, mpass=None, mpassSuffix=False, mpUsers=False, isAlpha=False, postEffect="", regionPrefix=""):
        """Returns the output filename with the given region prefix."""
        regionOutputFileName = self.GetOutputFileName( outputPath, outputFormat, outputNameFormat, take, isMulti=isMulti,
                                                       mpass=mpass, mpassSuffix=mpassSuffix, mpUsers=mpUsers,
                                                       regionPrefix=regionPrefix, postEffect=postEffect )
        if isAlpha:
            tempOutputFolder, tempOutputFile = os.path.split( regionOutputFileName )
            regionOutputFileName = os.path.join( tempOutputFolder, "A_" + tempOutputFile )
        
        return regionOutputFileName

    def createDTAConfigFile( self, frame, renderData, outputPath, outputFormat, outputNameFormat, take, isMulti=False, mpass=None, mpassSuffix=False, mpUsers=False, isAlpha=False, postEffect="" ):
        """
        Creates a tile rendering config file for the given frame.
        :return: A name of the created config file.
        """
        # Partial function, that requires region prefix to be passed when called.
        get_region_output_filename_function = partial(self.get_region_output_filename, outputPath, outputFormat, outputNameFormat, take, isMulti,
                                                      mpass, mpassSuffix, mpUsers, isAlpha, postEffect)

        output_name = get_region_output_filename_function("") # Get output filename without a region prefix.
        return self.create_dta_config_file(frame, renderData, output_name, get_region_output_filename_function)

    def getTextureSearchPaths( self ):
        """
        A wrapper function to grab the texture search paths based on the Cinema 4D major version.
        :return: List of texture search paths
        """
        # In R20, they deprecated GetGlobalTexturePath() and created GetGlobalTexturePaths()
        if self.c4dMajorVersion >= 20:
            # Search paths looks like this: [ ['C:\\my\\path\\to\\search', True], ... ]
            return [ path for path, isEnabled in c4d.GetGlobalTexturePaths() if isEnabled ]
        else:
            return [ c4d.GetGlobalTexturePath( index ) for index in range( 10 ) ]
    
    def get_general_token_context(self, doc, take=""):
        """
        Creates a dictinary used to evaluate Cinema4D tokens in output paths.
        Does not add mappings for render passes.
        """
        if take == "" and useTakes:
            take = doc.GetTakeData().GetCurrentTake().GetName()
        rdata = doc.GetActiveRenderData()
        bd = doc.GetRenderBaseDraw()
        fps = doc.GetFps()
        time = doc.GetTime()
        range_ = ( rdata[ c4d.RDATA_FRAMEFROM ], rdata[ c4d.RDATA_FRAMETO ] )

        # The project name is created from the document name (eg. myfile.c4d) with the extension stripped off
        proj_name, _ = os.path.splitext(doc.GetDocumentName())
        
        context = {
            'prj': proj_name,
            'camera': bd.GetSceneCamera( doc ).GetName(),
            'take': take,
            'frame': doc.GetTime().GetFrame( doc.GetFps() ),
            'rs': rdata.GetName(),
            'res': '%dx%d' % ( rdata[c4d.RDATA_XRES ], rdata[ c4d.RDATA_YRES ] ),
            'range': '%d-%d' % tuple(x.GetFrame(fps) for x in range_),
            'fps': fps }

        return context

    def get_token_context(self, doc, take="", isMulti=False, mpass=None, mpUsers=False, postEffect="" ):
        """
        Returns a dictionary used to evaluate Cinema4D tokens in output paths.
        Adds all the necessary mappings to evaluate render passes.
        """
        context = get_general_token_context(doc, take)

        if not isMulti:
            context[ 'pass' ] = "rgb"
            context[ 'userpass' ] = "RGB"
        elif mpass:
            passType = mpass[ c4d.MULTIPASSOBJECT_TYPE ]
            if passType == c4d.VPBUFFER_BLEND:
                blendCount = self.GetBlendIndex( mpass )
                context[ 'userpass' ] = mpass.GetName() + "blend_" + str( blendCount )
                if mpUsers:
                    context[ 'pass' ] = mpass.GetName() + "blend_" + str( blendCount )
                else:
                    context[ 'pass' ] = "blend_" + str( blendCount )
            elif passType == c4d.VPBUFFER_ALLPOSTEFFECTS:
                context[ 'pass' ] = postEffect.lower()
                context[ 'userpass' ] = postEffect
            else:
                context[ 'userpass' ] = mpass.GetName()
                if mpUsers:
                    context[ 'pass' ] = mpass.GetName().lower()
                else:
                    #Layer Type code does not work if "User Defined Layer Name" is enabled in render settings and we are currently unable to pull that setting.
                    if passType == c4d.VPBUFFER_OBJECTBUFFER:
                        bufferID = mpass[ c4d.MULTIPASSOBJECT_OBJECTBUFFER ]
                        context[ 'pass' ] = ( "object_%s" % bufferID )
                    else:
                        context[ 'pass' ] = SubmitC4DToDeadlineDialog.gpuRenderers[ mpass.GetTypeName() ]
                        
        return context

    def get_general_render_path_data(self, doc, take):
        """
        Returns a dictionary used to evaluate Cinema4D tokens in output paths.
        Does not add mappings for render passes.
        """
        rdata = doc.GetActiveRenderData()
        rBc = rdata.GetDataInstance()

        rpData = {
            '_doc' : doc,
            '_rData' : rdata,
            '_rBc' : rBc,
            '_frame' : doc.GetTime().GetFrame( doc.GetFps() )
        }
        
        if take:
            rpData[ '_take' ] = take

        return rpData

    def get_renderPathData(self, doc, take, isMulti=False, mpass=None, mpUsers=False, postEffect="" ):
        """
        Returns a dictionary used to evaluate Cinema4D tokens in output paths.
        Adds all the necessary mappings to evaluate render passes.
        """
        rpData = self.get_general_render_path_data(doc, take)

        if not isMulti:
            rpData[ '_layerName' ] = "rgb"
            rpData[ '_layerTypeName' ] = "RGB"
        elif mpass:
            rpData[ '_rBc' ] = mpass.GetDataInstance()
            passType = mpass[ c4d.MULTIPASSOBJECT_TYPE ]
            if passType == c4d.VPBUFFER_BLEND:
                blendCount = self.GetBlendIndex( mpass )
                rpData[ '_layerName' ] = mpass.GetName() + "blend_" + str( blendCount )
                if mpUsers:
                    rpData[ '_layerTypeName' ] = mpass.GetName() + "blend_" + str( blendCount )
                else:
                    rpData[ '_layerTypeName' ] = "blend_" + str( blendCount )
            elif passType == c4d.VPBUFFER_ALLPOSTEFFECTS:
                rpData[ 'pass' ] = postEffect.lower()
                rpData[ 'userpass' ] = postEffect
            else:
                rpData[ '_layerName' ] = mpass.GetName()
                
                if mpUsers:
                    rpData[ '_layerTypeName' ] = mpass.GetName().lower()
                else:
                    #Layer Type code does not work if "User Defined Layer Name" is enabled in render settings and we are currently unable to pull that setting.
                    if passType == c4d.VPBUFFER_OBJECTBUFFER:
                        bufferID = mpass[ c4d.MULTIPASSOBJECT_OBJECTBUFFER ]
                        rpData[ '_layerTypeName' ] = ( "object_%s" % bufferID )
                    else:
                        rpData[ '_layerTypeName' ] = SubmitC4DToDeadlineDialog.mPassTypePrefixDict[ mpass.GetDataInstance()[ c4d.MULTIPASSOBJECT_TYPE ] ]
        
        return rpData

    def tokenSystem_eval( self, text, rpData ):
        return tokensystem.FilenameConvertTokens( text, rpData )
        
    def token_eval( self, text, context ):
        return TokenString( text ).safe_substitute( context )
        
    def GetOutputFileName( self, outputPath, outputFormat, outputNameFormat, take, isMulti=False, mpass=None, mpassSuffix=False, mpUsers=False, regionPrefix="", postEffect="" ):
        if not outputPath:
            return ""
        
        doc = documents.GetActiveDocument()
        # C4D always throws away the last extension in the file name, so we'll do that too.
        outputPrefix, tempOutputExtension = os.path.splitext( outputPath )
        outputExtension = self.GetExtensionFromFormat( outputFormat )
        
        if isMulti and mpass is not None:
             #Layer Type code does not work if "User Defined Layer Name" is enabled in render settings and we are currently unable to pull that setting.
            if mpUsers:
                passType = mpass[ c4d.MULTIPASSOBJECT_TYPE ]
                if passType == c4d.VPBUFFER_BLEND:
                    blendCount = self.GetBlendIndex( mpass )
                    mpassValue = blendCount + "blend_" + str( blendCount )
                elif passType == c4d.VPBUFFER_ALLPOSTEFFECTS:
                    mpassValue = postEffect
                else:
                    mpassValue = mpass.GetName()
            else:
                passType = mpass[ c4d.MULTIPASSOBJECT_TYPE ]
                if passType == c4d.VPBUFFER_OBJECTBUFFER:
                    bufferID = mpass[ c4d.MULTIPASSOBJECT_OBJECTBUFFER ]
                    mpassValue = ("object_%s" %bufferID)
                elif passType == c4d.VPBUFFER_BLEND:
                    blendCount = self.GetBlendIndex( mpass )
                    mpassValue = ( "blend_%s" % blendCount )
                elif passType == c4d.VPBUFFER_ALLPOSTEFFECTS:
                    mpassValue = postEffect.lower()
                else:
                    mpassValue = SubmitC4DToDeadlineDialog.mPassTypePrefixDict[ mpass.GetDataInstance()[ c4d.MULTIPASSOBJECT_TYPE ] ]
        
            if mpassSuffix:
                mpassValue = "_" + mpassValue
                outputPrefix = outputPrefix + regionPrefix + mpassValue
            else:
                mpassValue = mpassValue + "_"
                outPrefixParts = os.path.split( outputPrefix )
                outputPrefix = os.path.join( outPrefixParts[ 0 ],  mpassValue+outPrefixParts[ 1 ] + regionPrefix )
        else:
            outputPrefix = outputPrefix + regionPrefix
                
        # If the name requires an extension, and an extension could not be determined,
        # we simply return an empty output filename because we don't have all the info.
        if outputNameFormat == 0 or outputNameFormat == 3 or outputNameFormat == 6:
            if outputExtension == "":
                return ""

        if useTokens:
            rpData = self.get_renderPathData( doc, take, isMulti=isMulti, mpass=mpass, mpUsers = mpUsers, postEffect = postEffect )
            outputPrefix = self.tokenSystem_eval( outputPrefix, rpData )
        else:
            context = self.get_token_context( doc, take=take, isMulti=isMulti, mpass=mpass, mpUsers = mpUsers, postEffect = postEffect )
            outputPrefix = self.token_eval( outputPrefix, context )
        
        # If the output ends with a digit, and the output name scheme doesn't start with a '.', then C4D automatically appends an underscore.
        if len( outputPrefix ) > 0 and outputPrefix[ len( outputPrefix ) - 1 ].isdigit() and outputNameFormat not in ( 2, 5, 6 ):
            outputPrefix = outputPrefix + "_"
        
        # Format the output filename based on the selected output name.
        if outputNameFormat == 0:
            return outputPrefix + "####." + outputExtension
        elif outputNameFormat == 1:
            return outputPrefix + "####"
        elif outputNameFormat == 2:
            return outputPrefix + ".####"
        elif outputNameFormat == 3:
            return outputPrefix + "###." + outputExtension
        elif outputNameFormat == 4:
            return outputPrefix + "###"
        elif outputNameFormat == 5:
            return outputPrefix + ".###"
        elif outputNameFormat == 6:
            return outputPrefix + ".####." + outputExtension
        
        return ""
    
    def GetBlendIndex( self, MPass ):
        blendCount = 1
        remainingMPass = MPass.GetNext()
        while remainingMPass is not None:
            remainingPassType = remainingMPass[ c4d.MULTIPASSOBJECT_TYPE ]
            if remainingPassType == c4d.VPBUFFER_BLEND:
                blendCount += 1
            remainingMPass = remainingMPass.GetNext()
        return blendCount
    
    def GetExtensionFromFormat( self, outputFormat ):
        extension = ""
        
        # These values are pulled from coffeesymbols.h, which can be found in
        # the 'resource' folder in the C4D install directory.
        if outputFormat == 1102: # BMP
            extension = "bmp"
        elif outputFormat == 1109: # B3D
            extension = "b3d"
        elif outputFormat == 1023737: # DPX
            extension = "dpx"
        elif outputFormat == 1103: # IFF
            extension = "iff"
        elif outputFormat == 1104: # JPG
            extension = "jpg"
        elif outputFormat == 1016606: # openEXR
            extension = "exr"
        elif outputFormat == 1106: # PSD
            extension = "psd"
        elif outputFormat == 1111: # PSB
            extension = "psb"
        elif outputFormat == 1105: # PICT
            extension = "pct"
        elif outputFormat == 1023671: # PNG
            extension = "png"
        elif outputFormat == 1001379: # HDR
            extension = "hdr"
        elif outputFormat == 1107: # RLA
            extension = "rla"
        elif outputFormat == 1108: # RPF
            extension = "rpf"
        elif outputFormat == 1101: # TGA
            extension = "tga"
        elif outputFormat == 1110: # TIF (B3D Layers)
            extension = "tif"
        elif outputFormat == 1100: # TIF (PSD Layers)
            extension = "tif"
        elif outputFormat == 1024463: # IES
            extension = "ies"
        elif outputFormat == 1122: # AVI
            extension = "avi"
        elif outputFormat == 1125: # QT
            extension = "mov"
        elif outputFormat == 1150: # QT (Panarama)
            extension = "mov"
        elif outputFormat == 1151: # QT (object)
            extension = "mov"
        elif outputFormat == 1112363110: # QT (bmp)
            extension = "bmp"
        elif outputFormat == 1903454566: # QT (image)
            extension = "qtif"
        elif outputFormat == 1785737760: # QT (jp2)
            extension = "jp2"
        elif outputFormat == 1246774599: # QT (jpg)
            extension = "jpg"
        elif outputFormat == 943870035: # QT (photoshop)
            extension = "psd"
        elif outputFormat == 1346978644: # QT (pict)
            extension = "pct"
        elif outputFormat == 1347307366: # QT (png)
            extension = "png"
        elif outputFormat == 777209673: # QT (sgi)
            extension = "sgi"
        elif outputFormat == 1414088262: # QT (tiff)
            extension = "tif"
        
        return extension

    def GetTakeFromName( self, name ):
        return deadlinec4d.takes.find_take(name)
    
    def GetRenderInfo( self, scene, take=None ):
        return deadlinec4d.utils.get_render_data(scene,take)

    def GetAllAssets( self, submitScene, sceneFile ):
        """ 
        Retrieves all the assets from the document
        If we are submitting the main scene file, then don't return it
        :param submitScene: are we submitting the scene file with this job
        :param sceneFile: the name of the main scene file
        :return: a list of asset file names
        """
        assets = []
        kwargs = { 'doc': documents.GetActiveDocument(), 'allowDialogs': False, 'lastPath': '' }

        if self.c4dMajorVersion >= 20:
            # Flags parameter was added in R20
            kwargs[ 'flags' ] = c4d.ASSETDATA_FLAG_NONE

        if self.c4dMajorVersion >= 21 and submitScene:
            # In R21 a flag was added that filters the scene file from the list
            kwargs[ 'flags' ] |= c4d.ASSETDATA_FLAG_NODOCUMENT

        # Turn it into a set for easy looks/deletions
        assets = { asset[ 'filename' ] for asset in documents.GetAllAssets( **kwargs ) }

        # Delete this when R20 support and earlier is dropped since ASSETDATA_FLAG_NODOCUMENT takes care of it
        if submitScene and sceneFile in assets:
            assets.remove( sceneFile )

        return assets

    def getRenderer( self, scene=None, take=None, renderInfo=None ):
       if renderInfo is None:
           if scene is None:
               scene = documents.GetActiveDocument()
           if take is None:
               takeData = scene.GetTakeData()
               take = takeData.GetMainTake().GetName()
           renderInfo = self.GetRenderInfo( scene, take )
       return self.GetRendererName( renderInfo[ c4d.RDATA_RENDERENGINE ] )

    def getPostEffectPasses( self, take=None ):
        """
        Retrieves a list of all post effects passes for the current renderer
        :param take: the take that is being submitted
        :return: A list of render passes that will be renderered
        """
        scene = documents.GetActiveDocument()
        renderInfo = self.GetRenderInfo( scene, take )

        renderer = self.getRenderer( scene=scene, take=take, renderInfo=renderInfo )
        if renderer == "iray":
            return self.getIrayPostEffectPasses( renderInfo )
        elif renderer == "arnold":
            return self.getArnoldPostEffectPasses( scene )
        elif renderer == "vray":
            return self.getVrayPostEffectPasses( scene )
        return []

    def getIrayPostEffectPasses( self, renderInfo ):
        """
        Retrieves a list of post effects which Iray will render with the current settings
        :param renderInfo: The current render settings object
        :return: the list of Post effects passes
        """
        videoPost = renderInfo.GetFirstVideoPost()
        while videoPost is not None and not self.GetRendererName( videoPost.GetType() ) == "iray":
            videoPost = videoPost.GetNext()

        if not videoPost:
            return []

        irayPostEffects = [
            #THE CAPITALIZATION MISTAKE IS ON PURPOSE BECAUSE IRAY HAS THAT MISTAKE IN THE FILE NAMES
            ( c4d.VP_IRAY_MULTIPASS_AUX_ALPHA, "NVIDIA Iray ALpha_" ),
            ( c4d.VP_IRAY_MULTIPASS_AUX_DEPTH, "NVIDIA Iray Depth_" ),
            ( c4d.VP_IRAY_MULTIPASS_AUX_NORMAL, "NVIDIA Iray Normal_" ),
            ( c4d.VP_IRAY_MULTIPASS_AUX_UV, "NVIDIA Iray UVs_" ),
        ]

        # Get all the iray post effect passes in use
        passes = [ passName for passId, passName in irayPostEffects if videoPost[ passId ] ]
        # Append the pass number to the pass name in the order they're rendered, one-indexed
        return [ passName + str( i ) for i, passName in enumerate( passes, 1 ) ]
            
    def getArnoldPostEffectPasses( self, scene ):
        """
        Returns a list of post effects which Arnold will render with the current settings
        :param scene: the current scene
        :return: the list of post effects passes
        """
        # Arnold drivers completely ignore Takes, so grab all of them from the scene
        drivers = [ obj for obj in scene.GetObjects() if obj.GetType() == SubmitC4DToDeadlineDialog.ARNOLD_DRIVER ]

        # Even if there are no drivers or if they and every AOV is disabled, Arnold will always render an alpha pass first
        passes = [ "alpha_1" ]
        for driver in drivers:
            # Currently only support c4d_display_drivers, since the other drivers need to be special cased across this script (user_layer_names, output_prefix, etc.)
            if driver[ c4d.C4DAI_DRIVER_TYPE ] == SubmitC4DToDeadlineDialog.ARNOLD_C4D_DISPLAY_DRIVER_TYPE:
                # Get all enabled AOVs for the driver
                AOVs = driver.GetChildren()

                # c4d.ID_BASEOBJECT_GENERATOR_FLAG is checking if the AOV is enabled. c4d_display_driver ignores the beauty AOV (it's the regular image file, instead of a multipass)
                driverPasses = [ AOV.GetName() + "_" + str( i ) for i, AOV in enumerate( AOVs, 2 ) if AOV[ c4d.ID_BASEOBJECT_GENERATOR_FLAG ] and AOV.GetName() != "beauty" ]

                # Add them to the existing passes
                passes.extend( driverPasses )

                # Arnold only cares about the first 'driver_c4d_display' driver in the scene. This will need to be changed when you add support for more driver types ("continue" if it's not the first one)
                break

        # Remove any duplicates, since we only support region rendering for the beauty/multi-pass image file output location (no custom locations for AOVs/drivers)
        return set( passes )
        
    def getVrayPostEffectPasses( self, scene ):
        """
        Returns a list of the names of each pass that is rendered by the Post Effects Multipass object.
        V-Ray 3.7 only.
        :param scene: A hook to the current scene.
        :return: a list of the pass naming for each Vray Multipass object.
        """
        # Scene Hooks
        mpSceneHook = scene.FindSceneHook( self.VRAY_MULTIPASS_PLUGIN_ID )
        try:
            branch = mpSceneHook.GetBranchInfo()
        except AttributeError:
            #GetBranchInfo was exposed to python C4D R19
            return []

        #Multipass nodes are stored in the last branch
        categoryNode = branch[ -1 ][ "head" ].GetFirst()

        #Vray Post Effects are stored in a linked list of Category nodes which each contain a list of the nodes within that category.
        channels = []
        while categoryNode:
            # Process the nodes within a category if the category is enabled.
            if categoryNode.GetDataInstance()[ c4d.MPNODE_ISENABLED ]:
                channelNode = categoryNode.GetDown()
                while channelNode:
                    #process the individual channels in a category if they are enabled.
                    if channelNode.GetDataInstance()[ c4d.MPNODE_ISENABLED ]:
                        channels.append( channelNode.GetName() )

                    channelNode = channelNode.GetNext()

            categoryNode = categoryNode.GetNext()

        #Vray Post Effects pass names are always of the form NodeName_Index with index starting at 2.
        #The nodes are always indexed in the reverse order than what we can walk.
        return [ "%s_%s" % ( nodeName, index ) for index, nodeName in enumerate( reversed( channels ), 2 ) ]

    def getEachMultipass( self, take=None ):
        """
        A generator function which will yield every multipass defined in the current render settings.
        For Post Effect Passes it will return each pass as defined by the current renderer
        :param take: Which take we are currently submitting.
        :return: Tuples in the form of ( Multipass Object, Post Effect Pass )
        """

        scene = documents.GetActiveDocument()

        for additionalPass in self.getAdditionalMultipasses( take=take ):
            yield ( additionalPass, "" )

        mPass = scene.GetActiveRenderData().GetFirstMultipass()
        while mPass is not None:
            if not mPass.GetBit( c4d.BIT_VPDISABLED ):
                passType = mPass[ c4d.MULTIPASSOBJECT_TYPE ]

                if passType == c4d.VPBUFFER_ALLPOSTEFFECTS:
                    for innerPass in self.getPostEffectPasses( take=take ):
                        yield ( mPass, innerPass )
                else:
                    yield ( mPass, "" )

            mPass = mPass.GetNext()
        

    def getAdditionalMultipasses( self, take=None ):
        """
        Some renderers always add specific additional passes that are always added regardless of what Multipasses are enabled
        :param take: The current take that is being rendered.
        :return: An iterator of Multipass objects that are added outside of the user defined Multipasses.
        """
        renderer = self.getRenderer( take=take )

        if renderer == "vray":
            for rpass in self.getVrayAdditionalPasses():
                yield rpass

    def getVrayAdditionalPasses( self ):
        """
        VRay automatically adds an RGB pass if one is not already set within the Render settings.
        V-Ray 3.7 only.
        :return: An iterator of Multipass objects that are added by V-ray ( RGB if none is defined )
        """
        scene = documents.GetActiveDocument()

        mPass = scene.GetActiveRenderData().GetFirstMultipass()
        #Go through all of the multipasses and break out if we find an RGBA pass
        while mPass is not None:
            if not mPass.GetBit( c4d.BIT_VPDISABLED ):
                passType = mPass[ c4d.MULTIPASSOBJECT_TYPE ]
                if passType == c4d.VPBUFFER_RGBA:
                    break
            mPass = mPass.GetNext()
        else:
            # we did not find an RGBA Pass so we create our own.
            rgbPass = c4d.BaseList2D( c4d.Zmultipass )
            rgbPass.GetDataInstance()[ c4d.MULTIPASSOBJECT_TYPE ] = c4d.VPBUFFER_RGBA
            rgbPass.SetName( "rgb" )
            yield rgbPas

    def GetRendererName( self, rendererID ):
        return self.renderersDict.get(rendererID)


class CheckRenderPassesResult(object):
    __slots__ = ( "DenoisedBeautyAndAllPasses", "RenderPassesEnabled", "CustomRenderPassName",
                  "CompressionEnabled", "UnrecognizedCompression", "MultilayerEnabled" )

    def __init__( self ):
        self.DenoisedBeautyAndAllPasses = False
        self.RenderPassesEnabled = False
        self.CustomRenderPassName = False
        self.CompressionEnabled = False
        self.UnrecognizedCompression = False
        self.MultilayerEnabled = False

## Class to create the submission menu item in C4D.
class SubmitC4DtoDeadlineMenu( plugins.CommandData ):
    ScriptPath = ""
    
    def __init__( self, path ):
        self.ScriptPath = path
    
    def Execute( self, doc ):
        if SaveScene():
            dialog = SubmitC4DToDeadlineDialog()
            dialog.Open( c4d.DLG_TYPE_MODAL )
        return True
    
    def GetScriptName( self ):
        return "Submit To Deadline"
    
def GetDeadlineCommand( useDeadlineBg=False ):
    deadlineBin = ""
    try:
        deadlineBin = os.environ['DEADLINE_PATH']
    except KeyError:
        #if the error is a key error it means that DEADLINE_PATH is not set. however Deadline command may be in the PATH or on OSX it could be in the file /Users/Shared/Thinkbox/DEADLINE_PATH
        pass
        
    # On OSX, we look for the DEADLINE_PATH file if the environment variable does not exist.
    if not deadlineBin and os.path.isfile( "/Users/Shared/Thinkbox/DEADLINE_PATH" ):
        with io.open( "/Users/Shared/Thinkbox/DEADLINE_PATH", encoding="utf-8" ) as f:
            deadlineBin = f.read().strip()
    
    exeName = "deadlinecommand"
    if useDeadlineBg:
        exeName += "bg"
    
    deadlineCommand = os.path.join( deadlineBin, exeName )

    return deadlineCommand

def CreateArgFile( arguments, tmpDir ):
    tmpFile = os.path.join( tmpDir, "args.txt" )
    
    with io.open( tmpFile, 'w', encoding="utf-8-sig" ) as fileHandle:
        for argument in arguments:
            line = "%s\n" % ( argument )
            if not isinstance(line, unicode_type):
                line = line.decode("utf-8")
            fileHandle.write( line )
        
    return tmpFile
    
def CallDeadlineCommand( arguments, hideWindow=True, useArgFile=False, useDeadlineBg=False ):
    deadlineCommand = GetDeadlineCommand( useDeadlineBg )
    tmpdir = None
    
    if useArgFile or useDeadlineBg:
        tmpdir = tempfile.mkdtemp()
        
    startupArgs = [deadlineCommand]
    
    if useDeadlineBg:
        arguments = ["-outputfiles", os.path.join(tmpdir,"dlout.txt"), os.path.join(tmpdir,"dlexit.txt") ] + arguments
    
    startupinfo = None
    creationflags = 0

    if os.name == 'nt':
        if hideWindow:
            # Python 2.6 has subprocess.STARTF_USESHOWWINDOW, and Python 2.7 has subprocess._subprocess.STARTF_USESHOWWINDOW, so check for both.
            if hasattr( subprocess, '_subprocess' ) and hasattr( subprocess._subprocess, 'STARTF_USESHOWWINDOW' ):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess._subprocess.STARTF_USESHOWWINDOW
            elif hasattr( subprocess, 'STARTF_USESHOWWINDOW' ):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        else:
            # still show top-level windows, but don't show a console window
            CREATE_NO_WINDOW = 0x08000000   #MSDN process creation flag
            creationflags = CREATE_NO_WINDOW

    if useArgFile:
        arguments = [ CreateArgFile( arguments, tmpdir ) ]
    
    arguments = startupArgs + arguments
    
    # Specifying PIPE for all handles to workaround a Python bug on Windows. The unused handles are then closed immediatley afterwards.
    proc = subprocess.Popen(arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags)
    output, errors = proc.communicate()
    
    if useDeadlineBg:
        with io.open( os.path.join( tmpdir, "dlout.txt" ), 'r', encoding='utf-8' ) as fileHandle:
            output = fileHandle.read()
    else:
        output = output.decode('utf-8')
    
    if tmpdir:
        try:
            shutil.rmtree(tmpdir)
        except:
            print( 'Failed to remove temp directory: "%s"' % tmpdir )

    return output.strip()

class TokenString(string.Template):
    idpattern = '[a-zA-Z]+'

# Iterate through objects in take (op)
def GetNextObject( op ):
    if op == None:
      return None
  
    if op.GetDown():
      return op.GetDown()
  
    while not op.GetNext() and op.GetUp():
      op = op.GetUp()
  
    return op.GetNext()    

## Global function to save the scene. Returns True if the scene has been saved and it's OK to continue.
def SaveScene():
    scene = documents.GetActiveDocument()
    
    # Save the scene if required.
    if scene.GetDocumentPath() == "" or scene.GetChanged():
        print( "Scene file needs to be saved" )
        c4d.CallCommand( 12098 ) # this is the ID for the Save command (from Command Manager)
        if scene.GetDocumentPath() == "":
            gui.MessageDialog( "The scene must be saved before it can be submitted to Deadline" )
            return False
    
    return True
    
def hasArnoldDriver():
    doc = documents.GetActiveDocument()
    return innerHasArnoldDriver( doc, doc.GetFirstObject() )
    
def innerHasArnoldDriver(doc, bl2d):
    while bl2d:
        if bl2d.GetTypeName() == "Arnold Driver":
            return True
        
        if innerHasArnoldDriver( doc, bl2d.GetDown() ):
            return True
        bl2d = bl2d.GetNext()

    return False

def compute_tile_region(tile_num, tiles_in_x, tiles_in_y, height, width, renderer):
    """
    Computes the coordinates for a tile based on the renderer, image pixel dimensions, and the
    tile grid.

    Arguments:
        tile_num (int): The index of the tile between the range of [0, tiles_in_x * tiles_in_y)
        tiles_in_x (int): The number of tiles in the x-axis
        tiles_in_y (int): The number of tiles in the y-axis
        height (int): The number of pixels for the full image in the y-axis
        width (int): The number of pixels for the full image in the x-axis
        renderer (str): The name of the renderer. Different renderers expect different region coordinate
            representations.
    
    Returns:
        Region: A named tuple containing the region coordinates for the tile.
    """

    # Compute which tile we are calculating
    y, x = divmod( tile_num, tiles_in_x )

    if renderer == "octane":
        # Octane uses floating-point percentages in the range of [0, 1] to specify the render region. Each
        # region boundary (top/left/bottom/right) is expressed as a percentage of the pixels in the corresponding
        # dimension away from the boundary's image border.

        # Compute the percentage factors for each of the tile dimensions.
        x_tile_pct = 1.0 / tiles_in_x
        y_tile_pct = 1.0 / tiles_in_y
        # Pad by the percentage of the dimension making up one pixel in case the
        # number of tiles does not evenly divide the output image dimension
        x_tile_pad = 1.0 / width
        y_tile_pad = 1.0 / height

        
        left = max(0, x_tile_pct * x - x_tile_pad)                  # Percentage from the left
        right = min(1.0, 1.0 - left - x_tile_pct - x_tile_pad)      # Percentage from the right
        top = max(0, y_tile_pct * y - y_tile_pad)                   # Percentage from the top
        bottom = min(1.0, 1.0 - top - y_tile_pct - y_tile_pad)      # Percentage from the bottom
    else:
        # Other renderers use the standard C4D region coordinates and are expressed in pixel offsets
        # where the origin is the top-left corner

        # Compute the number of pixels from the left image border
        left = ( float( x ) / tiles_in_x ) * width
        left = int( left + 0.5 )

        # Compute the number of pixels from the right image border
        right = ( float( x + 1 ) / tiles_in_x ) * width
        right = int( right + 0.5 )
        right = width - right

        # Compute the number of pixels from the top image border
        top = ( float( y ) / tiles_in_y ) * height
        top = int( top + 0.5 )

        # Compute the number of pixels from the bottom image border
        bottom = ( float( y + 1 ) / tiles_in_y ) *height
        bottom = int( bottom + 0.5 )
        bottom = height - bottom
    
    return Region(
        left=left,
        top=top,
        right=right,
        bottom=bottom
    )

def insert_before_substring(input_string, before_substring, to_insert):
    """
    Insert text into a string before a given substring, if substring exists.
    If there are several entries of the substring, the text will be inserted only once before the first entry.
    :param input_string: The string to insert into.
    :param before_substring: Insert the text before this substring, if it's present.
    :param to_insert: The substring to insert into the original string.
    :return: Either an original string, or the modified string, if insertion was successful.
    """
    idx = input_string.find(before_substring)
    if idx != -1:
        return input_string[:idx] + to_insert + input_string[idx:]

    return input_string

## Global function used to register our submission script as a plugin.
def main( path ):
    pluginID = 1025665
    plugins.RegisterCommandPlugin( pluginID, "Submit To Deadline", 0, None, "Submit a Cinema 4D job to Deadline.", SubmitC4DtoDeadlineMenu( path ) )

## For debugging.
if __name__=='__main__':
    if SaveScene():
        dialog = SubmitC4DToDeadlineDialog()
        dialog.Open( c4d.DLG_TYPE_MODAL )
