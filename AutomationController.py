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
vcManageDirectory='vc_project'
vcCoverDirectory='vc_coverage'
vcScriptsDirectory='vc_ut_scripts'
vcHistoryDirectory='vc_history'

# These global are set for each run of the utiltity
# compilerNodeName is the location where we will insert new environments
defaultCompilerNodeName = 'UnitTestingCompilerNode'
compilerNodeName = defaultCompilerNodeName
# currentLanguage controls the name of the test suites and groups
currentLanguage = 'none'

# Unit Test Configuration Files
ADA_CONFIG_FILE = 'ADACAST_.CFG'
C_CONFIG_FILE = 'CCAST_.CFG'

# Controls the output of the stdout from all VectorCAST commands
verboseOutput = False

# Controls the failing/continuing of the scripts after a VectorCAST command failes
globalAbortOnError = True

# Controls the updating of system_test.py
globalUpdateSystemTestPy = True

# These variables are constructed from the --projectname arg
coverageProjectName=""
manageProjectName=""

# This is the startup directory where the script is being run
originalWorkingDirectory=os.getcwd()
cfgFileLocation=os.getcwd()

# This is the location of the vcshell.db file, passed in by the caller
# It might be the same as the originalWorkingDirectory
vcshellDBlocation=''
vcshellDBname='vcshell.db'


# This is the make command info from the database
topLevelMakeCommand = ''
topLevelMakeLocation = ''
applicationList = []


clicastVersion = ''
vcInstallDir = os.environ["VECTORCAST_DIR"]
locationOfInstrumentScript=os.path.join (vcInstallDir,'python','vector','apps','vcshell')
pathToUnInstrumentScript=os.path.join (vcInstallDir,'python','vector','apps','EnvCreator','UnInstrument.py')
pathToEnvCreateScript=os.path.join (vcInstallDir,'python','vector','apps','vcshell','EnvCreate.py')

# List of all files in the DB
listOfAllFiles = []
listOfFiles = []
listOfPaths = []

# Contains the status message to display at the end of the run
summaryStatusFileHandle = 0



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
    
    
    
def runVCcommand(command, abortOnError=globalAbortOnError):
    '''
    Run Command with subprocess.Popen and return status
    If the fatal flag is true, we abort the process, if 
    not, we print the stdout and continue ...
    '''
    
    global verboseOutput

    cmdOutput = ''
    commandToRun = os.path.join (vcInstallDir, command)
    
    print '   running command: ' + commandToRun
    vcProc = subprocess.Popen(commandToRun, stdout=subprocess.PIPE,\
                                stderr=subprocess.PIPE,universal_newlines=True,shell=True)
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
            print "AC: Raising Exception"
            raise Exception ('VectorCAST command failed')

    return cmdOutput, exitCode
    

def readCFGoption (optionName):
    '''
    This function will look for optionName in the local directory
    CCAST_.CFG file and return the value.  If the option is not
    found or there is not a CCAST_.CFG file we return ""
    '''
    optionValue, exitCode = runVCcommand ('vcutil -lc get_option ' + optionName)
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
        fileList.close ()
    else:
        # if there is no existing file list, just call un-instrument
        fullCommand =  'vpython '
        fullCommand += pathToUnInstrumentScript
        stdOut, exitCode = runVCcommand (fullCommand)
    
    
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
    stdOut, exitCode = runVCcommand ('clicast -lc option vcast_vcdb_flag_string ' + vcdbFlagString)
    
    
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

    addToSummaryStatus ('   checking for work area ...')
    workAreaPath = os.path.join (os.getcwd(), vcWorkArea)
    
    # Pre September 2017 we use vc_manage to store the manage project
    # Now we use vc_project ... to handle this, we check for this case
    # and delelete the old vcast-workarea if necessary
    addToSummaryStatus ('Checking for old work-area ...')
    oldPath = os.path.join (workAreaPath, 'vc_manage')
    if os.path.isdir (oldPath):
       addToSummaryStatus ('   removing old work-area instance')
       shutil.rmtree (workAreaPath)
 
    # If we already have a workarea
    if os.path.isdir (workAreaPath):
       addToSummaryStatus ('   found existing work area')
       os.chdir (vcWorkArea)
       projectMode = 'update'
    else: # create the workarea
        projectMode = 'new'
        addToSummaryStatus ('   creating new work area ...')
        addToSummaryStatus ('   location: ' + os.getcwd())
        os.mkdir (vcWorkArea)
        os.chdir (vcWorkArea)
        os.mkdir (vcCoverDirectory)
        os.mkdir (vcManageDirectory)
        os.mkdir (vcScriptsDirectory)
        os.mkdir (vcHistoryDirectory)
        
    return projectMode
    

