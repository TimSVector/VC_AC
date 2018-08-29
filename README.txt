
Updated Automation Controller files



Install:

* copy AutomationController.py to $VECTORCAST_DIR/python/vector/apps/EnvCreator
* copy startAutomation.py, vcdb2vcm.py, gen-vcshell-db.py and master.CCAST_.CFG to location of vcshell.db or build log
* Run where bulid log is something like vim_compile.json:
     $VECTORCAST_DIR/vpython gen-vcshell-db.py <build log>