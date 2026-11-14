"""JSON fayllarga xavfsiz yozish/o'qish."""
import json
import threading
from pathlib import Path

_lock = threading.Lock()


def load_json(path: Path, default):
    with _lock:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default


def save_json(path: Path, data) -> None:
    with _lock:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
