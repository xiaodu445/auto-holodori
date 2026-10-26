"""Manual read-only vision benchmark. No model requests or input injection."""
import json
from pathlib import Path
import statistics
import time
from modular_agent.agent.launcher import GameLauncher
from modular_agent.perception import GeneralVision, KnowledgeMatcher

root=Path(__file__).resolve().parents[1]
profile=json.loads((root/'domains'/'hololive_dreams'/'launch.json').read_text(encoding='utf-8'))
vision=GeneralVision.for_project(root,'hololive_dreams')
try:
    started=time.perf_counter()
    vision.warmup(lambda text:print(text,flush=True))
    warmup_ms=(time.perf_counter()-started)*1000
    windows=vision.desktop.windows()
    game=GameLauncher(vision,None,profile)._window(windows)
    handle=game['handle'] if game and not game.get('minimized') else None
    results={}
    policies={
        'full':{'enable_ocr':True,'enable_uia':True,'enable_cv_buttons':True,'ocr_max_side':1600},
        'balanced':{'enable_ocr':True,'enable_uia':False,'enable_cv_buttons':False,'ocr_max_side':960},
        'icons':{'enable_ocr':False,'enable_uia':False,'enable_cv_buttons':False}}
    for mode,options in policies.items():
        vision.knowledge.scales=tuple(profile['template_scales']) if mode=='full' else (1.0,)
        measurements=[]
        for _ in range(3):
            started=time.perf_counter()
            report=vision.observe(monitor=0,environment='hololive_dreams',window_handle=handle,**options)
            measurements.append({'total_ms':round((time.perf_counter()-started)*1000,2),'stages_ms':report.timings_ms,'warnings':report.warnings})
        results[mode]={'median_ms':round(statistics.median(m['total_ms'] for m in measurements),2),'samples':measurements}
        print(mode,results[mode]['median_ms'],'ms',flush=True)
    result={'warmup_ms':round(warmup_ms,2),'target':'game_window' if handle else 'desktop','game_foreground':game.get('foreground') if game else None,'uia_worker_pid':vision.desktop.uia.process.pid if vision.desktop.uia.process else None,'template_count':sum(len(l.records()) for l in vision.knowledge.libraries),'measurements':results,'note':'Read-only current visible desktop, 3 fresh captures per mode; full warmed, not old cold-process baseline; game-template count may be small.'}
    (root/'runtime'/'vision-benchmark.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='measurements'},ensure_ascii=False),flush=True)
finally: vision.close()
