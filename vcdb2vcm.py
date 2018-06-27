

'''
This is a simple configuration files that will allow you to build a complete set
of VectorCAST projects automatically from the build settings gathered by vcShell
The following workflow should be used:
 
    - Copy this file and the other files located in: VECTORCAST_DIR/examples/AutomationController
    -     into the build directory root, or some other work directory
    - edit the constants at the top of this script to match your application
    - run the startAutomation.py file using the command: $VECTORCAST_DIR/vpython startAutomation.py
    -     (for windows, double click on the runShell.bat file to open a shell first)
'''


import traceback
import os
import subprocess
import sys

from vector.apps.EnvCreator import AutomationController

# exit on error
AutomationController.abortOnError = True

#######################################################################################
#######################################################################################
# If you are building the VC project from existing VC/C++ environments, 
# you only need to setup the configuration variables in this first section.  
# If you are building from a VCShell database, then please review all 
# configuration variables.

### Project name is any ASCII string that is used by
### VectorCAST as the prefix the various projects
### Change this to something meaningful for your project
PROJECT_NAME=os.environ['emul']
VCAST_WORKAREA='vcast-workarea-' + PROJECT_NAME
VCDB_FILENAME=PROJECT_NAME+'.db'

### VectorCAST Compiler Tag
### Must be consistent with the compiler that was used to build the app.
### This variable can be set to 
###    a. A VectorCAST Compiler Tag: 'GNU_C_46'
###    b: The full path to an existing CFG file: /home/VC/CCAST_.CFG
VCAST_COMPILER_CONFIGURATION='/emc/jlewis/vcast_environments/scripts/master.CCAST_.CFG'


#######################################################################################
# The following set of options will take care of most normal use cases

### Project Limits (for first time use to make things faster)
### To test the configuration, we recommend using the default values of 1,1,0
### This will provide a FAST initial test of the build and build settings.
### If the first run works nicely and you get a VC project, bump the 
### numbers up to 50, 50, 5, for a second run, which will generate a cover 
### project with 50 files, 50 unit test environments and 5 fully built unit test environments.
### You can set these variables to 'max' or 'all' to process all files from the vcshell.db
### If you only want to do System Testing set MAXIMUM_FILES_TO_UNIT_TEST to 0
### If you only want to do Unit Testing, set MAXIMUM_FILES_TO_SYSTEM_TEST to 0
### MAXIMUM_FILES_TO_SYSTEM_TEST=0
MAXIMUM_FILES_TO_UNIT_TEST=0
MAXIMUM_UNIT_TESTS_TO_BUILD=0

### Specify the files to be prioritized when building the VectorCAST project
### If you specify ['foo.c', .bar.c', 'main.c'] these will be the first 3
### units processed.  If you specify a file limit of 2, we will process foo.c
### and bar.c in the rist invocation, and main.c next time
FILES_OF_INTEREST=[AutomationController.parameterNotSetString]

### FILES_OF_INTEREST=[s.strip() for s in open(PROJECT_NAME + "_filter.list","r").readlines()]

### VCShell DataBase Location
### The vcshell.db file should always be generated at the build area root directory
### (the place where you normally run the make command).  The default workflow is to run
### the Automation Controller scripts in that build area root directory, which results
### in the VectorCAST workarea (vcast-workarea) being generated there also.
### If you wish to run create the VectorCAST workarea in some other place, copy
### the automation controller files to that alternate location, and set VCSHELL_DB_LOCATION
### to point at location of the vcshell.db (the build area root)
### You must use an absolute path for this file (not relative)
VCSHELL_DB_LOCATION=os.getcwd()

### Code Coverage
### Choices are: none, statement, branch, mcdc, statement+branch, statement+mcdc, basis_paths, probe_point, coupling
VCAST_COVERAGE_TYPE='statement'

### This will construct the .env files with the path to the vcshell, rather than the search paths and unit options
### Change it to False if you wish to construct .env files with search paths and unit options
### Default value is True which uses ENVIRO.VCDB_FILENAME
ENV_FILES_USE_VCDB=True

### Instrument in place means that the original file foo.c is backed up
### to foo.c.vcast.bak, and an instrumented foo.c is stoed in its place
####INSTRUMENT_IN_PLACE=0

INSTRUMENT_IN_PLACE=False

### The VCDB_FLAG_STRING flags will be used as "extra" flags when we call vcdb
### to get the unit options.  If nothing is passed we will use the -I and -D flags only
### A common value for this for GNU is "-isystem=1"
VCAST_VCDB_FLAG_STRING='-iquote=1'