def vcshellDBarg (force=False):
    '''
    This function will return the "--db path" arg to be passed
    to the vcdb command when the location of the vcshell.db is NOT
    the same as the current working directory
    '''
    global vcshellDBlocation
    global vcshellDBname
    global originalWorkingDirectory

    if force or vcshellDBlocation!=originalWorkingDirectory:
        return '--db=' + os.path.join (vcshellDBlocation, vcshellDBname)
    else:
        return "--db=" + vcshellDBname
    
def normalizePath (path):
    '''
    This function will a path to be all lower case if we are on windows
    '''
    if os.name == 'nt':
        return path.lower()
    else:
        return path
        
    
def initialize (compilerCFG, filterFunction, vcdbFlagString, filesOfInterest):

    global listOfFiles
    global listOfAllFiles
    global listOfPaths
    global vcshellDBlocation
    global topLevelMakeCommand
    global topLevelMakeLocation
    global applicationList   
    global vcshellDBname
    
    
    projectMode = ''
    fullFileList = []
    fullPathList = []
    sectionBreak ('')
    
    addToSummaryStatus ('Validating vcshell.db ... (' + vcshellDBname + ")")
    startMS = time.time()*1000.0
 
    # Generate the compiler configuration file
    initializeCFGfile (compilerCFG, vcdbFlagString)
    
    if os.path.isfile (os.path.join (vcshellDBlocation, vcshellDBname)):
        # Create a global list of all of the files in the DB
        stdOut, exitCode = runVCcommand ('vcdb ' + vcshellDBarg() + ' getfiles', True)
        # strip the trailing CR and then split
        listOfAllFiles = stdOut.rstrip('\n').split('\n')
        if len (listOfAllFiles) == 0:
            fatalError ('No files found in vcshell.db (' + vcshellDBname + ')')
        else:
            addToSummaryStatus ('   found ' + str(len (listOfAllFiles)) + ' total source files')
            
        # Now Call the user supplied filter function to filter the fullFileList
        addToSummaryStatus ('   applying the user-defined filter to the file list ... ')
        # filterFunction is the user supplied callback function
        originalFileListLength = len (listOfAllFiles)
        listOfAllFiles = filterFunction(listOfAllFiles)
        if len (listOfAllFiles) < originalFileListLength:
            addToSummaryStatus ('   user filter reduced file count to: ' + str (len (listOfAllFiles)))
            
        # Move the user specified files of interest to the begining in listOfAllFiles
        if filesOfInterest != [parameterNotSetString]:
            if os.name == "nt":
                filesOfInterest = [file.lower() for file in filesOfInterest]
            sortedListOfAllFiles = list(listOfAllFiles)
            filesNotInDb = list(filesOfInterest)
            index = 0
            for file in listOfAllFiles:
                fullPath = ''
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
            listOfAllFiles = list(sortedListOfAllFiles)
        # filter based on: already in project and max size
        listOfFiles = filterTheFileList (listOfAllFiles)
        addToSummaryStatus ('   ' + str(len (listOfFiles)) + ' files will be added for system testing ... ')

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
            
        # Read the top level make command and directory from the database
        cmdOutput, exitCode = runVCcommand ('vcdb ' + vcshellDBarg() + ' gettopdir')
        if exitCode==0:
            topLevelMakeLocation=cmdOutput.strip('\n')
        else:
            topLevelMakeLocation=''
            
        cmdOutput, exitCode = runVCcommand ('vcdb ' + vcshellDBarg() + ' gettopcmd')
        if exitCode==0:
            topLevelMakeCommand = cmdOutput.strip('\n')
        else:
            topLevelMakeCommand=''
        stdOut, exitCode = runVCcommand (command='vcdb ' + vcshellDBarg() + ' getapps')
        if 'Apps Not found' in stdOut:
            applicationList = []
        else:
            applicationList = stdOut.split ('\n')
         
    else:
        # This call will exit the program
        fatalError ('Cannot find file: vcshell.db (' + vcshellDBname + ' in directory: ' + vcshellDBlocation + ', please build project with vcshell before running this script\n')  
        

    # Build the workarea directory structure
    projectMode = buildWorkarea()
        
    # Write the new list of files into the vcWorkArea
    writeFileListToFile (listOfFiles)
    
    endMS = time.time()*1000.0
    addToSummaryStatus ('   complete (' + getTimeString (endMS-startMS) + ')')
    
    return projectMode


           
