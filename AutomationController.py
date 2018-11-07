import argparse
import contextlib
import glob
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

from vector.lib.core import VC_Status

'''
This is a quick-start utility that uses operates on an exiting vcshell.db to:

    Create a coverage project for all files in the database
    Instrument these files for a particular level of coverage
    
    Create Unit Test Environment Scripts
    
    Create a Manage Project with all of those pieces
    
    Build a subset of the test environments
    
    Create Basis Path test for those environments

'''

toolName = 'VectorCAST-QuickStart Utility'

globalCoverageProjectExists=True

# Parameter Default
parameterNotSetString = '<notset>'

# To make the building as fast as possible, these values allow us to  only process
# a sub-set of the files that exist in the vcshell.db to increase speed
maximumFilesToSystemTest=sys.maxint
maximumFilesToUnitTest=sys.maxint
maximumUnitTestsToBuild=0

# This file contains the list of source files to process for this pass
listOfFilenamesFile = 'vcast-latest-filelist.txt'
# This file will contain the cumulative list of files in the project
listOfFilesInProject = 'vcast-inproject-filelist.txt'
listOfEnvironmentsInProject = 'vcast-inproject-envirolist.txt'

vcWorkArea='vcast-workarea'
vcshellDbName='vcshell.db'
vcManageDirectory='vc_project'
vcCoverDirectory='vc_coverage'
vcScriptsDirectory='vc_ut_scripts'
vcHistoryDirectory='vc_history'
vcEnterpriseMode = False

# These global are set for each run of the utiltity
# compilerNodeName is the location where we will insert new environments
defaultCompilerNodeName = 'UnitTestingCompilerNode'
compilerNodeName = defaultCompilerNodeName
# currentLanguage controls the name of the test suites and groups
currentLanguage = 'none'

# Unit Test Configuration Files
ADA_CONFIG_FILE = 'ADACAST_.CFG'
C_CONFIG_FILE = 'CCAST_.CFG'
CUDA_HOST = 'HOST'

# Controls the output of the stdout from all VectorCAST commands
verboseOutput = False

# JAL Controls the updating of system_test.py
globalUpdateSystemTestPy = False

# Controls the failing/continuing of the scripts after a VectorCAST command failes
globalAbortOnError = True

# These variables are constructed from the --projectname arg
coverageProjectName=""
manageProjectName=""

# This is the startup directory where the script is being run
originalWorkingDirectory=os.getcwd()
cfgFileLocation=os.getcwd()

# This is the location of the vcshell.db file, passed in by the caller
# It might be the same as the originalWorkingDirectory
vcshellDBlocation=''


# This is the make command info from the database
topLevelMakeCommand = ''
topLevelMakeLocation = ''
applicationList = []


clicastVersion = ''
vcInstallDir = os.environ["VECTORCAST_DIR"]
locationOfInstrumentScript=os.path.join (vcInstallDir,'python','vector','apps','vcshell')
pathToUnInstrumentScript=os.path.join (vcInstallDir,'python','vector','apps','AutomationController','UnInstrument.py')
pathToEnvCreateScript=os.path.join (vcInstallDir,'python','vector','apps','vcshell','EnvCreate.py')

# List of all files in the DB
listOfAllFiles = []
listOfFiles = []
listOfPaths = []

# CUDA artifacts
cudaArchitectures = []
cudaHostOnlyFiles = []

# Contains the status message to display at the end of the run
summaryStatusFileHandle = 0

# Information for parallel instrumentation
useParallelInstrumentation = False
useParallelJobs = ""
useParallelDestination = ""
useParallelUseInPlace = False


def setVcWorkArea(vcastWorkArea):
    '''
        Api to set the global variables vcastWorkArea
    '''
    global vcWorkArea
    vcWorkArea=vcastWorkArea

def setVcshellDbName(vcshellDB):
    '''
        Api to set the global variable vcshellDbName
    '''
    global vcshellDbName
    vcshellDbName=vcshellDB

def addToSummaryStatus (message):
    '''
    This is just a wrapper so that we can capture the main status messages for
    display at the end of the process
    '''
    
    global summaryStatusFileHandle
    print message
    summaryStatusFileHandle.write (message + '\n')
    summaryStatusFileHandle.flush()
    

def sectionBreak (message):
    print '\n\n'   
    print '---------------------------------------------------------------------------------------------'
    print '---------------------------------------------------------------------------------------------'
    if len (message) > 0:
        print message
        print '---------------------------------------------------------------------------------------------'
        print '---------------------------------------------------------------------------------------------'
    
    
def getTimeString (milliSeconds):
    '''
    Convert a milliseconds float value to a seconds string
    '''
    seconds = milliSeconds/1000
    if seconds > 60: 
        return "%1.1f " % (seconds/60) + ' minutes'
    else:
        return "%1.1f " % (seconds) + ' seconds'
        
    
def fatalError (errorString):
    print errorString;
    print ('Terminating ...\n\n')
    raise Exception ('VCAST Termination Error')    
    
def isCuda():
    return len(cudaArchitectures) > 0
    
def runVCcommand(command, abortOnError=False):
    '''
    Run Command with subprocess.Popen and return status
    If the fatal flag is true, we abort the process, if 
    not, we print the stdout and continue ...
    '''
    
    global verboseOutput

    cmdOutput = ''
    commandToRun = os.path.join (vcInstallDir, command)
    
    print '   running command: ' + commandToRun
    vcProc = subprocess.Popen(commandToRun,
                              stdout=subprocess.PIPE,
                              stdin=subprocess.PIPE,
                              stderr=subprocess.PIPE,
                              universal_newlines=True,
                              shell=True)
    stdoutLines = iter(vcProc.stdout.readline, "")
    stderrLines = iter(vcProc.stderr.readline, "")

    for line in stdoutLines:
        if verboseOutput:
           sys.stdout.write(line)
        else:
            sys.stdout.write('.')
        cmdOutput+=line
        
    for line in stderrLines:
        if verboseOutput:
           sys.stderr.write(line)
        else:
            sys.stderr.write('.')
        cmdOutput+=line    
        
    vcProc.stdout.close()
    exitCode = vcProc.wait()
    sys.stdout.write('\n')
    
    # check for license error and handle this as a special case
    if 'FLEXlm Error:' in cmdOutput:
        print ('FLEXlm Error While Running VectorCAST Command')
        print (re.search('FLEXlm Error:(.*)\n', cmdOutput).group(1))
        raise Exception ('FLEXlm Error')
            
    # check for project lock error, and handle this as a special case
    elif 'Unable to obtain read lock' in cmdOutput:
        print ('   work-area: "' + os.getcwd() + '"')
        print ('   project: "' + manageProjectName + '" is locked by another user ...')
        print ('   close this connection or choose different work-area')
        fatalError ('Workarea Project is Locked')

    # handle all other errors ...
    elif exitCode != 0:
        # In all cases, we print out the 
        print '   command returned a non-zero exit code: ' + str(exitCode)
        print '   stdout/stderr => '
        print cmdOutput
        if abortOnError:
            raise Exception ('VectorCAST command failed')

    return cmdOutput, exitCode
    

def readCFGoption (optionName):
    '''
    This function will look for optionName in the local directory
    CCAST_.CFG file and return the value.  If the option is not
    found or there is not a CCAST_.CFG file we return ""
    '''
    optionValue, exitCode = runVCcommand ('vcutil -lc get_option ' + optionName, globalAbortOnError)
    return optionValue.rstrip('\n')
       
def readAdaCFGoption (optionName):
    ''' 
    vcutil does not work for ada ...
    '''
    cfgFile = open (ADA_CONFIG_FILE, 'r')
    for line in cfgFile.readlines():
        if line.startswith (optionName+':'):
            return line.split (':')[1].strip()

    
def runPythonScript (scriptLocation, scriptFile, argString):
    '''
    This function will dynamically import and call a python script
    rather than starting vpython.  Hopefully this is faster
    
    Leaving this un-used for now.
    '''
    # Dynamically import the correct python file
    sys.path.append (scriptLocation)
    pyFile = __import__(scriptFile)
    
    argList = [scriptFile]
    argList += argString.split()
    sys.argv = argList
    pyFile.main()


def unInstrumentSourceFiles():
    '''
    This function will spin through the files in listOfFilesInProject and
    un-instrument them.
    '''
    existingFiles = os.path.join (originalWorkingDirectory, vcWorkArea, listOfFilesInProject)
    if os.path.isfile (existingFiles):
        fileList = open (existingFiles, 'r')
        for fileLine in fileList:
            originalFile = fileLine.strip ('\n')
            bakFile = originalFile+'.vcast.bak'
            if os.path.isfile (bakFile):
                print ('original file: ' + originalFile)
                print ('bak file:      ' + bakFile)
                shutil.copy (bakFile, originalFile)
                os.remove (bakFile)        
            cudaFile = originalFile+'.vcast.cuda'
            if os.path.isfile (cudaFile):
                os.remove (cudaFile)        
        fileList.close ()
    else:
        # if there is no existing file list, just call un-instrument
        fullCommand =  'vpython '
        fullCommand += pathToUnInstrumentScript
        stdOut, exitCode = runVCcommand (fullCommand, globalAbortOnError)
    
    
def filterTheFileList (fullFileList):
    '''
    This function takes in the full list of files from the vcshell.db and
    filters it down to the files of interest for the current run.  The 
    first filter is to remove any files that already exist in the cover
    project, the second filter is based on the user-supplied: maximumFilesToSystemTest
    '''

    global maximumFilesToSystemTest
    localFileList = fullFileList[:]
    listItemsToRemove = []
    fileCount = 0
    
    # First step is to remove any files that are already in the coverage project
    if os.path.isdir (os.path.join (originalWorkingDirectory, vcWorkArea)):
        existingFiles = os.path.join (originalWorkingDirectory, vcWorkArea, listOfFilesInProject)
        if os.path.isfile (existingFiles):
            addToSummaryStatus ('   checking the existing project files ... ')
            oldFile = open (existingFiles, 'r')
            lines = oldFile.readlines()
            for line in lines: 
                strippedLine = line.strip()
                if strippedLine in localFileList:
                    localFileList.remove (strippedLine)
    
    # If we have more files than the requested max, then truncate.
    if len (localFileList) > maximumFilesToSystemTest:
        # take the first N files
        addToSummaryStatus ('   limiting file list to (MAXIMUM_FILES_TO_SYSTEM_TEST)=' + str (maximumFilesToSystemTest))
        localFileList = localFileList[0:maximumFilesToSystemTest]
      
    return localFileList


def writeFileListToFile (list):
    
    global listOfFilenamesFile
    
    listFile = open (listOfFilenamesFile, 'w')
    for file in list:
        listFile.write (file + '\n')
    
    listFile.close()
    

def initializeCFGfile (compilerCFG, vcdbFlagString):
    ''' 
    This function will create a CCCAST_.CFG file in the 
    originalWorkingDirectory.  This file will either be created from
    the compilerCFG which will be either a VC template name of the
    path to an existing CFG file.  This will allow the rest of
    the tool to use: os.path.join (originalWorkingDirectory, C_CONFIG_FILE)
    as the correct file
    '''
    
    if os.path.isfile (compilerCFG):
        # If the user passed in the location of the local CCAST_.CFG 
        # we don't need to do anything
        if os.path.isfile (C_CONFIG_FILE) and (os.stat(compilerCFG) == os.stat(C_CONFIG_FILE)):
            pass
        else:
            shutil.copyfile(compilerCFG, C_CONFIG_FILE)
    else:
        stdOut, exitCode = runVCcommand ('clicast -lc template ' + compilerCFG, True)
        
    # Now setup any command over-rides that are requested by the configuration
    # By doing the option changes here we are setting the value in the base CCAST_.CFG
    # which gets copied everywhere in the vcast-workarea.
    stdOut, exitCode = runVCcommand ('clicast -lc option vcast_vcdb_flag_string ' + vcdbFlagString, globalAbortOnError)
    
    
def getCFGfile ():
    '''
    This function will copy the CFG from the orignalWorkingDirectory
    to the current working directory.  We delete any existing CFG
    files in the destination area, so that we only have the CCAST
    or the ADACAST depending on the type of enviro we are adding.
    '''
    global cfgFileLocation
    
    cfgFile = os.path.join (cfgFileLocation, C_CONFIG_FILE)
    # if there is a local file, and it is the one we want then do nothing
    if os.path.isfile(cfgFile):
        if os.path.isfile (C_CONFIG_FILE) and (os.stat (cfgFile) == os.stat (C_CONFIG_FILE)):
            pass
        elif os.path.isfile (cfgFile):
            shutil.copyfile(cfgFile, C_CONFIG_FILE)
    cfgFile = os.path.join (cfgFileLocation, ADA_CONFIG_FILE)
    if os.path.isfile(cfgFile):
        if os.path.isfile (ADA_CONFIG_FILE) and (os.stat (cfgFile) == os.stat (ADA_CONFIG_FILE)):
            pass
        elif os.path.isfile (cfgFile):
            shutil.copyfile(cfgFile, ADA_CONFIG_FILE)
    
    
    

