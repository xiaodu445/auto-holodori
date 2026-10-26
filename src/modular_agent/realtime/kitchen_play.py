"""Compatibility entrypoint for the domain-owned kitchen runtime."""
import importlib.util
from pathlib import Path
import sys

path=Path(__file__).resolve().parents[3]/'domains/hololive_dreams/models/kitchen/kitchen_play.py'
spec=importlib.util.spec_from_file_location('holodori_kitchen_runtime',path)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
if __name__=='__main__':
    module.main()
else:
    sys.modules[__name__]=module
