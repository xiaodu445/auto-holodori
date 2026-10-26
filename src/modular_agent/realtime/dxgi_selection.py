"""Bounded DXGI selection by desktop coordinates, not adapter numbering."""
import time,json

class CaptureSafetyStop(RuntimeError):pass

def checked_bounds(guard,expected):
    try:current=guard.bounds()
    except Exception as error:raise CaptureSafetyStop(str(error)) from error
    if current!=expected:raise CaptureSafetyStop('window_changed_during_dxgi_selection')

def enumerate_outputs(dxcam):
    # Pinned dxcam 0.3.0 has no public structured output enumeration. Use its
    # factory descriptors; never confuse public display numbers with indices.
    from importlib.metadata import version
    if version('dxcam')!='0.3.0':raise RuntimeError('DXGI enumeration requires reviewed dxcam 0.3.0 adapter')
    factory=getattr(dxcam,'__factory',None)
    if factory is None:raise RuntimeError('DXGI output enumeration unavailable')
    result=[]
    for did,outputs in enumerate(factory.outputs):
        for oid,output in enumerate(outputs):
            output.update_desc();desc=output.desc;r=desc.DesktopCoordinates
            result.append(dict(device_idx=did,output_idx=oid,name=str(output.devicename),
                attached=bool(desc.AttachedToDesktop),left=int(r.left),top=int(r.top),
                width=int(r.right-r.left),height=int(r.bottom-r.top)))
    return result

def select_output(guard,dxcam,release,*,inventory=None,wait=time.sleep):
    try:bounds=guard.bounds()
    except Exception as error:raise CaptureSafetyStop(str(error)) from error
    x,y,w,h=bounds
    outputs=enumerate_outputs(dxcam) if inventory is None else inventory
    attempts=[]
    for item in outputs:
        row=dict(item);attempts.append(row)
        matches=(item['attached'] and item['left']<=x and item['top']<=y and
            x+w<=item['left']+item['width'] and y+h<=item['top']+item['height'])
        if not matches:row['result']='not_game_screen';continue
        checked_bounds(guard,bounds);camera=None
        try:
            camera=dxcam.create(device_idx=item['device_idx'],output_idx=item['output_idx'],
                backend='dxgi',output_color='BGR',max_buffer_len=2)
            if (camera.width,camera.height)!=(item['width'],item['height']):raise RuntimeError('output_geometry_mismatch')
            region=(x-item['left'],y-item['top'],x+w-item['left'],y+h-item['top'])
            for _ in range(20):
                checked_bounds(guard,bounds)
                frame=camera.grab(region=region,copy=True,new_frame_only=True)
                checked_bounds(guard,bounds)
                if frame is not None:
                    if frame.shape!=(h,w,3):raise RuntimeError('probe_frame_dimensions_mismatch')
                    row['result']='verified_frame'
                    return camera,{k:item[k] for k in ('left','top','width','height')},attempts
                wait(.01)
            raise RuntimeError('DXGI probe produced no fresh frame')
        except CaptureSafetyStop:
            if camera is not None:release(camera)
            raise
        except Exception as error:
            row['result']='failed';row['reason']=str(error)
            if camera is not None:release(camera)
    raise RuntimeError('DXGI no verified output for game window: '+json.dumps(attempts,ensure_ascii=False))
