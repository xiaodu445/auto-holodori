import json
from pathlib import Path
import time
import numpy as np
import torch
import onnxruntime as ort
from train import PointNet,load_samples
from predict import decode

run=Path(__file__).parent/'runs/baseline-20261022'
config=json.loads((run/'config.json').read_text(encoding='utf-8'))
manifest=Path(__file__).resolve().parents[2]/'runtime/kitchen/manual-labeling/20261021-212928-866150/dataset/manifest.json'
_,samples=load_samples(manifest,config['width'],config['height'],config['class_ids'])
torch.set_num_threads(4)
model=PointNet(len(config['class_ids'])).eval()
model.load_state_dict(torch.load(run/'best.pt',map_location='cpu',weights_only=False)['state_dict'])
options=ort.SessionOptions();options.intra_op_num_threads=4
session=ort.InferenceSession(str(run/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
max_error=[0.,0.];predictions=0
with torch.inference_mode():
 for sample in samples:
  x=sample['x'][None];expected=model(x);actual=session.run(None,{'image':x.numpy()})
  for i in range(2):max_error[i]=max(max_error[i],float(np.max(np.abs(expected[i].numpy()-actual[i]))))
  predictions+=len(decode(actual,config,sample['box']))
assert max_error[0]<.003 and max_error[1]<.0001,max_error
x=samples[0]['x'][None].numpy();timings=[]
for i in range(120):
 start=time.perf_counter();session.run(None,{'image':x});elapsed=(time.perf_counter()-start)*1000
 if i>=20:timings.append(elapsed)
report=dict(real_image_max_abs_error=dict(logits=max_error[0],offset=max_error[1]),onnx_training_predictions=predictions,
 cpu_onnx_threads=4,measurements=100,warmup=20,inference_only_ms=dict(p50=float(np.median(timings)),p95=float(np.percentile(timings,95))),
 onnx_bytes=(run/'model.onnx').stat().st_size,notes='CPU inference only; excludes screen capture, preprocessing, decoding, mouse input and waits.')
(run/'runtime-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