def buildWorkarea():

    workAreaPath = os.path.join (os.getcwd(), vcWorkArea)
    
    # Pre September 2017 we use vc_manage to store the manage project
    # Now we use vc_project ... to handle this, we check for this case
    # and delelete the old vcast-workarea if necessary
    addToSummaryStatus ('Checking for old work-area ...')
    oldPath = os.path.join (workAreaPath, 'vc_manage')
    if os.path.isdir (oldPath):
        addToSummaryStatus ('   removing old work-area instance')
        shutil.rmtree (workAreaPath)
 
    createWorkspace = True
    
    # If we already have a workarea
    if os.path.isdir (workAreaPath):
        fullCoverProject  = os.path.join(workAreaPath, vcCoverDirectory, coverageProjectName+".vcp")
        fullManageProject = os.path.join(workAreaPath, vcManageDirectory, manageProjectName+".vcm")

        # check to make sure the .vcp and .vcm files are present
        if os.path.isfile (fullCoverProject) and os.path.isfile(fullManageProject):
            # if they are, use them and update 
            addToSummaryStatus ('   found existing work area')
            os.chdir (vcWorkArea)
            projectMode = 'update'
            createWorkspace = False
        else:
            addToSummaryStatus ("   Found partial work area -- removing VectorCAST directories -- starting new")
            dirs = [vcCoverDirectory, vcManageDirectory, vcScriptsDirectory, vcHistoryDirectory]
            for dir in dirs:
                fullDir = os.path.join(workAreaPath,dir)
                print "   Trying to delete: " + fullDir
                if os.path.isdir(fullDir):
                    shutil.rmtree (fullDir)
    
    if createWorkspace: # create the workarea
        projectMode = 'new'
        addToSummaryStatus ('Creating new work area ...')
        addToSummaryStatus ('   location: ' + os.getcwd())
        #os.mkdir (vcWorkArea)
        try:    
            os.makedirs (vcWorkArea)
        except:
            pass
        os.chdir (vcWorkArea)
        os.mkdir (vcCoverDirectory)
        os.mkdir (vcManageDirectory)
        os.mkdir (vcScriptsDirectory)
        os.mkdir (vcHistoryDirectory)

    return projectMode
    

def vcshellDBarg (force=False, cfgFile=False):
    '''
    This function will return the "--db path" arg to be passed
    to the vcdb command when the location of the vcshell.db is NOT
    the same as the current working directory
    '''
    global vcshellDBlocation
    global vcshellDbName
    global originalWorkingDirectory
    global cfgFileLocation

    retVal = ""

    if force or vcshellDBlocation!=originalWorkingDirectory or vcshellDbName!='vcshell.db':
        retVal = '--db=' + os.path.join (vcshellDBlocation, vcshellDbName)
    else:
        retVal =""

    # pass in the CFG file if it has been specified
    if len(cfgFileLocation) > 0:
        cfg = cfgFileLocation
        if cfgFile:
           cfg = os.path.join(cfg, C_CONFIG_FILE)
        retVal = retVal + " --cfg=" + cfg

    return retVal
    

def normalizePath (path):
    '''
    This function will a path to be all lower case if we are on windows
    '''
    if os.name == 'nt':
        return path.lower()
    else:
        return path
        
def initialize (compilerCFG, filterFunction, vcdbFlagString, filesOfInterest):

    global listOfPaths
    global vcshellDBlocation
    
    
    projectMode = ''
    fullFileList = []
    fullPathList = []
    sectionBreak ('')
    
    addToSummaryStatus ('Validating %s ...' % vcshellDbName)
    startMS = time.time()*1000.0
 
    # Generate the compiler configuration file
    initializeCFGfile (compilerCFG, vcdbFlagString)

    initializeCudaArtifacts ( compilerCFG )

    addToSummaryStatus ('Validating %s ...' % vcshellDbName)
    if os.path.isfile (os.path.join (vcshellDBlocation, vcshellDbName)):
        setupGlobalFileListsFromDatabase(filterFunction, filesOfInterest, vcshellDBarg())

        # Create a global list of all of the directory paths in the DB
        stdOut, exitCode = runVCcommand ('vcdb ' + vcshellDBarg() + ' getpaths', True)
        fullPathList = stdOut.split('\n')
        
        for path in fullPathList:
            # We get some blank lines from the getpaths for some reason
            if len (path) > 4 and path[0]=='(' and path[2]==')' and path[3]==' ':
                # The output of the getpaths command looks like
                # (s) path, so split the (s) part into the second part of a tuple
                splitText = path.split(' ')
                listOfPaths.append((normalizePath (splitText[1]), splitText[0]))
                
        # destroy the temp list
        del fullPathList[:]
        if len (listOfPaths) > 0:
            addToSummaryStatus ('   found ' + str(len (listOfPaths)) + ' source paths')   

        setupApplicationBuildGlobals(vcshellDBarg())
         
    else:
        # This call will exit the program
        fatalError ('Cannot find file: %s in directory: ' % vcshellDbName + vcshellDBlocation + ', please build project with vcshell before running this script\n')  
        

    # Build the workarea directory structure
    projectMode = buildWorkarea()
        
    # Write the new list of files into the vcWorkArea
    writeFileListToFile (listOfFiles)
    
    endMS = time.time()*1000.0
    addToSummaryStatus ('   complete (' + getTimeString (endMS-startMS) + ')')
    
    return projectMode

def cudaArchMacro ( architecture, definition=True ):
    if architecture.isdigit():
        if definition:
            return "__CUDA_ARCH__=" + architecture + "0"
        else:
            return "__CUDA_ARCH__==" + architecture + "0"
    else:
        return ""

def cudaArchName ( architecture ):
    if architecture.isdigit():
        return "ARCH_" + architecture
    else:
        return CUDA_HOST

'''
These are files that have a .cpp extension, but are not forced to
be treated as a device file via the "-x cu" compiler option
'''
def initializeCudaHostOnlyFiles ( listOfAllFiles ):
    global cudaHostOnlyFiles
    cudaHostOnlyFiles = []
    # only set this up if we're dealing with CUDA
    if isCuda():
        for a_file in listOfAllFiles:
            if os.path.splitext(a_file)[1] != '.cu':
                # get compiler command for this file
                command, exitCode = runVCcommand (command='vcdb ' +
                                                  vcshellDBarg(force=True) +
                                                  ' getcommand --file=' +
                                                  a_file)
                # if the flag is not there, add it to our list
                if "-x cu" not in command:
                    cudaHostOnlyFiles.append(a_file)

def buildCudaCoverageProjects (projectMode, workingDir):
    global cudaHostOnlyFiles

    addToSummaryStatus ('Building CUDA Coverage Environments ...')
    os.chdir ( workingDir )
    currentDirectory = os.getcwd()
    for arch in cudaArchitectures:
        arch_name = cudaArchName ( arch )
        arch_macro = cudaArchMacro ( arch )
        os.mkdir ( arch_name )
        buildCoverageProject (projectMode=projectMode,
                              projectName=arch_name,
                              inplace=False,
                              workingDirectory=os.path.join(currentDirectory, arch_name),
                              instDir='.')

        # remove any files that are host-only
        if 'HOST' not in arch_name:
            for a_file in cudaHostOnlyFiles:
                runVCcommand ('clicast -e ' + arch_name +
                                  ' -u ' + a_file +
                                  ' cover source remove',
                              True);

        # set macro flag for CUDA architectures
        if len(arch_macro) > 0:
            runVCcommand ('clicast -lc options_append C_DEFINE_LIST ' + arch_macro)

        # add include paths to cover project
        for include in listOfPaths:
            runVCcommand ('clicast -lc Option LIBRARY_INCLUDE_DIR ' + include[0])
        os.chdir ( currentDirectory )
 

def setupGlobalFileListsFromDatabase(filterFunction, filesOfInterest, vcshellArg):
    '''
    This function will set the listOfAllFiles and listOfFiles globals
    from the files in the database.
    '''

    global listOfFiles
    global listOfAllFiles

    # Create a global list of all of the files in the DB
    listOfAllFiles = prependFilesOfInterest(
        getFilesFromDatabase(filterFunction, vcshellArg),
        filesOfInterest)

    # filter based on: already in project and max size
    listOfFiles = filterTheFileList (listOfAllFiles)
    addToSummaryStatus ('   ' + str(len (listOfFiles)) + ' files will be added for system testing ... ')


def getAllFilesFromDatabase(vcshellArg):
    '''
    This function returns all the files in the database.
    '''
    stdOut, exitCode = runVCcommand ('vcdb ' + vcshellArg + ' getfiles', True)
    # strip the trailing CR and then split
    out = stdOut.rstrip('\n').split('\n')
    if len (out) == 0:
        fatalError ('No files found in %s' % vcshellDbName)
    else:
        addToSummaryStatus ('   found ' + str(len (out)) + ' total source files')

    return out

def getFilesFromDatabase(filterFunction, vcshellArg):
    '''
    This function returns the files from the database. The filter function can be used to
    filter the files.
    '''
    original = getAllFilesFromDatabase(vcshellArg)
    addToSummaryStatus ('   applying the user-defined filter to the file list ... ')
    # filterFunction is the user supplied callback function
    originalFileListLength = len (original)
    out = filterFunction(original)
    if len (out) < originalFileListLength:
        addToSummaryStatus ('   user filter reduced file count to: ' + str (len (out)))

    return out

def prependFilesOfInterest(original, filesOfInterest):
    '''
    This function moves filesOfInterest to the begining of original
    '''
    if filesOfInterest == [parameterNotSetString]:
        return original

    if os.name == "nt":
        filesOfInterest = [file.lower() for file in filesOfInterest]
    sortedListOfAllFiles = list(original)
    filesNotInDb = list(filesOfInterest)
    index = 0
    for file in original:
        if os.name == "nt":
            tempFile = file.lower()
        else:
            tempFile = file
        # If file matches any entry in filesOfInterest 
        if tempFile in filesOfInterest or os.path.basename(file) in filesOfInterest:
            sortedListOfAllFiles.remove(file)
            sortedListOfAllFiles.insert(index, file)
            index += 1
            if tempFile in filesOfInterest:
                filesNotInDb.remove(tempFile)
            else:
                filesNotInDb.remove(os.path.basename(file))
        # Exit the loop if all files in files of interest processed
        if not filesNotInDb:
            break
    # If the user specified file is not in db. Log the file in summary and continue
    if filesNotInDb:
       addToSummaryStatus('   File %s in FILES_OF_INTEREST not found in db' % str(filesNotInDb))
    return list(sortedListOfAllFiles)

def setupApplicationBuildGlobals(vcshellArg):
    '''
    Sets the globals related to building the applications under test.
    '''

    global topLevelMakeLocation
    global topLevelMakeCommand
    global applicationList

    topLevelMakeLocation = getTopLevelMakeLocation(vcshellArg)
    topLevelMakeCommand = getTopLevelMakeCommand(vcshellArg)
    applicationList = getApplicationList(vcshellArg)

def getTopLevelMakeLocation(vcshellArg):
    '''
    Return the top level make directory from the database.
    '''
    cmdOutput, exitCode = runVCcommand ('vcdb ' + vcshellArg + ' gettopdir')
    if exitCode==0:
        return cmdOutput.strip('\n')
    else:
        return ''

def getTopLevelMakeCommand(vcshellArg):
    '''
    Return the top level make command from the database.
    '''
    cmdOutput, exitCode = runVCcommand ('vcdb ' + vcshellArg + ' gettopcmd')
    if exitCode==0:
        return cmdOutput.strip('\n')
    else:
        return ''

def getApplicationList(vcshellArg):
    '''
    Get the application list from the database.
    '''
    stdOut, exitCode = runVCcommand (command='vcdb ' + vcshellArg + ' getapps')
    if 'Apps Not found' in stdOut:
        return []
    else:
        return stdOut.split ('\n')

