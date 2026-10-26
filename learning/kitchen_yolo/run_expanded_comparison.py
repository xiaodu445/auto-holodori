"""Mild augmentation versus no-augmentation on the identical frozen dataset."""
import os,sys,subprocess,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
run=ROOT/'learning/kitchen_yolo/runs/x-expanded-20261022'
data=ROOT/'learning/kitchen_yolo/datasets/combined-457d15abe170/data.yaml'
os.environ.setdefault('MPLCONFIGDIR',str(ROOT/'runtime/kitchen/matplotlib-cache'))
commands=[
 [sys.executable,str(Path(__file__).with_name('train.py')),'--model-size','x','--data',str(data),'--run-dir',str(run),'--diagnostic','--mild-augment','--epochs','150','--batch','2'],
 [sys.executable,str(Path(__file__).with_name('review_combined.py')),'--data',str(data),'--run',str(run),'--old',str(ROOT/'learning/kitchen_yolo/runs/x-mild-20261022/weights/best.pt')]
]
for i,cmd in enumerate(commands):
 with (run.parent/f'{run.name}-stage{i+1}.log').open('w',encoding='utf-8') as log:
  subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True,cwd=str(ROOT))
