"""Executed by EVERY bundled Python process, including direct GUI workers."""
import os,sys
_runtime=os.path.dirname(sys.executable)
# Retain handles for process lifetime; never add developer paths or the CWD.
_dll_handles=[os.add_dll_directory(p) for p in (
    _runtime,os.path.join(_runtime,'DLLs'),os.path.join(_runtime,'natives'),
    os.path.join(_runtime,'Lib','site-packages','numpy.libs'),
    os.path.join(_runtime,'Lib','site-packages','shapely.libs')) if os.path.isdir(p)]
os.environ['TCL_LIBRARY']=os.path.join(_runtime,'tcl','tcl8.6')
os.environ['TK_LIBRARY']=os.path.join(_runtime,'tcl','tk8.6')