def buildCoverageProject (projectMode, projectName, inplace, workingDirectory, instDir='vcast-inst'):
    '''
    This function will build a coverage project, and add all of the files from the vcdb
    We do not instrument in this function, we do that after the lint analysis runs
    '''
    
    global listOfFiles
    global listOfFilenamesFile
    global globalCoverageProjectExists

    sectionBreak('')
    addToSummaryStatus ('Building Coverage Environment ' + projectName + ' ...')
    startMS = time.time()*1000.0

    os.chdir(workingDirectory) 
    
    try:
        if projectMode=='new':
            # Get the compiler configuration file ...
            getCFGfile ()
                          
            addToSummaryStatus ('   creating the coverage project ...')
            stdOut, exitCode = runVCcommand ('clicast cover env create ' + projectName, True);
            
            if inplace:
                runVCcommand ('clicast -e ' + projectName + ' cover options in_place Y', True);
            else:
                # Create the instrumentation directory if we are not instrumenting in place.
                vcInstDir = instDir
                if not os.path.isdir (vcInstDir):
                    os.mkdir (vcInstDir)
                stdOut, exitCode = runVCcommand ('clicast -e ' + projectName + ' cover options set_instrumentation_directory ' + vcInstDir, True);
                stdOut, exitCode = runVCcommand ('clicast -e ' + projectName + ' cover options in_place n', True);

        if len (listOfFiles) > 0:
            filecountString = str (len (listOfFiles) )
            addToSummaryStatus ('   adding ' + filecountString +' source files  ...')
            # This clicover command will look like:
            # cliccover add_source_vcdb vcshell.db vcast-latest-filelist.txt
            stdOut, exitCode = runVCcommand ('clicover add_source_vcdb ' + projectName + ' ' + \
                 os.path.join (vcshellDBlocation, vcshellDbName) + ' ' + \
                 os.path.join (originalWorkingDirectory, vcWorkArea, listOfFilenamesFile), True);       
                 
        globalCoverageProjectExists=True
        endMS = time.time()*1000.0
        addToSummaryStatus ('   complete (' + getTimeString(endMS-startMS) + ')')
        
    except Exception, err:
        # If we get a flex error, we continue
        if globalAbortOnError:
            raise e
        elif str(err)=='FLEXlm error' or str(err)=='VectorCAST command failed':
            addToSummaryStatus ('   error creating cover project, continuing ...')
            globalCoverageProjectExists = False
        else:
            raise
            
'''
This function will take the full path to the cover Environment vcp
file and return a tuple of the directory and the environment name.
e.g. "/foo/bar/workarea/environment.vcp" will return
( "/foo/bar/workarea", environment )
'''
def coverDirectoryAndName ( coverEnvironmentFullPath ):
    directory = os.path.dirname ( coverEnvironmentFullPath )
    environment = os.path.basename ( coverEnvironmentFullPath )
    return directory, environment

'''
This function will instrument and/or perform Lint analysis on all the
cover environments in a CUDA-based Manage project
'''
def instrumentCudaCoverageProjects ( coverageType,
                                     runLint,
                                     localListOfMainFiles,
                                     workingDir ):
    os.chdir ( workingDir )
    addToSummaryStatus ('Instrumenting CUDA Coverage Environments ...')
    for arch in cudaArchitectures:
        arch_name = cudaArchName ( arch )
        coverageDirectory = os.path.join(workingDir, vcCoverDirectory)
        coverDirectory = os.path.join(coverageDirectory, arch_name)
        instrumentCoverageProject ( coverageType,
                                    runLint,
                                    localListOfMainFiles,
                                    os.path.join ( coverDirectory, arch_name + '.vcp' ) )
        os.chdir ( workingDir )

'''
This function will parse the line read from 'cuda_device_coverage.h'
and generate the search key and actual size from line
Each line we process from will be in the format:
   __device__ __align__(4) char vcast_unit_stmt_bytes_1_device[1] = { 0 };
'''
def getCudaKeyAndSize ( line ):
    pieces = line.strip().split(' ')
    # 3rd element contains the key and size
    key_and_size = pieces[3].split('_')
    # size will be embedded in the last element of key_and_size
    key = '_'.join(key_and_size[:-1])
    start_size = line.find('[')
    end_size = line.find(']')
    size = line[start_size+1:end_size]
    return key, int(size)

'''
Instrumentation will create a header file 'cuda_device_coverage.h'
that contains the coverage objects we need for the CUDA devices.
The original coverage objects need to be as big as the largest
device object, so we will search through each file for the largest size, and
update the coverage objects in vcast_c_options.h to be able to handle data
from all devices.
We will create a dictionary (sizes) whose key is the typemark/name for
the object, and whose value is the largest size we can find
'''
def updateCudaHostEnvironment ( workingDir ):
    addToSummaryStatus ('Verifying CUDA Coverage Environments ...')
    # dictionary of largest sizes found
    # (key is '<object name>')
    maxSizes = {}
    # dictionary of host sizes (for searching)
    # (key is '<object name>)'
    hostSizes = {}
    # dictionary of sizes for each object per architecture
    # (key is '<arch> <object name>')
    archSizes = {}
    for arch in cudaArchitectures:
        arch_name = cudaArchName ( arch )
        sizeFilename = os.path.join ( workingDir,       # location of project
                                      vcCoverDirectory, # location of environments
                                      arch_name,        # architecture folder
                                      arch_name,        # cover environment
                                      'cuda_device_coverage.h' )
        if os.path.isfile ( sizeFilename ):
            addToSummaryStatus ('   scanning options file for ' + arch_name )
            with open ( sizeFilename, 'r' ) as sizeFile:
                # for each line in file
                for line in sizeFile:
                    # if the line matches our template, then process it
                    if line.startswith('__device__'):
                        # extract the key and size from this line
                        sizeKey, size = getCudaKeyAndSize ( line )
                        # need to save the host values for searching later
                        if arch == CUDA_HOST:
                            hostSizes[sizeKey] = size
                        # need to save arch values for populating size array
                        else:
                            archSizes[arch+' '+sizeKey] = size
                        # if the key is already in the dictionary,
                        if sizeKey in maxSizes:
                            # the key value is max between previous and this
                            size = max(size, maxSizes[sizeKey])
                        maxSizes[sizeKey] = size
        else:
            addToSummaryStatus ('   failed to find size file for ' +
                                arch_name +
                                ', continuing ...')

    # Now update the host environment with the max sizes
    hostFilename = os.path.join ( workingDir,       # location of project
                                  vcCoverDirectory, # location of environments
                                  CUDA_HOST,        # architecture folder
                                  CUDA_HOST,        # cover environment
                                  'vcast_c_options.h' )
    addToSummaryStatus ('   updating options file for host' )
    hostFile = open ( hostFilename, 'r' )
    contents = open ( hostFilename ).read()
    hostFile.close()
    # create backup of file
    backup = open ( hostFilename + '.bak', 'w' )
    backup.write ( contents )
    backup.close()
    # replace each copy of the key with the largest size
    for key in maxSizes:
        # we can find objects that were not on the host, so
        # protect against that here
        if key not in hostSizes:
            hostSizes[key] = 0
        original = key + '[' + str(hostSizes[key]) + ']'
        replacement = key + '[' + str(maxSizes[key]) + ']'
        contents = contents.replace(original, replacement)
    # update original file
    hostFile = open ( hostFilename, 'w' )
    hostFile.write ( contents )
    hostFile.close()

    # Now update the host environment with the size array initialization
    addToSummaryStatus ('   updating size information object' )
    hostFilename = os.path.join ( workingDir,       # location of project
                                  vcCoverDirectory, # location of environments
                                  CUDA_HOST,        # architecture folder
                                  CUDA_HOST,        # cover environment
                                  'cuda_size_initialization.h' )
    hostFile = open ( hostFilename, 'w' )
    for key in sorted(archSizes):
        # first item is architecture, second is object name
        pieces = key.split(' ')
        arch = int(pieces[0])
        major = arch / 10
        minor = arch - ( major * 10 )
        arrayIndex = '[' + str(major) + '][' + str(minor) + ']'
        hostFile.write ( 'sizes_' + pieces[1] + arrayIndex + ' = ' +
                         str(archSizes[key]) + ';\n' )
    hostFile.close()

'''
This function will instrument and/or perform Lint analysis on the
specified cover environment
'''
def instrumentCoverageProject ( coverageType,
                                runLint,
                                localListOfMainFiles, 
                                coverEnvironmentFullPath ):
        
    if coverageType != 'none':
        instrumentFiles ( coverageType, localListOfMainFiles, coverEnvironmentFullPath )

    # If the caller requested lint analysis
    if maximumFilesToSystemTest>0 and runLint:
        runLintAnalysis ( coverEnvironmentFullPath )
        

    
def runLintAnalysis (coverEnvironmentFullPath):
    '''
    This will do the Lint analysis
    We need to run the following command on the VC/Cover project
    $VECTORCAST_DIR/clicast -e <env> cover tools lint_analyze
    '''

    workingDir, coverageProjectName  = coverDirectoryAndName (
                                         coverEnvironmentFullPath )
       
    sectionBreak('')
    addToSummaryStatus ('Starting Lint Analysis ...')
    startMS = time.time()*1000.0
    
    try:      
        os.chdir ( workingDir )
        stdOut, exitCode = runVCcommand ('clicast -e ' + coverageProjectName + ' cover tools lint_analyze')
        
        endMS = time.time()*1000.0
        addToSummaryStatus ('   complete (' + getTimeString(endMS-startMS) + ')')
        
    except Exception, err:
        # If we get a flex or command error, we continue
        if str(err)=='FLEXlm error' or str(err)=='VectorCAST command failed':
            addToSummaryStatus ('   error running lint analysis, continuing ...')
            globalCoverageProjectExists = False
        else:
            raise
    
   
    
def instrumentFiles (coverageType, listOfMainFiles, coverEnvironmentFullPath):
    '''
    This function will instrument all of the files in the cover project
    We do this in two parts, for the new files that just got added during
    this round, we need to do an explicit instrument call.  And then we
    need to do a incremental re-instrument to bring the whole project up to date
    '''
    
    global listOfFiles
    
    sectionBreak('')
    startMS = time.time()*1000.0
    
    try:
        
        workingDir, coverageProjectName  = coverDirectoryAndName (
                                               coverEnvironmentFullPath )

        addToSummaryStatus ('Starting Instrumentation for ' + coverageProjectName + ' ...')

        os.chdir (workingDir)
        
        # The instrumented files need functions that are defined in the
        # VectorCAST coverage library file: c_cover_io.c.  The easiest way
        # to get this code into an application is to #include the file 
        # c_cover_io.c into each of the main files of an application.
        # We now use a clicast command to do this.  
        # Previously we used a py function: appendCoverIOfileToMainFiles
        for file in listOfMainFiles:
            stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover append_cover_io true -u' + file, globalAbortOnError)
        
               
        # Call the instrumentor for any new files
        listOfFilesString = ''
        for file in listOfFiles:
            fileNameOnly = os.path.basename(file)
            listOfFilesString += fileNameOnly + ' '
        
        # We don't want to overwhelm the command line if we have 10k files for example
        if len (listOfFilesString) > 1000:
            stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover instrument ' + coverageType, globalAbortOnError)
        else:
            # Run instrumentation on the new files ...
            stdOut, exitCode = runVCcommand ('clicover instrument_' + coverageType.replace ('+', '_') + ' ' + coverageProjectName + ' ' + listOfFilesString, globalAbortOnError)
            # Run incremental re-instrument to pick up any source changes
            stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover source incremental_reinstrument', globalAbortOnError)
            
            
        endMS = time.time()*1000.0
        addToSummaryStatus ('   complete (' + getTimeString(endMS-startMS) + ')')
        
    except Exception, err:
        # If we get a flex error, we continue
        if str(err)=='FLEXlm error' or str(err)=='VectorCAST command failed':
            addToSummaryStatus ('   error instrumenting files, continuing ...')
            globalCoverageProjectExists = False
        else:
            raise   


def envCoverArgString (coverageType):
    '''
    This function will return the correct flag for coverage to the EnvCreate.py call
    '''
    if coverageType=='none':
        return ''
    else:
        return ' --coverage=' + coverageType
        

def splitIncludeList (includeList):
    '''
    includeList is a list of tuples with the paths and type
    This function will break this list into three based on types
    '''
    includes = []
    libs = []
    types = []
    for item in includeList:
        if item[1] == 'LIB':
            libs.append (item[0])
        elif item [1] == 'TYPE':
            types.append (item[0])
        elif item [1] == 'SEARCH':
            includes.append (item[0])

    return includes, types, libs
   
        
def pathArgs (includeList, excludeList):
    '''
    This function will take the two lists and create the args to be passed
    to EnvCreate.py.  The includeList contains tuples with the path as the
    first element, and LIB TYPE or SEARCH as the second.
    '''
    argString = ' '
    includes, types, libs = splitIncludeList(includeList)

    if len (includes) > 0:
        argString += '--includepath='
        for dir in includes:
            argString += dir + ','
        # get rid of the "extra" ,
        argString = argString[:-1] + ' '
        
    if len (types) > 0:      
        argString += '--type_handled_list='
        for dir in types:
            argString += dir + ','
        # get rid of the "extra" ,
        argString = argString[:-1] + ' '        
        
    if len (libs) > 0:      
        argString += '--library_list='
        for dir in libs:
            argString += dir + ','
        # get rid of the "extra" ,
        argString = argString[:-1] + ' '   
        
    if len (excludeList) > 0:
        argString += '--excludepath='
        for I in excludeList:
            argString += I + ','
        # get rid of the "extra" ,
        argString = argString[:-1] + ' '
        
    return argString
            
