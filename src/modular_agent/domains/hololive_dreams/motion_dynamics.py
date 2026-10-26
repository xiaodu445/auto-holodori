"""Offline measurements in minimap pixels, seconds and injected mouse counts."""
import math
import cv2
import numpy as np


def camera_headings(images,*,half_angle=None):
    """Recover the moving yellow cone, independent of the white actor pointer.

    The character must remain stationary. A temporal minimum removes static
    yellow terrain; the inner pointer and outer HUD never enter the estimate.
    """
    if len(images)<8:raise ValueError('镜头样本不足8帧')
    frames=np.asarray([cv2.resize(im,(164,164)).astype(np.float32) for im in images])
    warmth=frames[:,:,:,2]-frames[:,:,:,0]
    baseline=np.min(warmth,axis=0);span=np.max(warmth,axis=0)-baseline
    yy,xx=np.mgrid[:164,:164];dx=xx-82;dy=yy-82;radius=np.hypot(dx,dy)
    valid=(radius>31)&(radius<65)&(span>5)
    if valid.sum()<500:return [None]*len(images),[dict(valid=False,reason='insufficient_changing_cone')] *len(images)
    angles=np.rad2deg(np.arctan2(dy,dx))%360
    bins=np.rint(angles[valid]/2).astype(int)%180
    weights=np.bincount(bins,minlength=180).astype(np.float32)
    profiles=np.asarray([np.bincount(bins,weights=np.clip((frame[valid]-baseline[valid])/span[valid],0,1),minlength=180) for frame in warmth],np.float32)
    # Normalize each terrain pixel by its own observed change. Unchanged areas
    # are UNKNOWN, not absent cone. This removes partial-sweep centroid bias.
    base=((profiles/np.maximum(weights,1))**2*weights).sum(axis=1)
    distances=np.abs((np.arange(180)[None,:]*2-np.arange(360)[:,None]+180)%360-180)
    best=None
    for half_width in ([half_angle] if half_angle is not None else range(30,71,2)):
        templates=(distances<=half_width).astype(np.float32)
        loss=(base[:,None]+(templates@weights)[None,:]-2*(profiles@templates.T))/weights.sum()
        loss=np.maximum(loss,0);cost=float(loss.min(axis=1).mean())
        if best is None or cost<best[0]:best=(cost,half_width,loss)
    _,half_width,loss=best;headings=[];quality=[]
    for scores in loss:
        heading=int(np.argmin(scores));minimum=float(scores[heading])
        rival=float(np.min(scores[np.abs((np.arange(360)-heading+180)%360-180)>=20]))
        good=minimum<.20 and rival-minimum>.01
        # Quadratic interpolation removes the one-degree template quantization.
        left=float(scores[(heading-1)%360]);right=float(scores[(heading+1)%360]);curvature=left-2*minimum+right
        offset=float(np.clip(.5*(left-right)/curvature,-.5,.5)) if curvature>1e-5 else 0
        headings.append(float((heading+offset)%360) if good else None)
        quality.append(dict(valid=good,half_angle_degrees=half_width,fit_mse=minimum,margin=rival-minimum,
                            method='normalized_two_boundary_sector_fit'))
    return headings,quality


