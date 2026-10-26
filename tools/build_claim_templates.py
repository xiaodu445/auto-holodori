"""Derive small stable claim UI anchors; never use artwork or reward quantities."""
import json
from pathlib import Path
from PIL import Image
from modular_agent.perception.template_import import import_game_templates
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'domains/hololive_dreams/data/world_reference/20261017'
DEST=ROOT/'domains/hololive_dreams/data/template_sources/in_game/claims'
SPECS=[
 ('claim_pass_page','049a80a7-aa25-44ca-bb15-81f4d487d435',(99,70,238,105)),
 ('claim_tasks_tab','73fbf1d6-3348-4181-bbf4-d599c494280e',(382,187,437,214)),
 ('claim_pass_tab','049a80a7-aa25-44ca-bb15-81f4d487d435',(141,187,215,214)),
 ('claim_daily_tab','73fbf1d6-3348-4181-bbf4-d599c494280e',(169,286,215,313)),
 ('claim_weekly_tab','53418a90-0daa-44ae-bb50-0ae5aa489134',(169,368,215,396)),
 ('claim_season_tab','73fbf1d6-3348-4181-bbf4-d599c494280e',(169,458,215,486)),
 ('claim_all','0fa79e05-fa45-4357-9fbd-0aec03562164',(1070,665,1178,692)),
 ('claim_all_task','73fbf1d6-3348-4181-bbf4-d599c494280e',(1030,666,1161,694)),
 ('claim_one','a39c4d07-ac3d-4f8a-b056-96ab50604e0c',(1080,221,1120,245)),
 ('claim_available','8aa2acca-3e60-4c4d-9117-2bfada427150',(1115,233,1177,256)),
 ('claim_achievement_page','8aa2acca-3e60-4c4d-9117-2bfada427150',(99,86,157,116)),
 ('claim_event_carousel','bda4e805-131f-4b85-81fb-07d2ef2d1bf6',(113,146,212,165)),
 ('claim_event_page','6922dbdd-9ea0-41e3-8511-5456d63c4aef',(100,55,211,117)),
 ('claim_event_home','5d6e9988-5b6d-4d05-9439-3b04c873e1b4',(1195,463,1236,488)),
 ('claim_event_go','bda4e805-131f-4b85-81fb-07d2ef2d1bf6',(1083,679,1155,706)),
 ('claim_event_daily','6922dbdd-9ea0-41e3-8511-5456d63c4aef',(595,171,641,197)),
 ('claim_event_free','f5c82501-ab6d-4378-8770-a534ce14b84b',(1003,171,1048,197)),
]
if __name__=='__main__':
 DEST.mkdir(parents=True,exist_ok=True)
 for name,source,box in SPECS:
  Image.open(SOURCE/f'codex-clipboard-{source}.png').crop(box).save(DEST/f'{name}.png')
  (DEST/f'{name}.json').write_text(json.dumps(dict(name=name,role='panel',threshold=.92,notes=f'领取模块稳定文字；来源{source}裁剪{box}；待实机验证'),ensure_ascii=False),encoding='utf-8')
 print(import_game_templates(ROOT,'hololive_dreams',DEST))