typesToHandle={} 
typesToHandle['LIB'] = '(L)'
typesToHandle['TYPE'] = '(T)'
typesToHandle['SEARCH'] = '(S)'
def setTypeCommandNeeded (path):
    '''
    This function will determine if we need to invoke vcdb
    to change the path type in vcshell.db.  
    The 'path' parameter is a tuple that looks like: (/home/path, path-type)
        where type can be: TYPE, LIB, SEARCH, NONE
    The listOfPaths is a tuple that looks like: (/home/path, path-type)
        where type can be: (T), (L), or (S)
    If the path is already in the database and the type matches
    no work is needed.
    '''
    global listOfPaths
    
    # for all the paths that are in the database
    for libPath in listOfPaths:
        # if the path we are processing is in the database
        if libPath[0]==normalizePath(path[0]):
            # If the new type is one we care about
            if path[1] in typesToHandle:
                if typesToHandle[path[1]] == libPath[1]:
                    return False
                else:
                    return True
            else:
                return False
                
    # path not in the DB
    return False
    
    
def vcdbArgsOption (vcdbFlagString):
    '''
    '''
    if len (vcdbFlagString) == 0:
        return ''
    else:
        defineFlag = readCFGoption ('C_DEFINE_FLAG') + '=1'
        return ' --vcdbOpt=--flags="' + defineFlag + ',' + vcdbFlagString + '"'
        
        
def inListOfPaths (path):
    '''
    We need this function because listOfPaths is a tuples
    '''
    global listOfPaths
    
    for listItem in listOfPaths:
        if path == listItem[0]:
            return True
            
    return False

 
            
def buildEnvScripts (coverageType, includePathOverRide, envFileEditor, vcdbFlagString, envFilesUseVcdb):
    '''
    This function will use the IDC EnvCreate.py script to build environment scripts for all files.
    '''

    # This has all files not just the ones added to the cover project
    global listOfAllFiles
    # the listOfPaths is a tuple that looks like: (/home/path, path-type)
    global listOfPaths
    global maximumFilesToUnitTest
    
    excludeList = []
    includeList = []
    
    sectionBreak('')
    addToSummaryStatus ('Building Environment Scripts ...')
    startMS = time.time()*1000.0
    
    try:
        if len (listOfAllFiles) > 0:
        
            os.chdir (os.path.join (originalWorkingDirectory, vcWorkArea, vcScriptsDirectory ))
            
            # Get the compiler configuration file ...
            getCFGfile ()
            
            # Use the include path over-ride parameter to 
            # ensure that the directory types are set properly in the db
            for dir in includePathOverRide:
            
                # Any paths with the NONE qualifier should be omitted
                pathType = dir[1].upper()
                if pathType=='NONE':
                    # Only need to exlude if it is in the DB
                    currentPath = normalizePath (dir[0])
                    if inListOfPaths (currentPath):
                        excludeList.append(currentPath)
                    
                # Only modify the directories that are in the database.
                # Some of the directories in the includePathOverRide list might be "adds"
                # in this case, this function call with return false
                elif setTypeCommandNeeded(dir):
                    fullCommand =  'vcdb ' + vcshellDBarg(force=True) + ' setpathtype ' + dir[0] + ' ' + dir[1].upper()
                    stdOut, exitCode = runVCcommand (fullCommand, globalAbortOnError)

                else:
                    # if we get here then this is a new directory so save it to the list along with the type
                    currentPath = normalizePath (dir[0])
                    # Use a tuple so that we maintain the path type
                    includeList.append((currentPath, pathType))
                    

            # Prune the list of all files to remove any .env files that already exist
            prunedList = []
            count = 0
            for fileName in listOfAllFiles:
                # fileName is the full path, so strip path,
                # strip extension, and force upper case
                filePart = os.path.basename(fileName).split('.')[0].upper()
                if not os.path.isfile (filePart + '.env'):
                    prunedList.append (fileName)
                    count = count + 1
                    if count == maximumFilesToUnitTest:
                        break                   
                    
            if len (prunedList) > 0:
                
                # create a temp file that has the pruned list
                tempFile = tempfile.NamedTemporaryFile (delete=False)
                for fileName in prunedList:
                    tempFile.write (fileName + '\n')
                tempFileName = tempFile.name
                tempFile.close()
        
                addToSummaryStatus ('   building ' + str(len(prunedList)) + ' environment scripts ...') 
                
                # Call the EnvCreate.py script to build the env files.
                commandArgs =  ' ' + vcshellDBarg(force=True,cfgFile=True) + ' ' + envCoverArgString(coverageType) 
                commandArgs += pathArgs (includeList, excludeList)
                commandArgs += ' --filelist=' + os.path.join (originalWorkingDirectory, vcWorkArea, tempFileName)
                commandArgs += vcdbArgsOption(vcdbFlagString)
                # This will constuct the .env files with the path to the vcshell, rather than the search paths and unit options
                if envFilesUseVcdb:
                    commandArgs += ' --add_db_name'
                    
                fullCommand =  'vpython '
                fullCommand += pathToEnvCreateScript + commandArgs
                stdOut, exitCode = runVCcommand (fullCommand, globalAbortOnError)
                
                # delete the temp-file
                os.remove (tempFileName)
                
                # Now for each environment script, call the user-supplied editor function
                addToSummaryStatus ('   calling the user-supplied environment script editor ...')
                for filePath in listOfAllFiles:
                    fileName = os.path.basename(filePath)
                    envFileName = fileName.split('.')[0].upper() + '.env'
                    envFileEditor (envFileName)             
    
        endMS = time.time()*1000.0
        addToSummaryStatus ('   complete (' + getTimeString(endMS-startMS) + ')')
    
    except Exception, err:
        # If we get a flex error, we continue
        if str(err)=='FLEXlm error' or str(err)=='VectorCAST command failed':
            addToSummaryStatus ('   error creating environment scripts, continuing ...')
        else:
            raise




def runManageCommands(project, commands):
    '''
    This function  takes a project name and a list of commands, builds a temp file
    containing the commands, and then invokes manage 1 time.
    '''
    manageScriptName='script.msh'

    with open(manageScriptName, "w") as f:
        f.write("\n".join(commands))
        
    # We do not make any of the manage commands fatal ... the project create is done
    # by using runVCcommand directly
    stdOut, exitCode = runVCcommand('manage -p %s --script %s' % (project, manageScriptName), globalAbortOnError)  
    os.remove (manageScriptName) 
    
    return stdOut 


def platformLevelString ():
    '''
    This will return the string that should be used for the Platform level
       Source/Windows, Source/Linux, or Source/Solaris
    '''
    global clicastVersion
    if not clicastVersion:
        clicastVersion, exitCode = runVCcommand('clicast --version', globalAbortOnError)
    if 'Version 6.' in clicastVersion:
        if platform.system()=='Windows':
            return '--level Source/Windows'
        else:
            return '--level Source/Linux'
    else:
        return ''
        

def platformLevelStringWithSlash ():
    if platformLevelString():
        return platformLevelString() + '/'
    else:
        return '--level '


def getListOfCompilerNodes ():
    '''
    This function will interrogate an existing manage project and return the list
    of compiler nodes that are already defined.
    '''
    command = ['--list-compilers']
    stdOut = runManageCommands (manageProjectName, command)
    return [i for i in stdOut.splitlines() if i and not i.startswith('Running')]


def computeCompilerNodeName ():
    '''
    This function will compute the compiler node name backwards from the CFG file
    If there is not a CFG file, we assume we are building for monitored environments
    and we just create a generic node
    '''
    global compilerNodeName  
    global currentLanguage
    
    if os.path.isfile (C_CONFIG_FILE):
        compilerNodeName = readCFGoption ('C_COMPILER_HIERARCHY_STRING').replace (' ', '_')
        currentLanguage = 'c'
        
    elif os.path.isfile (ADA_CONFIG_FILE):
        compilerNodeName = readAdaCFGoption ('COMPILATION_SYSTEM').replace (' ', '_')  
        currentLanguage = 'ada'

    else:
        compilerNodeName = defaultCompilerNodeName
        currentLanguage = 'none'



        
def unitTestTestSuiteName ():
    '''
    We might eventually create separate nodes per compiler
    for now, just using one
    ''' 
    if currentLanguage=='ada':
        return 'UnitTesting-Ada'
    else:
        return 'UnitTesting'
        
def unitTestDefaultGroupName():
    '''
    Returns the default unit test group name.
    '''
    return 'UT-Group'

def unitTestGroupName ():
    '''
    the nextUTgroupName will contain the unique group
    name based on the contents of the existing project
    ''' 
    if currentLanguage=='ada':
        return '{0}{1}{2}'.format(unitTestDefaultGroupName(), '-Ada-', compilerNodeName)
    else:
        return '{0}{1}{2}'.format(unitTestDefaultGroupName(), '-', compilerNodeName)

def addCudaGencodeOptions ( manageCommands ):
    if len(cudaArchitectures) > 0:
        # need to find original C_COMPILE_CMD
        cwd = os.getcwd()
        os.chdir(cfgFileLocation)
        compileCmd, exitCode = runVCcommand('clicast -lc get_option C_COMPILE_CMD')
        linkCmd, exitCode = runVCcommand('clicast -lc get_option C_LINK_CMD')
        os.chdir(cwd)

        # build gencode options
        cudaOptions = ''
        for arch in cudaArchitectures:
            if 'HOST' not in arch:
                cudaOptions = ( cudaOptions + ' -gencode' +
                                ' arch=compute_' + arch +
                                '\,code=sm_' + arch )
        # set compile/link commands to original command plus gencode options
        addToSummaryStatus ("   adding 'gencode' options for CUDA Unit Test Node")
        manageCommands.append('--compiler=' + compilerNodeName +
                              ' --config=C_COMPILE_CMD="' +
                              compileCmd.strip('\n') + ' ' + cudaOptions + '"')
        manageCommands.append('--compiler ' + compilerNodeName +
                              ' --config=C_LINK_CMD="' +
                              linkCmd.strip('\n') + ' ' + cudaOptions + '"')
            
def buildCompilerNode ():
    '''
    This function will add a new compiler node to the manage tree
    If we find a CCAST_.CFG file we create a node for the compiler
    from this config, same thing for ADACAST_.CFG.  If we do not 
    find a CFG file, we create a "generic" node
    '''

    global compilerNodeName
    manageCommands = []
    computeCompilerNodeName ()
    currentCompilerNodeList = getListOfCompilerNodes()
    
    if compilerNodeName not in currentCompilerNodeList:
    
        if currentLanguage=='c':
            manageCommands.append('--cfg-to-compiler=CCAST_.CFG')
            # Manage Creates a testsuite node called "TestSuite" by default
            manageCommands.append('--testsuite=TestSuite --delete')

            # add gencode options for CUDA
            addCudaGencodeOptions ( manageCommands )
            
        elif currentLanguage=='ada':
            manageCommands.append('--cfg-to-compiler=ADACAST_.CFG')
            manageCommands.append('--testsuite=TestSuite --delete')

        else:
            manageCommands.append(platformLevelStringWithSlash() + compilerNodeName + ' --create')
            
        # Create the TestSuite and Group Nodes
        manageCommands.append(platformLevelStringWithSlash() + compilerNodeName + '/' + unitTestTestSuiteName() + ' --create')
        manageCommands.append('--group ' + unitTestGroupName() + ' --create')
        manageCommands.append(platformLevelStringWithSlash() + compilerNodeName + '/' + unitTestTestSuiteName() + ' --add ' + unitTestGroupName())
        
    return manageCommands
   

def getDefaultSystemTestingGroupName():
    '''
    This function returns the default system testing manage project group name
    '''
    return 'ST-Group'


def getDefaultSystemTestingTestSuiteName():
    '''
    This function return the default system testing manage project testsuite name
    '''
    return 'SystemTesting'

def commandsToBuildProjectTree ( projectPaths,
                                 coverageType,
                                 tcTimeOut,
                                 systeTestCompilerNodeName='SystemTestingCompilerNode' ):
    '''
    This function will create the basic structure of the manage project
    groupAndProject is a list of tuples, with the first element in the tuple being
    the group name, and the second element being the full path to the .vcp file
    '''

    manageCommands = []
    if platformLevelString():
        manageCommands.append(platformLevelString() + ' --create')

    lanaguage='none'
    manageCommands.append(platformLevelString() + ' --config="VCDB_FILENAME=%s"' % (os.path.join (vcshellDBlocation, vcshellDbName)))
    manageCommands.append(platformLevelString() + ' --coverage-type="%s"' % (coverageType))
    manageCommands.append(platformLevelStringWithSlash()+ systeTestCompilerNodeName + ' --create')
    
    manageCommands.append('{0}{1}/{2} --create'.format(
        platformLevelStringWithSlash(),
        systeTestCompilerNodeName,
        getDefaultSystemTestingTestSuiteName()))
    manageCommands.append('--group %s --create' % getDefaultSystemTestingGroupName())
    manageCommands.append(
        '{0}{1}/{2} --add {3}'.format(
            platformLevelStringWithSlash(),
            systeTestCompilerNodeName,
            getDefaultSystemTestingTestSuiteName(),
            getDefaultSystemTestingGroupName()))
    for projectPath in projectPaths:
        if globalCoverageProjectExists and len (projectPath) > 0:
            addToSummaryStatus ('   adding the coverage environment ' + projectPath)
            manageCommands.append('--import ' + os.path.join ('..', vcCoverDirectory, projectPath))
            projectName = os.path.splitext(os.path.basename(projectPath))[0]
            manageCommands.append('--group {0} --add {1}'.format(
                getDefaultSystemTestingGroupName(),
                projectName))
    
    # Make sure that we got a number for this option
    if type (tcTimeOut)==int:
        # Only set it explicitly if it is NOT 0
        if tcTimeOut!=0:
            manageCommands.append(' --config=TEST_CASE_TIMEOUT='+str(tcTimeOut))

    return manageCommands
    
    
    
