from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _backup_corrupt_json(path: Path, raw: str) -> None:
    backup = path.with_suffix(
        f"{path.suffix}.corrupt.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    )
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(raw, encoding="utf-8")


def _load_payload(path: Path, raw: str) -> tuple[dict[str, Any], bool]:
    if not raw.strip():
        return {}, False
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _backup_corrupt_json(path, raw)
        return {}, True
    if not isinstance(payload, dict):
        _backup_corrupt_json(path, raw)
        return {}, True
    return payload, False


def parse_state_json_file(path: Path, raw: str) -> dict[str, Any]:
    payload, _ = _load_payload(path, raw)
    return payload


def _serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _fsync_directory(path: Path) -> None:
    try:
        directory_fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _atomic_write(path: Path, serialized: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


class LockedJsonFile:
    def __init__(self, path: Path):
        self.path = path
        self.lock_path = path.with_name(f".{path.name}.lock")
        self.handle = None
        self.payload: dict[str, Any] = {}
        self._file_existed = False
        self._recovered_corrupt_input = False
        self._serialized_on_enter = ""

    def __enter__(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.lock_path.open("a+", encoding="utf-8")
        fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX)
        self._file_existed = self.path.exists()
        raw = self.path.read_text(encoding="utf-8") if self._file_existed else ""
        self.payload, self._recovered_corrupt_input = _load_payload(self.path, raw)
        if raw.strip() and not self._recovered_corrupt_input:
            self._serialized_on_enter = raw
        else:
            self._serialized_on_enter = ""
        return self.payload

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        try:
            if exc_type is None:
                serialized = _serialize_payload(self.payload)
                should_write = self._recovered_corrupt_input or serialized != self._serialized_on_enter
                if not self._file_existed and not self.payload and not self._recovered_corrupt_input:
                    should_write = False
                if should_write:
                    _atomic_write(self.path, serialized)
        finally:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
