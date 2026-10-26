"""Observable UI states. Workflow actions never belong in this vocabulary."""
from dataclasses import asdict, dataclass
from enum import StrEnum

class UIState(StrEnum):
 UNKNOWN='unknown'
 WORLD='world.free'
 MAP='map.overview'
 LOCATION_DETAIL='map.location_detail'
 INTERACTION='world.interaction'
 OPTIONS='interaction.options'
 NOTIFICATION='overlay.notifications'
 ACHIEVEMENT_DETAIL='achievement.detail'
 ACHIEVEMENT_LIST='achievement.list'
 DIALOGUE='dialogue'
 REWARD='overlay.reward'
 RANK_UP='overlay.rank_up'
 SCRATCH_TICKET='overlay.scratch_ticket'
 LOADING='transition.loading'
 ERROR='overlay.error'
 GREED_READY='minigame.greed.ready'
 GREED_PLAY='minigame.greed.play'

@dataclass(frozen=True)
class Recognition:
 state: UIState
 evidence: tuple[str,...]=()
 map_name: str|None=None
 def to_dict(self): return asdict(self)

def normalize(value): return ''.join(value.split()).lower().replace('＆','&')

def classify(report):
 values=[normalize(t.get('text','')) for t in report.texts]
 labels={m.get('label') for m in report.knowledge_matches}
 features=report.frame.get('world_features',{})
 def has(word): return any(normalize(word) in v for v in values)
 def result(state,*evidence,map_name=None): return Recognition(state,tuple(evidence),map_name)
 if any(has(w) for w in ('连接失败','登录失败','验证码','购买确认','确认购买')):
  return result(UIState.ERROR,'explicit_error_or_confirmation')
 if has('RANK UP') or features.get('rank_up'): return result(UIState.RANK_UP,'rank_up_title')
 if has('GET!') or 'daily_rewards_get' in labels or features.get('reward'):
  return result(UIState.REWARD,'reward_overlay')
 if features.get('scratch_ticket'):
  return result(UIState.SCRATCH_TICKET,'scratch_open_label','pink_ticket_surface')
 if features.get('notification_panel'):
  return result(UIState.NOTIFICATION,'notification_title')
 if features.get('dialogue'):
  return result(UIState.DIALOGUE,'bottom_e_anchor','bottom_next_anchor')
 if features.get('achievement_detail'):
  return result(UIState.ACHIEVEMENT_DETAIL,'rank_header_and_claim_text')
 if features.get('achievement_list'):
  return result(UIState.ACHIEVEMENT_LIST,'achievement_title')
 maps={'entry_map_garden':'协律花园','entry_map_arcade':'电玩巨蛋城','entry_map_bay':'汽水泡泡海湾'}
 map_name=next((n for n in maps.values() if has(n)),None)
 map_name=next((n for label,n in maps.items() if label in labels),map_name)
 is_map=features.get('map') or bool(set(maps)&labels) or (has('MAP') and map_name is not None) or bool(labels & {'entry_detail_greed','entry_lever_detail'} and 'entry_move' in labels)
 if is_map:
  if ('entry_detail_greed' in labels or 'entry_lever_detail' in labels or has('移动')):
   return result(UIState.LOCATION_DETAIL,'map_title','detail_content',map_name=map_name)
  return result(UIState.MAP,'map_title',map_name=map_name)
 if {'entry_ready_logo','entry_ready_start'}<=labels or (has('High&Low') and has('押注并开始游戏')):
  return result(UIState.GREED_READY,'greed_logo_and_start')
 if has('High&Low') and (has('替换') or has('猜高') or has('猜低')):
  return result(UIState.GREED_PLAY,'greed_play_controls')
 if any(has(w) for w in ('Cruising','移动中','加载中','loading','connecting','downloading')):
  return result(UIState.LOADING,'loading_indicator')
 if 'entry_dialogue' in labels or (has('Shiori') and has('为了抓住机会')):
  return result(UIState.DIALOGUE,'known_shiori_dialogue')
 if features.get('gift_prompt'):
  return result(UIState.INTERACTION,'gift_label','nearby_e_key')
 if features.get('wheel_prompt'):
  return result(UIState.INTERACTION,'scratch_ticket_label','nearby_e_key')
 if features.get('options') or 'entry_to_game' in labels or has('切换为赌场区') or has('切换为游戏区'):
  return result(UIState.OPTIONS,'lever_options')
 if labels & {'entry_interact','entry_lever_interact'} or any(normalize(t.get('text','')) in ('猜高低','切换操纵杆') for t in report.texts):
  return result(UIState.INTERACTION,'interaction_prompt')
 if features.get('hud_count',0)>=3 or sum(has(s) for s in ('活动','游戏','演出','任务','成就','扭蛋'))>=4 or len(labels&{'menu','stage','task'})>=2:
  return result(UIState.WORLD,'hud_combination')
 return result(UIState.UNKNOWN,'insufficient_evidence')
