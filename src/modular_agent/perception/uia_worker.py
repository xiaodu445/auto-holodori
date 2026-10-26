"""Isolated UIA worker: read only, bounded traversal; parent enforces timeout."""
import json
import sys
from collections import deque
from .report import Rect

_desktop=None

def inspect(handles,max_nodes=400,max_depth=6):
    global _desktop
    if _desktop is None:
        from modular_agent.computer.windows import WindowsBackend
        WindowsBackend()  # Physical-pixel DPI context before UIA initialization.
        from pywinauto import Desktop
        _desktop=Desktop(backend='uia')
    desktop=_desktop
    buttons=[]; texts=[]; warnings=[]
    for handle in handles:
        try:
            root=desktop.window(handle=handle).wrapper_object()
            queue=deque([(root,0)])
            visited=0
            while queue and visited<max_nodes:
                control,depth=queue.popleft(); visited+=1
                try:
                    if not control.is_visible(): continue
                    rectangle=control.rectangle()
                    bounds=Rect.from_bbox((rectangle.left,rectangle.top,rectangle.right,rectangle.bottom))
                    if bounds.area==0: continue
                    kind=control.element_info.control_type
                    label=control.window_text()
                    identifier=f'uia:{handle}:{visited}'
                    if kind=='Button':
                        buttons.append({'id':identifier,'label':label,'bounds':bounds.to_dict(),
                            'confidence':1.0,'source':'uia','semantic_confirmed':True,
                            'enabled':control.is_enabled(),'window_handle':handle,'text_ids':[]})
                    if label and kind in ('Button','Text','Edit','Hyperlink','MenuItem','TabItem'):
                        texts.append({'id':identifier+':text','text':label,'bounds':bounds.to_dict(),
                            'confidence':1.0,'source':'uia','geometry_kind':'control_bounds',
                            'window_handle':handle,'button_ids':[identifier] if kind=='Button' else []})
                    if depth<max_depth:
                        queue.extend((child,depth+1) for child in control.children())
                except Exception: continue
            if queue: warnings.append(f'UIA traversal limit reached for window {handle}')
        except Exception as error: warnings.append(f'UIA window {handle}: {type(error).__name__}')
    return {'buttons':buttons,'texts':texts,'warnings':warnings}

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    if '--serve' in sys.argv:
        sys.stdin.reconfigure(encoding='utf-8')
        for line in sys.stdin:
            try:
                request=json.loads(line)
                handles=request['handles']
                if not isinstance(handles,list) or any(type(h) is not int for h in handles): raise ValueError('Invalid handles')
                reply=inspect(handles)
            except Exception as error: reply={'error':type(error).__name__}
            print(json.dumps(reply,ensure_ascii=False),flush=True)
    else:
        print(json.dumps(inspect([int(h) for h in sys.argv[1:]]),ensure_ascii=False))
