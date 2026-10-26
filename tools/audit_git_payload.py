"""Check the staged upload for credentials, private paths and oversized files."""
from pathlib import Path
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
GIT = ["git", "-c", f"safe.directory={ROOT.as_posix()}"]
TOKEN = re.compile(rb"(?:sk-[A-Za-z0-9_-]{24,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)")
PRIVATE = {"runtime", ".conda", ".venv", "__pycache__"}


def main():
    names = subprocess.check_output(GIT + ["diff", "--cached", "--name-only", "-z"], cwd=ROOT).split(b"\0")
    issues = []
    total = 0
    largest = []
    reader = subprocess.Popen(GIT + ["cat-file", "--batch"], cwd=ROOT,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    for raw in filter(None, names):
        name = raw.decode("utf-8")
        path = ROOT / name
        reader.stdin.write(b":" + raw + b"\n")
        reader.stdin.flush()
        header = reader.stdout.readline().split()
        if len(header) != 3:
            raise RuntimeError(f"Cannot read staged blob: {name}")
        payload = reader.stdout.read(int(header[2]))
        reader.stdout.read(1)
        size = len(payload)
        total += size
        largest.append((size, name))
        if size >= 95 * 1024**2:
            issues.append({"path": name, "reason": "oversized Git file"})
        if PRIVATE.intersection(Path(name).parts) or name in {"config/model.json", "config/models.json"}:
            issues.append({"path": name, "reason": "private runtime/config/environment"})
        if TOKEN.search(payload):
            issues.append({"path": name, "reason": "credential-like literal"})
        if path.suffix.lower() == ".json":
            try:
                data = json.loads(payload.decode("utf-8-sig"))
            except (ValueError, UnicodeDecodeError):
                continue
            def check(value):
                if isinstance(value, dict):
                    for key, item in value.items():
                        if key.lower() in {"api_key", "password", "access_token", "refresh_token", "client_secret"} and item:
                            issues.append({"path": name, "reason": "nonempty credential field"})
                        check(item)
                elif isinstance(value, list):
                    for item in value:
                        check(item)
            check(data)
    reader.stdin.close()
    if reader.wait() != 0:
        raise RuntimeError("git cat-file failed")
    print(json.dumps({"files": len(list(filter(None, names))), "bytes": total,
                      "largest": sorted(largest, reverse=True)[:8], "issues": issues}, ensure_ascii=False))
    return bool(issues)


if __name__ == "__main__":
    raise SystemExit(main())
