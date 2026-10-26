"""Local game launcher: visual evidence -> input -> window verification."""
from __future__ import annotations
import json
from pathlib import Path
import re
import time
from modular_agent.core import Action, Outcome

class GameLauncher:
    def __init__(self,vision,computer,config,*,clock=time.monotonic,sleep=time.sleep):
        self.vision=vision
        self.computer=computer
        self.config=config
        self.clock=clock
        self.sleep=sleep
        self.patterns=[re.compile(p,re.I) for p in config['window_title_patterns']]

    def _window(self,windows):
        # Do not treat browser documentation or an open terminal title as the game.
        excluded=('chrome','edge','firefox','powershell','cmd.exe','windowsterminal','codex','explorer.exe','openconsole','conhost')
        candidates=[]
        for window in windows:
            title=window.get('title','')
            process=(window.get('process_name') or '').lower()
            if any(p in process for p in excluded): continue
            if any(pattern.search(title) for pattern in self.patterns): candidates.append(window)
        def priority(window):
            b=window.get('bounds',{})
            return (window.get('class_name')=='UnityWndClass',b.get('width',0)*b.get('height',0))
        return max(candidates,key=priority) if candidates else None

    def _action(self,name,arguments=None):
        result=self.computer.perform(Action(name,arguments=arguments or {}))
        if result.outcome!=Outcome.SUCCESS: raise RuntimeError(result.message)
        return result

    def _focus_verified(self,window):
        # Activation can settle asynchronously. Verify the same handle after a bounded wait.
        for attempt in range(3):
            if getattr(self.computer,'stopped',False): raise RuntimeError('用户停止窗口切换')
            try: self._action('focus',{'handle':window['handle']})
            except RuntimeError: pass
            for _ in range(4):
                current=self._window(self.vision.desktop.windows())
                if not current or current['handle']!=window['handle']:
                    raise RuntimeError('切换焦点时游戏窗口消失或改变')
                if current.get('foreground') and not current.get('minimized'):
                    return current
                self._action('wait',{'duration':.1})
        raise RuntimeError('尝试切换并等待后，游戏仍未处于前台；请手动切回游戏。')

    def run(self,goal,progress=lambda message:None):
        live=self.computer.live
        if not live:
            return {'outcome':'unknown','verified':False,'message':'当前为模拟模式。使用 --live 才能真正启动游戏。'}
        original_window=None
        succeeded=False
        try:
            self.computer.release_all()
            initial_windows=self.vision.desktop.windows()
            original_window=next((w for w in initial_windows if w.get("foreground")),None)
            window=self._window(initial_windows)
            if window:
                current=self._focus_verified(window)
                current=self._prepare_window(current,progress)
                succeeded=True
                return self._success(current,'已找到游戏窗口并切换到前台。')
            if self.config.get('launch_method')=='steam':
                executable=self.config.get('steam_executable')
                app_id=self.config.get('steam_app_id')
                if not isinstance(executable,str) or not executable or Path(executable).name.lower()!='steam.exe':
                    raise ValueError('需要配置有效的 steam_executable（Steam 客户端路径）。')
                if not isinstance(app_id,str) or not re.fullmatch(r'[1-9][0-9]*',app_id):
                    raise ValueError('需要配置正确的 steam_app_id。')
                progress(f'通过 Steam 启动游戏（AppID {app_id}）……')
                launch_args=self.config.get('steam_launch_arguments',[])
                if not isinstance(launch_args,list) or any(not isinstance(v,str) for v in launch_args): raise ValueError('steam_launch_arguments must be a list of strings')
                self._action('launch',{'executable':executable,'arguments':['-applaunch',app_id,*launch_args]})
            else:
                failure=self._start_icon(progress)
                if failure: return failure
            progress('等待游戏窗口出现……（F12 可停止）')
            deadline=self.clock()+self.config.get('timeout_seconds',60)
            while self.clock()<deadline:
                self._action('wait',{'duration':self.config.get('poll_seconds',1)})
                window=self._window(self.vision.desktop.windows())
                if window:
                    current=self._focus_verified(window)
                    current=self._prepare_window(current,progress)
                    succeeded=True
                    return self._success(current,'游戏窗口已出现并切到前台；尚未验证游戏主菜单或登录界面。')
            return {'outcome':'unknown','verified':False,
                'message':'已发送启动请求，但超时未发现匹配的游戏窗口。请检查 Steam 登录、更新或启动对话框；该结果将反馈给顶层模型继续处理。'}
        except Exception as error:
            return {'outcome':'failure','verified':False,'message':str(error)}
        finally:
            self.computer.release_all()
            if not succeeded and original_window is not None:
                self.computer.perform(Action("focus",arguments={"handle":original_window["handle"]}))

    def _drag_resize(self,window,size,progress):
        current=self._window(self.vision.desktop.windows())
        if not current or current['handle']!=window['handle']: raise RuntimeError('拖动前游戏窗口改变')
        if not current.get('foreground'): current=self._focus_verified(current)
        info=self._action('window_resize_info',{'handle':current['handle']}).data
        b=info['bounds'];grip=info['grip'];area=info['work_area']
        x=grip['x']+size['width']-b['width']
        y=grip['y']+size['height']-b['height']
        if not (area['left']<=x<area['right'] and area['top']<=y<area['bottom']):
            raise RuntimeError('放大目标超出屏幕工作区，请先将游戏窗口移向左上方再运行')
        progress(f"拖动窗口边缘：({grip['x']}, {grip['y']}) → ({x}, {y})；按住 Alt")
        self._action('release_all')
        self._action('move_to',grip)
        self._action('wait',{'duration':.1})
        self._action('drag',{'x':x,'y':y,'duration':.6,'steps':30,'modifiers':['alt']})

    def _prepare_window(self,window,progress):
        size=self.config.get('window_size')
        if size is None: return window
        if not isinstance(size,dict) or set(size)!={'width','height'} or any(type(size[k]) is not int or not 100<=size[k]<=10000 for k in size):
            raise ValueError('window_size requires integer width/height between 100 and 10000')
        def acceptable(bounds):
            return abs(bounds.get('width',0)-size['width'])<=20 and abs(bounds.get('height',0)-size['height'])<=10
        current=self._window(self.vision.desktop.windows())
        if not current: raise RuntimeError('检查尺寸时未找到游戏窗口')
        bounds=current.get('bounds',{})
        if acceptable(bounds):
            if not current.get('foreground') or current.get('minimized'):
                current=self._focus_verified(current)
                bounds=current.get('bounds',{})
            if acceptable(bounds):
                progress(f"窗口尺寸可用：实际 {bounds['width']}×{bounds['height']}，目标约 {size['width']}×{size['height']}，跳过调整。")
                return current
        progress('等待2秒让游戏启动窗口稳定，再调整尺寸……')
        self._action('wait',{'duration':2})
        current=self._window(self.vision.desktop.windows())
        if not current: raise RuntimeError('等待启动后未找到游戏窗口')
        window=current
        if not window.get('foreground') or window.get('minimized'):
            window=self._focus_verified(window)
        progress(f"调整游戏窗口为 {size['width']}×{size['height']}……")
        last_bounds={}
        method=self.config.get('window_resize_method','native')
        if method not in ('native','drag'): raise ValueError('Unknown window_resize_method')
        for attempt in range(3):
            if method=='drag':
                current=self._window(self.vision.desktop.windows())
                if not current or current['handle']!=window['handle']: raise RuntimeError('调整前窗口改变')
                b=current.get('bounds',{})
                if not acceptable(b):
                    try: self._drag_resize(current,size,progress)
                    except (RuntimeError,ValueError) as error:
                        if getattr(self.computer,'stopped',False): raise
                        progress('窗口拖动未完成，保留当前尺寸继续：'+str(error))
                        return self._focus_verified(current)
                resized=None
            else:
                resized=self._action('resize_window',{'handle':window['handle'],**size})
            if resized is not None and resized.data.get('immediate_bounds'):
                b=resized.data['immediate_bounds']
                progress(f"原生调整即时反馈：{b['width']}×{b['height']}")
            stable=0
            for _ in range(10):
                self._action('wait',{'duration':.2})
                current=self._window(self.vision.desktop.windows())
                if not current or current['handle']!=window['handle']: raise RuntimeError('调整尺寸时游戏窗口消失或改变')
                last_bounds=current.get('bounds',{})
                matches=acceptable(last_bounds)
                stable=stable+1 if matches and current.get('foreground') else 0
                if stable>=5:
                    progress(f"窗口尺寸已连续稳定：实际 {last_bounds['width']}×{last_bounds['height']}")
                    return current
            progress(f"尺寸尚未稳定，实际 {last_bounds.get('width')}×{last_bounds.get('height')}；类型 {current.get('class_name','unknown')}；句柄 {current['handle']}；调整尝试 {attempt+1}/3")
        if not last_bounds.get('width') or not last_bounds.get('height'):
            raise RuntimeError('尺寸未达到可核验状态：无法读取实际游戏窗口边界。')
        progress(f"窗口尺寸调整未生效，保留实际 {last_bounds.get('width')}×{last_bounds.get('height')} 继续；目标仅为参考。")
        return self._focus_verified(current)

    def _start_icon(self,progress):
        progress('切换到桌面，寻找启动图标……')
        self._action('show_desktop')
        self._action('wait',{'duration':.4})
        report=self.vision.observe(monitor=0,environment=self.config['domain'])
        if report.capabilities.get('knowledge')!='ok':
            return {'outcome':'failure','verified':False,'message':'视觉知识匹配失败：'+ '; '.join(report.warnings)}
        matches=[m for m in report.knowledge_matches
            if m['label']==self.config['launch_template']
            and m['similarity']>=self.config.get('minimum_similarity',.65)]
        matches.sort(key=lambda m:m['similarity'],reverse=True)
        if not matches:
            return {'outcome':'unknown','verified':False,'message':'没有找到启动图标。请确认图标在桌面可见，且大小/样式与模板相符。'}
        if len(matches)>1 and matches[0]['similarity']-matches[1]['similarity']<.03:
            return {'outcome':'unknown','verified':False,'message':'找到多个相近启动图标，暂不猜测点击；请只保留一个可见图标。'}
        match=matches[0]
        b=match['bounds']; x=b['x']+b['width']//2; y=b['y']+b['height']//2
        progress(f"找到启动图标，相似度 {match['similarity']:.3f}，双击启动……")
        self._action('click',{'x':x,'y':y,'count':2,'interval':.08})
        return None

    @staticmethod
    def _success(window,message):
        return {'outcome':'success','verified':True,'verification':'matching_window_foreground',
            'window':{'handle':window['handle'],'title':window['title'],'pid':window.get('pid')},'message':message}
