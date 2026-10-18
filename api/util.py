"""Small shared helpers: keyed build locks, atomic writes, JSON reading."""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@contextmanager
def build_lock(key: str) -> Iterator[None]:
    """One builder per key inside this process; concurrent requests wait for the first build."""
    with _locks_guard:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        yield


def tmp_path_for(path: Path) -> Path:
    return path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(path)
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_bytes(path, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode())


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def is_stale(target: Path, *sources: Path) -> bool:
    """True when `target` is missing or older than any existing source."""
    if not target.exists():
        return True
    t = target.stat().st_mtime
    return any(s.exists() and s.stat().st_mtime > t for s in sources)


def atomic_save_npy(path: Path, arr: Any) -> None:
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_path_for(path)
    with tmp.open("wb") as fh:
        np.save(fh, arr)
    os.replace(tmp, path)
