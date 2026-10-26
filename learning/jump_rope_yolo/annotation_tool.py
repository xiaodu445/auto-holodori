"""Build a self-contained annotation page from selected frames of any recording."""
import argparse,base64,hashlib,json
from pathlib import Path
import cv2,numpy as np
HERE=Path(__file__).parent

def url(image,ext='.png'):
 ok,raw=cv2.imencode(ext,image)
 if not ok:raise RuntimeError('Image encoding failed')
 return 'data:image/'+('jpeg' if ext=='.jpg' else 'png')+';base64,'+base64.b64encode(raw).decode()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--video',type=Path,required=True);p.add_argument('--frames',required=True,help='Comma-separated frame indices, e.g. 600,601,602');p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 ids=sorted(set(int(x) for x in a.frames.split(',')))
 if not ids or min(ids)<0:p.error('Frame indices must be nonnegative')
 if a.output.exists():raise FileExistsError('Use a new output folder to preserve previous annotations')
 cap=cv2.VideoCapture(str(a.video));frames=[];seeds=[]
 try:
  if not cap.isOpened():raise FileNotFoundError(a.video)
  for f in ids:
   cap.set(cv2.CAP_PROP_POS_FRAMES,f);ok,image=cap.read()
   if not ok:raise ValueError(f'Cannot decode frame {f}')
   h,w=image.shape[:2];ok,raw=cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,95]);digest=hashlib.sha256(raw.tobytes()).hexdigest();blank=url(np.zeros((h,w),np.uint8))
   frames.append(dict(frame=f,width=w,height=h,image='data:image/jpeg;base64,'+base64.b64encode(raw).decode(),image_sha256=digest,mask=blank,band=blank,gaps=blank))
   seeds.append(dict(frame=f,image_sha256=digest,visible_mask_png=blank,uncertain_mask_png=blank,review_status='unreviewed',notes=''))
 finally:cap.release()
 source=hashlib.sha256(json.dumps([(r['frame'],r['image_sha256']) for r in frames]).encode()).hexdigest()
 data=dict(manifest={'dataset_id':a.output.name},frames=frames,seed_annotations=seeds,source_annotations_sha256=source)
 html=(HERE/'rope_mask_visibility_review.html').read_text(encoding='utf-8');script=(HERE/'rope_mask_visibility_review.js').read_text(encoding='utf-8')
 html=html.replace('__EMBEDDED_DATA__',json.dumps(data,ensure_ascii=False).replace('</','<\\/')).replace('__EDITOR_SCRIPT__',script)
 a.output.mkdir(parents=True);(a.output/'index.html').write_text(html,encoding='utf-8');(a.output/'source.json').write_text(json.dumps({'video':str(a.video.resolve()),'frames':ids,'source_annotations_sha256':source},indent=2),encoding='utf-8')
 print(a.output/'index.html')
if __name__=='__main__':main()