def fit_camera(counts,headings):
    counts=np.asarray(counts,dtype=float)
    if len(counts)!=len(headings) or not np.all(np.isfinite(counts)):raise ValueError('无效鼠标样本')
    valid=np.asarray([a is not None and math.isfinite(a) for a in headings])
    if valid.sum()<8:raise ValueError('光锥有效方向不足，拒绝用人物突起代替镜头方向')
    # Missing observations may hide whole revolutions; never unwrap across gaps.
    indexes=np.flatnonzero(valid)
    runs=np.split(indexes,np.flatnonzero(np.diff(indexes)>1)+1)
    indexes=max(runs,key=len)
    if len(indexes)<8:raise ValueError('缺少连续可靠的光锥采样')
    x=counts[indexes];raw=np.asarray(headings,dtype=object)[indexes].astype(float)
    y=np.rad2deg(np.unwrap(np.deg2rad(raw)))
    if np.max(np.abs(np.diff(y)))>80:raise ValueError('单步镜头转角过大，需减小鼠标步长')
    if np.ptp(y)<90 or np.ptp(x)<1:raise ValueError('实际观察转角不足90度')
    design=np.column_stack((x,np.ones_like(x)))
    slope,intercept=np.linalg.lstsq(design,y,rcond=None)[0]
    residual=y-(slope*x+intercept)
    rms=float(np.sqrt(np.mean(residual**2)))
    if abs(slope)<.001 or rms>8:raise ValueError('镜头计数关系不稳定；可能有回正、鼠标加速或光锥识别误差')
    advance=float(abs(y[-1]-y[0]));closure=float(abs((raw[-1]-raw[0]+180)%360-180))
    complete=advance>=360 and closure<=12
    return dict(degrees_per_count=float(slope),counts_per_360=float(360/abs(slope)),
        observed_degrees=float(np.ptp(y)),directed_advance_degrees=advance,closure_error_degrees=closure,full_turn_observed=bool(complete),
        angle_rms_degrees=rms,samples=len(x),direction='clockwise' if y[-1]>y[0] else 'counterclockwise',
        positive_count_direction='clockwise' if slope>0 else 'counterclockwise',
        heading_source='temporal_yellow_cone',hardware_dpi_measured=False,
        note='Effective injected relative mouse counts at this sensitivity and step timing, not hardware DPI.')


def measure_cruise(trials):
    """Confirm a velocity plateau from position slopes, independently of a model."""
    candidates=[]
    for index,trial in enumerate(trials):
        rows=trial['samples'];duration=float(trial['held_seconds'])
        t=np.asarray([r['t'] for r in rows],float);xy=np.asarray([[r['x'],r['y']] for r in rows],float)
        if len(t)<6 or not np.isfinite(t).all() or not np.isfinite(xy).all() or np.any(np.diff(t)<=0):continue
        held=(t>=0)&(t<=duration-.025)
        if held.sum()<6:continue
        end=xy[np.flatnonzero(held)[-1]]-xy[0];distance=float(np.linalg.norm(end))
        if distance<2:continue
        direction=end/distance;along=(xy-xy[0])@direction;windows=[]
        for start in np.arange(.10,max(.10,duration-.27),.125):
            valid=held&(t>=start)&(t<=start+.25)
            if valid.sum()<4:continue
            ts=t[valid];d=along[valid]
            if np.ptp(ts)<.18:continue
            slope,offset=np.linalg.lstsq(np.column_stack((ts,np.ones(len(ts)))),d,rcond=None)[0]
            rms=float(np.sqrt(np.mean((d-(slope*ts+offset))**2)))
            if slope>=2 and rms<=1:windows.append(dict(t=float(np.mean(ts)),speed=float(slope),start=float(ts[0]),end=float(ts[-1])))
        for count in range(3,len(windows)+1):
            group=windows[-count:];speeds=np.asarray([w['speed'] for w in group]);times=np.asarray([w['t'] for w in group]);median=float(np.median(speeds))
            trend=float(np.polyfit(times,speeds,1)[0])
            if group[-1]['end']-group[0]['start']>=.45 and np.ptp(speeds)<=median*.10 and abs(trend)<=median*.12:
                candidates.append(dict(trial=index+1,speed=median,start=group[0]['start'],end=group[-1]['end'],spread=float(np.ptp(speeds))))
    if not candidates:return dict(plateau_observed=False,steady_speed_pixels_per_second=None,reason='no_sustained_velocity_plateau',plateaus=[])
    speeds=np.asarray([c['speed'] for c in candidates]);median=float(np.median(speeds))
    if np.ptp(speeds)>median*.15:return dict(plateau_observed=False,steady_speed_pixels_per_second=None,reason='inconsistent_plateau_speeds',plateaus=candidates)
    return dict(plateau_observed=True,steady_speed_pixels_per_second=median,reason='measured_position_slope_plateau',plateaus=candidates)


