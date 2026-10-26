"""Sequential GPU comparisons; the new user-selected video is excluded."""
import json,os,subprocess,sys,time,traceback
from pathlib import Path
from prepare import ROOT,prepare
from train import publish_progress
from modular_agent.realtime.kitchen_labels import atomic_json


def main():
    report,data=prepare()
    if not report['ready']:raise RuntimeError('existing labels not ready')
    folder=ROOT/'learning/kitchen_yolo/runs/native-comparison-20261022';folder.mkdir(parents=True,exist_ok=False)
    jobs=[dict(model='m',run=folder/'medium-native'),dict(model='x',run=folder/'xlarge-native')]
    status=folder/'progress.json';start=time.perf_counter();results=[]
    def publish(**kwargs):
        payload=dict(epochs=80,epoch=0,percent=0,elapsed_seconds=time.perf_counter()-start,run_dir=str(folder));payload.update(kwargs)
        publish_progress(status,payload)
        publish_progress(ROOT/'learning/kitchen_yolo/latest-run.json',dict(run_dir=str(folder),pid=os.getpid(),status_file=str(status)))
    atomic_json(folder/'comparison-plan.json',dict(data=str(data),jobs=[dict(model=j['model'],run=str(j['run'])) for j in jobs],protocol='80 epochs; no augmentation; native pixels padded736; same seed/split/batch2/nbs2; fresh pretrained; new recording excluded'))
    publish(phase='preparing',label='原生输入 M / X 对比')
    subprocess.Popen([str(ROOT/'.conda/pythonw.exe'),str(Path(__file__).with_name('progress.py')),'--status',str(status)],creationflags=0x08000000)
    try:
        for position,job in enumerate(jobs):
            command=[sys.executable,str(Path(__file__).with_name('train.py')),'--model-size',job['model'],'--data',str(data),'--run-dir',str(job['run']),'--diagnostic','--epochs','80','--batch','2','--no-progress-window']
            with (folder/f'{job["model"]}-train.log').open('w',encoding='utf-8') as log:
                process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONIOENCODING':'utf-8'})
                while process.poll() is None:
                    state={}
                    try:state=json.loads((job['run']/'progress.json').read_text(encoding='utf-8'))
                    except (OSError,ValueError):pass
                    payload=dict(state);payload.pop('run_dir',None);payload.pop('elapsed_seconds',None)
                    payload.update(label=f'{position+1}/2 YOLO26{job["model"]} 原生736',percent=50*(position+state.get('percent',0)/100))
                    publish(**payload);time.sleep(1)
                if process.returncode:raise RuntimeError(f'{job["model"]} training failed; see {log.name}')
            state=json.loads((job['run']/'progress.json').read_text(encoding='utf-8'))
            results.append(dict(model=job['model'],run=str(job['run']),metrics=state.get('metrics',{}),optimizer_steps=state.get('optimizer_steps'),input_size=state.get('input_size')))
            with (folder/f'{job["model"]}-review.log').open('w',encoding='utf-8') as log:
                subprocess.run([sys.executable,str(Path(__file__).with_name('review_native.py')),'--run-dir',str(job['run']),'--data',str(data)],stdout=log,stderr=subprocess.STDOUT,check=True)
            atomic_json(folder/'comparison.json',dict(scope='same-session diagnostic holdout; no independent generalization claim',results=results))
        publish(phase='completed',label='M / X 原生输入对比完成',percent=100,epoch=80,metrics=results[-1]['metrics'])
    except BaseException as error:
        (folder/'error.txt').write_text(traceback.format_exc(),encoding='utf-8');publish(phase='failed',error=str(error),label='原生输入对比失败');raise


if __name__=='__main__':main()
