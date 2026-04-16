from __future__ import annotations

import fcntl
import json
from pathlib import Path
from typing import Any


class LockedJsonFile:
    def __init__(self, path: Path):
        self.path = path
        self.handle = None
        self.payload: dict[str, Any] = {}

    def __enter__(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        self.handle.seek(0)
        raw = self.handle.read()
        self.payload = json.loads(raw) if raw.strip() else {}
        return self.payload

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        if exc_type is None:
            self.handle.seek(0)
            self.handle.truncate()
            json.dump(self.payload, self.handle, indent=2, sort_keys=True)
            self.handle.write("\n")
            self.handle.flush()
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
