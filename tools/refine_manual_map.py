"""Fill a human-assembled map from recorded observations, preserving its known pixels.

Offline geometric registration, not generative inpainting. Original manual tiles,
positions, masks and map are read-only. Uncertain areas remain uncovered.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import time

import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.minimap_mapper import MapperSettings,register_tiles
from modular_agent.domains.hololive_dreams.patrol_vision import read_image,write_image
from modular_agent.realtime.minimap_alignment import AlignmentProject,atomic_json,load_rows


def extract(image,center,n):
    """Exact integer crop with unknown padding; return tile and top-left."""
    x,y = np.rint(np.asarray(center)-n/2).astype(int)
    tile = np.zeros((n,n)+image.shape[2:],image.dtype)
    h,w = image.shape[:2];left,top,right,bottom = max(0,x),max(0,y),min(w,x+n),min(h,y+n)
    if right>left and bottom>top:tile[top-y:bottom-y,left-x:right-x] = image[top:bottom,left:right]
    return tile,(int(x),int(y))


def brightness_match(source,reference,common):
    """Median offset from observed overlap only; never uses black missing pixels."""
    valid = cv2.erode(common.astype(np.uint8),np.ones((3,3),np.uint8))>0
    if np.count_nonzero(valid)<150:return source.copy(),np.zeros(3)
    difference = reference[valid].astype(float)-source[valid].astype(float)
    offset = np.clip(np.median(difference,axis=0),-15,15)
    return np.clip(source.astype(float)+offset,0,255).astype(np.uint8),offset


def preserve_manual(reference,known,candidate,support,minimum=3):
    valid = (support>=minimum)&~known
    count,labels,stats,_ = cv2.connectedComponentsWithStats(valid.astype(np.uint8))
    for index in range(1,count):
        if stats[index,cv2.CC_STAT_AREA]<10:valid[labels==index] = False
    result = reference.copy();result[valid] = candidate[valid]
    return result,known|valid,valid


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('manual_export',type=Path)
    p.add_argument('--baseline',type=Path,required=True,help='full timestamp-aligned automatic trajectory for search prediction only')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--minimum-support',type=int,default=3)
    a = p.parse_args(argv)
    if not 2<=a.minimum_support<=20:p.error('minimum support must be 2..20')
    a.output.mkdir(parents=True,exist_ok=False);cv2.setNumThreads(1)
    source = a.manual_export
    data = json.loads((source/'alignment.json').read_text(encoding='utf-8'))
    project = AlignmentProject(data['recording'],data['placements'],source/'alignment.json')
    original = read_image(source/'map.png')
    coverage = cv2.imdecode(np.fromfile(str(source/'coverage.png'),np.uint8),cv2.IMREAD_GRAYSCALE)>0
    metadata = json.loads((source/'mapping.json').read_text(encoding='utf-8'))
    origin = np.array(metadata['origin_world_xy'],float);n = project.settings.tile_size
    manual = json.loads((source/'corrected-placements.json').read_text(encoding='utf-8'))
    baseline = load_rows(a.baseline)
    if len(baseline)!=len(project.raw) or any(abs(x['t']-y['t'])>1e-8 for x,y in zip(baseline,project.raw)):
        raise ValueError('baseline does not match raw recording timestamps')
    baseline_positions = np.array([[r['x'],r['y']] for r in baseline])
    anchors = sorted(manual,key=lambda r:r['t'])
    times = np.array([r['t'] for r in project.raw])
    anchor_times = np.array([r['t'] for r in anchors])
    corrections = np.array([[r['x'],r['y']] for r in anchors])-np.array([baseline_positions[project.lookup[r['frame_id']]] for r in anchors])
    predicted = baseline_positions+np.column_stack([np.interp(times,anchor_times,corrections[:,axis]) for axis in (0,1)])
    h,w = coverage.shape
    best = np.zeros_like(original);best_rank = np.full((h,w),np.inf,np.float32);support = np.zeros((h,w),np.uint16)
    yy,xx = np.ogrid[:n,:n];radius = np.sqrt((xx-n/2)**2+(yy-n/2)**2)/(n/2)
    base_mask = ((radius<.80)&(radius>.34)).astype(np.uint8)*255
    settings = replace(MapperSettings(),max_shift=24,min_similarity=.91,min_overlap=.35)
    rows = [];manual_ids = {r['frame_id'] for r in manual};last_fused = None;matches = 0;fused = 0
    start = time.perf_counter()
    for i,fid in enumerate(project.ids):
        row = dict(frame_id=fid,t=project.time(fid),accepted=False)
        if fid in manual_ids:row['reason'] = 'original_manual_frame_locked'
        elif project.raw[i].get('hud_score',1)<.9:row['reason'] = 'original_scene_gate'
        else:
            image = project.tile(fid);guess = predicted[i]
            reference,corner = extract(original,guess-origin,n)
            known,_ = extract(coverage.astype(np.uint8)*255,guess-origin,n)
            mask = project.mask(fid) if str(fid) in project.data['masks']['frames'] else base_mask.copy()
            match = register_tiles(reference,image,known,mask,settings,global_match=True)
            if match is None:row['reason'] = 'registration_unreliable'
            else:
                pixel_position = np.array(corner)+n/2+np.array((match['dx'],match['dy']))
                position = origin+pixel_position
                row.update(accepted=True,reason='matched_manual_reference',x=float(position[0]),y=float(position[1]),
                           correction_from_prediction=float(np.linalg.norm(position-guess)),**match)
                matches += 1
                if last_fused is None or np.linalg.norm(position-last_fused)>=4:
                    integer = np.rint(pixel_position);fraction = pixel_position-integer
                    shift = np.float32([[1,0,fraction[0]],[0,1,fraction[1]]])
                    shifted = cv2.warpAffine(image,shift,(n,n))
                    shifted_mask = cv2.warpAffine(mask,shift,(n,n),flags=cv2.INTER_NEAREST)>0
                    target,where = extract(original,integer,n)
                    target_valid,_ = extract(coverage.astype(np.uint8),integer,n)
                    common = shifted_mask&(target_valid>0)
                    adjusted,offset = brightness_match(shifted,target,common)
                    difference = adjusted.astype(np.int16)-target.astype(np.int16)
                    bad = common&((np.max(np.abs(difference),axis=2)>30)|((difference[:,:,2]>8)&(difference[:,:,0]<-3)))
                    shifted_mask[bad] = False
                    # Infer warm cone angles from observed overlap; exclude that
                    # radial direction in unknown pixels as well when supported.
                    angle = ((np.arctan2(yy-n/2,xx-n/2)+np.pi)/(2*np.pi)*48).astype(int)%48
                    for sector in range(48):
                        sector_known = common&(angle==sector)
                        if np.count_nonzero(sector_known)>=20 and np.mean(bad[sector_known])>.35:
                            shifted_mask[angle==sector] = False
                    left,top = where;right,bottom = min(w,left+n),min(h,top+n)
                    x0,y0 = max(0,left),max(0,top)
                    if right>x0 and bottom>y0:
                        sy,sx = y0-top,x0-left;rh,rw = bottom-y0,right-x0
                        valid = shifted_mask[sy:sy+rh,sx:sx+rw]
                        colors = adjusted[sy:sy+rh,sx:sx+rw]
                        rank = colors[:,:,2].astype(float)*2-colors[:,:,0]+radius[sy:sy+rh,sx:sx+rw]*25
                        region_rank = best_rank[y0:bottom,x0:right];region = best[y0:bottom,x0:right]
                        update = valid&(rank<region_rank)
                        region[update] = colors[update];region_rank[update] = rank[update]
                        region_support = support[y0:bottom,x0:right];region_support[valid] += 1
                        last_fused = position;fused += 1;row['fused'] = True;row['brightness_offset_bgr'] = offset.tolist()
        rows.append(row)
        if i%100==0:print(f'{i+1}/{len(project.ids)} matched={matches} contributing={fused} elapsed={time.perf_counter()-start:.1f}s',flush=True)
    # Low-frequency seam adjustment is estimated strictly on real shared pixels.
    common = coverage&(support>=a.minimum_support)
    weight = cv2.GaussianBlur(common.astype(np.float32),(0,0),8)
    delta = (original.astype(float)-best.astype(float))*common[:,:,None]
    adjustment = cv2.GaussianBlur(delta.astype(np.float32),(0,0),8)/np.maximum(weight[:,:,None],1e-5)
    adjustment[weight<.08] = 0
    best = np.clip(best.astype(float)+np.clip(adjustment,-12,12),0,255).astype(np.uint8)
    result,final_known,new = preserve_manual(original,coverage,best,support,a.minimum_support)
    write_image(a.output/'map.png',result)
    write_image(a.output/'coverage.png',final_known.astype(np.uint8)*255)
    write_image(a.output/'new-pixels.png',new.astype(np.uint8)*255)
    rgba = cv2.cvtColor(result,cv2.COLOR_BGR2BGRA);rgba[:,:,3] = final_known.astype(np.uint8)*255
    write_image(a.output/'map-transparent.png',rgba)
    config = json.loads((source/'patrol-config.json').read_text(encoding='utf-8'))
    config.update(reference='map.png',coverage='coverage.png',reference_reviewed=False)
    if config.get('input_mask'):
        (a.output/Path(config['input_mask']).name).write_bytes((source/config['input_mask']).read_bytes())
        config['input_mask'] = Path(config['input_mask']).name
    atomic_json(a.output/'patrol-config.json',config)
    atomic_json(a.output/'matches.json',rows)
    report = dict(source_manual_export=str(source.resolve()),manual_frames=len(manual),matched_frames=matches,
                  contributing_frames=fused,original_known_pixels=int(np.count_nonzero(coverage)),
                  new_observed_pixels=int(np.count_nonzero(new)),minimum_support=a.minimum_support,
                  manual_known_pixels_unchanged=bool(np.array_equal(result[coverage],original[coverage])),
                  entire_world_explored=False,live_verified=False,sends_input=False,
                  note='Original manual pixels/poses are locked. New pixels are from locally registered raw observations; uncertainty remains.')
    atomic_json(a.output/'refinement.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
