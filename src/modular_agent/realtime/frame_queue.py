"""Bounded latest-frame queue shared by runtime consumers."""
import queue

def offer_latest(items,item):
    """Bounded encoder queue: discard oldest unencoded image on overflow."""
    try:items.put_nowait(item);return 0
    except queue.Full:
        try:items.get_nowait()
        except queue.Empty:pass
        items.put_nowait(item);return 1
