import gzip
import hashlib
import json
from pathlib import Path


def read_jsonl(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Required local file missing: {path.resolve()}. No automatic download.")
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_gzip(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    path.write_bytes(gzip.compress(raw, mtime=0))


def load_gzip(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Required local index missing: {path.resolve()}. Run run.py build first; no download is attempted.")
    return json.loads(gzip.decompress(path.read_bytes()))