def buildCoverageProject (projectMode, inplace):
    '''
    This function will build a coverage project, and add all of the files from the vcdb
    We do not instrument in this function, we do that after the lint analysis runs
    '''
    
    global listOfFiles
    global listOfFilenamesFile
    global globalCoverageProjectExists
    global vcshellDBlocation
    global vcshellDBname
    global globalAbortOnError

    sectionBreak('')
    addToSummaryStatus ('Building Coverage Environment ...')
    startMS = time.time()*1000.0

    os.chdir (os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory )) 
    
    try:
        if projectMode=='new':
            # Get the compiler configuration file ...
            getCFGfile ()
                          
            addToSummaryStatus ('   creating the coverage project ...')
            stdOut, exitCode = runVCcommand ('clicast cover env create ' + coverageProjectName, True);
            
            # Create the instrumentation directory if we are not instrumenting in place.
            if not inplace:
                vcInstDir = 'vcast-inst'
                if not os.path.isdir (vcInstDir):
                    os.mkdir (vcInstDir)
                stdOut, exitCode = runVCcommand ('clicast -e ' + coverageProjectName + ' cover options set_instrumentation_directory ' + vcInstDir, True);
                stdOut, exitCode = runVCcommand ('clicast -e ' + coverageProjectName + ' cover options in_place n', True);
               
        if len (listOfFiles) > 0:
            filecountString = str (len (listOfFiles) )
            addToSummaryStatus ('   adding ' + filecountString +' source files  ...')
            # This clicover command will look like:
            # cliccover add_source_vcdb vcshell.db vcast-latest-filelist.txt
            stdOut, exitCode = runVCcommand ('clicover add_source_vcdb ' + coverageProjectName + ' ' + \
                 os.path.join (vcshellDBlocation, vcshellDBname) + ' ' + \
                 os.path.join (originalWorkingDirectory, vcWorkArea, listOfFilenamesFile), True);       
                 
        globalCoverageProjectExists=True
        endMS = time.time()*1000.0
        addToSummaryStatus ('   complete (' + getTimeString(endMS-startMS) + ')')
        
    except Exception, err:
        # If we get a flex error, we continue
        if globalAbortOnError:
            print "AC: raising error: " + str(e)
            raise e
        elif str(err)=='FLEXlm error' or str(err)=='VectorCAST command failed':
            addToSummaryStatus ('   error creating cover project, continuing ...')
            globalCoverageProjectExists = False
        else:
            print "AC: raising error: " + str(e)
            raise
            
    
def runLintAnalysis ():
    '''
    This will do the Lint analysis
    We need to run the following command on the VC/Cover project
    $VECTORCAST_DIR/clicast -e <env> cover tools lint_analyze
    '''
       
    sectionBreak('')
    addToSummaryStatus ('Starting Lint Analysis ...')
    startMS = time.time()*1000.0
    
    try:      
        os.chdir (os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory ))
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
    
   
    
