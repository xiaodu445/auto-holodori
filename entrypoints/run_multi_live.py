"""Run a bounded Hololive Dreams MULTI session. Default: print plan only."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
import time
import os

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


class SessionLock:
    def __init__(self,path):self.path=path;self.file=None
    def __enter__(self):
        import msvcrt
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+b');self.file.seek(0);self.file.write(b'0');self.file.flush();self.file.seek(0)
        try:msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            self.file.close();raise RuntimeError('另一个多人循环脚本正在运行')
        return self
    def __exit__(self,*args):
        import msvcrt
        self.file.seek(0);msvcrt.locking(self.file.fileno(),msvcrt.LK_UNLCK,1);self.file.close()


def focus_game_on_start(backend,computer,handle,*,wait,check,emit=lambda *a,**k:None):
    """Restore/activate the selected game and await verified focus before capture.

    Only used once at session startup. Runtime capture retains its existing
    foreground guard and never steals focus back after the user switches away.
    """
    from modular_agent.core import Action,Outcome
    if not computer.live:raise RuntimeError('startup_focus_requires_live')
    for attempt in range(3):
        check()
        current=next((w for w in backend.windows() if w.get('handle')==handle),None)
        if not current or current.get('title','').lower()!='hololive-dreams':
            raise RuntimeError('startup_game_window_disappeared')
        if not current.get('foreground') or current.get('minimized'):
            check()
            result=computer.perform(Action('focus',arguments={'handle':handle}))
            emit('startup_focus_attempt',attempt=attempt+1,outcome=result.outcome.value)
            # Windows activation can complete asynchronously even if the initial
            # API reports failure. Observe the same handle before deciding.
        stable=0
        for _ in range(10):
            check()
            current=next((w for w in backend.windows() if w.get('handle')==handle),None)
            if not current or current.get('title','').lower()!='hololive-dreams':
                raise RuntimeError('startup_game_window_disappeared')
            stable=stable+1 if current.get('foreground') and not current.get('minimized') else 0
            if stable>=2:
                emit('startup_focus_verified',handle=handle)
                return
            wait(.1)
    raise RuntimeError('startup_focus_failed: Windows未允许切换到游戏前台；未开始识别或游戏输入')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rounds',type=int,required=True,help='目标完成局数，1..1000')
    parser.add_argument('--offset',type=float)
    parser.add_argument('--grid-snap',type=float)
    parser.add_argument('--window-width',type=int,default=0)
    parser.add_argument('--window-height',type=int,default=0)
    parser.add_argument('--stop-file',type=Path)
    parser.add_argument('--result-file',type=Path,help='Write the existing structured session result')
    parser.add_argument('--live',action='store_true',help='显式允许菜单及打歌输入')
    parser.add_argument('--recognition-preview',action='store_true',help='显示已有游戏采集画面和识别状态；不额外采集')
    parser.add_argument('--single-song',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--timeout',type=float,default=0,help='会话总时长上限（秒），0=不限，默认按局数运行')
    parser.add_argument('--song-timeout',type=float,default=1800,help='单曲安全上限（秒）')
    parser.add_argument('--matching-timeout',type=float,default=600)
    parser.add_argument('--config',type=Path,help='可选现有音游JSON配置；只读取')
    parser.add_argument('--rhythm-profile',choices=('mechanism','tuning','config'),
                        help='默认沿用机关关闭实验入口；显式config时默认仅使用该JSON')
    parser.add_argument('--inspect-image',type=Path,help='离线识别归档截图；不运行游戏')
    args=parser.parse_args(argv)
    if args.offset is not None and (not math.isfinite(args.offset) or not -500<=args.offset<=500):parser.error('offset: -500..500 ms')
    if args.grid_snap is not None and (not math.isfinite(args.grid_snap) or not 0<=args.grid_snap<=25):parser.error('grid-snap: 0..25 ms')
    if (args.window_width,args.window_height)!=(0,0) and not (640<=args.window_width<=7680 and 400<=args.window_height<=4320):parser.error('window size: 640..7680 x 400..4320; or both zero')
    if not 1<=args.rounds<=1000:parser.error('rounds must be 1..1000')
    if not math.isfinite(args.timeout) or args.timeout<0:parser.error('timeout must be finite and nonnegative; 0=unlimited')
    if any(not math.isfinite(v) or v<=0 for v in (args.song_timeout,args.matching_timeout)):
        parser.error('timeouts must be finite and positive')
    if args.config and not args.config.is_file():parser.error('config does not exist')
    if args.inspect_image and args.live:parser.error('inspect-image cannot be combined with live')
    from modular_agent.domains.hololive_dreams.rhythm_profile import load_profile
    profile=args.rhythm_profile or ('config' if args.config else 'mechanism')
    try:overrides,profile_sources=load_profile(ROOT,profile)
    except (OSError,ValueError) as error:parser.error(str(error))
    if args.offset is not None:overrides['input_offset_ms']=args.offset
    if args.grid_snap is not None:overrides['grid_snap_ms']=args.grid_snap
    from modular_agent.domains.hololive_dreams.multi_live_vision import LiveVision
    vision=LiveVision(ROOT)
    if args.inspect_image:
        import cv2
        import numpy as np
        image=cv2.imdecode(np.fromfile(args.inspect_image,dtype=np.uint8),cv2.IMREAD_COLOR)
        if image is None:parser.error('cannot read image')
        # Archived user screenshots include a 38px title bar.
        if image.shape[:2]==(747,1261) or image.shape[:2]==(747,1260):image=image[38:747,:1260]
        frame=vision.detect(image)
        print(json.dumps(frame.__dict__,ensure_ascii=False,indent=2));return 0
    if not args.live:
        print(json.dumps({'mode':'plan_only','rounds':args.rounds,'timeout':args.timeout,
            'route':['演出','MULTI','GRADE','等人（零点击）','Pickup','沿用当前设置决定','现有打歌引擎',
                     '确认结算并停止引擎','多层奖励','未达局数：玩同一个游戏；达标：停在续玩页'],
            'live':False,'rhythm_profile':profile,'profile_sources':profile_sources,
            'rhythm_overrides':overrides},ensure_ascii=False,indent=2));return 0
    from modular_agent.computer import ActionComputer
    from modular_agent.computer.windows import WindowsBackend
    from modular_agent.core import Action,Outcome
    from modular_agent.realtime.runtime import WindowCapture
    from modular_agent.domains.hololive_dreams.multi_live import MultiLiveSession,run_song
    from modular_agent.domains.hololive_dreams.rhythm_journal import RhythmJournal,cleanup_old_rhythm_logs
    import importlib.util
    spec=importlib.util.spec_from_file_location('multi_live_engine',ROOT/'domains/hololive_dreams/models/rhythm/rhythm_game.py')
    engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
    config=engine.load_config(ROOT,args.config)
    config.update(overrides)
    if list(config.get('roi',[]))!=[0,0,1,1]:parser.error('多人曲终监测要求现有音游配置 roi=[0,0,1,1]，脚本不会修改配置')
    backend=WindowsBackend()
    windows=[w for w in backend.windows() if w['title'].lower()=='hololive-dreams']
    if len(windows)!=1:parser.error('请打开且只打开一个 hololive-Dreams 游戏窗口')
    handle=windows[0]['handle']
    data_root=Path(os.environ.get('HOLOLIVE_DATA_DIR',str(ROOT)))
    journal=RhythmJournal(data_root)
    (journal.directory/'rhythm-log-policy.json').write_text(json.dumps({'kind':'hololive-rhythm','retention_days':7,'keep_runs':3,'event_file_bytes':journal.max_bytes,'event_files':3,'screenshot_songs':3}),encoding='utf-8')
    journal('rhythm_settings',profile=profile,sources=profile_sources,config_path=str(args.config) if args.config else None,
            settings=config,overrides=overrides)
    print('运行日志：'+str(journal.directory),flush=True)
    print('打歌参数来源：'+profile+' '+', '.join(profile_sources),flush=True)
    print('有效参数：'+json.dumps(config,ensure_ascii=False,sort_keys=True),flush=True)
    print('启动后自动将游戏切到前台。F12停止；达到目标局数后停在续玩选择页。',flush=True)
    with SessionLock(data_root/'runtime/multi-live/session.lock'),ActionComputer(live=True,audit_path=journal.directory/'inputs.jsonl') as computer:
        cleanup=cleanup_old_rhythm_logs(data_root/'runtime/daily-tasks')
        journal('old_log_cleanup',**cleanup)
        print('日志精简已启用；本次清理过期打歌日志 '+str(cleanup['removed'])+' 份（保留至少最近3次及7天内记录）。',flush=True)
        deadline=time.monotonic()+args.timeout if args.timeout else math.inf
        capture=None;session=None;last_bounds=None;last_image=None
        recognition_preview=None
        if args.recognition_preview:
            try:
                from modular_agent.domains.hololive_dreams.recognition_preview import RecognitionPreview
                recognition_preview=RecognitionPreview(config)
            except Exception as error:print('识别窗口启动失败（循环仍可运行）：'+str(error),flush=True)
        def check():
            if computer.stopped or backend.emergency_pressed() or (args.stop_file and args.stop_file.exists()):raise RuntimeError('cancelled')
            if time.monotonic()>=deadline:raise RuntimeError('session_timeout')
        def wait(seconds):
            end=time.monotonic()+seconds
            while time.monotonic()<end:
                check();time.sleep(min(.05,max(0,end-time.monotonic())))
        def observe(ocr=False):
            nonlocal capture,last_bounds,last_image
            check()
            if capture is None:capture=WindowCapture(handle)
            image,bounds=capture.grab([0,0,1,1]);last_bounds=bounds;last_image=image
            frame=vision.detect(image,bounds,ocr=ocr)
            if recognition_preview:recognition_preview.publish(image,bounds,{'gate_state':frame.state,'gate_ready':False})
            return frame
        def click(target):
            check()
            if capture is None or capture.bounds()!=last_bounds:raise RuntimeError('window_changed_before_menu_input')
            b=target['bounds'];x=b['x']+b['width']//2;y=b['y']+b['height']//2
            bx,by,bw,bh=last_bounds
            if not (bx<=x<bx+bw and by<=y<by+bh):raise RuntimeError('target_outside_game')
            if target.get('label') in ('决定成员','确认成员'):raise RuntimeError('forbidden_member_confirmation')
            result=computer.perform(Action('click',arguments={'x':x,'y':y,'modifiers':['alt']}))
            if result.outcome!=Outcome.SUCCESS:raise RuntimeError(result.message)
        def play(wait_for_start=False):
            nonlocal capture
            check();computer.release_all()
            if computer.keys or computer.buttons:raise RuntimeError('menu_inputs_not_released')
            if capture:capture.close();capture=None
            song_result=run_song(ROOT,handle,vision,engine=engine,config_path=args.config,overrides=overrides,
                wait_for_start=wait_for_start,emit=journal,
                recognition_preview=recognition_preview,
                diagnostic_dir=journal.song_directory('song-diagnostic-'+str(session.completed+1)+'-'+str(time.time_ns())),
                timeout=min(args.song_timeout,max(.01,deadline-time.monotonic())),
                cancelled=lambda:computer.stopped or backend.emergency_pressed() or bool(args.stop_file and args.stop_file.exists()),progress=lambda t:print(t,flush=True))
            if song_result.get('reason')=='song_timeout' and time.monotonic()>=deadline:
                song_result={**song_result,'reason':'session_timeout'}
            return song_result
        try:
            session=MultiLiveSession(rounds=args.rounds,observe=observe,click=click,play=play,wait=wait,check=check,
                emit=journal,timeout=args.timeout,matching_timeout=args.matching_timeout)
            try:
                focus_game_on_start(backend,computer,handle,wait=wait,check=check,emit=journal)
                if args.window_width and not args.single_song:
                    check()
                    resized=backend.resize_window(handle,args.window_width,args.window_height)
                    journal('startup_resize',result=resized)
                    wait(.5)
                if args.single_song:
                    song=play(wait_for_start=True)
                    complete=song.get('reason')=='settlement_observed' and song.get('scheduler_stopped') and not song.get('cleanup_error')
                    if complete:session.completed=1
                    result=session.result('success' if complete else 'unknown','single_song:'+str(song.get('reason')))
                else:result=session.run()
            except Exception as error:
                result=session.result('unknown',type(error).__name__+': '+str(error))
            if result['outcome']!='success' and last_image is not None:
                import cv2
                cv2.imencode('.png',last_image)[1].tofile(journal.directory/'stopped-frame.png')
            journal.finish(result);print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
            if args.result_file:
                args.result_file.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            return 0 if result['outcome']=='success' else 2
        finally:
            if capture:capture.close()
            computer.release_all()
            if recognition_preview:recognition_preview.close()


if __name__=='__main__':raise SystemExit(main())