def fit_forward(trials):
    """First-order rise/coast model, fitted to measured position, not input delivery."""
    samples=[];durations=[];intervals=[]
    distances=[];coasts=[];directions=[]
    for trial in trials:
        duration=float(trial['held_seconds']);rows=trial['samples']
        if not 0<duration<=2.1 or len(rows)<6:raise ValueError('W采样不足或持键时长无效')
        t=np.asarray([r['t'] for r in rows],float)
        xy=np.asarray([[r['x'],r['y']] for r in rows],float)
        if not np.all(np.isfinite(t)) or not np.all(np.isfinite(xy)) or np.any(np.diff(t)<=0):raise ValueError('W采样时间/坐标无效')
        if t[0]>.04 or np.count_nonzero(t<=duration)<3:raise ValueError('按住W期间有效帧不足，不能辨识加速度')
        delta=xy[-1]-xy[0];distance=float(np.linalg.norm(delta))
        if distance<2:raise ValueError('W位移不足：可能按键未生效或撞墙')
        direction=delta/distance;directions.append(float(np.rad2deg(np.arctan2(direction[1],direction[0]))%360));along=(xy-xy[0])@direction
        cross=np.linalg.norm((xy-xy[0])-along[:,None]*direction,axis=1)
        if cross.max()>max(3,distance*.15):raise ValueError('W轨迹明显转弯，不能拟合直线加速')
        samples.append((t,along,duration));durations.append(duration);intervals.extend(np.diff(t))
        release_distance=float(np.interp(duration,t,along));distances.append(distance);coasts.append(distance-release_distance)
    if len(samples)<2:raise ValueError('至少需要两种W持键时长')
    if max(durations)-min(durations)<.03:raise ValueError('请至少测量两种不同的W持键时长')
    if any(abs((d-directions[0]+180)%360-180)>15 for d in directions):raise ValueError('多组W方向变化，可能镜头移动，拒绝合并拟合')
    best=None
    for rise in np.geomspace(.01,1,45):
        for decay in np.geomspace(.01,1,45):
            basis=[];observed=[]
            for t,d,duration in samples:
                on=np.minimum(t,duration)
                shape=on-rise*(1-np.exp(-on/rise))
                shape+=(1-np.exp(-duration/rise))*decay*(1-np.exp(-np.maximum(t-duration,0)/decay))
                basis.extend(shape);observed.extend(d)
            basis=np.asarray(basis);observed=np.asarray(observed)
            speed=float(basis@observed/max(basis@basis,1e-9))
            error=float(np.sqrt(np.mean((basis*speed-observed)**2)))
            if best is None or error<best[0]:best=(error,speed,float(rise),float(decay))
    error,speed,rise,decay=best
    if error>max(1.5,np.mean(distances)*.08):raise ValueError('W动力学拟合误差过大，保留原始数据供检查')
    median=float(np.median(intervals))
    resolved=median<=min(rise,decay)/2 and rise>.011 and decay>.011 and rise<.99 and decay<.99
    cruise=measure_cruise(trials)
    return dict(steady_speed_pixels_per_second=cruise['steady_speed_pixels_per_second'],plateau_observed=cruise['plateau_observed'],
        speed_measurement=cruise,model_terminal_speed_pixels_per_second=speed,acceleration_time_constant_seconds=rise,
        damping_time_constant_seconds=decay,initial_acceleration_pixels_per_second_squared=speed/rise,
        damping_rate_per_second=1/decay,position_rms_pixels=error,median_sample_interval_seconds=median,
        dynamics_resolved=bool(resolved),coast_distances_pixels=coasts,held_seconds=durations,forward_directions_degrees=directions,
        model='first_order_velocity_rise_and_decay',live_verified=False,
        note='Low sampling rate or boundary fits are estimates only; collisions and terrain slopes invalidate this model.')
