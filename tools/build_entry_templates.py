"""Build entry-only UI crops from archived, user-confirmed screenshots."""
import json
from pathlib import Path
from PIL import Image
from modular_agent.perception.template_import import import_game_templates
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'domains/hololive_dreams/data/world_reference/20261017'
DEST=ROOT/'domains/hololive_dreams/data/template_sources/in_game/entry'
SPECS=[
 ('entry_map_garden','e4d701bc-5942-43ed-8ca5-c631d58a2674',(105,56,246,115),'MAP 协律花园'),
 ('entry_map_arcade','8e6f38a1-d645-4bb5-8941-cd90ac89b6d6',(105,56,283,115),'MAP 电玩巨蛋城'),
 ('entry_map_bay','22d43c4f-9a90-4b4c-800a-602839ec027f',(105,56,309,115),'MAP 汽水泡泡海湾'),
 ('entry_detail_greed','320db1de-9bc8-479a-a218-d2ce4b7c9115',(950,220,1060,302),'强欲之牌 猜高低'),
 ('entry_move','320db1de-9bc8-479a-a218-d2ce4b7c9115',(993,548,1046,581),'移动'),
 ('entry_area','8e6f38a1-d645-4bb5-8941-cd90ac89b6d6',(281,680,372,708),'游玩区域'),
 ('entry_lobby','13225c2e-73c0-4ca4-b400-ed9b4970d493',(188,678,235,707),'大厅'),
 ('entry_lever_detail','5c5f91de-3ea7-4ac5-b0b7-5481d30a7983',(940,218,1070,300),'切换操纵杆 更改游玩区域'),
 ('entry_lever_interact','6c3b8da1-0722-451d-9445-1dea3bfe803b',(925,460,1037,490),'切换操纵杆'),
 ('entry_to_game','7be9e448-7b6f-4a25-8a4f-fc705a07467d',(925,391,1057,422),'切换为游戏区'),
 ('entry_keep','7be9e448-7b6f-4a25-8a4f-fc705a07467d',(925,459,1038,491),'不进行更改'),
 ('entry_interact','71d0a821-6f9d-4a0b-ba32-cb7fda90d0d8',(925,457,990,491),'猜高低'),
 ('entry_dialogue','ab709d1b-1754-4fcc-9222-766a22aa604a',(449,649,801,689),'为了抓住机会'),
 ('entry_ready_logo','826b8d5c-5a0f-4762-b8c6-46652ade974b',(37,78,240,196),'High&Low'),
 ('entry_ready_start','826b8d5c-5a0f-4762-b8c6-46652ade974b',(554,598,709,629),'押注并开始游戏'),
]
if __name__=='__main__':
 DEST.mkdir(parents=True,exist_ok=True)
 for name,source,box,meaning in SPECS:
  Image.open(SOURCE/f'codex-clipboard-{source}.png').crop(box).save(DEST/f'{name}.png')
  (DEST/f'{name}.json').write_text(json.dumps(dict(name=name,role='panel',threshold=.90,notes=f'入口模块稳定UI裁剪，语义：{meaning}。来源：归档截图{source}，尚待实机验证。'),ensure_ascii=False,indent=2),encoding='utf-8')
 print(import_game_templates(ROOT,'hololive_dreams',DEST))
