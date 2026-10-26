"""Inventory local assets and reversibly archive only disposable release workspaces."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "maintenance"
SKIP = {".git", ".conda", ".venv", "__pycache__", ".pytest_cache", ".ultralytics"}


def files(folder):
    for base, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not (Path(base) / d).is_symlink())
        for name in sorted(names):
            path = Path(base) / name
            if not path.is_symlink():
                yield path


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-release-caches", action="store_true")
    args = parser.parse_args()
    REPORT.mkdir(exist_ok=True)
    protected = []
    scopes = ["learning/jump_rope_yolo/datasets", "learning/jump_rope_yolo/loop_assets",
              "runtime/jump-rope/frame-review", "runtime/kitchen/manual-labeling",
              "learning/kitchen_yolo/datasets", "data/kitchen"]
    # Byte hashes cover labels AND source images. Runtime recordings stay untouched.
    for scope in scopes:
        for path in files(ROOT / scope):
            protected.append({"path": path.relative_to(ROOT).as_posix(),
                              "bytes": path.stat().st_size, "sha256": digest(path)})
    manifest = REPORT / "protected-assets.local.json"
    manifest.write_text(json.dumps(protected, ensure_ascii=False, indent=2), encoding="utf-8")
    archive = ROOT.parent / "workspace-archive" / "2026-10-26" / "Game_agent"
    moves = []
    if args.archive_release_caches:
        release = ROOT / "release"
        candidates = [p for p in release.iterdir() if p.is_dir() and
                      (p.name in {"build", "verification-cache", "中文 空格验证"}
                       or p.name.startswith("部署验证 中文 空格 "))]
        for source in sorted(candidates):
            source = source.resolve()
            if source.parent != release.resolve() or source.is_symlink():
                raise ValueError(f"Unexpected source: {source}")
            target = archive / source.relative_to(ROOT)
            if not target.resolve().is_relative_to((ROOT.parent / "workspace-archive").resolve()):
                raise ValueError("Archive outside workspace")
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise FileExistsError(target)
            count = 0
            size = 0
            for path in files(source):
                count += 1
                size += path.stat().st_size
            source.rename(target)
            moves.append({"from": str(source), "to": str(target), "files": count, "bytes": size})
            (REPORT / "archive-moves.local.json").write_text(
                json.dumps(moves, ensure_ascii=False, indent=2), encoding="utf-8")
    for row in protected:
        path = ROOT / row["path"]
        if path.stat().st_size != row["bytes"] or digest(path) != row["sha256"]:
            raise RuntimeError(f"Protected asset changed: {path}")
    totals = {}
    for path in files(ROOT):
        rel = path.relative_to(ROOT)
        key = "/".join(rel.parts[:2]) if len(rel.parts) > 1 else "root files"
        item = totals.setdefault(key, {"files": 0, "bytes": 0})
        item["files"] += 1
        item["bytes"] += path.stat().st_size
    (REPORT / "inventory.local.json").write_text(json.dumps(totals, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"protected_files_verified": len(protected), "archived_directories": len(moves),
                      "archived_bytes": sum(r["bytes"] for r in moves)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
