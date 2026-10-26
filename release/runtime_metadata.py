"""Collect distribution metadata for the packages actually shipped."""
from importlib.metadata import distributions
from pathlib import Path
import shutil,json

def collect_metadata(source,target,packages):
    roots={name.split('/')[0] for name in packages}
    result={}
    for distribution in distributions(path=[str(source)]):
        files=list(distribution.files or [])
        if not any(str(file).replace('\\','/').split('/')[0] in roots for file in files):continue
        metadata_file=next((file for file in files if str(file).replace('\\','/').endswith('.dist-info/METADATA')),None)
        if metadata_file is None:raise RuntimeError('Missing METADATA for '+str(distribution.metadata.get('Name')))
        folder=Path(distribution.locate_file(metadata_file)).parent
        shutil.copytree(folder,Path(target)/folder.name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        result[distribution.metadata['Name']]=distribution.version
    if not any(name.lower()=='dxcam' for name in result):raise RuntimeError('Required dxcam metadata missing')
    (Path(target).parent.parent/'distribution-metadata.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
