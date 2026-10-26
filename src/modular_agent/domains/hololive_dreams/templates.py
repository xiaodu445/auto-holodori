"""Entry template groups and explicit template semantics, shared by observers."""
MAP=['entry_map_garden','entry_map_arcade','entry_map_bay']
DETAIL=['entry_detail_greed','entry_move','entry_area','entry_lobby','entry_lever_detail']
WORLD=['entry_interact','entry_dialogue','entry_lever_interact','entry_to_game','entry_keep']
READY=['entry_ready_logo','entry_ready_start']
SEMANTICS={
 'entry_map_garden':['MAP','协律花园'],'entry_map_arcade':['MAP','电玩巨蛋城'],
 'entry_map_bay':['MAP','汽水泡泡海湾'],'entry_detail_greed':['强欲之牌','猜高低'],
 'entry_move':['移动'],'entry_area':['游玩区域'],'entry_lobby':['大厅'],
 'entry_lever_detail':['切换操纵杆','更改游玩区域'],'entry_lever_interact':['切换操纵杆'],
 'entry_to_game':['切换为游戏区'],'entry_keep':['不进行更改'],
 'entry_interact':['猜高低'],'entry_dialogue':['Shiori','为了抓住机会'],
}
