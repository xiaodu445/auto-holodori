import unittest
from modular_agent.agent.daily_tasks import DailyTasks
from test_daily_tasks import report,Computer
from test_daily_planning import config

class HoloHomeRouteTests(unittest.TestCase):
 def run_route(self,frames):
  c=Computer();it=iter(frames)
  tree=DailyTasks(config(),lambda:next(it),c,lambda _:None,clock=lambda:c.seconds)
  tree.gift('holo_home')
  return [a.arguments for a in c.actions if a.name=='press']
 def gift(self):
  r=report('menu','stage');r.frame['world_features']={'gift_prompt':True,'hud_count':3};return r
 def test_config_w_then_short_d(self):
  self.assertEqual(config()['holo_home_route'],[{'key':'w','seconds':2.5},{'key':'d','seconds':.3}])
 def test_walk_w_then_d_then_interact(self):
  free=report('menu','stage')
  actions=self.run_route([free]*5+[self.gift(),report('daily_rewards_get')]+[free]*3)
  self.assertEqual(actions,[{'key':'w','duration':2.5},{'key':'d','duration':.3},{'key':'e','duration':.08}])
 def test_skip_d_if_gift_already_visible_after_w(self):
  free=report('menu','stage')
  actions=self.run_route([free]*4+[self.gift()]*2+[report('daily_rewards_get')]+[free]*3)
  self.assertEqual(actions,[{'key':'w','duration':2.5},{'key':'e','duration':.08}])

if __name__=='__main__':unittest.main()
