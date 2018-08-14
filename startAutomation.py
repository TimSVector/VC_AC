
''' 
This is a simple shell script that can be used to provide a choices menu 
of what automation command to run
 
    - build a demo VC Project using the command: $VECTORCAST_DIR/vpython vcdb2vcm.py
    - copy this python script into the directory where you ran vcdb2vcm.py
    - run this script using the command: $VECTORCAST_DIR/vpython startAutomation.py

Respond to the menu of command choices    
 
'''

import argparse
import os
import shutil
import subprocess
import traceback
import sys

from vector.apps.EnvCreator import AutomationController
import vcdb2vcm


# This is the startup directory where the script is being run
# It is assumed that this directory contains vcshell.db file
originalWorkingDirectory=os.getcwd()

vcInstallDir = os.environ["VECTORCAST_DIR"]
globalMakeCommand = ''
vceBaseDirectory = ''


def setupArgs (toolName):
    '''
    '''
    
    parser = argparse.ArgumentParser(description=toolName)
    
    group = parser.add_mutually_exclusive_group(required=True)
    
    # Base directory for building and vc projects and scripts.
    group.add_argument ('--interactive', dest='interactive', action='store_true', default=False,
                           help='Interactive mode')    

    # Command to run -- for non Interactive mode
    commandChoices=['make', 'clean', 'build-db', 'build-vce', 'vcast', 'analytics', 'enable', 'disable', 'toolbar', 'enterprise']
    group.add_argument ('--command', dest='command', action='store', default='full',
                           choices=commandChoices, help='Command Choice')

    # Make command
    parser.add_argument ('--makecmd', dest='makecmd', action='store', default='',
                           help='Comand to make the application')

    # VCE Root Directory
    parser.add_argument ('--vceroot', dest='vceroot', action='store', default='',
                           help='Root path to VectorCAST environments')

    # Path to the VC project file: .vcm, .vce, .vcp (used for command='toolbar')
    parser.add_argument ('--project', dest='project', action='store', default='',
                           help='Full path to the VectorCAST project file')
                           
    # Path to the environment script file (used for command='enterprise')
    parser.add_argument ('--script', dest='script', action='store', default='',
                           help='Root path to the VectorCAST workarea')                              
                           
    # Root for vcast-workarea directory (used for command='toolbar' || 'enterprise')
    parser.add_argument ('--workarea', dest='workarea', action='store', default='',
                           help='Root path to the VectorCAST workarea')    
                           
    parser.add_argument ('--verbose', dest='verbose', action='store_true', default=False,
                           help='Root path to VectorCAST environments')    

    parser.add_argument ('--parallel', dest='parallel', action='store_true', default=False,
                           help='Use parallel instrumentor')    

    return parser



def solicitChoice():

    AutomationController.sectionBreak('');
    print 'VectorCAST Automation Controller Script'
    print '   (1) Build Application under vcShell'
    print '   (2) Delete VectorCAST Project and un-instrument files'
    print '   (3) Build/Extend a VectorCAST Project from vcshell.db'
    print '   (4) Build/Extend a VectorCAST Project from .vce'
    print '   (5) Start VectorCAST'
    print '   (6) Start the Analytics Server'
    print '   (7) Disable Coverage'
    print '   (8) Enable Coverage'
    print '   (9) Quit'
    
    try:
        listChoiceString = ( raw_input ('Action to take: '))
        listChoice = int (listChoiceString)
    except:
        # 0 means do nothing
        listChoice = 0

    return listChoice

    
def clean ():
    '''
    This function will un-instrument all of the files that are in the cover project
    and then remove the vcast-workarea directory.  We do this rather than using
    the clicast un-instrument, because this is _MUCH_ faster
    '''
    workArea = 'vcast-workarea'
    
    # Un-instument any instrumented source files
    AutomationController.unInstrumentSourceFiles() 
    
    if os.path.isdir (workArea):
        print 'Removing the previous vcast-workarea'
        shutil.rmtree (workArea)

    