@contextlib.contextmanager
def make_tempDirectory():
    '''
    Create a temp directory for use when building the script files
    '''
    tempDirectory = tempfile.mkdtemp()
    yield tempDirectory
    shutil.rmtree(tempDirectory)

        
class scriptFiles:
    '''
    This class Is used to create to keeep track of the script files for one file
    '''
    def __init__(self, tempDirectory, envFile):
        self.baseFilename = os.path.splitext (os.path.basename (envFile))[0]
        self.envFilename = os.path.join(tempDirectory, self.baseFilename + '.env')
        self.originalScriptFile = envFile

    def generate_files(self):
        if not os.path.isfile(self.originalScriptFile):
            return
        
        shutil.copyfile(self.originalScriptFile, self.envFilename)
        

def filterEnviroList(enviroList):
    '''
    Remove any environments form the environment list that are already in the Manage project

    We check if the vcWorkArea exists and has a list of files already in the project.  
    If it does, it will remove those files from the list that was passed in.
    Initially, we were checking the full path to the vce ... but that was wrong
    because manage does not allow two enivornments with the same name!  
    So now, the firest thing we do is to strip the directory prefix from enviroList
    '''
        
    if os.path.isdir (os.path.join (originalWorkingDirectory, vcWorkArea)):
        existingEnviroments = os.path.join (originalWorkingDirectory, vcWorkArea, listOfEnvironmentsInProject)
        if os.path.isfile (existingEnviroments):
            addToSummaryStatus ('   checking the existing environments file ... ')
            oldFile = open (existingEnviroments, 'r')
            lines = oldFile.readlines()
            # Build a list of the enviro names currently in the project
            bareEnviroNames = []
            for line in lines:
                bareEnviroNames.append (os.path.basename (line.strip()))
            # If any of the new enviros have that same name, remove them
            listCopy = enviroList[:]
            for enviro in listCopy:
                strippedName = os.path.basename(enviro)
                if strippedName in bareEnviroNames:
                    addToSummaryStatus ('   environment name: ' + strippedName + ' already exists in this project ...')
                    enviroList.remove (enviro)

                    
                    
def saveEnvironmentsInProject (enviroList):
    '''
    Append the new enviro list to the list of enviros in the project
    '''
    fullEnvironmentList = os.path.join (originalWorkingDirectory, vcWorkArea, listOfEnvironmentsInProject);
    oldFile = open (fullEnvironmentList, 'a')
    for file in enviroList:
        oldFile.write (file + '\n')
    oldFile.close() 
    
        
def createFileClassList (tempDirectory):
    '''
    This function will create the .env file
    for each of the files that we want to add to the manage project
    We use the class above to manage the actual work
    The files get generated in a temporary directory
    '''

    global listOfAllFiles
    global maximumUnitTestsToBuild
    
    # First we find the list of all .env files that exist in 
    pathToEnvFiles = os.path.join (originalWorkingDirectory, vcWorkArea, vcScriptsDirectory)
    envFileList = glob.glob (os.path.join (pathToEnvFiles, '*.env'))
    filterEnviroList (envFileList)
    saveEnvironmentsInProject (envFileList)
        
    out = []
    for enviroCount, envFile in enumerate (envFileList):
        if enviroCount==maximumUnitTestsToBuild:
            break
        else:
            out.append(scriptFiles(tempDirectory, os.path.join (pathToEnvFiles, envFile)))

    for i in out:
        i.generate_files()

    return out

def commandsToAddOneEnvironment (fileClass):
     '''
     This function will return the commands needed to add one file to the manage project
     '''
     levelArg = platformLevelStringWithSlash() + compilerNodeName + '/' + unitTestTestSuiteName() + '/' + fileClass.baseFilename
     out = []      
     out.append ('--import ' + fileClass.envFilename)
     out.append ('--group ' + unitTestGroupName() + ' --add ' + fileClass.baseFilename)
     out.append ('--migrate ' + levelArg)
     return out
    
def commandsToAddAllEnvironment ():
    '''
    This function will return the command needed to add all .env files to the
    manage project
    '''
    
    levelArg = platformLevelStringWithSlash() + compilerNodeName + '/' + unitTestTestSuiteName()

    out = ""
    envScriptDir = os.path.join(originalWorkingDirectory,
                                vcWorkArea, vcScriptsDirectory)
    out += '--import-all ' + envScriptDir
    out += ' --group ' + unitTestGroupName()
    out += ' --migrate ' + levelArg
    return [out]
    
    
def commandsToBuildOneEnvironment (fileClass):
    '''
    This function will return the commands needed to build one environment in the manage project
    '''
    levelArg = platformLevelStringWithSlash() + compilerNodeName + '/' + unitTestTestSuiteName() + '/' + fileClass.baseFilename
    
    out = []   
    out.append(levelArg + ' --build')
    out.append(levelArg + ' --clicast-args tools auto_test temp.tst')
    out.append(levelArg + ' --clicast-args test script run temp.tst')
    out.append(levelArg + ' --apply-changes --force')
    return out


def commandsToExecuteOneEnvironment (fileClass):
    '''
    Not currently used.
    This function will return the commands needed to execute one environment in the manage project
    We don't use this yet, because execute could hang on a test etc.
    '''
    levelArg = platformLevelStringWithSlash() + compilerNodeName + '/' + unitTestTestSuiteName() + '/' + fileClass.baseFilename
    
    out = []
    out.append(levelArg + ' --execute')
    return out


    
def commandsToAddAndBuildEnvironments (fileClassList):
    '''
    This function will return a list of all of the commands needed to add
    all of the environmet scripts to the manage project
    '''    
    addCommands = []
    buildCommands = []
    if (maximumFilesToUnitTest) > 0 and (not vcEnterpriseMode):
        addCommands += commandsToAddAllEnvironment ()
    if maximumUnitTestsToBuild>0:
        for enviroCount, fileClass in enumerate(fileClassList):
            if vcEnterpriseMode:
                addCommands += commandsToAddOneEnvironment (fileClass)
            # To make this quicker, we only build maximumUnitTestsToBuild environment
            if enviroCount < maximumUnitTestsToBuild:
                 buildCommands += commandsToBuildOneEnvironment (fileClass)

    return addCommands, buildCommands
    
 
 
def addEnvFilesToManageProject ():
    '''
    We will loop over all of the .env files and add those environments
    to the Manage project
    '''   
        
    sectionBreak('')
    addToSummaryStatus ('Adding Unit Test Scripts to Manage Project ...')
    startMS = time.time()*1000.0
    
    with make_tempDirectory () as tempDirectory:
        fileClassList = createFileClassList(tempDirectory)
        
        # Get the commands needed to do the work
        addCommands, buildCommands = commandsToAddAndBuildEnvironments (fileClassList)        
        
        # I do this in two pieces so that we can have times for each piece.
        # Run the 'add' commands
        if len (addCommands) > 0:
            stdOut = runManageCommands(manageProjectName, addCommands )
            endMS = time.time()*1000.0
            addToSummaryStatus ('   ' + str (len (addCommands)/3) + ' environment script(s) added (' + getTimeString(endMS-startMS) + ')')
        
        # Run the 'build' commands
        if len (buildCommands) > 0:
            startMS = time.time()*1000.0
            stdOut = runManageCommands(manageProjectName, buildCommands )
            endMS = time.time()*1000.0
            addToSummaryStatus ('   ' + str (len (buildCommands)/3) + ' environment node(s) built (' + getTimeString(endMS-startMS) + ')')


            
def convertOneLine (originalLine, flagText, newValue):
    '''
    Common code to simply replace the "end" of the line with the flagText with the new value
    '''
    if flagText in originalLine:
        endIndex = originalLine.find (flagText) + len (flagText)
        return originalLine[0:endIndex] + ' = ' + newValue.replace('\\','\\\\') + '\n'

        
commonCommentLine     = '        # **Auto-inserted by VectorCAST from vcshell data \n'
def commentForExecutable():
    '''
    We comment the code with the names of the apps if there are multiple apps
    '''
    returnString = commonCommentLine
    if len (applicationList) > 1:
        returnString += '        #   project has multiple applications: '
        for app in applicationList:
            returnString += os.path.basename(app) + ' '
            
        returnString += '\n'
    return returnString
 
def isRunTestCaseLine(original):
    '''
    This function checks if the original is a run test case line
    '''
    return './' in original and 'nameOfTestExecutable' in original

def convertRunTestCaseLineToAbs(original):
    '''
    This function removes the execute string from original
    '''
    return original.replace("'./' + ", '')

locationWhereWeRunMakeString = '        self.locationWhereWeRunMake'
topLevelMakeCommandString    = '        self.topLevelMakeCommand'
whereWeRunTestsString        = '        self.locationWhereWeRunTests'
nameOfExecutableString       = '        self.nameOfTestExecutable'
listOfTestcasesString        = '        self.masterListOfTestCases'
def convertSystemTestLine (originalLine):
    '''
    This function replaces specific lines in the system_tests.py file based on the 
    values that we retrieved from the vcshell.db during initialization
    '''
    global globalUpdateSystemTestPy
    if globalUpdateSystemTestPy is False:
        return originalLine
		
    exe = str()
    if len(applicationList) > 0:
        exe = applicationList[0]

    if locationWhereWeRunMakeString in originalLine:
        return commonCommentLine + convertOneLine (originalLine, locationWhereWeRunMakeString, 'r"' + topLevelMakeLocation + '"')
    
    elif topLevelMakeCommandString in originalLine:
        return commonCommentLine + convertOneLine (originalLine, topLevelMakeCommandString, 'r"' + topLevelMakeCommand + '"')
        
    # TBD: We could have multiple applications in the vcdb, for now I am just choosing the first one
    elif len(applicationList) > 0 and  whereWeRunTestsString in originalLine:
        # location is the first part of the path ...
        location = os.path.dirname(applicationList[0])
        return commentForExecutable() + convertOneLine (originalLine, whereWeRunTestsString, 'r"' + location + '"')

    elif isRunTestCaseLine(originalLine) and os.path.isabs(exe):
        return convertRunTestCaseLineToAbs(originalLine)

    # TBD: We could have multiple applications in the vcdb, for now I am just choosing the first one
    elif exe and nameOfExecutableString in originalLine:
        return commentForExecutable() + convertOneLine (originalLine, nameOfExecutableString, 'r"' + exe + '"')
        
    # TBD: We could have multiple applications in the vcdb, for now I am just choosing the first one
    elif listOfTestcasesString in originalLine:
        return ( '        # TBD: Testcase(s) to execute\n' +
                 convertOneLine (originalLine, listOfTestcasesString, "[TestCase('Test1')]" ) )
        
    else:
        return originalLine

            
def autoConfigureSystemTest():
    '''
    This function will open the system_test.py file in the just created manage project 
    and fill in some of the varaibles that we captured during the build process
    '''

    # We only do this special processing if we have "good data" for the topLevelMakeCommand
    if len (topLevelMakeCommand) > 0:
    
        # create temp file to hold the updates
        addToSummaryStatus ('   updating the system_test.py file ...')       

        systemTestFileName = os.path.join (os.getcwd(), manageProjectName, 'python', 'system_tests.py')
        oldFile = open (systemTestFileName, 'r')
        newFile = tempfile.NamedTemporaryFile (delete=False)
        
        for line in oldFile:
            newFile.write(convertSystemTestLine (line))
        oldFile.close()
        newFile.close()
        shutil.move(newFile.name, systemTestFileName)
    
