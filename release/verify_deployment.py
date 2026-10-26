"""Offline EXE deployment verification; never opens/captures/controls the game."""
from pathlib import Path
import os,sys,subprocess,json,hashlib,time
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'release/output/HololiveRhythm-1.0.8'
info=json.loads((OUT/'build-info.json').read_text())
exe=Path(info['exe'])
cache=ROOT/'release'/('部署验证 中文 空格 '+info['payload_sha256'][:8])
env={k:v for k,v in os.environ.items() if not k.upper().startswith(('PYTHON','CONDA','VIRTUAL_ENV'))}
env['PATH']=str(Path(os.environ['SystemRoot'])/'System32')
# Poison values must be stripped by the launcher, not just absent on this host.
env['PYTHONHOME']=r'Z:\nonexistent-python';env['PYTHONPATH']=r'Z:\nonexistent-site'
results=[]
for mode in ('cold','warm'):
    started=time.monotonic()
    result=subprocess.run([str(exe),'--self-test','--cache-root',str(cache)],cwd=os.environ['SystemRoot'],env=env,timeout=120)
    output=(cache/'self-test.txt').read_text(encoding='utf-8-sig')
    assert result.returncode==0,(mode,result.returncode,output)
    assert 'NATIVE_PROBE_OK python.exe' in output and 'NATIVE_PROBE_OK pythonw.exe' in output
    assert 'GUI_SELF_TEST_OK' in output and '"ocr_models": "ok"' in output
    assert 'CAPTURE_CLEANUP_OK' in output
    assert 'SONG_DIAGNOSTICS_OK' in output
    assert 'RECOGNITION_PREVIEW_OK' in output
    assert 'DXGI_SELECTION_OK' in output
    assert 'UNLIMITED_SESSION_OK' in output
    assert 'COMPACT_LOGGING_OK' in output
    results.append({'mode':mode,'exit_code':result.returncode,'seconds':round(time.monotonic()-started,2)})
target=cache/info['payload_sha256'][:16]
probes={name:json.loads((target/('native-probe-'+name+'.json')).read_text(encoding='utf-8')) for name in ('python','pythonw')}
native=json.loads((target/'native-dependencies.json').read_text())
assert native['missing']==[]
metadata=json.loads((target/'runtime/distribution-metadata.json').read_text())
assert metadata['dxcam']=='0.3.0'
unchanged={}
old=ROOT/'release/build/rhythm-1.0.0/app'
for name in ['gui/release_gui.py','tools/run_multi_live.py','domains/hololive_dreams/models/rhythm/rhythm_game.py','domains/hololive_dreams/models/rhythm/rhythm_game_config.json','src/modular_agent/domains/hololive_dreams/multi_live.py','src/modular_agent/domains/hololive_dreams/multi_live_vision.py']:
    unchanged[name]=hashlib.sha256((old/name).read_bytes()).hexdigest()==hashlib.sha256((target/'app'/name).read_bytes()).hexdigest()
assert all(unchanged[name] for name in unchanged if name not in ('gui/release_gui.py','tools/run_multi_live.py','src/modular_agent/domains/hololive_dreams/multi_live.py')),unchanged
name='src/modular_agent/realtime/rhythm_capture.py'
unchanged[name]=hashlib.sha256((old/name).read_bytes()).hexdigest()==hashlib.sha256((target/'app'/name).read_bytes()).hexdigest()
# Capture selection intentionally changed; note engine/config/vision stay fixed.
report={'build':info,'exe_mib':round(exe.stat().st_size/1024**2,2),'runs':results,'native_graph_scanned':native['scanned'],'missing':native['missing'],'native_probes':probes,'unchanged_features':unchanged,'clean_path':True,'poisoned_python_environment':True,'neutral_working_directory':True,'unicode_cache_path':True,'another_clean_windows_machine_tested':False,'gameplay_tested':False}
report.update(capture_cleanup_probe=True,distribution_metadata=metadata)
(OUT/'deployment-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='native_probes'},ensure_ascii=False,indent=2))
