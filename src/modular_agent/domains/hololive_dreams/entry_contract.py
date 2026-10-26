"""Expected observable outcomes for entry steps; diagnostics, not proof of success."""
from .states import UIState as S
EXPECTED={
 'map_zoom_out':(S.MAP,), 'map_pan':(S.MAP,),
 'free_main':(S.MAP,), 'select_arcade':(S.MAP,),
 'select_area':(S.MAP,), 'select_smallgame':(S.LOCATION_DETAIL,),
 'teleport':(S.LOADING,S.WORLD,S.INTERACTION),
 'arrived':(S.INTERACTION,), 'interact':(S.DIALOGUE,S.GREED_READY),
 'dialogue':(S.GREED_READY,), 'await_game':(S.GREED_READY,),
 'reinteract':(S.DIALOGUE,S.GREED_READY),
 'select_lobby':(S.MAP,), 'select_lever':(S.LOCATION_DETAIL,),
 'lever_teleport':(S.LOADING,S.INTERACTION),
 'lever_interact':(S.OPTIONS,), 'switch_casino':(S.LOADING,S.WORLD),
 'keep_casino':(S.WORLD,), 'open_map_after_switch':(S.MAP,),
 'wrong_detail':(S.MAP,),
}