def buildCudaEnterpriseProject ( coverageType, tcTimeOut, workArea ):
    '''
    This function will create a manage project for a CUDA environment.
    This is different than typical projects because we have multiple
    cover environments, one per CUDA architecture
    '''

    sectionBreak('')  
    addToSummaryStatus ('Building VectorCAST Project for CUDA ...')
    startMS = time.time()*1000.0
    addToSummaryStatus ('   location: ' + os.getcwd())

    # Get the compiler configuration file we do this in all cases, because
    # we could be using a new CFG file for an existing manage project.
    # Think about one that had Ada, and now we are adding C
    getCFGfile ()
    
    # Create the empty manage project    
    stdOut, exitCode = runVCcommand ('manage -p' + manageProjectName + ' --create ', True )
        
    addToSummaryStatus ('   building project structure nodes')
        
    # build a list of all of the coverage projects we just created
    projectPaths = []
    for arch in cudaArchitectures:
        arch_name = cudaArchName ( arch )
        vcpFile = os.path.join ( workArea, vcCoverDirectory, arch_name, arch_name + '.vcp' )
        projectPaths.append ( vcpFile )
    
    # To make this fast, we write all of the manage commands to build the 
    # basic project structure, into a command file and then call manage.exe 
    # one time with this file.
    commands = commandsToBuildProjectTree( projectPaths, coverageType, tcTimeOut, 'CudaSystemTest' )

    # we don't want Manage moving our instrumented source code anywhere
    commands.append(' --group ST-Group --apply-instrumentation=NEVER')

    stdOut = runManageCommands(manageProjectName, commands)
        
    # Auto-configure the system_test.py file
    autoConfigureSystemTest ()

    # update host environment coverage objects with sizes
    # based on all architectures
    updateCudaHostEnvironment ( workArea )
        
    # Determine the name of the compiler node, and if we need to build a new one ...
    nodeCommands =  buildCompilerNode ()
    stdOut = runManageCommands(manageProjectName, nodeCommands)

    # Now spin though all of the Env files and add those nodes to the manage project
    if maximumUnitTestsToBuild>0:
        addEnvFilesToManageProject ()

    endMS = time.time()*1000.0
    addToSummaryStatus ('   complete (' + getTimeString(endMS-startMS) + ')')
            
def buildEnterpriseProject (projectMode, coverageType, tcTimeOut):
    '''
    This function will create a manage project, add the already existing Cover Project
    and then also add all of the UT environment scripts
    '''
    global maximumUnitTestsToBuild

    sectionBreak('')  
    addToSummaryStatus ('Building VectorCAST Project ...')
    startMS = time.time()*1000.0
    addToSummaryStatus ('   location: ' + os.getcwd())


    # Get the compiler configuration file we do this in all cases, because
    # we could be using a new CFG file for an existing manage project.
    # Think about one that had Ada, and now we are adding C
    getCFGfile ()
    
    if projectMode == 'new':

        # Create the empty manage project    
        stdOut, exitCode = runVCcommand ('manage -p' + manageProjectName + ' --create ', True )
        
        addToSummaryStatus ('   building project structure nodes')
        
        # To make this fast, we write all of the manage commands to build the 
        # basic project structure, into a command file and then call manage.exe 
        # one time with this file.
        projectPaths = []
        # add coverage project if found
        if len(coverageProjectName) > 0 and maximumFilesToSystemTest > 0:
            projectPaths.append (os.path.join ('..',
                                               vcCoverDirectory,
                                               coverageProjectName + '.vcp'))
        commands = commandsToBuildProjectTree( projectPaths, coverageType, tcTimeOut)
        stdOut = runManageCommands(manageProjectName, commands)
        
        # Auto-configure the system_test.py file
        autoConfigureSystemTest ()

    # Determine the name of the compiler node, and if we need to build a new one ... 
    nodeCommands =  buildCompilerNode ()
    stdOut = runManageCommands(manageProjectName, nodeCommands)
        
    # Now spin though all of the Env files and add those nodes to the manage project
    addEnvFilesToManageProject ()
    
    endMS = time.time()*1000.0
    addToSummaryStatus ('   complete (' + getTimeString(endMS-startMS) + ')')

def findInstrumentedFilename(coverWorkarea, directory, filename):
    '''
    This subprogram will look in the appropriate directory for the
    instrumented version of the source file.
    If the source filename is "foobar.cu", then the instrumented
    file will be in the format "foobar.*.cu" (where * is a number
    that we don't care about).
    If the file is found, this will return a #include string.
    If the file is not found, this will return a #error string.
    '''
    instrumented, extension = os.path.splitext(filename)
    fileList = glob.glob (os.path.join (coverWorkarea,
                                        directory,
                                        instrumented + '.*' + extension))
    if len(fileList) == 0:
        return '#error "no file ' + filename + '"'
    else:
        if len(fileList) > 1:
           addToSummaryStatus("Found multiple versions of " + filename + " in " + directory)
           addToSummaryStatus("   Using " + fileList[0])
        return '#include "' + fileList[0] + '"'


def buildCudaAggregateFiles(coverWorkarea):
    '''
    This function will cycle through all of the source files to create
    an "instrumented" version that will pull in the file that is
    instrumented for the appropriate architecture
    '''
    addToSummaryStatus ( "Building CUDA aggregation source files" )
    # need to write each file into a data file so that system_tests.py
    # can replace the original source with the aggregate version 
    # after instrumentation
    list_file = open ( os.path.join ( coverWorkarea, 'vcast.cuda.txt' ) , 'w' )
    for a_file in listOfAllFiles:
        filename = os.path.basename(a_file)
        list_file.write ( a_file + '\n' )
        the_file = open(a_file + '.vcast.cuda', 'w')
        # If __CUDA_ARCH__ is defined, we're compiling for GPUs
        the_file.write ( '#ifdef __CUDA_ARCH__\n' )
        the_file.write ( '\n' )
        if_text = '#if '
        for arch in cudaArchitectures:
            # only do this for 'real' architectures
            if arch.isdigit():
                # determine full path to instrumented file
                toWrite = findInstrumentedFilename(coverWorkarea, 
                                                   cudaArchName ( arch ),
                                                   filename )
                # for compile switch "arch=compute30", the __CUDA_ARCH__
                # flag needs to be 300
                arch_flag = arch + '0'
                the_file.write ( if_text + cudaArchMacro ( arch, False ) + '\n' )
                the_file.write ( findInstrumentedFilename(coverWorkarea, 
                                                          cudaArchName ( arch ),
                                                          filename) +
                                 "\n\n" )
                if_text = '#elif '
        # end of CPU code
        the_file.write ( '#endif\n\n' )

        # handle Host architecture ('else' block)
        the_file.write ( '#else\n' )
        the_file.write ( findInstrumentedFilename(coverWorkarea, 
                                                  CUDA_HOST,
                                                  filename) +
                         '\n\n' )
        the_file.write ( '#endif\n' )

        the_file.close()

    
manageProjectNotFound='not-found'
def findManageProject():
    '''
    This helper function will change the working directory to where
    the manage project is, and then return the manage project name.
    '''
    manageProjectName = manageProjectNotFound
    manageDirectory = os.path.join (originalWorkingDirectory, vcWorkArea, vcManageDirectory)
    if os.path.isdir(manageDirectory):
        os.chdir (manageDirectory)
        
        # Figure out the name of the manage project
        for file in os.listdir('.'):
            if file.endswith ('_project.vcm'):
                # We just grab the first one because there should only be one!
                manageProjectName = file
                break
    if manageProjectName==manageProjectNotFound:
        print 'Manage Project Does Not Exist'
    return manageProjectName
    
    

def findCoverProject():
    '''
    This helper function will change the working directory to where
    the cover project is, and then return the cover project name.
    '''
    os.chdir (os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory ))
    
    # Figure out the name of the manage project
    coverProjectName = ''
    for file in os.listdir('.'):
        if file.endswith ('_coverage.vcp'):
            # We just grab the first one because there should only be one!
            coverProjectName = file
            break
            
    return coverProjectName
    

def startManageGUI():
    '''
    This function will simply start VC for the manage project
    '''
    manageProjectName = findManageProject()
    if manageProjectName!=manageProjectNotFound:
        print ('Opening VC Project ...')
        commandToRun = os.path.join (vcInstallDir,'vcastqt') + ' -e ' + manageProjectName
        print '   ' + commandToRun
        subprocess.call (commandToRun, shell=True)
        # Change back to original dir
        os.chdir (originalWorkingDirectory)
    
    

def startAnalytics(vcshellLocation):
    '''
    This function will simply start VC for the manage project
    '''
   
    manageProjectName = findManageProject() 
    if manageProjectName!=manageProjectNotFound:
        projectArgument = '--project=' + manageProjectName
    elif os.path.isfile (os.path.join (vcshellLocation, vcshellDbName)):
        os.chdir (vcshellLocation)
        projectArgument = '--vcdb=%s' % vcshellDbName
    else:
        print 'VCShell Database does not exist'
        return
    
    # Start vcdash
    # Start a browser window
    print ('This script will startup the VectorCAST/Analytics server')
    print ('   Once the server initialization completes, you may')
    print ('   view the VectrorCAST/Analytics Dashboard by')
    print ('   pointing your broswer at URL: http://localhost:8128/')
    
    print ('Starting VC/Analytics Server ...')
    commandToRun = os.path.join (vcInstallDir,'vcdash ') + projectArgument
    print '   ' + commandToRun
    try:
        # user needs to hit ctrl-c to exit vcdash, so handle exception
        subprocess.call (commandToRun, shell=True)
    except:
        pass
    # Change back to original dir
    os.chdir (originalWorkingDirectory)
        

def enableCoverage():
    '''
    Enable coverage for the Coverage Project
    '''

    manageProjectName = findManageProject()
    if manageProjectName!=manageProjectNotFound:
        coverProjectName = manageProjectName.split ('_')[0] + '_coverage'
        stdOut, exitCode = runVCcommand ('manage -p' + manageProjectName + ' -e ' + coverProjectName + ' --enable-instrument-in-place', globalAbortOnError)

        # We have to do a reinstrument action to pick up the changes, because the enable simply
        # copies the new foo.c file onto the foo.c.vcast.bak, and relies on the incremental_reinstrument to
        # compare the files and decide what needs to be re-instrumented.
        coverProjectName = findCoverProject()
        stdOut, exitCode = runVCcommand ('clicast -e ' + coverProjectName + ' cover source incremental_reinstrument', globalAbortOnError)
        # Change back to original dir
        os.chdir (originalWorkingDirectory)
    

def disableCoverage():
    '''
    Disable coverage for the Coverage Project
    '''
    manageProjectName = findManageProject()
    if manageProjectName!=manageProjectNotFound:
        coverProjectName = manageProjectName.split ('_')[0] + '_coverage'
        stdOut, exitCode = runVCcommand ('manage -p' + manageProjectName + ' -e' + coverProjectName + ' --disable-instrument-in-place', globalAbortOnError)
        # Change back to original dir
        os.chdir (originalWorkingDirectory)

                   
       
def findAllEnvironments (rootDirectory):
    '''
    This function will search for all .vce files starting at rootDirectory
    and return them in a list
    '''
    returnList = []
    
    addToSummaryStatus ('Finding List of Existing Environments ...')
    
    if not os.path.isdir (rootDirectory):
        print 'Invalid directory path: ' + rootDirectory
    else:
        for root, dirs, files in os.walk(rootDirectory):
            for name in dirs:
                candidateVCE = os.path.abspath (os.path.join(root, name+'.vce'))
                candiateVCP = os.path.abspath (os.path.join(root, name+'.vcp'))
                if os.path.isfile (candiateVCP):
                    returnList.append (candiateVCP)
                elif '.BAK' not in candidateVCE and os.path.isfile (candidateVCE):
                    returnList.append (candidateVCE)     

        addToSummaryStatus ('   found ' + str(len (returnList)) + ' total environments ...')
        
        # Filter the list by removing any environments that we previously added
        filterEnviroList (returnList)
        if len (returnList) ==0:
            addToSummaryStatus ('   no unique environments to be added to the project ...')
        else:
            addToSummaryStatus ('   found ' + str(len (returnList)) + ' environment(s) not currently in the project')
    
    return returnList
    
    
    
def addEnviromentsToManage (enviroList):
    '''
    This function will take a list of already built environments 
    and Cover Project and add them to the Manage project
    '''
    manageCommands = []
    
    sectionBreak('')
    addToSummaryStatus ('Adding Unit Test Environments to Manage Project ...')
    startMS = time.time()*1000.0   
   
    for enviro in enviroList:
        addToSummaryStatus ('   Adding environment: ' + os.path.basename (enviro))
        manageCommands.append ('--import ' + enviro)
        if '.vce' in enviro:
            # Get the commands needed to do the work
            manageCommands.append ('--group ' + unitTestGroupName() + ' --add ' + os.path.splitext (os.path.basename (enviro))[0])
        elif '.vcp' in enviro:
            manageCommands.append ('--group {0} --add {1}'.format(
                getDefaultSystemTestingGroupName(),
                os.path.splitext (os.path.basename (enviro))[0]))
                    
    if len (manageCommands) > 0:
        stdOut = runManageCommands(manageProjectName, manageCommands )
        endMS = time.time()*1000.0
        addToSummaryStatus ('   ' + str (len (enviroList)) + ' environment(s) added (' + getTimeString(endMS-startMS) + ')')
           
    
