"""Policy-owned exact command authorization for repo-patch verification."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class AuthorizedTestCommand:
    argv: tuple[str, ...]
    executable_path: str
    executable_digest: str
    command_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "executable_path": self.executable_path,
            "executable_digest": self.executable_digest,
            "command_digest": self.command_digest,
        }


class RepoPatchTestCommandPolicy:
    def __init__(
        self,
        allowed_commands: Sequence[Sequence[str]],
        *,
        require_at_least_one: bool = True,
    ) -> None:
        normalized: set[tuple[str, ...]] = set()
        for command in allowed_commands:
            argv = tuple(str(value) for value in command)
            if not argv or any(not value for value in argv):
                raise ValueError("repo patch test policy contains an empty command or argument")
            normalized.add(argv)
        self.allowed_commands = frozenset(normalized)
        self.require_at_least_one = require_at_least_one

    @classmethod
    def from_environment(cls, *, require_at_least_one: bool = True) -> RepoPatchTestCommandPolicy:
        raw = os.getenv("MESH_REPO_PATCH_ALLOWED_TEST_COMMANDS_JSON", "").strip()
        if not raw:
            return cls([], require_at_least_one=require_at_least_one)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("repo patch test command policy is invalid JSON") from exc
        if not isinstance(payload, list) or any(not isinstance(command, list) for command in payload):
            raise ValueError("repo patch test command policy must be an array of argv arrays")
        return cls(payload, require_at_least_one=require_at_least_one)

    def authorize(self, commands: Sequence[str]) -> tuple[AuthorizedTestCommand, ...]:
        if self.require_at_least_one and not commands:
            raise ValueError("repo patch authority requires at least one verification command")
        authorized: list[AuthorizedTestCommand] = []
        for command in commands:
            if _uses_shell_syntax(command):
                raise ValueError("repo patch verification command contains prohibited shell syntax")
            argv = tuple(shlex.split(command))
            if not argv:
                raise ValueError("repo patch verification command is empty")
            if argv not in self.allowed_commands:
                raise ValueError("repo patch verification command is not policy-authorized")
            executable_path = _resolve_executable(argv[0])
            executable_digest = _file_digest(executable_path)
            command_digest = _canonical_digest(
                {
                    "argv": argv,
                    "executable_path": str(executable_path),
                    "executable_digest": executable_digest,
                }
            )
            authorized.append(
                AuthorizedTestCommand(
                    argv=argv,
                    executable_path=str(executable_path),
                    executable_digest=executable_digest,
                    command_digest=command_digest,
                )
            )
        return tuple(authorized)


def validate_authorized_test_commands(
    records: Sequence[dict[str, Any]],
    policy: RepoPatchTestCommandPolicy,
) -> tuple[AuthorizedTestCommand, ...]:
    commands: list[str] = []
    for record in records:
        argv = record.get("argv")
        if not isinstance(argv, list) or any(not isinstance(value, str) for value in argv):
            raise ValueError("repo patch authorized command record has invalid argv")
        commands.append(shlex.join(argv))
    authorized = policy.authorize(commands)
    if [command.to_dict() for command in authorized] != list(records):
        raise ValueError("repo patch authorized command record drifted from current policy or executable")
    return authorized


def _resolve_executable(value: str) -> Path:
    candidate = Path(value)
    resolved_text = str(candidate) if candidate.is_absolute() else shutil.which(value)
    if not resolved_text:
        raise ValueError("repo patch verification executable is unavailable")
    resolved = Path(resolved_text).resolve()
    try:
        metadata = resolved.stat(follow_symlinks=False)
    except OSError as exc:
        raise ValueError(f"repo patch verification executable is unavailable: {exc}") from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
        raise ValueError("repo patch verification executable is not a regular executable file")
    return resolved


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _uses_shell_syntax(command: str) -> bool:
    stripped = command.strip()
    return stripped.startswith("cd ") or any(
        token in command for token in ("&&", "||", ";", "|", ">", "<", "$(", "`")
    )
