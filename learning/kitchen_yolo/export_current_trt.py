"""Build a local FP16 engine preserving the current predictor's detection branch."""
import os,json,time,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.environ['YOLO_CONFIG_DIR']=str(ROOT/'learning/kitchen_points/ultralytics-config')
os.environ['MPLCONFIGDIR']=str(ROOT/'runtime/kitchen/matplotlib-cache')
import torch,tensorrt,ultralytics
from ultralytics import YOLO
profile=json.loads((ROOT/'data/kitchen/runtime-profile.json').read_text(encoding='utf-8'))
source=ROOT/profile['weights'];folder=ROOT/'learning/kitchen_yolo/engines/confusions-20261024-736-fp16';folder.mkdir(parents=True,exist_ok=True)
copy=folder/'kitchen.pt';shutil.copy2(source,copy);start=time.perf_counter()
engine=YOLO(str(copy),task='pose').export(format='engine',imgsz=736,batch=1,quantize=16,device=0,workspace=1,dynamic=False,nms=None,simplify=False)
report=dict(source=str(source.relative_to(ROOT)),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),engine=str(Path(engine).relative_to(ROOT)),gpu=torch.cuda.get_device_name(0),torch=torch.__version__,tensorrt=tensorrt.__version__,ultralytics=ultralytics.__version__,input_size=736,precision='FP16',nms=None,branch='one-to-many plus external NMS, identical to current predict default',seconds=time.perf_counter()-start)
(folder/'export.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report),flush=True)