def vcmFromEnvironments (projectName, rootDirectory, statusfile, verbose):
    '''
    This function support an alternate way of building a Manage project
    Rather than using a vcshell.db it creates a Manage project for existing
    VectorCAST Unit Test Environments
    '''
    global summaryStatusFileHandle
    global maximumUnitTestsToBuild
    global maximumFilesToUnitTest
    global verboseOutput
    global manageProjectName
    global coverageProjectName
    
    verboseOutput = (verbose=='True')
    manageProjectName   = projectName + '_project'
    
    coverageProjectName=''
    maximumUnitTestsToBuild = 0
    maximumFilesToUnitTest = 0
   
    sectionBreak ('')
    summaryStatusFileHandle = open (statusfile, 'w', 1)
    addToSummaryStatus (toolName)
    startMS = time.time()*1000.0  
    rootDirectory = os.path.abspath(rootDirectory)
 
    # Build the work-area directory structure
    # or just change our default directory to be the work-area and return "update"
    projectMode=buildWorkarea()   
       
    # Find all of the .vce and .vcp files downstream of the rootDirectory
    enviroList = findAllEnvironments(rootDirectory)
    
    if len (enviroList) > 0:
      
        # Build the manage project structure
        os.chdir (os.path.join (originalWorkingDirectory, vcWorkArea, vcManageDirectory ))
        buildEnterpriseProject (projectMode, 'none', 0)
        
        # Add the environments ...
        addEnviromentsToManage (enviroList)
        
        # Save the enviro list for next time
        saveEnvironmentsInProject(enviroList)

        endMS = time.time()*1000.0
        addToSummaryStatus ('Total Time: ' + getTimeString(endMS-startMS))
        
    else:
        addToSummaryStatus ('   refreshing the project ...')

        # We want to call the --refresh command below even if we did not add any new enviros
        # This allows the user to "push" new coverage data for an existing environment.
        os.chdir (os.path.join (originalWorkingDirectory, vcWorkArea, vcManageDirectory ))
        # We need to do this to force manage to build the coverage data cache so that Analytics 
        # has the data it needs even if the Manage project is never opened
        manageCommands = []
        
        # TBD: Do we want to do this only for the local enviro?
        manageCommands.append ('--refresh --force')  
        stdOut = runManageCommands(manageProjectName, manageCommands )
           
       
    # Close the summary file
    summaryStatusFileHandle.close()



allowedEditTypes = ['replace', 'insert']
def commonEnvFileEditor(pathToEnvFile, editType, flag='', oldValue='', newValue='', newCommand=''):
    '''
    Since so much of the code (temp file looping etc) is common
    all of the envirionment editors use this common function
    '''
    tempFile = tempfile.NamedTemporaryFile (delete=False)
    envFile = open (pathToEnvFile, 'r')
    for line in envFile:
        if editType=='replace':
            if flag in line and oldValue in line:
                tempFile.write (flag + ': '  + newValue + '\n')
            else:
                tempFile.write (line)
        elif editType=='insert':
            if 'ENVIRO.END' in line:
                tempFile.write (newCommand)
                tempFile.write (line)
            else:
                tempFile.write (line);
            
    tempFileName = tempFile.name
    tempFile.close()
    envFile.close()
    shutil.copyfile (tempFileName, pathToEnvFile)
    os.remove (tempFileName)
    
    
    
def editEnvCommand (pathToEnvFile, flag, oldValue, newValue):
    '''
    This function will allow the user to edit the default default .env file
    It will make this conversion 
        ENVIRO.<flag>: oldValue  -> ENVIRO.<flag>: newValue
    Example
        ENVIRO.STUB: ALL_BY_PROTOTYPE  -> ENVIRO.STUB: NONE
    '''
    commonEnvFileEditor (pathToEnvFile=pathToEnvFile, editType='replace', flag=flag, oldValue=oldValue, newValue=newValue)


    
def insertEnvCommand (pathToEnvFile, newCommand):
    '''
    This function will allow the user to add a new command or block to the default .env file 
    We insert this new command, right before the ENVIRO.END
    '''
    commonEnvFileEditor (pathToEnvFile=pathToEnvFile, editType='insert', newCommand=newCommand)
    
    
def buildListOfMainFilesFromDB(vcshellArg):
    '''
    This function will retrieve the list of files whre we should insert c_cover_io ...
    '''
    global cudaHostOnlyFiles

    sectionBreak('')
    addToSummaryStatus ('Computing insert locations for c_cover_io.c ...')
    returnList = []
        
    stdOut, exitCode = runVCcommand ('vcdb ' + vcshellArg + ' getapps', globalAbortOnError) 
    if 'Apps Not found' in stdOut:
        applicationList = []
    else:
        applicationList = stdOut.rstrip('\n').split('\n')
    
    if len (applicationList)>0:
        
        # Build a list of sets.  One file set for each application
        appFileLists = []
        for app in applicationList: 
            stdOut, exitCode = runVCcommand ('vcdb ' + vcshellArg + ' --app=' + app + ' getappfiles', globalAbortOnError)
            listOfAppFiles = stdOut.rstrip('\n').split('\n')
            
            # but only consider files that are in the cover project
            setOfAppFiles = set (listOfAppFiles) & set (listOfFiles)
                       
            fileSet = set()
            for file in setOfAppFiles:
                fileName = os.path.basename (file)
                if file not in cudaHostOnlyFiles:
                    fileSet.add (fileName) 
            appFileLists.append (fileSet)
           
        # if we have exactly one application, just return the first filename in the list ...
        if len (appFileLists)==1 and len (appFileLists[0])>0:
           returnList.append (appFileLists[0].pop())

        elif len (appFileLists) > 1: # we have multiple applications, at least 2 ...
            
            # A candidate for where to put the c_cover_io is a file that exists in ALL applications
            # Let's see if there are one or more common files and if so return one of these ...
            commonFileList =  (appFileLists[0]).intersection(*appFileLists)
            if len (commonFileList) > 0:
                returnList.append (commonFileList.pop())
           
            else:  
                # there are no common files, so let's find the unique files in each application.
                numberOfApplications = len (appFileLists)
                appUniqueFileLists = []
                for outerLoopIndex in range (0, numberOfApplications):
                    for innerLoopIndex in range (0, numberOfApplications):
                        if outerLoopIndex!=innerLoopIndex:
                            # We converted the list of files to a set above ...
                            appUniqueFileLists.append ( appFileLists [outerLoopIndex] - appFileLists [innerLoopIndex] )
               
                # So now we have a list of unique files for each appliacation, grab the first
                # on from each appliation and return that file.  If the set is empty then we have
                # the odd case where we an application does not have any unique files, so indicate an error
                for index, value in enumerate (applicationList):
                    if len (appUniqueFileLists[index]) == 0:
                        addToSummaryStatus ('    could not find insert location for app: ' + value)
                    else:
                        returnList.append (appUniqueFileLists[index].pop())
        
    if len (returnList) > 0:
        addToSummaryStatus ('   file list: ' + ', '.join (returnList))
    elif len(listOfFiles) > 0:
        addToSummaryStatus ('   no candidates found - using first file in list')
        returnList.append ( listOfFiles[0] )
    else:
        addToSummaryStatus ('   no candidates found')

    return returnList

'''
if compilerTemplate contains the word CUDA or
if it is a CFG file that contains CUDA, then this
is a CUDA template
'''
def isCudaTemplate ( compilerTemplate ):
    retVal = False
    if 'CUDA' in compilerTemplate:
        retVal = True
    elif os.path.isfile ( compilerTemplate ):
        theFile = open ( compilerTemplate, 'r')
        for line in theFile:
           if 'C_COMPILER_FAMILY_NAME' in line:
              retVal = 'CUDA' in line
              break
        theFile.close()
    return retVal
    
def initializeCudaArtifacts ( compilerTemplate ):
    '''
    
    This function will dump all of the command from the DB, and parse
    the nvcc command to extract the list of active architectures.
    
    An example compile command looks like:
    nvcc -gencode arch=compute_30,code=sm_30 -gencode arch=compute_35 ...
    
    So we want to get all of the 'arch=' arguments ...
    
    We don't want to look at every command, because there could be 
    a lot and they are probably all the same, on the other hand
    until this is in the field, I wanted and easy way to process all
    of the lines.  To process, all change maxCommandsToProcess to be 0
    
    '''
    global cudaArchitectures
    cudaArchitectures = []
    maxCommandsToProcess = 1
    commandsProcessed = 0

    # we're return a null list if this is not a CUDA compiler
    if isCudaTemplate ( compilerTemplate ):
        addToSummaryStatus ( "Determining CUDA Architectures" )
        # seed the architectures with 'Host'
        cudaArchitectures.append ( CUDA_HOST )
        # get a list of commands
        lines, exitCode = runVCcommand ('vcdb ' + vcshellDBarg(force=True) + ' dumpcommands' )

        # look for 'nvcc' in output
        commands = lines.split('\n')
        for command in commands:
            # if we find the nvcc command, build our list of architectures
            if command.find('nvcc') >= 0:
                parsed = False
                # split tokens so we can search for each 'arch=' option
                tokens = command.split(' ')
                for token in tokens:
                    if token.startswith('arch'):
                        # We have something like: arch=compute_30,code=sm_30
                        # split on the ',' arch string to get rid of 'code' part
                        tokens = token.split(',')
                        # find beginning of architecture
                        underscore = tokens[0].find('_')
                        if underscore > 0:
                            parsed = True
                            arch = tokens[0][underscore+1:]
                            # add to the list if it's not already there
                            if arch not in cudaArchitectures:
                                cudaArchitectures.append(arch)
                # if we found architecture data, increment our count
                # if our count matches our maximum, then stop parsing
                if parsed:
                    commandsProcessed += 1
                    if commandsProcessed == maxCommandsToProcess:
                       break

        cudaArchitectures.sort()