def instrumentFiles (coverageType, listOfMainFiles):
    '''
    This function will instrument all of the files in the cover project
    We do this in two parts, for the new files that just got added during
    this round, we need to do an explicit instrument call.  And then we
    need to do a incremental re-instrument to bring the whole project up to date
    '''
    
    global listOfFiles
    
    sectionBreak('')
    addToSummaryStatus ('Starting Instrumentation ...')
    startMS = time.time()*1000.0
    
    try:
        
        locationOfCoverageProject = os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory )
        os.chdir (locationOfCoverageProject)
        
        # The instrumented files need functions that are defined in the
        # VectorCAST coverage library file: c_cover_io.c.  The easiest way
        # to get this code into an application is to #include the file 
        # c_cover_io.c into each of the main files of an application.
        # We now use a clicast command to do this.  
        # Previously we used a py function: appendCoverIOfileToMainFiles
        for file in listOfMainFiles:
            stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover append_cover_io true -u' + file)
        
               
        # Call the instrumentor for any new files
        listOfFilesString = ''
        for file in listOfFiles:
            fileNameOnly = os.path.basename(file)
            listOfFilesString += fileNameOnly + ' '
        
        # We don't want to overwhelm the command line if we have 10k files for example
        if len (listOfFilesString) > 1000:
           stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover instrument ' + coverageType)
        else:
            # Run instrumentation on the new files ...
            stdOut, exitCode = runVCcommand ('clicover instrument_' + coverageType.replace ('+', '_') + ' ' + coverageProjectName + ' ' + listOfFilesString)
            # Run incremental re-instrument to pick up any source changes
            stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover source incremental_reinstrument')
            
            
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
                    stdOut, exitCode = runVCcommand (fullCommand)

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
                if not os.path.isfile ('ENV_' + filePart + '.env'):
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
                commandArgs =  ' ' + vcshellDBarg(force=True) + ' ' + envCoverArgString(coverageType) 
                commandArgs += pathArgs (includeList, excludeList)
                commandArgs += ' --filelist=' + os.path.join (originalWorkingDirectory, vcWorkArea, tempFileName)
                commandArgs += vcdbArgsOption(vcdbFlagString)
                # This will constuct the .env files with the path to the vcshell, rather than the search paths and unit options
                if envFilesUseVcdb:
                    commandArgs += ' --add_db_name'
                    
                fullCommand =  'vpython '
                fullCommand += pathToEnvCreateScript + commandArgs
                stdOut, exitCode = runVCcommand (fullCommand)
                
                # delete the temp-file
                os.remove (tempFileName)
                
                # Now for each environment script, call the user-supplied editor function
                addToSummaryStatus ('   calling the user-supplied environment script editor ...')
                for filePath in listOfAllFiles:
                    fileName = os.path.basename(filePath)
                    envFileName = 'ENV_' + fileName.split('.')[0].upper() + '.env'
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
    stdOut, exitCode = runVCcommand('manage -p %s --script %s' % (project, manageScriptName))  
    os.remove (manageScriptName) 
    
    return stdOut 


def platformLevelString ():
    '''
    This will return the string that should be used for the Platform level
       Source/Windows, Source/Linux, or Source/Solaris
    '''
    global clicastVersion
    if not clicastVersion:
        clicastVersion, exitCode = runVCcommand('clicast --version')
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
        
        
        
def unitTestGroupName ():
    '''
    the nextUTgroupName will contain the unique group
    name based on the contents of the existing project
    ''' 
    if currentLanguage=='ada':
        return 'UT-Group-Ada-' + compilerNodeName
    else:
        return 'UT-Group-'+ compilerNodeName


        
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
   


def commandsToBuildProjectTree (coverageProjectName, coverageType, tcTimeOut):
    '''
    This function will create the basic structure of the manage project
    '''

    manageCommands = []
    if platformLevelString():
        manageCommands.append(platformLevelString() + ' --create')

    systeTestCompilerNodeName = 'SystemTestingCompilerNode'
    lanaguage='none'
    manageCommands.append(platformLevelString() + ' --config="VCDB_FILENAME=%s"' % (os.path.join (vcshellDBlocation, 'vcshell.db')))
    manageCommands.append(platformLevelString() + ' --coverage-type="%s"' % (coverageType))
    manageCommands.append(platformLevelStringWithSlash()+ systeTestCompilerNodeName + ' --create')
    
    manageCommands.append(platformLevelStringWithSlash() + systeTestCompilerNodeName + '/SystemTesting --create')
    manageCommands.append('--group ST-Group --create')
    manageCommands.append(platformLevelStringWithSlash() + systeTestCompilerNodeName + '/SystemTesting --add ST-Group')
    if globalCoverageProjectExists and len (coverageProjectName) > 0:
        addToSummaryStatus ('   adding the coverage project for system testing')
        manageCommands.append('--import ' + os.path.join ('..', vcCoverDirectory, coverageProjectName + '.vcp'))
        manageCommands.append('--group ST-Group --add ' + coverageProjectName)
    
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
    for enviroCount, fileClass in enumerate(fileClassList):
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
 
         
            
