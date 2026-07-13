"""Detached-worktree preparation, verification, and atomic promotion for repo patches."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence


MAX_TARGET_FILE_BYTES = 1024 * 1024


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _file_digest(root: Path, relative_path: Path, label: str) -> str:
    return _sha256_bytes(_read_contained_regular_file(root, relative_path, label))


def _run_git(repo: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        env=_command_environment(),
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise ValueError(diagnostic)
    return completed.stdout.strip()


def _command_environment() -> dict[str, str]:
    environment = {
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    home = os.environ.get("HOME")
    if home:
        environment["HOME"] = home
    return environment


@dataclass(frozen=True)
class PreparedPatchReceipt:
    base_commit: str
    base_tree: str
    target_path: str
    target_preimage_digest: str
    target_postimage_digest: str
    authorized_diff_digest: str
    changed_paths: tuple[str, ...]
    test_results: tuple[dict[str, Any], ...]


class PreparedRepoPatch:
    """One detached preparation that can be promoted at most once."""

    def __init__(
        self,
        *,
        source_repo: Path,
        workspace: Path,
        relative_target: Path,
        allowed_paths: frozenset[str],
        base_commit: str,
        base_tree: str,
        target_preimage_digest: str,
        original_bytes: bytes,
        updated_bytes: bytes,
    ) -> None:
        self.source_repo = source_repo
        self.workspace = workspace
        self.relative_target = relative_target
        self.allowed_paths = allowed_paths
        self.base_commit = base_commit
        self.base_tree = base_tree
        self.target_preimage_digest = target_preimage_digest
        self.original_bytes = original_bytes
        self.updated_bytes = updated_bytes
        self.target_postimage_digest = _sha256_bytes(updated_bytes)
        self.authorized_diff_digest = _sha256_bytes(original_bytes + b"\0" + updated_bytes)
        self.test_results: list[dict[str, Any]] = []
        self.changed_paths: tuple[str, ...] = ()
        self.verified = False
        self.promoted = False
        self.closed = False

    def accept_verifier_results(
        self,
        commands: Sequence[Sequence[str]],
        results: Sequence[dict[str, Any]],
    ) -> PreparedPatchReceipt:
        """Accept bound sidecar results, then independently verify the canonical worktree."""

        if self.closed:
            raise ValueError("repo patch workspace is closed")
        if self.verified:
            raise ValueError("repo patch workspace was already verified")
        if len(commands) != len(results):
            raise ValueError("repo patch verifier result count mismatch")
        for command, result in zip(commands, results, strict=True):
            arguments = [str(value) for value in command]
            if not arguments or any(not value for value in arguments):
                raise ValueError("repo patch verification command contains an empty argument")
            if result.get("argv") != arguments:
                raise ValueError("repo patch verifier result argv mismatch")
            returncode = result.get("returncode")
            stdout_digest = result.get("stdout_digest")
            stderr_digest = result.get("stderr_digest")
            if not isinstance(returncode, int) or isinstance(returncode, bool):
                raise ValueError("repo patch verifier result return code rejected")
            if not _is_digest(stdout_digest) or not _is_digest(stderr_digest):
                raise ValueError("repo patch verifier result output digest rejected")
            if returncode != 0:
                raise ValueError("repo patch verification command failed")
            self.test_results.append(
                {
                    "argv": arguments,
                    "returncode": returncode,
                    "stdout_digest": stdout_digest,
                    "stderr_digest": stderr_digest,
                }
            )

        self.changed_paths = self._changed_paths()
        undeclared = sorted(set(self.changed_paths) - self.allowed_paths)
        if undeclared:
            raise ValueError(f"repo patch verification produced undeclared changes: {undeclared}")
        expected_target = self.relative_target.as_posix()
        if self.changed_paths != (expected_target,):
            raise ValueError("repo patch verification did not produce exactly the authorized target change")
        if _file_digest(self.workspace, self.relative_target, "workspace target") != self.target_postimage_digest:
            raise ValueError("repo patch workspace postimage drifted from the authorized bytes")
        self.verified = True
        return self.receipt()

    def promote(self) -> PreparedPatchReceipt:
        if self.closed:
            raise ValueError("repo patch workspace is closed")
        if not self.verified:
            raise ValueError("repo patch workspace must verify before promotion")
        if self.promoted:
            raise ValueError("repo patch workspace was already promoted")
        if _run_git(self.source_repo, "rev-parse", "HEAD") != self.base_commit:
            raise ValueError("source repository HEAD changed after preparation")
        if _run_git(self.source_repo, "rev-parse", "HEAD^{tree}") != self.base_tree:
            raise ValueError("source repository tree changed after preparation")
        if _file_digest(self.source_repo, self.relative_target, "source target") != self.target_preimage_digest:
            raise ValueError("source target preimage changed after preparation")
        status_output = _run_git(self.source_repo, "status", "--porcelain=v1", "--untracked-files=all")
        if status_output:
            raise ValueError("source repository became dirty after preparation")

        _promote_contained_regular_file(
            self.source_repo,
            self.relative_target,
            expected_preimage_digest=self.target_preimage_digest,
            updated_bytes=self.updated_bytes,
            expected_postimage_digest=self.target_postimage_digest,
        )
        self.promoted = True
        return self.receipt()

    def receipt(self) -> PreparedPatchReceipt:
        return PreparedPatchReceipt(
            base_commit=self.base_commit,
            base_tree=self.base_tree,
            target_path=self.relative_target.as_posix(),
            target_preimage_digest=self.target_preimage_digest,
            target_postimage_digest=self.target_postimage_digest,
            authorized_diff_digest=self.authorized_diff_digest,
            changed_paths=self.changed_paths,
            test_results=tuple(self.test_results),
        )

    def close(self) -> None:
        if self.closed:
            return
        try:
            subprocess.run(
                ["git", "-C", str(self.source_repo), "worktree", "remove", "--force", str(self.workspace)],
                capture_output=True,
                check=False,
                timeout=30,
                env=_command_environment(),
            )
        finally:
            if self.workspace.exists():
                shutil.rmtree(self.workspace)
            subprocess.run(
                ["git", "-C", str(self.source_repo), "worktree", "prune"],
                capture_output=True,
                check=False,
                timeout=30,
                env=_command_environment(),
            )
            self.closed = True

    def __enter__(self) -> PreparedRepoPatch:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _changed_paths(self) -> tuple[str, ...]:
        completed = subprocess.run(
            ["git", "-C", str(self.workspace), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True,
            check=False,
            timeout=30,
            env=_command_environment(),
        )
        if completed.returncode != 0:
            raise ValueError("repo patch workspace status inventory failed")
        entries = [entry for entry in completed.stdout.split(b"\0") if entry]
        paths: list[str] = []
        for entry in entries:
            if len(entry) < 4:
                raise ValueError("repo patch workspace status entry is malformed")
            status_code = entry[:2]
            raw_path = entry[3:]
            if status_code[:1] in {b"R", b"C"} or status_code[1:2] in {b"R", b"C"}:
                raise ValueError("repo patch workspace renames and copies are not authorized")
            paths.append(raw_path.decode("utf-8", errors="strict"))
        return tuple(sorted(paths))


class RepoPatchWorkspaceManager:
    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    def prepare(
        self,
        *,
        repo_path: str | Path,
        target_file: str,
        allowed_paths: Sequence[str],
        find_text: str,
        replace_text: str,
        workspace_id: str,
    ) -> PreparedRepoPatch:
        source_repo = Path(repo_path)
        if not source_repo.is_absolute() or source_repo.is_symlink():
            raise ValueError("source repository must be an absolute non-symlink path")
        source_repo = source_repo.resolve()
        if _run_git(source_repo, "rev-parse", "--show-toplevel") != str(source_repo):
            raise ValueError("source repository path must be the Git worktree root")
        if _run_git(source_repo, "status", "--porcelain=v1", "--untracked-files=all"):
            raise ValueError("source repository must be clean before preparation")
        try:
            self.workspace_root.relative_to(source_repo)
        except ValueError:
            pass
        else:
            raise ValueError("repo patch workspace root must be outside the source repository")
        if self.workspace_root.is_symlink():
            raise ValueError("repo patch workspace root must not be a symlink")

        relative_target = Path(target_file)
        if (
            relative_target.is_absolute()
            or ".." in relative_target.parts
            or relative_target.as_posix() in {"", "."}
            or relative_target.as_posix() != target_file
        ):
            raise ValueError("repo patch target must be a portable relative path")
        allowed = frozenset(Path(value).as_posix() for value in allowed_paths)
        if relative_target.as_posix() not in allowed:
            raise ValueError("repo patch target falls outside allowed patch scope")
        _validate_git_index_regular_blob(source_repo, relative_target, "source target")
        original_bytes = _read_contained_regular_file(source_repo, relative_target, "source target")
        try:
            original_text = original_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("repo patch target must be UTF-8 text") from exc
        if find_text not in original_text:
            raise ValueError("repo patch anchor not found in source target")
        updated_bytes = original_text.replace(find_text, replace_text, 1).encode("utf-8")

        base_commit = _run_git(source_repo, "rev-parse", "HEAD")
        base_tree = _run_git(source_repo, "rev-parse", "HEAD^{tree}")
        safe_workspace_id = "workspace_" + hashlib.sha256(workspace_id.encode("utf-8")).hexdigest()
        workspace = self.workspace_root / safe_workspace_id
        if workspace.exists() or workspace.is_symlink():
            raise ValueError("repo patch workspace already exists")
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            ["git", "-C", str(source_repo), "worktree", "add", "--detach", str(workspace), base_commit],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
            env=_command_environment(),
        )
        if completed.returncode != 0:
            raise ValueError(completed.stderr.strip() or "repo patch worktree creation failed")
        try:
            _validate_git_index_regular_blob(workspace, relative_target, "workspace target")
            if _file_digest(workspace, relative_target, "workspace target") != _sha256_bytes(original_bytes):
                raise ValueError("repo patch worktree target does not match the authorized preimage")
            _write_contained_regular_file(workspace, relative_target, updated_bytes, "workspace target")
            return PreparedRepoPatch(
                source_repo=source_repo,
                workspace=workspace,
                relative_target=relative_target,
                allowed_paths=allowed,
                base_commit=base_commit,
                base_tree=base_tree,
                target_preimage_digest=_sha256_bytes(original_bytes),
                original_bytes=original_bytes,
                updated_bytes=updated_bytes,
            )
        except Exception:
            subprocess.run(
                ["git", "-C", str(source_repo), "worktree", "remove", "--force", str(workspace)],
                capture_output=True,
                check=False,
                timeout=30,
                env=_command_environment(),
            )
            if workspace.exists():
                shutil.rmtree(workspace)
            raise


def _validate_git_index_regular_blob(repo: Path, relative_path: Path, label: str) -> None:
    completed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--stage", "-z", "--", relative_path.as_posix()],
        capture_output=True,
        check=False,
        timeout=30,
        env=_command_environment(),
    )
    if completed.returncode != 0:
        raise ValueError(f"{label} Git index lookup failed")
    entries = [entry for entry in completed.stdout.split(b"\0") if entry]
    if len(entries) != 1:
        raise ValueError(f"{label} must be exactly one Git-indexed regular blob")
    try:
        metadata, indexed_path = entries[0].split(b"\t", 1)
        mode, _object_id, stage = metadata.split(b" ", 2)
    except ValueError as exc:
        raise ValueError(f"{label} Git index entry is malformed") from exc
    if indexed_path.decode("utf-8", errors="strict") != relative_path.as_posix():
        raise ValueError(f"{label} Git index path mismatch")
    if mode not in {b"100644", b"100755"} or stage != b"0":
        raise ValueError(f"{label} must be a stage-zero Git-indexed regular blob")


def _is_digest(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


@contextmanager
def _open_contained_parent(root: Path, relative_path: Path, label: str) -> Iterator[tuple[int, str]]:
    parts = relative_path.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} path is not portable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        current_descriptor = os.open(root, flags)
    except OSError as exc:
        raise ValueError(f"{label} root is unavailable without symlink traversal: {exc}") from exc
    try:
        for component in parts[:-1]:
            try:
                next_descriptor = os.open(component, flags, dir_fd=current_descriptor)
            except OSError as exc:
                raise ValueError(f"{label} parent contains a symlink or non-directory component: {exc}") from exc
            os.close(current_descriptor)
            current_descriptor = next_descriptor
        yield current_descriptor, parts[-1]
    finally:
        os.close(current_descriptor)


def _open_contained_regular_file(parent_descriptor: int, filename: str, label: str, flags: int) -> int:
    try:
        descriptor = os.open(
            filename,
            flags | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
    except OSError as exc:
        raise ValueError(f"{label} is unavailable without symlink traversal: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"{label} must be a regular file")
        if metadata.st_nlink != 1:
            raise ValueError(f"{label} must not be hard linked")
        if metadata.st_size > MAX_TARGET_FILE_BYTES:
            raise ValueError(f"{label} exceeds the bounded file-size limit")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _read_descriptor(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    while True:
        chunk = os.read(descriptor, 64 * 1024)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


def _write_descriptor(descriptor: int, payload: bytes) -> None:
    os.ftruncate(descriptor, 0)
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise ValueError("repo patch file write made no progress")
        view = view[written:]
    os.fsync(descriptor)


def _read_contained_regular_file(root: Path, relative_path: Path, label: str) -> bytes:
    with _open_contained_parent(root, relative_path, label) as (parent_descriptor, filename):
        descriptor = _open_contained_regular_file(parent_descriptor, filename, label, os.O_RDONLY)
        try:
            return _read_descriptor(descriptor)
        finally:
            os.close(descriptor)


def _write_contained_regular_file(root: Path, relative_path: Path, payload: bytes, label: str) -> None:
    if len(payload) > MAX_TARGET_FILE_BYTES:
        raise ValueError(f"{label} postimage exceeds the bounded file-size limit")
    with _open_contained_parent(root, relative_path, label) as (parent_descriptor, filename):
        descriptor = _open_contained_regular_file(parent_descriptor, filename, label, os.O_WRONLY)
        try:
            _write_descriptor(descriptor, payload)
        finally:
            os.close(descriptor)


def _promote_contained_regular_file(
    root: Path,
    relative_path: Path,
    *,
    expected_preimage_digest: str,
    updated_bytes: bytes,
    expected_postimage_digest: str,
) -> None:
    if len(updated_bytes) > MAX_TARGET_FILE_BYTES:
        raise ValueError("source target postimage exceeds the bounded file-size limit")
    with _open_contained_parent(root, relative_path, "source target") as (parent_descriptor, filename):
        source_descriptor = _open_contained_regular_file(parent_descriptor, filename, "source target", os.O_RDONLY)
        try:
            source_metadata = os.fstat(source_descriptor)
            source_bytes = _read_descriptor(source_descriptor)
        finally:
            os.close(source_descriptor)
        if _sha256_bytes(source_bytes) != expected_preimage_digest:
            raise ValueError("source target changed immediately before promotion")

        staging_name = f".{filename}.mesh-promote-{os.getpid()}"
        staging_descriptor: int | None = None
        try:
            staging_descriptor = os.open(
                staging_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
                stat.S_IMODE(source_metadata.st_mode),
                dir_fd=parent_descriptor,
            )
            _write_descriptor(staging_descriptor, updated_bytes)
            os.close(staging_descriptor)
            staging_descriptor = None

            check_descriptor = _open_contained_regular_file(
                parent_descriptor,
                staging_name,
                "repo patch promotion staging file",
                os.O_RDONLY,
            )
            try:
                staging_digest = _sha256_bytes(_read_descriptor(check_descriptor))
            finally:
                os.close(check_descriptor)
            if staging_digest != expected_postimage_digest:
                raise ValueError("repo patch promotion staging digest mismatch")

            current_descriptor = _open_contained_regular_file(
                parent_descriptor,
                filename,
                "source target",
                os.O_RDONLY,
            )
            try:
                current_digest = _sha256_bytes(_read_descriptor(current_descriptor))
            finally:
                os.close(current_descriptor)
            if current_digest != expected_preimage_digest:
                raise ValueError("source target changed immediately before promotion")
            os.replace(staging_name, filename, src_dir_fd=parent_descriptor, dst_dir_fd=parent_descriptor)
            os.fsync(parent_descriptor)
        except OSError as exc:
            raise ValueError(f"repo patch atomic promotion failed: {exc}") from exc
        finally:
            if staging_descriptor is not None:
                os.close(staging_descriptor)
            try:
                os.unlink(staging_name, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
