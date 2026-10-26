import sys,tempfile,unittest
from pathlib import Path
from importlib.metadata import distributions
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'release'))
from runtime_metadata import collect_metadata
from capture_cleanup_probe import check_cleanup

class MetadataTests(unittest.TestCase):
    def test_actual_curve_end_release(self):
        result=check_cleanup()
        self.assertEqual(result['dxcam_version'],'0.3.0')
        self.assertEqual(result['camera_release_calls'],1)
        self.assertEqual(result['native_addref_calls'],2)
    def test_missing_metadata_fails_build(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,'dxcam metadata missing'):
                collect_metadata(Path(folder),Path(folder)/'target',['dxcam'])
    def test_distribution_name_need_not_match_import_name(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);source=base/'source';source.mkdir();target=base/'runtime/Lib/site-packages';target.mkdir(parents=True)
            for name,version,module in [('dxcam','0.3.0','dxcam'),('Pillow','12.0','PIL')]:
                (source/module).mkdir();(source/module/'__init__.py').write_text('')
                info=source/(name+'-'+version+'.dist-info');info.mkdir()
                (info/'METADATA').write_text('Metadata-Version: 2.1\nName: '+name+'\nVersion: '+version+'\n')
                (info/'RECORD').write_text(module+'/__init__.py,,\n'+info.name+'/METADATA,,\n'+info.name+'/RECORD,,\n')
            result=collect_metadata(source,target,['dxcam','PIL'])
            self.assertEqual(result,{'dxcam':'0.3.0','Pillow':'12.0'})
            self.assertEqual({d.metadata['Name']:d.version for d in distributions(path=[str(target)])},result)

if __name__=='__main__':unittest.main()