locationWhereWeRunMakeString = '        self.locationWhereWeRunMake'
topLevelMakeCommandString    = '        self.topLevelMakeCommand'
whereWeRunTestsString        = '        self.locationWhereWeRunTests'
nameOfExecutableString       = '        self.nameOfTestExecutable'
def convertSystemTestLine (originalLine):
    '''
    This function replaces specific lines in the system_tests.py file based on the 
    values that we retrieved from the vcshell.db during initialization
    '''

    global globalUpdateSystemTestPy
    
    if globalUpdateSystemTestPy is False:
        return originalLine
        
    if locationWhereWeRunMakeString in originalLine:
        return commonCommentLine + convertOneLine (originalLine, locationWhereWeRunMakeString, 'r"' + topLevelMakeLocation + '"')
    
    elif topLevelMakeCommandString in originalLine:
        return commonCommentLine + convertOneLine (originalLine, topLevelMakeCommandString, 'r"' + topLevelMakeCommand + '"')
        
    # TBD: We could have multiple applications in the vcdb, for now I am just choosing the first one
    elif len(applicationList) > 0 and  whereWeRunTestsString in originalLine:
        # location is the first part of the path ...
        location = os.path.dirname(applicationList[0])
        return commentForExecutable() + convertOneLine (originalLine, whereWeRunTestsString, 'r"' + location + '"')
   
    # TBD: We could have multiple applications in the vcdb, for now I am just choosing the first one
    elif len(applicationList) > 0 and nameOfExecutableString in originalLine:
        exe = applicationList[0]
        return commentForExecutable() + convertOneLine (originalLine, nameOfExecutableString, 'r"' + exe + '"')
        
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
        commands = commandsToBuildProjectTree(coverageProjectName, coverageType, tcTimeOut)
        stdOut = runManageCommands(manageProjectName, commands)
        
        # Auto-configure the system_test.py file
        autoConfigureSystemTest ()
        

    # Determine the name of the compiler node, and if we need to build a new one ... 
    nodeCommands =  buildCompilerNode ()
    stdOut = runManageCommands(manageProjectName, nodeCommands)
        
    # Now spin though all of the Env files and add those nodes to the manage project
    if maximumUnitTestsToBuild>0:
        addEnvFilesToManageProject ()
    
    endMS = time.time()*1000.0
    addToSummaryStatus ('   complete (' + getTimeString(endMS-startMS) + ')')


    
    
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
    global vcshellDBname
    manageProjectName = findManageProject() 
    if manageProjectName!=manageProjectNotFound:
        projectArgument = '--project=' + manageProjectName
    elif os.path.isfile (os.path.join (vcshellLocation, vcshellDBname)):
        os.chdir (vcshellLocation)
        projectArgument = '--vcdb=' + vcshellDBname
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
        stdOut, exitCode = runVCcommand ('manage -p' + manageProjectName + ' -e ' + coverProjectName + ' --enable-instrument-in-place')

        # We have to do a reinstrument action to pick up the changes, because the enable simply
        # copies the new foo.c file onto the foo.c.vcast.bak, and relies on the incremental_reinstrument to
        # compare the files and decide what needs to be re-instrumented.
        coverProjectName = findCoverProject()
        stdOut, exitCode = runVCcommand ('clicast -e ' + coverProjectName + ' cover source incremental_reinstrument')
        # Change back to original dir
        os.chdir (originalWorkingDirectory)
    

def disableCoverage():
    '''
    Disable coverage for the Coverage Project
    '''
    manageProjectName = findManageProject()
    if manageProjectName!=manageProjectNotFound:
        coverProjectName = manageProjectName.split ('_')[0] + '_coverage'
        stdOut, exitCode = runVCcommand ('manage -p' + manageProjectName + ' -e' + coverProjectName + ' --disable-instrument-in-place')
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
            manageCommands.append ('--group ST-Group --add ' + os.path.splitext (os.path.basename (enviro))[0])
                    
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
    global verboseOutput
    global manageProjectName
    global coverageProjectName
    
    verboseOutput = (verbose=='True')
    manageProjectName   = projectName + '_project'
    
    # TBD kind of a kludge, but it might be ok
    coverageProjectName=''
    maximumUnitTestsToBuild = 0
   
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
    
    
def buildListOfMainFilesFromDB():
    '''
    This function will retrieve the list of files whre we should insert c_cover_io ...

    '''
    sectionBreak('')
    addToSummaryStatus ('Computing insert locations for c_cover_io.c ...')
    returnList = []
        
    stdOut, exitCode = runVCcommand (command='vcdb ' + vcshellDBarg(force=True) + ' getapps') 
    if 'Apps Not found' in stdOut:
        applicationList = []
    else:
        applicationList = stdOut.rstrip('\n').split('\n')
    
    
    if len (applicationList)>0:
        
        # Build a list of sets.  One file set for each application
        appFileLists = []
        for app in applicationList: 
            stdOut, exitCode = runVCcommand ('vcdb ' + vcshellDBarg(force=True) + ' --app=' + app + ' getappfiles') 
            listOfAppFiles = stdOut.rstrip('\n').split('\n')
            
            # but only consider files that are in the cover project
            setOfAppFiles = set (listOfAppFiles) & set (listOfFiles)
                       
            fileSet = set()
            for file in setOfAppFiles:
                fileName = os.path.basename (file)
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
    else:
        addToSummaryStatus ('   no candidates found')

    return returnList
    


