"""Fail-closed client contract for isolated repo-patch verification."""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import stat
import struct
from copy import deepcopy
from pathlib import Path
from typing import Any, Sequence

from .perennial.signing import verify_ed25519_signature_proof
from .repo_patch_authority import receive_json_frame, send_json_frame
from .repo_patch_test_policy import AuthorizedTestCommand
from .schema_validation import validate_payload


VERIFIER_REQUEST_VERSION = "mesh.repo_patch_verifier_request.v1"
VERIFIER_RESPONSE_VERSION = "mesh.repo_patch_verifier_response.v2"
VERIFIER_PROTOCOL_STATE_SLICE = "mesh.repo_patch_verifier_protocol.v1"
VERIFIER_RECEIPT_STATE_SLICE = "mesh.repo_patch_verifier_receipt.v2"
VERIFIER_HANDOFF_STATE_SLICE = "mesh.repo_patch_verifier_workspace_handoff.v1"
VERIFIER_RESPONSE_SCHEMA = "repo-patch-verifier-response-v2.schema.json"
VERIFIER_RECEIPT_SIGNING_PROFILE = "mesh-repo-patch-verifier-receipt-ed25519-v2"
MAX_VERIFIER_FRAME_BYTES = 1024 * 1024
MAX_WORKSPACE_FILES = 10_000
MAX_WORKSPACE_BYTES = 64 * 1024 * 1024
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_WORKSPACE_ID_PATTERN = re.compile(r"^workspace_[0-9a-f]{64}$")
_JOB_ID_PATTERN = re.compile(r"^verifier_job_[0-9a-f]{64}$")
_GIT_OBJECT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")


class RepoPatchVerifierError(RuntimeError):
    """Raised when isolated verification fails closed."""


def canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def workspace_id_for(value: str) -> str:
    return "workspace_" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def workspace_manifest_digest(root: str | Path) -> str:
    """Hash a bounded regular-file tree while excluding detached-worktree Git metadata."""

    workspace = Path(root)
    if not workspace.is_absolute() or workspace.is_symlink() or not workspace.is_dir():
        raise ValueError("verifier workspace must be an absolute non-symlink directory")
    records: list[dict[str, Any]] = []
    file_count = 0
    total_bytes = 0
    for path in sorted(workspace.rglob("*"), key=lambda item: item.relative_to(workspace).as_posix()):
        relative = path.relative_to(workspace)
        if ".git" in relative.parts:
            continue
        metadata = path.lstat()
        portable = relative.as_posix()
        if stat.S_ISLNK(metadata.st_mode):
            raise ValueError("verifier workspace symlinks are not supported")
        if stat.S_ISDIR(metadata.st_mode):
            records.append({"path": portable, "type": "directory"})
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("verifier workspace contains a non-regular file")
        file_count += 1
        total_bytes += metadata.st_size
        if file_count > MAX_WORKSPACE_FILES or total_bytes > MAX_WORKSPACE_BYTES:
            raise ValueError("verifier workspace exceeds the bounded handoff limit")
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        records.append(
            {
                "path": portable,
                "type": "file",
                "executable": bool(stat.S_IMODE(metadata.st_mode) & 0o111),
                "size": metadata.st_size,
                "sha256": digest.hexdigest(),
            }
        )
    return canonical_digest(records)


