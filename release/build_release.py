"""Build an isolated source bundle and optionally a PyInstaller package.

This script never edits the working configuration and never starts the game.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release" / "output"
SOURCE_OUT = OUT / "HololiveDreamsGUI-source"


def copy_source_bundle() -> None:
    if SOURCE_OUT.exists():
        shutil.rmtree(SOURCE_OUT)
    SOURCE_OUT.mkdir(parents=True)
    for name in ("gui", "src", "domains", "pyproject.toml", "AGENTS.md"):
        source = ROOT / name
        target = SOURCE_OUT / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "runtime"))
        else:
            shutil.copy2(source, target)
    (SOURCE_OUT / "runtime").mkdir()
    manifest = {
        "product": "HololiveDreamsGUI",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "source-bundle",
        "entry": "gui/hololive_dreams_gui.py",
        "engine_entry": "domains/hololive_dreams/models/rhythm_game.py:run",
        "multi_live": "not implemented; GUI is status-only",
        "algorithm_changes": False,
        "real_game_test": False,
        "config_writeback": False,
    }
    (SOURCE_OUT / "release-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def build_pyinstaller() -> int:
    spec = ROOT / "release" / "hololive_dreams_gui.spec"
    dist = OUT / "HololiveDreamsGUI"
    work = OUT / "pyinstaller-work"
    if dist.exists():
        shutil.rmtree(dist)
    if work.exists():
        shutil.rmtree(work)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(OUT), "--workpath", str(work), str(spec)]
    print("Executing:", " ".join(command))
    return subprocess.call(command, cwd=ROOT)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pyinstaller", action="store_true", help="also build the onedir Windows package")
    args = parser.parse_args()
    copy_source_bundle()
    print(f"Source bundle: {SOURCE_OUT}")
    if not args.pyinstaller:
        return 0
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed; source bundle is complete and no EXE was produced.", file=sys.stderr)
        return 2
    return build_pyinstaller()


if __name__ == "__main__":
    raise SystemExit(main())