# Case     
validCoverageTypes=['none', 'statement', 'branch', 'mcdc', 'statement+branch', 'statement+mcdc', 'basis_paths', 'probe_point', 'coupling']
def automationController (projectName, vcshellLocation, listOfMainFiles, runLint, maxToSystemTest, maxToUnitTest,\
                          filterFunction, maxToBuild, compilerCFG, coverageType, \
                          inplace, vcdbFlagString, tcTimeOut, includePathOverRide, envFileEditor, statusfile, verbose,
                          filesOfInterest,vcast_workarea="vcast-workarea",vcDbName="vcshell.db",envFilesUseVcdb=True):
              
    '''
    This function is passed the configuration data from the vcdb2vcm.py file and 
    create a VectorCAST project which contains a VectorCAST/Cover Environment
    and optionally VectorCAST/C++ Unit Test Environments
    
    All of the created stuff is store in vcast-workarea
    See the sub-functions called from here for details.
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
    global vcshellDBname
    
    print "Automation Controller (AutomataionController.py) : 6/29/2018"

    vcWorkArea = vcast_workarea
    
    useParallelInstrumentation = False
    vcshellDBname = vcDbName     
    
    if os.path.isfile (os.path.join (vcshellLocation, vcshellDBname)):
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
    if maxToSystemTest == -1:
        print '    Using parallel instrumentation'
        maxToSystemTest = sys.maxint
        useParallelInstrumentation = True
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
        stdOut, exitCode = runVCcommand ('vcutil instrument --coverage=' + coverageType)

        print ("Copying CCAST_.CFG file")
        shutil.copy("CCAST_.CFG",os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory , "CCAST_.CFG"))

        # run command to build the manage project
        stdOut, exitCode = runVCcommand ('clicast cover environment build ' +  os.path.join (vcWorkArea, vcCoverDirectory , coverageProjectName) + ' vc-inst')

        os.chdir(os.path.join (originalWorkingDirectory, vcWorkArea, vcCoverDirectory))
        if len(listOfMainFiles)==1 and listOfMainFiles[0]==parameterNotSetString:
            localListOfMainFiles = buildListOfMainFilesFromDB()
        else:
            localListOfMainFiles = listOfMainFiles
        for file in listOfMainFiles:
            stdOut, exitCode = runVCcommand ('clicast -e' + coverageProjectName + ' cover append_cover_io true -u' + file)

        os.chdir(startCwd)

        
    else:
        # We always build an empty coverage project even if the number of 
        # files to system test is 0, because this allows us to add files to it later.
        buildCoverageProject (projectMode, inplace)
    
        # If the caller requested lint analysis
        if maximumFilesToSystemTest>0 and globalCoverageProjectExists:
            if maximumFilesToSystemTest>0 and runLint:
                runLintAnalysis ()
            
            if len(listOfMainFiles)==1 and listOfMainFiles[0]==parameterNotSetString:
                localListOfMainFiles = buildListOfMainFilesFromDB()
            else:
                localListOfMainFiles = listOfMainFiles
            
            if coverageType != 'none':
                instrumentFiles (coverageType, localListOfMainFiles)
        
    # Use the IDC EnvCreate to build .env scripts for each file.
    if maximumFilesToUnitTest > 0:
        buildEnvScripts (coverageType, includePathOverRide, envFileEditor, vcdbFlagString, envFilesUseVcdb)  
        
    # Build the manage project
    os.chdir (os.path.join (originalWorkingDirectory, vcWorkArea, vcManageDirectory ))
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
            manageCommands.append ('--group ST-Group --add ' + scriptFile.split('.')[0])
            stdOut = runManageCommands(manageProjectName, manageCommands)
   
                
        summaryStatusFileHandle.close()
                       
    else:        
        print 'Script file: "' + scriptFile + '" is invalid'
        print 'Only environment scripts (.env files), and coverage project files (.vcp) are supported'
        
        
     


        