class RepoPatchVerifierClient:
    """Peer-UID- and signing-key-pinned client for the verifier sidecar."""

    def __init__(
        self,
        socket_path: str | Path,
        *,
        expected_verifier_uid: int,
        verifier_image_digest: str,
        sandbox_profile_digest: str,
        verifier_public_key_pem: str | None = None,
        verifier_key_id: str | None = None,
        timeout_seconds: float = 35.0,
        max_frame_bytes: int = MAX_VERIFIER_FRAME_BYTES,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.expected_verifier_uid = expected_verifier_uid
        self.verifier_image_digest = verifier_image_digest
        self.sandbox_profile_digest = sandbox_profile_digest
        self.verifier_public_key_pem = _resolve_verifier_public_key(verifier_public_key_pem)
        self.verifier_key_id = _resolve_verifier_key_id(verifier_key_id)
        self.timeout_seconds = timeout_seconds
        self.max_frame_bytes = max_frame_bytes
        self._last_verified_receipt: dict[str, Any] | None = None
        if not self.socket_path.is_absolute():
            raise ValueError("repo patch verifier socket path must be absolute")
        if expected_verifier_uid < 0:
            raise ValueError("repo patch verifier UID must be non-negative")
        for value, label in (
            (verifier_image_digest, "image"),
            (sandbox_profile_digest, "sandbox profile"),
        ):
            if not _DIGEST_PATTERN.fullmatch(value):
                raise ValueError(f"repo patch verifier {label} digest is invalid")
        if timeout_seconds <= 0 or not 1024 <= max_frame_bytes <= MAX_VERIFIER_FRAME_BYTES:
            raise ValueError("repo patch verifier client limits are invalid")

    @property
    def last_verified_receipt(self) -> dict[str, Any] | None:
        """Return a defensive copy of the current request's verified terminal receipt."""

        return deepcopy(self._last_verified_receipt)

    def verify(
        self,
        *,
        workspace_id: str,
        workspace_manifest: str,
        candidate_binding: dict[str, str],
        commands: Sequence[AuthorizedTestCommand],
        timeout_seconds: int = 30,
        output_limit_bytes: int = 64 * 1024,
    ) -> tuple[dict[str, Any], ...]:
        self._last_verified_receipt = None
        if not _WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
            raise RepoPatchVerifierError("repo patch verifier workspace id rejected")
        if not _DIGEST_PATTERN.fullmatch(workspace_manifest):
            raise RepoPatchVerifierError("repo patch verifier workspace manifest rejected")
        command_records = [command.to_dict() for command in commands]
        job_binding = {
            "state_slice": VERIFIER_HANDOFF_STATE_SLICE,
            "workspace_id": workspace_id,
            "workspace_manifest_digest": workspace_manifest,
            "candidate_binding": candidate_binding,
            "commands": command_records,
            "verifier_image_digest": self.verifier_image_digest,
            "sandbox_profile_digest": self.sandbox_profile_digest,
        }
        job_id = "verifier_job_" + canonical_digest(job_binding).removeprefix("sha256:")
        unsigned = {
            "schema_version": VERIFIER_REQUEST_VERSION,
            "state_slice": VERIFIER_PROTOCOL_STATE_SLICE,
            "job_id": job_id,
            "workspace_id": workspace_id,
            "workspace_manifest_digest": workspace_manifest,
            "candidate_binding": candidate_binding,
            "commands": command_records,
            "verifier_image_digest": self.verifier_image_digest,
            "sandbox_profile_digest": self.sandbox_profile_digest,
            "timeout_seconds": timeout_seconds,
            "output_limit_bytes": output_limit_bytes,
        }
        request = {**unsigned, "request_digest": canonical_digest(unsigned)}
        validate_payload("repo-patch-verifier-request.schema.json", request)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(str(self.socket_path))
                if _peer_uid(connection) != self.expected_verifier_uid:
                    raise RepoPatchVerifierError("repo patch verifier peer identity rejected")
                send_json_frame(connection, request, max_frame_bytes=self.max_frame_bytes)
                response = receive_json_frame(connection, max_frame_bytes=self.max_frame_bytes)
        except RepoPatchVerifierError:
            raise
        except (OSError, TimeoutError, ValueError) as exc:
            raise RepoPatchVerifierError(f"repo patch verifier transport failed: {type(exc).__name__}") from exc
        try:
            validate_signed_verifier_response(
                response,
                expected_key_id=self.verifier_key_id,
                public_key_pem=self.verifier_public_key_pem,
            )
            if response["job_id"] != job_id or response["request_digest"] != request["request_digest"]:
                raise ValueError("verifier response request binding mismatch")
            if response["workspace_manifest_before"] != workspace_manifest:
                raise ValueError("verifier response input manifest mismatch")
            if response["verifier_image_digest"] != self.verifier_image_digest:
                raise ValueError("verifier response image binding mismatch")
            if response["sandbox_profile_digest"] != self.sandbox_profile_digest:
                raise ValueError("verifier response sandbox binding mismatch")
            self._last_verified_receipt = deepcopy(response)
            if response["status"] != "succeeded":
                raise RepoPatchVerifierError(f"repo patch verifier rejected: {response['code']}")
            if response["workspace_manifest_after"] != workspace_manifest:
                raise ValueError("verifier response workspace drifted")
            results = tuple(response["test_results"])
            expected_argv = [[command.executable_path, *command.argv[1:]] for command in commands]
            if [result["argv"] for result in results] != expected_argv:
                raise ValueError("verifier result command binding mismatch")
            if any(result["returncode"] != 0 for result in results):
                raise ValueError("verifier success response contains a failed command")
            return results
        except RepoPatchVerifierError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise RepoPatchVerifierError("repo patch verifier response contract rejected") from exc


def verifier_receipt_signed_payload(response: dict[str, Any]) -> dict[str, Any]:
    """Return the exact terminal fields bound by the verifier signature."""

    return {key: value for key, value in response.items() if key != "authorization_proof"}


def validate_signed_verifier_response(
    response: dict[str, Any],
    *,
    expected_key_id: str,
    public_key_pem: str,
) -> None:
    """Validate a v2 terminal receipt against an authority-pinned verifier key."""

    validate_payload(VERIFIER_RESPONSE_SCHEMA, response)
    proof = response.get("authorization_proof")
    if not isinstance(proof, dict):
        raise ValueError("repo patch verifier receipt signature is missing")
    if (
        proof.get("signing_profile") != VERIFIER_RECEIPT_SIGNING_PROFILE
        or proof.get("algorithm") != "ed25519"
        or proof.get("key_id") != expected_key_id
        or proof.get("status") != "verified"
        or proof.get("verifier") != "orbital_mesh_ed25519_v1"
        or str(proof.get("public_key_pem") or "").strip() != public_key_pem.strip()
    ):
        raise ValueError("repo patch verifier receipt signer identity rejected")
    if not verify_ed25519_signature_proof(
        verifier_receipt_signed_payload(response),
        proof,
        public_key_pem=public_key_pem,
    ):
        raise ValueError("repo patch verifier receipt signature rejected")


def validate_verifier_request(request: dict[str, Any]) -> None:
    validate_payload("repo-patch-verifier-request.schema.json", request)
    if request.get("schema_version") != VERIFIER_REQUEST_VERSION:
        raise ValueError("repo patch verifier request version mismatch")
    if request.get("state_slice") != VERIFIER_PROTOCOL_STATE_SLICE:
        raise ValueError("repo patch verifier request state slice mismatch")
    if not _JOB_ID_PATTERN.fullmatch(str(request.get("job_id") or "")):
        raise ValueError("repo patch verifier job id rejected")
    if not _WORKSPACE_ID_PATTERN.fullmatch(str(request.get("workspace_id") or "")):
        raise ValueError("repo patch verifier workspace id rejected")
    for field in (
        "workspace_manifest_digest",
        "verifier_image_digest",
        "sandbox_profile_digest",
        "request_digest",
    ):
        if not _DIGEST_PATTERN.fullmatch(str(request.get(field) or "")):
            raise ValueError(f"repo patch verifier {field} rejected")
    candidate = request["candidate_binding"]
    if not _GIT_OBJECT_PATTERN.fullmatch(candidate["base_commit"]) or not _GIT_OBJECT_PATTERN.fullmatch(
        candidate["base_tree"]
    ):
        raise ValueError("repo patch verifier Git identity rejected")
    target_path = Path(candidate["target_path"])
    if (
        target_path.is_absolute()
        or ".." in target_path.parts
        or target_path.as_posix() in {"", "."}
        or target_path.as_posix() != candidate["target_path"]
    ):
        raise ValueError("repo patch verifier target path rejected")
    for field in ("target_preimage_digest", "target_postimage_digest", "authorized_diff_digest"):
        if not _DIGEST_PATTERN.fullmatch(candidate[field]):
            raise ValueError("repo patch verifier candidate digest rejected")
    for command in request["commands"]:
        argv = command["argv"]
        if any(not value for value in argv) or not Path(command["executable_path"]).is_absolute():
            raise ValueError("repo patch verifier command identity rejected")
        if not _DIGEST_PATTERN.fullmatch(command["executable_digest"]):
            raise ValueError("repo patch verifier executable digest rejected")
        if command["command_digest"] != canonical_digest(
            {
                "argv": argv,
                "executable_path": command["executable_path"],
                "executable_digest": command["executable_digest"],
            }
        ):
            raise ValueError("repo patch verifier command digest rejected")
    supplied_digest = request.get("request_digest")
    unsigned = {key: value for key, value in request.items() if key != "request_digest"}
    if supplied_digest != canonical_digest(unsigned):
        raise ValueError("repo patch verifier request digest mismatch")


def _resolve_verifier_public_key(explicit: str | None) -> str:
    if explicit is not None:
        public_key = explicit.strip()
    else:
        raw_path = os.environ.get("MESH_REPO_PATCH_VERIFIER_PUBLIC_KEY_PATH", "").strip()
        path = Path(raw_path)
        if not raw_path or not path.is_absolute():
            raise ValueError("repo patch verifier public key path must be absolute")
        metadata = path.lstat()
        if path.is_symlink() or not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 64 * 1024:
            raise ValueError("repo patch verifier public key path rejected")
        public_key = path.read_text(encoding="utf-8").strip()
    if not public_key or "BEGIN PUBLIC KEY" not in public_key or "END PUBLIC KEY" not in public_key:
        raise ValueError("repo patch verifier public key is invalid")
    return public_key + "\n"


def _resolve_verifier_key_id(explicit: str | None) -> str:
    key_id = (
        explicit
        if explicit is not None
        else os.environ.get("MESH_REPO_PATCH_VERIFIER_KEY_ID", "")
    ).strip()
    if not key_id or len(key_id) > 128:
        raise ValueError("repo patch verifier key id is invalid")
    return key_id


def _peer_uid(connection: socket.socket) -> int:
    if not hasattr(socket, "SO_PEERCRED"):
        raise RepoPatchVerifierError("repo patch verifier peer credentials are unavailable")
    credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _, uid, _ = struct.unpack("3i", credentials)
    return int(uid)