# This list of main files will be used to automatically append the c_cover_io.c file
# to one file in each application that is being instrumented.
# If you want VectorCAST to automatically compute the insert locations for c_cover_io:
LIST_OF_MAIN_FILES = [AutomationController.parameterNotSetString]
# If you want to manually choose the files where c_cover_io is inserted do this:
# LIST_OF_MAIN_FILES = ['firstMain.c', 'secondMain.c']
# To disable the insert of the c_cover_io.c completely, do this:
# LIST_OF_MAIN_FILES = []
LIST_OF_MAIN_FILES = ['70_inlines.c']


### You can optionally run Lint analysis on the files in the project
LINT=False

### This value will be used to set a TCAST_CASE_TIMEOUT option for the UnitTest node
### This is useful, especially for basis path tests that sometimes loop foreever.
### If you do not want to use a timeout value, set this variable to 0
TEST_TIMEOUT=10



#######################################################################################
# The follow set of configuration option supports advanced workflows

### When vcshell creates a settings database, it makes all of the -I paths that it finds
### VectorCAST search paths.  In some cases, you may want to over-ride this default behavior
### The INCLUDE_PATH_OVERRIDE feature allows you to exactly control how Include Paths 
### are handled by the automation controller.  The INCLUDE_PATH_OVERRIDE variable
### is a list of tuples which contain the include path and the OverRide Action.
### Possible OverRide Action values are: 
###             NONE:   Do not use this Include Path
###             SEARCH: Consider the path a Search Path (default)
###             LIB:    Consider the path a Library Include Path
###             TYPE:   Consider the path a Type Handled Path
### If the list contains a path that is not in the vcshell database, we will add that path
### INCLUDE_PATH_OVERRIDE = [('/home/mySourceCode/libDir', 'LIB'), ('/home/mySourceCode/newPath', 'SEARCH')
INCLUDE_PATH_OVERRIDE = []

### This filter function below can be used to limit the files that are processed.
### You can use the FILTER_PATTERNS objects with the default filterFiles 
### function, or you can completely replace the filterFiles function.
###
### The filter strings will OR'd and applied to the absolute file paths
### This allows you to filter down to a set or directories or files
### whose names contain any one of the strings.  For example, if you
### have a file structure like this: /home/source/subSystem1  
### /home/source/subSystem2, then the following filter pattern:
### FILTER_PATTERNS = ['/subSystem2', 'foo']  
### would yield all of the files in subSystem2, and any other file
### whose path contains the string foo.  MAXIMUM_FILES_TO_SYSTEM_TEST 
### and MAXIMUM_FILES_FOR_UNIT_TEST 
### still control the maximum number of files to be processed.
###
###FILTER_PATTERNS = []
#FILTER_PATTERNS = ['sa/sa','70_inlines.c']
FILTER_PATTERNS = []
def matchesFilter(filePath):
    for filter in FILTER_PATTERNS:
        if filter in filePath:
            return True

#def filterFileList (originalList):
#    '''
#    This function is a white-list function.  It will spin through
#    the full file list and "keep" any files that have a pattern
#    from the filterStringList.  You can easily turn this function
#    into a black-list function that will omit file patterns.
#    '''
#    localFileList = []
#    if len (FILTER_PATTERNS) > 0:
#        for file in originalList:
#            if matchesFilter(file):
#                localFileList.append(file)
#    else:
#        localFileList=originalList[:]      
#    if 'instrumented_files' in os.environ:
#        if os.path.isfile(os.environ['instrumented_files']):
#            print 'Instrumenting from a file list'
#            localFileList=[os.environ['PWD'] + "/" + s.strip() for s in open(os.environ['instrumented_files'],"r").readlines()]
#    else:
#        print 'Instrumenting everything in the database'
#    return localFileList


def filterFileList (originalList):

    fileList = []
    PWD = os.getcwd()
        
    try:
        WHITE_LIST = [PWD + "/" + s.strip() for s in open(os.environ['instrumented_files'],"r").readlines()]
    except KeyError:
        WHITE_LIST = []
        print "White list not defined"
        
    try:
        BLACK_LIST = [PWD + "/" + s.strip() for s in open(os.environ['BLACK_LIST'],"r").readlines()]
    except KeyError:
        BLACK_LIST = []
        print "Black list not defined"

    for wf in WHITE_LIST:
        # Pass 1 through the black list looking for file matches
        for bf in BLACK_LIST:
             found = False
             if wf == bf:
                 print "Black-listed file " + wf + " will not be instrumented"
                 found = True
                 if wf in fileList:
                     fileList.remove(wf)
                 break
        if found == False:
             fileList.append(wf)
        # Pass 2 through the black list looking for directory matches
        for bf in BLACK_LIST:
             if not bf.endswith(".c"):
                 if wf.startswith(bf):
                     print "Black-listed directory " + bf + " found. "  +  wf + " will not be instrumented"
                     if wf in fileList:
                        fileList.remove(wf)
                        break

    print "Files to be instrumented after applying filters:"
    print '\n'.join(fileList)
    return fileList
    
