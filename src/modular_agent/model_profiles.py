"""Named model profiles and persistent selection; configuration contains no raw keys."""
import json
from pathlib import Path
from .model_client import ModelConfig,create_model_client

class ModelProfiles:
    def __init__(self,root):
        self.root=Path(root)
        self.path=self.root/'config'/'models.json'
    def names(self):
        if not self.path.exists(): return ['mock']
        return sorted(json.loads(self.path.read_text(encoding='utf-8-sig'))['profiles'])
    def resolve(self,name):
        if not self.path.exists():
            if name=='mock': return ModelConfig()
            raise ValueError('Unknown model profile; use /models to list profiles')
        data=json.loads(self.path.read_text(encoding='utf-8-sig'))
        if name not in data['profiles']: raise ValueError('Unknown model profile; use /models to list profiles')
        config=ModelConfig.from_dict(data['profiles'][name],self.path.parent)
        create_model_client(config)  # Validate provider before persisting selection.
        return config
    def select(self,name):
        config=self.resolve(name)
        data=config.public_dict()
        if config.api_key_file:
            import os
            data['api_key_file']=os.path.relpath(config.api_key_file,self.root/'config')
        directory=self.root/'config'; directory.mkdir(parents=True,exist_ok=True)
        temporary=directory/'model.json.tmp'
        temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(directory/'model.json')
        return config
