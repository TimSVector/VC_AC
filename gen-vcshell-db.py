
import sys
import os
import subprocess

if os.path.isfile("vcshell.db"):
    print "Removing old database"
    os.remove ("vcshell.db")     
    
build_log = sys.argv[1]
print "Parsing file: " + build_log
lines = open(build_log,"r").readlines()

current_dir = ""
cmd = ""
build_data = ""
for line in lines:
    da = line.split(":")
    if "u'command" in line:
        cmd =  da[1].split("'")[1]
        cmd = cmd.replace("bazel/tools/cpp/wrappers/clang++-ccache.sh","clang++")
        cmd = cmd.replace("bazel/tools/cpp/wrappers/clang-ccache.sh","clang")
    if "u'directory" in line:
        dir = da[1].split("'")[1]
    if "u'file" in line:
        if current_dir != dir:
            current_dir = dir
            build_data += "dir::"+current_dir+ "\n"
        build_data += "cmd::"+cmd + "\n"
        
print "Building intermediate log file: vc_build.log"
        
f=open("vc_build.log","w")
f.write(build_data)
f.close()

print "Building database..."
cmd2Run = os.path.join(os.environ['VECTORCAST_DIR'], "vcshell --inputcmds=out.log putcommand")

p = subprocess.Popen(cmd2Run, stdout=subprocess.PIPE, stderr=subprocess.PIPE,universal_newlines=True,shell=True)
o,e = p.communicate()

print o,e