### This envFileEditor function can be used to change the configuration of the 
### default .env files that are generated by the Automation Controller.
### This function will be called once for each .env file.
def envFileEditor(pathToEnvFile):
    '''
    There are two common edits that you might want to make to environment script
        1. Change the value of an existing line in the script
           For example, change ENVIRO.STUB: ALL_BY_PROTOTYPE to 
                               ENVIRO.STUB: NONE
        2. Add new lines to the script
           For example, ENVIRO.APPENDIX_USER_CODE 
    '''
    #This function will do no work by default ...
    return
    # To change an existing command, use this function call
    AutomationController.editEnvCommand (pathToEnvFile=pathToEnvFile, flag='ENVIRO.STUB', oldValue='ALL_BY_PROTOTYPE', newValue='NONE')
    # To insert a totally new line or block, use this function call
    AutomationController.insertEnvCommand (pathToEnvFile=pathToEnvFile, newCommand= \
        'ENVIRO.UNIT_APPENDIX_USER_CODE:\n' + \
        'ENVIRO.UNIT_APPENDIX_USER_CODE_FILE:manager \n'+ \
        '/* here is some appendix user code for manager */\n'+ \
        'ENVIRO.END_UNIT_APPENDIX_USER_CODE_FILE:\n' + \
        'ENVIRO.END_UNIT_APPENDIX_USER_CODE:\n' )
        
      
#######################################################################################
#######################################################################################
# The code below this comment should not be modified.

def maxToSystemTestArg():
    try:
        intVal = int (MAXIMUM_FILES_TO_SYSTEM_TEST)
        # if the MAX variable is an integer, then return the arg
        return MAXIMUM_FILES_TO_SYSTEM_TEST
    except:
        return sys.maxint

def maxToUnitTestArg():
    try:
        intVal = int (MAXIMUM_FILES_TO_UNIT_TEST)
        # if the MAX variable is an integer, then return the arg
        return MAXIMUM_FILES_TO_UNIT_TEST
    except:
        return sys.maxint

def maxToBuildArg():
    try:
        intVal = int (MAXIMUM_UNIT_TESTS_TO_BUILD)
        # if the MAX variable is an integer, then return the arg
        return MAXIMUM_UNIT_TESTS_TO_BUILD
    except:
        return sys.maxint

def instrumentInplaceArg ():
    if INSTRUMENT_IN_PLACE:
        return '--inplace'
    else:
        return ''

def main():
        
    print "Automation Controller (vcdb2vcm.py) : 6/27/2018"

    '''
    Calling arguments:
        command     command-arg      Verbose
        build-vce   root-directory   True|False
    '''
    
    if len (sys.argv) < 2:
        print 'This script must be called with and arg of "build-db" or "build-vce"'
    elif sys.argv[1]=='build-vce':
        AutomationController.vcmFromEnvironments ( \
            projectName=PROJECT_NAME, rootDirectory=sys.argv[2],\
            statusfile=PROJECT_NAME+'-automation-status.txt', verbose=sys.argv[3])
    elif sys.argv[1]=='build-db':
    
        try:
            AutomationController.automationController (projectName=PROJECT_NAME, \
                 vcshellLocation=VCSHELL_DB_LOCATION, \
                 listOfMainFiles=LIST_OF_MAIN_FILES, runLint=LINT, \
                 maxToSystemTest=maxToSystemTestArg(), maxToUnitTest=maxToUnitTestArg(), \
                 maxToBuild=maxToBuildArg(), filterFunction=filterFileList, 
                 compilerCFG=VCAST_COMPILER_CONFIGURATION, coverageType=VCAST_COVERAGE_TYPE, \
                 inplace=instrumentInplaceArg(), \
                 vcdbFlagString=VCAST_VCDB_FLAG_STRING, \
                 tcTimeOut=TEST_TIMEOUT, includePathOverRide=INCLUDE_PATH_OVERRIDE, \
                 envFileEditor=envFileEditor, statusfile=PROJECT_NAME+'-automation-status.txt', verbose=sys.argv[2],
                 filesOfInterest=FILES_OF_INTEREST,vcast_workarea=VCAST_WORKAREA, vcDbName=VCDB_FILENAME, envFilesUseVcdb=ENV_FILES_USE_VCDB)
        except Exception as e:
            print "VCDB2VCM: Raising exception"
            sys.exit(-1)
                 
if __name__ == "__main__":
    try:
        main()
    except Exception, err:
        # No need to output a stack trace if we failed for a vcast reason.
        if str(err) == 'VectorCAST command failed' or str(err)=='FLEXlm error' or str(err)=='VCAST Termination Error':
            pass
        else:
            print Exception, err
            print traceback.format_exc()
