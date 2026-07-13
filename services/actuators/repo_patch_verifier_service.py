"""Keyless sidecar that executes repo-patch checks outside the authority boundary."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import signal
import socket
import stat
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

from shared.mesh_runtime.repo_patch_authority import receive_json_frame, send_json_frame
from shared.mesh_runtime.repo_patch_verifier import (
    MAX_VERIFIER_FRAME_BYTES,
    VERIFIER_RECEIPT_STATE_SLICE,
    VERIFIER_RESPONSE_VERSION,
    canonical_digest,
    validate_verifier_request,
    workspace_manifest_digest,
)
from shared.mesh_runtime.schema_validation import validate_payload


VERIFIER_WORKER_STATE_SLICE = "mesh.repo_patch_verifier_worker.v1"
_EMPTY_DIGEST = "sha256:" + hashlib.sha256(b"").hexdigest()


class RepoPatchVerifierService:
    """Serial verifier supervisor with a distinct untrusted command UID."""

    def __init__(
        self,
        socket_path: str | Path,
        input_root: str | Path,
        scratch_root: str | Path,
        ledger_directory: str | Path,
        *,
        allowed_authority_uids: set[int] | frozenset[int],
        runner_uid: int,
        runner_gid: int,
        verifier_image_digest: str,
        sandbox_profile_digest: str,
        socket_gid: int | None = None,
        max_frame_bytes: int = MAX_VERIFIER_FRAME_BYTES,
        require_identity_separation: bool = True,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.input_root = Path(input_root)
        self.scratch_root = Path(scratch_root)
        self.ledger_directory = Path(ledger_directory)
        self.allowed_authority_uids = frozenset(allowed_authority_uids)
        self.runner_uid = runner_uid
        self.runner_gid = runner_gid
        self.verifier_image_digest = verifier_image_digest
        self.sandbox_profile_digest = sandbox_profile_digest
        self.socket_gid = socket_gid
        self.max_frame_bytes = max_frame_bytes
        self.require_identity_separation = require_identity_separation
        self._listener: socket.socket | None = None
        for path in (self.socket_path, self.input_root, self.scratch_root, self.ledger_directory):
            if not path.is_absolute():
                raise ValueError("repo patch verifier paths must be absolute")
        if not self.allowed_authority_uids or any(uid < 0 for uid in self.allowed_authority_uids):
            raise ValueError("repo patch verifier requires allowed authority UIDs")
        if runner_uid < 0 or runner_gid < 0:
            raise ValueError("repo patch verifier runner identity is invalid")
        if require_identity_separation and (os.geteuid() == runner_uid or os.getegid() == runner_gid):
            raise ValueError("repo patch verifier supervisor and command identities must be distinct")
        if socket_gid is not None and socket_gid < 0:
            raise ValueError("repo patch verifier socket gid is invalid")
        if not 1024 <= max_frame_bytes <= MAX_VERIFIER_FRAME_BYTES:
            raise ValueError("repo patch verifier frame limit is invalid")
        for digest, label in (
            (verifier_image_digest, "image"),
            (sandbox_profile_digest, "sandbox profile"),
        ):
            if not _is_digest(digest):
                raise ValueError(f"repo patch verifier {label} digest is invalid")

    def start(self) -> None:
        if self._listener is not None:
            raise RuntimeError("repo patch verifier service is already started")
        _prepare_directory(self.socket_path.parent, 0o750, gid=self.socket_gid)
        if self.input_root.is_symlink() or not self.input_root.is_dir():
            raise PermissionError("repo patch verifier input root is not a real directory")
        _prepare_directory(self.scratch_root, 0o711)
        _prepare_directory(self.ledger_directory, 0o700)
        self._recover_interrupted_jobs()
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise PermissionError("repo patch verifier socket path already exists")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.socket_path))
            if self.socket_gid is not None:
                os.chown(self.socket_path, -1, self.socket_gid)
            os.chmod(self.socket_path, 0o660)
            listener.listen(8)
        except Exception:
            listener.close()
            self._remove_socket()
            raise
        self._listener = listener

    def serve_once(self) -> None:
        if self._listener is None:
            raise RuntimeError("repo patch verifier service is not started")
        connection, _ = self._listener.accept()
        with connection:
            connection.settimeout(40.0)
            peer_uid = _peer_uid(connection)
            request = receive_json_frame(connection, max_frame_bytes=self.max_frame_bytes)
            response = self.handle_request(request, peer_uid=peer_uid)
            send_json_frame(connection, response, max_frame_bytes=self.max_frame_bytes)

    def serve_forever(self) -> None:
        while self._listener is not None:
            try:
                self.serve_once()
            except (ConnectionError, OSError, TimeoutError, ValueError):
                if self._listener is None:
                    return

    def handle_request(self, request: dict[str, Any], *, peer_uid: int) -> dict[str, Any]:
        base = self._response_base(request)
        if peer_uid not in self.allowed_authority_uids:
            return {**base, "status": "rejected", "code": "authority_peer_rejected", "test_results": []}
        try:
            validate_verifier_request(request)
            if request["verifier_image_digest"] != self.verifier_image_digest:
                raise ValueError("repo patch verifier image digest mismatch")
            if request["sandbox_profile_digest"] != self.sandbox_profile_digest:
                raise ValueError("repo patch verifier sandbox profile mismatch")
            timeout_seconds = request["timeout_seconds"]
            output_limit_bytes = request["output_limit_bytes"]
            if not isinstance(timeout_seconds, int) or isinstance(timeout_seconds, bool) or not 1 <= timeout_seconds <= 30:
                raise ValueError("repo patch verifier timeout rejected")
            if (
                not isinstance(output_limit_bytes, int)
                or isinstance(output_limit_bytes, bool)
                or not 1024 <= output_limit_bytes <= 64 * 1024
            ):
                raise ValueError("repo patch verifier output limit rejected")
            terminal_path = self._terminal_path(request["job_id"])
            if terminal_path.exists():
                terminal = _read_json_file(terminal_path)
                if terminal.get("request_digest") != request["request_digest"]:
                    raise ValueError("repo patch verifier replay binding mismatch")
                validate_payload("repo-patch-verifier-response.schema.json", terminal)
                return terminal
            running_path = self._running_path(request["job_id"])
            self._create_running_record(running_path, request)
        except (KeyError, OSError, TypeError, ValueError):
            return {**base, "status": "rejected", "code": "request_contract_rejected", "test_results": []}

        try:
            response = self._verify(request)
        except (OSError, RuntimeError, TypeError, ValueError):
            response = {**base, "status": "rejected", "code": "verifier_internal_failure", "test_results": []}
        try:
            validate_payload("repo-patch-verifier-response.schema.json", response)
            _write_json_atomic(self._terminal_path(request["job_id"]), response)
            return response
        finally:
            running_path.unlink(missing_ok=True)
            _fsync_directory(self.ledger_directory)

    def _verify(self, request: dict[str, Any]) -> dict[str, Any]:
        workspace_id = request["workspace_id"]
        source = self.input_root / workspace_id
        if source.parent != self.input_root or source.is_symlink() or not source.is_dir():
            raise ValueError("repo patch verifier handoff workspace rejected")
        before = workspace_manifest_digest(source)
        if before != request["workspace_manifest_digest"]:
            raise ValueError("repo patch verifier handoff manifest drifted")
        scratch = self.scratch_root / request["job_id"]
        if scratch.exists() or scratch.is_symlink():
            raise ValueError("repo patch verifier scratch path already exists")
        try:
            shutil.copytree(source, scratch, ignore=shutil.ignore_patterns(".git"), symlinks=False)
            copied = workspace_manifest_digest(scratch)
            if copied != before:
                raise ValueError("repo patch verifier scratch copy mismatch")
            if self.require_identity_separation:
                _prepare_runner_tree(scratch, self.runner_uid, self.runner_gid)
            results: list[dict[str, Any]] = []
            for command in request["commands"]:
                self._validate_command(command)
                result = self._execute_command(
                    [command["executable_path"], *command["argv"][1:]],
                    cwd=scratch,
                    timeout_seconds=request["timeout_seconds"],
                    output_limit_bytes=request["output_limit_bytes"],
                )
                results.append(result)
                if result["timed_out"]:
                    return self._terminal_response(request, before, before, results, "rejected", "command_timed_out")
                if result["output_limit_exceeded"]:
                    return self._terminal_response(request, before, before, results, "rejected", "output_limit_exceeded")
                if result["returncode"] != 0:
                    return self._terminal_response(request, before, before, results, "rejected", "command_failed")
            after = workspace_manifest_digest(scratch)
            if after != before:
                return self._terminal_response(request, before, after, results, "rejected", "workspace_mutation_rejected")
            return self._terminal_response(request, before, after, results, "succeeded", "verified")
        finally:
            self._kill_runner_processes()
            if scratch.exists():
                shutil.rmtree(scratch)

    def _validate_command(self, command: dict[str, Any]) -> None:
        argv = command.get("argv")
        executable_path = command.get("executable_path")
        if not isinstance(argv, list) or not argv or any(not isinstance(value, str) or not value for value in argv):
            raise ValueError("repo patch verifier command argv rejected")
        if not isinstance(executable_path, str) or not Path(executable_path).is_absolute():
            raise ValueError("repo patch verifier executable path rejected")
        executable = Path(executable_path)
        metadata = executable.stat(follow_symlinks=False)
        if not stat.S_ISREG(metadata.st_mode) or not os.access(executable, os.X_OK):
            raise ValueError("repo patch verifier executable rejected")
        if _file_digest(executable) != command.get("executable_digest"):
            raise ValueError("repo patch verifier executable digest drifted")
        expected_command_digest = canonical_digest(
            {
                "argv": argv,
                "executable_path": executable_path,
                "executable_digest": command["executable_digest"],
            }
        )
        if command.get("command_digest") != expected_command_digest:
            raise ValueError("repo patch verifier command digest drifted")

    def _execute_command(
        self,
        argv: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        output_limit_bytes: int,
    ) -> dict[str, Any]:
        popen_options: dict[str, Any] = {}
        if self.require_identity_separation:
            popen_options = {
                "user": self.runner_uid,
                "group": self.runner_gid,
                "extra_groups": (),
                "umask": 0o077,
            }
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            close_fds=True,
            start_new_session=True,
            env=_verifier_command_environment(cwd),
            **popen_options,
        )
        assert process.stdout is not None and process.stderr is not None
        selector = selectors.DefaultSelector()
        streams = {process.stdout: "stdout", process.stderr: "stderr"}
        digests = {name: hashlib.sha256() for name in streams.values()}
        byte_counts = {name: 0 for name in streams.values()}
        for stream in streams:
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, data=streams[stream])
        deadline = time.monotonic() + timeout_seconds
        timed_out = False
        output_limit_exceeded = False
        try:
            while selector.get_map():
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                for key, _ in selector.select(timeout=min(0.05, max(0.0, deadline - time.monotonic()))):
                    chunk = os.read(key.fd, 8192)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    name = str(key.data)
                    byte_counts[name] += len(chunk)
                    digests[name].update(chunk)
                    if byte_counts["stdout"] + byte_counts["stderr"] > output_limit_bytes:
                        output_limit_exceeded = True
                        break
                if output_limit_exceeded:
                    break
                if process.poll() is not None and not selector.get_map():
                    break
        finally:
            selector.close()
        if timed_out or output_limit_exceeded or process.poll() is None:
            _kill_process_group(process)
            self._kill_runner_processes()
        returncode = process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
        return {
            "argv": argv,
            "returncode": returncode,
            "stdout_digest": "sha256:" + digests["stdout"].hexdigest(),
            "stderr_digest": "sha256:" + digests["stderr"].hexdigest(),
            "stdout_bytes": byte_counts["stdout"],
            "stderr_bytes": byte_counts["stderr"],
            "timed_out": timed_out,
            "output_limit_exceeded": output_limit_exceeded,
        }

    def _kill_runner_processes(self) -> None:
        if not self.require_identity_separation or not Path("/proc").is_dir():
            return
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                status_text = (entry / "status").read_text(encoding="utf-8")
                uid_line = next(line for line in status_text.splitlines() if line.startswith("Uid:"))
                real_uid = int(uid_line.split()[1])
                if real_uid == self.runner_uid:
                    os.kill(int(entry.name), signal.SIGKILL)
            except (FileNotFoundError, PermissionError, ProcessLookupError, StopIteration, ValueError):
                continue

    def _terminal_response(
        self,
        request: dict[str, Any],
        before: str,
        after: str,
        results: list[dict[str, Any]],
        status_value: str,
        code: str,
    ) -> dict[str, Any]:
        return {
            **self._response_base(request),
            "status": status_value,
            "code": code,
            "workspace_manifest_before": before,
            "workspace_manifest_after": after,
            "test_results": results,
        }

    def _response_base(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": VERIFIER_RESPONSE_VERSION,
            "state_slice": VERIFIER_RECEIPT_STATE_SLICE,
            "job_id": str(request.get("job_id") or "invalid"),
            "request_digest": str(request.get("request_digest") or _EMPTY_DIGEST),
            "verifier_uid": os.geteuid(),
            "runner_uid": self.runner_uid,
            "verifier_image_digest": self.verifier_image_digest,
            "sandbox_profile_digest": self.sandbox_profile_digest,
            "workspace_manifest_before": str(request.get("workspace_manifest_digest") or _EMPTY_DIGEST),
            "workspace_manifest_after": str(request.get("workspace_manifest_digest") or _EMPTY_DIGEST),
        }

    def _create_running_record(self, path: Path, request: dict[str, Any]) -> None:
        payload = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_directory(self.ledger_directory)

    def _recover_interrupted_jobs(self) -> None:
        for running_path in sorted(self.ledger_directory.glob("verifier_job_*.running.json")):
            try:
                request = _read_json_file(running_path)
                terminal_path = self._terminal_path(str(request["job_id"]))
                if terminal_path.exists():
                    terminal = _read_json_file(terminal_path)
                    if terminal.get("request_digest") != request.get("request_digest"):
                        raise ValueError("repo patch verifier recovery binding mismatch")
                    validate_payload("repo-patch-verifier-response.schema.json", terminal)
                else:
                    response = {
                        **self._response_base(request),
                        "status": "rejected",
                        "code": "aborted_by_worker_restart",
                        "test_results": [],
                    }
                    _write_json_atomic(terminal_path, response)
            finally:
                running_path.unlink(missing_ok=True)
                _fsync_directory(self.ledger_directory)

    def _running_path(self, job_id: str) -> Path:
        return self.ledger_directory / f"{job_id}.running.json"

    def _terminal_path(self, job_id: str) -> Path:
        return self.ledger_directory / f"{job_id}.terminal.json"

    def close(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.close()
        self._remove_socket()

    def _remove_socket(self) -> None:
        try:
            metadata = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(metadata.st_mode) and metadata.st_uid == os.geteuid():
            self.socket_path.unlink()


def _verifier_command_environment(cwd: Path) -> dict[str, str]:
    return {
        "HOME": str(cwd),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _is_digest(value: str) -> bool:
    return len(value) == 71 and value.startswith("sha256:") and all(character in "0123456789abcdef" for character in value[7:])


def _prepare_directory(path: Path, mode: int, *, gid: int | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise PermissionError("repo patch verifier directory is not a real directory")
    if gid is not None:
        os.chown(path, -1, gid)
    os.chmod(path, mode)


def _prepare_runner_tree(root: Path, uid: int, gid: int) -> None:
    for path in [root, *root.rglob("*")]:
        metadata = path.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            os.chown(path, 0, gid, follow_symlinks=False)
            os.chmod(path, 0o770)
            continue
        os.chown(path, uid, gid, follow_symlinks=False)
        os.chmod(path, 0o700 if metadata.st_mode & 0o111 else 0o600)


def _peer_uid(connection: socket.socket) -> int:
    if not hasattr(socket, "SO_PEERCRED"):
        raise OSError("repo patch verifier requires Linux SO_PEERCRED")
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _, uid, _ = struct.unpack("3i", credentials)
    return int(uid)


def _read_json_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("repo patch verifier ledger record must be an object")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.new")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("repo patch verifier ledger write made no progress")
        remaining = remaining[written:]


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _required_absolute_path(name: str) -> Path:
    raw = os.environ.get(name, "").strip()
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise RuntimeError(f"{name} must be an absolute path")
    return path


def main() -> int:
    if os.geteuid() != 0:
        raise RuntimeError("repo patch verifier supervisor must run as root to drop the command identity")
    allowed_uids = {
        int(value.strip())
        for value in os.environ.get("MESH_REPO_PATCH_VERIFIER_ALLOWED_AUTHORITY_UIDS", "").split(",")
        if value.strip()
    }
    service = RepoPatchVerifierService(
        _required_absolute_path("MESH_REPO_PATCH_VERIFIER_SOCKET_PATH"),
        _required_absolute_path("MESH_REPO_PATCH_VERIFIER_INPUT_ROOT"),
        _required_absolute_path("MESH_REPO_PATCH_VERIFIER_SCRATCH_ROOT"),
        _required_absolute_path("MESH_REPO_PATCH_VERIFIER_LEDGER_DIRECTORY"),
        allowed_authority_uids=allowed_uids,
        runner_uid=int(os.environ["MESH_REPO_PATCH_VERIFIER_RUNNER_UID"]),
        runner_gid=int(os.environ["MESH_REPO_PATCH_VERIFIER_RUNNER_GID"]),
        verifier_image_digest=os.environ["MESH_REPO_PATCH_VERIFIER_IMAGE_DIGEST"].strip(),
        sandbox_profile_digest=os.environ["MESH_REPO_PATCH_VERIFIER_SANDBOX_PROFILE_DIGEST"].strip(),
        socket_gid=int(os.environ["MESH_REPO_PATCH_VERIFIER_SOCKET_GID"]),
    )
    try:
        service.start()
        service.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
