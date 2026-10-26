import os,sys,runpy,json,importlib.util
from pathlib import Path
BASE=Path(__file__).resolve().parent
runtime=BASE/'runtime'
handles=[os.add_dll_directory(str(p)) for p in [runtime/'natives',runtime/'Lib/site-packages/numpy.libs'] if p.exists()]
os.environ['TCL_LIBRARY']=str(runtime/'tcl/tcl8.6');os.environ['TK_LIBRARY']=str(runtime/'tcl/tk8.6')
os.environ['OPENBLAS_NUM_THREADS']='1'
sys.path.insert(0,str(BASE/'app/src'))
try:
    if '--self-test' in sys.argv:
        import subprocess
        clean={k:v for k,v in os.environ.items() if not k.upper().startswith(('PYTHON','CONDA','VIRTUAL_ENV'))}
        clean['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
        for executable in ('python.exe','pythonw.exe'):
            report_path=BASE/('native-probe-'+Path(executable).stem+'.json')
            report_path.unlink(missing_ok=True)
            child=subprocess.run([str(runtime/executable),'-I','-X','utf8',str(BASE/'runtime_probe.py')],cwd=os.environ['SystemRoot'],env=clean,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=60)
            print(child.stdout,flush=True)
            if child.returncode:raise RuntimeError(child.stderr)
            report=json.loads(report_path.read_text(encoding='utf-8'))
            assert not report['external_modules'] and report['isolated']==1
            print('NATIVE_PROBE_OK '+executable,flush=True)
        import cv2,numpy,mss,dxcam,comtypes
        check_cleanup=runpy.run_path(str(BASE/'capture_cleanup_probe.py'))['check_cleanup']
        print('CAPTURE_CLEANUP_OK '+json.dumps(check_cleanup()),flush=True)
        from types import SimpleNamespace
        from modular_agent.domains.hololive_dreams.song_diagnostics import SongDiagnostics
        from modular_agent.domains.hololive_dreams.multi_live import StartGateCapture
        probe=SongDiagnostics();ticks=iter((0.,.04,.08))
        pixels=numpy.zeros((18,32,3),numpy.uint8)
        source=SimpleNamespace(stats={},bounds=lambda:(0,0,32,18),grab=lambda roi:(pixels,(0,0,32,18)))
        recognizer=SimpleNamespace(detect=lambda *a:SimpleNamespace(state='unknown',targets={}),gameplay_hud=lambda image:True)
        gate=StartGateCapture(source,recognizer,clock=lambda:next(ticks),diagnostic=probe)
        assert gate.grab((0,0,1,1))[0] is None
        assert gate.grab((0,0,1,1))[0] is pixels
        assert probe.snapshot()['gate_ready'] and probe.snapshot()['captured_frames']==2
        print('SONG_DIAGNOSTICS_OK',flush=True)
        from modular_agent.domains.hololive_dreams.recognition_preview import render_recognition
        rendered=render_recognition(pixels,{'notes':[]},{'gate_ready':False},{},0.)
        assert rendered.shape[0]>pixels.shape[0] and not pixels.any()
        print('RECOGNITION_PREVIEW_OK',flush=True)
        from modular_agent.realtime.dxgi_selection import enumerate_outputs,select_output
        inventory=enumerate_outputs(dxcam)
        print('DXGI_OUTPUT_INVENTORY '+json.dumps(inventory),flush=True)
        fake_camera=SimpleNamespace(width=32,height=18,grab=lambda **kwargs:pixels)
        fake_module=SimpleNamespace(create=lambda **kwargs:fake_camera)
        fake_guard=SimpleNamespace(bounds=lambda:(0,0,32,18))
        selected=select_output(fake_guard,fake_module,lambda camera:None,inventory=[dict(device_idx=1,output_idx=0,name='offline',attached=True,left=0,top=0,width=32,height=18)])
        assert selected[0] is fake_camera and selected[2][0]['result']=='verified_frame'
        print('DXGI_SELECTION_OK',flush=True)
        import contextlib,io
        cli_spec=importlib.util.spec_from_file_location('release_session_cli',BASE/'app/tools/run_multi_live.py')
        cli=importlib.util.module_from_spec(cli_spec);cli_spec.loader.exec_module(cli)
        plan=io.StringIO()
        with contextlib.redirect_stdout(plan):assert cli.main(['--rounds','999'])==0
        assert json.loads(plan.getvalue())['timeout']==0
        print('UNLIMITED_SESSION_OK',flush=True)
        import tempfile
        from modular_agent.domains.hololive_dreams.rhythm_journal import RhythmJournal
        with tempfile.TemporaryDirectory(prefix='compact-probe-',dir=BASE) as temporary:
            journal=RhythmJournal(temporary)
            probe=SongDiagnostics(emit=journal,directory=journal.song_directory('song-diagnostic-1-1'))
            probe.finish({'reason':'cancelled','rows':['x'*1000000],'frames':10})
            assert (journal.directory/'events.jsonl').stat().st_size<10000
            assert 'rows' not in json.loads((probe.directory/'summary.json').read_text())['result']
        print('COMPACT_LOGGING_OK',flush=True)
        from rapidocr_onnxruntime import RapidOCR
        ocr=RapidOCR()
        from modular_agent.domains.hololive_dreams.multi_live_vision import LiveVision
        vision=LiveVision(BASE/'app')
        from modular_agent.domains.hololive_dreams.visual_features import references
        assert references(str(BASE/'app'))
        path=BASE/'app/domains/hololive_dreams/models/rhythm_game.py'
        spec=importlib.util.spec_from_file_location('rhythm_release_self_test',path)
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        print(json.dumps({'runtime':'ok','ocr_models':'ok','vision_templates':len(vision.templates),'engine_import':'ok','game_input':False}),flush=True)
    runpy.run_path(str(BASE/'app/gui/release_gui.py'),run_name='__main__')
except BaseException:
    import traceback
    DATA=Path(os.environ.get('LOCALAPPDATA',BASE))/'HololiveRhythm';DATA.mkdir(parents=True,exist_ok=True)
    (DATA/'bootstrap-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
    raise
