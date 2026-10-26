"""Small local dynamic-programming association for smooth rope evidence."""
import numpy as np

def coherent_offsets(cost, offsets, penalty=.45):
    """Minimize strip costs plus adjacent normal-offset variation.

    cost is curves x points x offsets. Occluded points should carry equal costs,
    allowing a smooth bridge without pretending those points were observed.
    """
    values=np.asarray(cost,dtype=float);offsets=np.asarray(offsets,dtype=float)
    if values.ndim!=3 or values.shape[2]!=len(offsets) or not len(offsets) or values.shape[1]<1 or not np.all(np.isfinite(values)) or penalty<0:raise ValueError('invalid strip evidence')
    transition=abs(offsets[:,None]-offsets[None,:])*penalty
    total=values[:,0].copy();parents=[]
    for point in range(1,values.shape[1]):
        trials=total[:,:,None]+transition[None,:,:]
        parent=np.argmin(trials,axis=1);parents.append(parent)
        total=values[:,point]+np.min(trials,axis=1)
    chosen=np.empty(values.shape[:2],dtype=int);chosen[:,-1]=np.argmin(total,axis=1);rows=np.arange(len(values))
    for point in range(values.shape[1]-2,-1,-1):chosen[:,point]=parents[point][rows,chosen[:,point+1]]
    return chosen