def performTask (whatToDo, verbose):
    '''
    This function will do the real work
    '''
    global globalMakeCommand
    global vceBaseDirectory
    global originalWorkingDirectory
    
    if whatToDo == 'make':
        if vcdb2vcm.VCSHELL_DB_LOCATION!=originalWorkingDirectory:
            os.chdir (vcdb2vcm.VCSHELL_DB_LOCATION)
        if not os.path.isfile ('CCAST_.CFG'):
            AutomationController.initializeCFGfile (vcdb2vcm.VCAST_COMPILER_CONFIGURATION, vcdb2vcm.VCAST_VCDB_FLAG_STRING)
        commandToRun = os.path.join (vcInstallDir, 'vcshell') + ' --metrics ' + globalMakeCommand
        print 'Running: ' + commandToRun
        subprocess.call (commandToRun, shell=True)
        os.chdir (originalWorkingDirectory)

    elif whatToDo == 'clean':
        clean()

    elif whatToDo == 'build-db' or whatToDo=='build-vce':
        # Run the vcdb2vcm script to create the project
        try:
            vcdb2vcm.main(whatToDo, vceBaseDirectory, verbose)
        except Exception as e:
            print e
            sys.exit("STARTAC: vcdb2vcm error")
  
    elif whatToDo == 'vcast':
        # Start VC for the project
        AutomationController.startManageGUI()      
    
    elif whatToDo == 'analytics':
        # Start Analytics for the project
        AutomationController.startAnalytics(vcdb2vcm.VCSHELL_DB_LOCATION)
        
    elif whatToDo == 'disable':
        # Start Analytics for the project
        AutomationController.disableCoverage()

    elif whatToDo == 'enable':
        # Start Analytics for the project
        AutomationController.enableCoverage()  



    
def interactiveMode(verbose):
    '''
    This function will run in an infinite loop to solicit input from the
    user and execute the command chosen
    '''
    global globalMakeCommand
    global vceBaseDirectory
    while (True):
    
        whatToDo = solicitChoice()
        command='none'
        
        if whatToDo == 1:
            # Solicit the build command
            makeCommand =  raw_input ('Enter the command to build your application: ')
            if len(makeCommand)>0:
                globalMakeCommand = makeCommand
                command = 'make'

        elif whatToDo == 2:
            try:
                listChoiceString = ( raw_input ('Enter "yes" to confirm clean action: '))
                if listChoiceString == 'yes':
                   command = 'clean'
            except:
                command = 'none'
                pass
           
        elif whatToDo == 3:
            command = 'build-db'

        elif whatToDo == 4:
            vceBaseDirectory = ( raw_input ('Enter base directory for environment search: '))
            if len(vceBaseDirectory)>0:
                command = 'build-vce'

        elif whatToDo == 5:
            command = 'vcast'
        
        elif whatToDo == 6:
            command = 'analytics'
        
        elif whatToDo == 7:
            command = 'disable'
        
        elif whatToDo == 8:
            command = 'enable'
        
        elif whatToDo == 9:
            break
        
        performTask (command, verbose)
    

def argsAreValid (args):

    if not os.path.isdir (args.workarea):
        print '--workarea arg: "' + args.workarea + '" is invalid'
        return False
    else:
        return True

    
def main():
    '''
    '''
    global globalMakeCommand
    global vceBaseDirectory
    
    parser = setupArgs ('startAutomation') 
    
    if parser.parallel:
        vcdb2vcm.MAXIMUM_FILES_TO_SYSTEM_TEST=-1

    # Read the arguments
    try:
        args = parser.parse_args()
    except SystemExit:
        raise
        
    if args.interactive:
        interactiveMode(args.verbose)
    elif args.command == 'make' and len (args.makecmd)==0:
        print 'Error: --makecmd not provided'
    elif args.command == 'build-vce' and len (args.vceroot)==0:
        print 'Error: --vceroot not provided'
    elif args.command =='toolbar':
        # Tool-bar mode starts an Analytics dashboard for the current project
        # This is only used by the toolbar icon
        if argsAreValid (args):
            AutomationController.toolBarDashIcon (workareaBaseDirectory=args.workarea, vcProjectFile=args.project)
    elif args.command =='enterprise':
        # enterprise mode builds a VectorCAST project, adds the environment script, and builds the environment
        if argsAreValid (args):
            AutomationController.enterpriseEnvironmentBuild (workareaBaseDirectory=args.workarea, projectName=args.project, scriptFile=args.script)
    else:
        globalMakeCommand = args.makecmd
        vceBaseDirectory = args.vceroot
        performTask (args.command, args.verbose)
        
    

if __name__ == "__main__":
    try:
    
        print "Automation Controller (startAutomation.py) : 7/18/2018"
        
        main()
    except Exception, err:
        if str(err) != 'VCAST Termination Error':
            print Exception, err
            print traceback.format_exc()
        print Exception, err
        print traceback.format_exc()




