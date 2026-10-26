"""Bridge the release GUI to the existing rhythm engine."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Callable


def bundle_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def _load_engine():
    source = bundle_root() / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from domains.hololive_dreams.models import rhythm_game
    return rhythm_game


def find_game_window() -> tuple[int, str]:
    """Find exactly one supported game window without activating it."""
    source = bundle_root() / "src"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))
    from modular_agent.computer.windows import WindowsBackend
    backend = WindowsBackend()
    windows = [item for item in backend.windows() if item["title"].lower() == "hololive-dreams"]
    if len(windows) != 1:
        raise RuntimeError(f"需要恰好一个 hololive-Dreams 窗口，当前找到 {len(windows)} 个")
    return int(windows[0]["handle"]), str(windows[0]["title"])


def run_rhythm_session(*, live: bool, duration: float, stop_event: threading.Event,
                       pause_event: threading.Event, progress: Callable[[str], None]) -> dict:
    """Run the existing engine once, with no menu controller attached."""
    if duration != 0 and not 1 <= duration <= 1800:
        raise ValueError("时长必须为 0（不限时）或 1..1800 秒")
    handle, _ = find_game_window()
    return _load_engine().run(bundle_root(), handle, live=live,
        overrides={"timeout": duration}, should_yield=stop_event.is_set,
        pause=pause_event.is_set, progress=progress)