# Case     
validCoverageTypes=['none', 'statement', 'branch', 'mcdc', 'statement+branch', 'statement+mcdc', 'basis_paths', 'probe_point', 'coupling']
def automationController (projectName, vcshellLocation, listOfMainFiles, runLint, maxToSystemTest, maxToUnitTest,\
                          filterFunction, maxToBuild, compilerCFG, coverageType, \
                          inplace, vcdbFlagString, tcTimeOut, includePathOverRide, envFileEditor, statusfile, verbose,
                          filesOfInterest,envFilesUseVcdb=True):
              
    '''
    This function is passed the configuration data from the vcdb2vcm.py file and 
    create a VectorCAST project which contains a VectorCAST/Cover Environment
    and optionally VectorCAST/C++ Unit Test Environments
    
    All of the created stuff is store in vcast-workarea
    See the sub-functions called from here for details.
    
    Notes:
        inplace has been removed as an option as of AC15, leaving param for backwards compatibility
    '''

    global manageProjectName
    global coverageProjectName
    global maximumFilesToSystemTest
    global maximumFilesToUnitTest
    global maximumUnitTestsToBuild
    global summaryStatusFileHandle
    global verboseOutput
    global vcshellDBlocation
    global vcWorkArea
    global vcshellDbName
    global useParallelInstrumentation
    global useParallelJobs
    global useParallelDestionation
    global useParallelUseInPlace
    
    
    if os.path.isfile (os.path.join (vcshellLocation, vcshellDbName)):
        vcshellDBlocation = vcshellLocation
    else: 
        vcshellDBlocation = os.getcwd()        

        
    # We use buffering=1 which means line buffering, so that 
    # the file gets updated in real time.
    summaryStatusFileHandle = open (statusfile, 'w', 1)
    addToSummaryStatus (toolName)
    startMS = time.time()*1000.0   

    verboseOutput = (verbose=='True')
    
    sectionBreak ('')
    addToSummaryStatus ('Validating configuration choices ...')
    # Validate some of the input parameters
    if coverageType not in validCoverageTypes:
        print '    Invalid VCAST_COVERAGE_TYPE requested: "' + coverageType + '", using coverage type none'
        coverageType = 'none'
    if useParallelInstrumentation:
        print '    Using parallel instrumentation'
        maxToSystemTest = sys.maxint
    elif maxToSystemTest < 0:
        print '    Invalid MAXIMUM_FILES_TO_SYSTEM requested, using 0'
        maxToSystemTest = 0
    projectName = projectName.replace (' ', '_')
    
    coverageProjectName = projectName + '_coverage'
    manageProjectName   = projectName + '_project'
    
    maximumFilesToSystemTest = int (maxToSystemTest)
    maximumFilesToUnitTest = int (maxToUnitTest)
    maximumUnitTestsToBuild = int (maxToBuild)
          
    # Initialize the project settings, projectMode will be 'update' or 'new'
    projectMode = initialize (compilerCFG, filterFunction, vcdbFlagString, filesOfInterest)

    if useParallelInstrumentation:
        startCwd =  os.getcwd()
        os.chdir(originalWorkingDirectory)

        # run vcutil to parallel instrument
        print "Running vcutil from : " + os.getcwd()
        if useParallelJobs:
           para_jobs_str =  " --jobs=" + useParallelJobs
        else:
           para_jobs_str = " "

        if useParallelDestination:
           para_dest_str =  " --destination_dir=" + useParallelDestination
           vc_inst_dir = " " + useParallelDestination
           if not os.path.isdir(useParallelDestination):
              os.makedirs (useParallelDestination)
        else:
           para_dest_str = " "
           vc_inst_dir = " vc-inst"

        stdOut, exitCode = runVCcommand ('vcutil instrument --all --coverage=' + coverageType + " --db="+ vcshellDbName + para_jobs_str + para_dest_str, globalAbortOnError)

        print ("Copying CCAST_.CFG file")
        shutil.copy("CCAST_.CFG",os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory , "CCAST_.CFG"))
        os.chdir(os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory))

        # run command to build the manage project
        if os.path.isdir(coverageProjectName):
           print "Removing existing working directory"
           shutil.rmtree(coverageProjectName)
        #stdOut, exitCode = runVCcommand ('clicast cover environment build ' +  coverageProjectName + vc_inst_dir, globalAbortOnError)
        stdOut, exitCode = runVCcommand ('clicast cover environment build ' +  coverageProjectName + " " + os.path.join (originalWorkingDirectory.strip(), vc_inst_dir.strip()), globalAbortOnError)
        os.chdir(os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory))

        if useParallelUseInPlace:
            stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover environment enable_instrumentation', globalAbortOnError)

        if len(listOfMainFiles)==1 and listOfMainFiles[0]==parameterNotSetString:
            localListOfMainFiles = buildListOfMainFilesFromDB()
        else:
            localListOfMainFiles = listOfMainFiles
        for file in listOfMainFiles:
            stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover append_cover_io true -u' + file, globalAbortOnError)

        os.chdir(startCwd)

    #not parallel    
    else:
        if maximumFilesToSystemTest > 0:
            if isCuda():
                buildCudaCoverageProjects (projectMode,
                                           vcCoverDirectory)
            else:
                # We always build an empty coverage project even if the number of 
                # files to system test is 0, because this allows us to add files to it later.
                buildCoverageProject (projectMode=projectMode,
                                      projectName=coverageProjectName,
                                      inplace=inplace,
                                      workingDirectory=vcCoverDirectory)
        
        if maximumFilesToSystemTest>0 and globalCoverageProjectExists:
            
            if len(listOfMainFiles)==1 and listOfMainFiles[0]==parameterNotSetString:
                localListOfMainFiles = buildListOfMainFilesFromDB(vcshellDBarg(force=True))
            else:
                localListOfMainFiles = listOfMainFiles

            if isCuda():
                instrumentCudaCoverageProjects ( coverageType,
                                                 runLint,
                                                 localListOfMainFiles, 
                                                 os.path.join ( originalWorkingDirectory,
                                                                vcWorkArea ) )
            else:
                instrumentCoverageProject ( coverageType,
                                            runLint,
                                            localListOfMainFiles, 
                                            os.path.join ( originalWorkingDirectory,
                                                           vcWorkArea,
                                                           vcCoverDirectory,
                                                           coverageProjectName ) )
        
    # Use the IDC EnvCreate to build .env scripts for each file.
    if maximumFilesToUnitTest > 0:
        buildEnvScripts (coverageType, includePathOverRide, envFileEditor, vcdbFlagString, envFilesUseVcdb)  
        
    # Build the manage project
    os.chdir (os.path.join (originalWorkingDirectory, vcWorkArea, vcManageDirectory ))

    if ( isCuda() ) and ( projectMode == 'new' ):
        buildCudaEnterpriseProject (coverageType,
                                    tcTimeOut,
                                    os.path.join (originalWorkingDirectory, vcWorkArea ) )
        buildCudaAggregateFiles(os.path.join (originalWorkingDirectory,
                                              vcWorkArea,
                                              vcCoverDirectory))
    else:
        buildEnterpriseProject (projectMode, coverageType, tcTimeOut)
    
    # Add the list of files to the cummulative list of files ...
    newFileList = os.path.join (originalWorkingDirectory, vcWorkArea, listOfFilenamesFile);
    fullFileList = os.path.join (originalWorkingDirectory, vcWorkArea, listOfFilesInProject);
    newFile = open (newFileList, 'r')
    oldFile = open (fullFileList, 'a')
    for line in newFile:
        oldFile.write (line)
        
    newFile.close()
    oldFile.close()

    endMS = time.time()*1000.0
    addToSummaryStatus ('Total Time: ' + getTimeString(endMS-startMS))

    addToSummaryStatus (toolName + ' Complete')
    summaryStatusFileHandle.close()

    # Display the status to stdout
    os.chdir (originalWorkingDirectory)
    statusMessages=''
    with open(statusfile, 'r') as summaryStatusFileHandle:
        statusMessages=summaryStatusFileHandle.read()
    sectionBreak (statusMessages)
   
    # TBD: Copy the vcast_lint.xml from the cover project to the manage project (FB 51133)
    if runLint:
        fromFile = os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory, coverageProjectName, 'vcast_lint.xml')
        toPath = os.path.join (originalWorkingDirectory, vcWorkArea, vcManageDirectory, manageProjectName)
        if os.path.isfile (fromFile):
            shutil.copy (fromFile, toPath)

    
def toolBarDashIcon (workareaBaseDirectory, vcProjectFile):
    '''
    This function will be called to start the vcdash for a manage project.
    The vcProjectFile argument will point to one of the following:
        a VC/C++, or VC/Cover project 
            we create a mananage project, and add that environment to it
        a VectorCAST Project
            we start the dash for that project
        a vcshell.db file
            we start the dash for the db file
    '''
    
    global originalWorkingDirectory
    global cfgFileLocation 
    
    print 'VectorCAST/Analytics startup utility' 
    projectType='None'
       
    # If the caller supplied a directory for us to look at for project files.
    if vcProjectFile.endswith ('.db'):
        projectName = 'VCShell Database'
        projectType = 'vcdb'
        vcdashArgs = '--vcdb=' + vcProjectFile
    elif vcProjectFile.endswith ('.vcm'):
        projectName = vcProjectFile.split(os.path.sep)[-1]
        projectType = 'manage'
        vcdashArgs = '--project=' + vcProjectFile
    elif vcProjectFile.endswith ('.vce') or vcProjectFile.endswith ('.vcp'):
        # When a VC/C++ or VC/Cover environment is open, the working directory
        # is the environment directory, so for our purposes we need to cd ..
        parentDirectoryPath = os.path.dirname (vcProjectFile)
        # In the case where we have an open Unit Test or Cover Project the CWD will 
        # be inside the project directory, so we need to set the Original working directory
        # to be up one level.
        cfgFileLocation = parentDirectoryPath
        # We need to override the orginalWorkingDirectory with the location
        # where we are asked to build the vcast-workarea.  In the normal case
        # we build the vcast-workarea in the startup directory
        os.chdir (workareaBaseDirectory)
        originalWorkingDirectory = os.getcwd()
        projectName = 'VectorCAST'
        projectType='vce'
        # Create or add-on to the vcast-workarea project
        vcmFromEnvironments (projectName, parentDirectoryPath, projectName+'-automation-status.txt', False)
        vcdashArgs = ''
        vcdashArgs =  '--history-dir=' + os.path.join(workareaBaseDirectory, vcWorkArea, vcHistoryDirectory + ' ')
        vcdashArgs += '--project=' + os.path.join(workareaBaseDirectory, vcWorkArea, vcManageDirectory, projectName+'_project ')
        # The vcmFromEnvironments will print a bunch of status, so we put a section break in the output
        sectionBreak('')
     
    if projectType=='None':
        print 'No VectorCAST Environments or Projects found'
    else:
        vcdashArgs = '--single-license-fallback ' + vcdashArgs
        print 'vcdash args: ' + vcdashArgs

    # The startup of vcdash and the web broswer happens back in the GUI.  

def updateSystemTestPy (systemTestFileName, vcshellLocation):
    global verboseOutput

    verboseOutput = True
    stdOut, exitCode = runVCcommand ('clicast -lc option vcast_vcdb_flag_string ')
    setupApplicationBuildGlobals('--db ' + vcshellLocation)

    if len (topLevelMakeCommand) > 0:
        oldFile = open (systemTestFileName, 'r')
        newFile = tempfile.NamedTemporaryFile (delete=False)

        for line in oldFile:
            newFile.write(convertSystemTestLine (line))
        oldFile.close()
        newFile.close()
        shutil.move(newFile.name, systemTestFileName)

def appendCoverIOFilterFn(originalList):
    return originalList[:]

def appendCoverIO (vcshellFile, coverageProjectName):
    global summaryStatusFileHandle
    global verboseOutput

    verboseOutput = True
    summaryStatusFileHandle = open ('append_cover_io.log', 'w', 1)
    vcshellArg = '--db=' + vcshellFile;
    setupGlobalFileListsFromDatabase(appendCoverIOFilterFn, [parameterNotSetString], vcshellArg)
    localListOfMainFiles = buildListOfMainFilesFromDB(vcshellArg)
    for file in localListOfMainFiles:
        stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover append_cover_io true -u' + file)

    
def enterpriseEnvironmentBuild (workareaBaseDirectory, projectName, scriptFile):
    '''
    This function will build a manage project in the local directory
    using the passed in projectName as the name of the manage project,
    the local CCAST_ (or ADACAST).CFG file for the compiler settings
    and the passed in scriptFile as the .env file to add to the manage project
    
    We are not trying to handle the add an environment to an existing manage
    project case, like we do with the rest of the Automation Controller stuff.
    The assumption here is that we are always doing a build new action.
    '''
    
    global cfgFileLocation 
    global summaryStatusFileHandle
    global manageProjectName
    global maximumUnitTestsToBuild
    global maximumFilesToUnitTest
    global vcWorkArea
    global vcEnterpriseMode

    vcEnterpriseMode = True
    vcWorkArea = workareaBaseDirectory
    maximumFilesToUnitTest = 0
    
    print 'VectorCAST Enterprise Utility' 
       
    # we are building an enterprise VC/C++ or VC/Ada
    if scriptFile=='':
        print 'Script file must be provided using the --script argument'
    
    elif not os.path.isfile(scriptFile):
        print 'The script file: "' + scriptFile + '" does not exist'
        
    elif projectName=='':
        print 'Project name must be provided using the --project argument'
               
    elif os.path.exists (projectName + '.vcm'):
        print 'Invalid project name: "' + projectName + '", ' + projectName + '.vcm already exists'
        
    elif os.path.exists (projectName):
        print 'Invalid project name: "' + projectName + '", a directory with this name already exists'

    
    elif scriptFile.endswith ('.env') or scriptFile.endswith ('.vcp'):
   
        # Change directory to the place where we will build the manage project
        os.chdir (workareaBaseDirectory)
        
        statusFile = 'vcast-enterprise-utility.txt'
        summaryStatusFileHandle = open (statusFile, 'w', 1)

        # Setup the common global variables
        cfgFileLocation = os.getcwd()
        manageProjectName = projectName
        # we are not building a coverage project
        coverageProjectName = ''
       
        # Build the structure of the manage project, which contains the 
        # Compiler nodes, system and unit test suites etc.
        buildEnterpriseProject (projectMode='new', coverageType='none', tcTimeOut=0)
        
        if scriptFile.endswith ('.env'):
            # Add the environment ...
            with make_tempDirectory () as tempDirectory:

                fileStructure = scriptFiles (tempDirectory, os.path.join (os.getcwd(), scriptFile))
                fileStructure.generate_files()

                # This global variable is used to compute the build commands below
                maximumUnitTestsToBuild = 1       
                
                # This function takes a list, so we create a one item list in the call
                addToSummaryStatus ('   adding environment to project')
                addCommands, buildCommands = commandsToAddAndBuildEnvironments ([fileStructure])
                stdOut = runManageCommands(manageProjectName, addCommands)
                addToSummaryStatus ('   building environment')
                stdOut = runManageCommands(manageProjectName, buildCommands)
                
        # scriptFile.endswith ('.vcp')
        else:
            addToSummaryStatus ('   adding environment to project')
            manageCommands = []
            manageCommands.append ('--import ' + scriptFile)
            scriptFile = os.path.basename (scriptFile)
            manageCommands.append ('--group {0} --add {1}'.format(
                getDefaultSystemTestingGroupName(),
                scriptFile.split('.')[0]))
            stdOut = runManageCommands(manageProjectName, manageCommands)
   
                
        summaryStatusFileHandle.close()
                       
    else:        
        print 'Script file: "' + scriptFile + '" is invalid'
        print 'Only environment scripts (.env files), and coverage project files (.vcp) are supported'

