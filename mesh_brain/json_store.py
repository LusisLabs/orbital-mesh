from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class LockedJsonFile:
    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_name(f".{path.name}.lock")
        self.handle = None
        self.payload: dict[str, Any] = {}
        self._serialized_on_enter = ""
        self._file_existed = False

    def __enter__(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.lock_path.open("a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        self._file_existed = self.path.exists()
        raw = self.path.read_text(encoding="utf-8") if self._file_existed else ""
        self.payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(self.payload, dict):
            self.payload = {}
        self._serialized_on_enter = _serialize(self.payload) if raw.strip() else ""
        return self.payload

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        try:
            if exc_type is None:
                serialized = _serialize(self.payload)
                if serialized != self._serialized_on_enter and (self._file_existed or self.payload):
                    _atomic_write(self.path, serialized)
        finally:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()


def _serialize(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _atomic_write(path: Path, serialized: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
