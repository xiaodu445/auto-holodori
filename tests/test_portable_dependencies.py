import unittest,sys,tempfile,shutil,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'))
from runtime_dependencies import imports,collect
class PortableDependenciesTests(unittest.TestCase):
    def test_actual_ctypes_import_names(self):
        names=[n.lower() for n in imports(ROOT/'.conda/DLLs/_ctypes.pyd')]
        self.assertIn('ffi-8.dll',names)
    def test_missing_native_dependency_fails_build(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runtime=root/'runtime';runtime.mkdir();python=root/'empty';python.mkdir()
            shutil.copy2(ROOT/'.conda/DLLs/_ctypes.pyd',runtime/'_ctypes.pyd')
            with self.assertRaisesRegex(RuntimeError,'ffi-8.dll'):collect(runtime,python)
            self.assertTrue(json.loads((root/'native-dependencies.json').read_text())['missing'])
    def test_invalid_pe_fails_instead_of_silent_skip(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'invalid.dll';p.write_bytes(b'not a PE')
            with self.assertRaises(ValueError):imports(p)
if __name__=='__main__':unittest.main()
