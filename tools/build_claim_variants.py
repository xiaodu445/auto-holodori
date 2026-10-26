"""Build local UI text variants from archived user evidence (no live inputs)."""
import json
from pathlib import Path
from PIL import Image
from modular_agent.perception.template_import import import_game_templates
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'domains/hololive_dreams/data/world_reference/20261025'
DEST=ROOT/'domains/hololive_dreams/data/template_sources/in_game/claims'
SPECS=[
 ('claim_event_home_sample','3723fc7c-8137-4491-8a6d-5d7ff1af09f0',(1180,460,1216,482)),
 ('claim_pass_page_sample','5162868c-17a2-494f-83d6-d25fd58fe187',(100,70,233,102)),
 ('claim_pt_limit','5162868c-17a2-494f-83d6-d25fd58fe187',(610,280,857,302)),
 ('claim_close','32e0fbcd-b280-4903-9a77-9bda1f7f5d03',(1188,79,1220,109)),
]
if __name__=='__main__':
 for name,source,box in SPECS:
  Image.open(SOURCE/f'codex-clipboard-{source}.png').crop(box).save(DEST/f'{name}.png')
  (DEST/f'{name}.json').write_text(json.dumps(dict(name=name,role='panel',threshold=.92,notes=f'20261025 archived {source}; crop {box}'),ensure_ascii=False),encoding='utf-8')
 print(import_game_templates(ROOT,'hololive_dreams',DEST))
