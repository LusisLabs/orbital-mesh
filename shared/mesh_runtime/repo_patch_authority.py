"""Authenticated Unix-socket protocol for the repo-patch authority service."""

from __future__ import annotations

import json
import re
import secrets
import socket
import struct
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .contracts import Decision, EvaluationResult
from .hsai_bridge import HSAI_EXECUTION_CONTEXT_KEY
from .perennial.signing import build_ed25519_signature_proof, verify_ed25519_signature_proof
from .schema_validation import validate_payload


AUTHORITY_REQUEST_VERSION = "mesh.repo_patch_authority_request.v1"
AUTHORITY_RESPONSE_VERSION = "mesh.repo_patch_authority_response.v1"
CLIENT_REQUEST_SIGNING_PROFILE = "mesh-repo-patch-authority-client-ed25519-v1"
AUTHORITY_RESPONSE_SIGNING_PROFILE = "mesh-repo-patch-authority-response-ed25519-v1"
MAX_FRAME_BYTES = 1024 * 1024
PREFLIGHT_RECEIPT_STATE_SLICE = "mesh.repo_patch_disposable_worktree.v1"
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_OBJECT_PATTERN = re.compile(r"^[0-9a-f]{40,64}$")


class RepoPatchAuthorityError(RuntimeError):
    """Raised when the authority transport or signed protocol fails closed."""


class DuplicateJsonKeyError(ValueError):
    """Raised when a JSON object repeats a member name."""


class RepoPatchAuthorityClient:
    """Pinned-key client for the out-of-process repo-patch authority."""

    def __init__(
        self,
        socket_path: str | Path,
        *,
        client_private_key_pem: str,
        client_key_id: str,
        authority_public_key_pem: str,
        authority_key_id: str,
        timeout_seconds: float = 10.0,
        request_ttl_seconds: int = 30,
        max_frame_bytes: int = MAX_FRAME_BYTES,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        if not self.socket_path.is_absolute():
            raise ValueError("repo patch authority socket path must be absolute")
        self.client_private_key_pem = client_private_key_pem.strip()
        self.client_key_id = client_key_id.strip()
        self.authority_public_key_pem = authority_public_key_pem.strip()
        self.authority_key_id = authority_key_id.strip()
        self.timeout_seconds = timeout_seconds
        self.request_ttl_seconds = request_ttl_seconds
        self.max_frame_bytes = max_frame_bytes
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        if not self.client_private_key_pem or not self.authority_public_key_pem:
            raise ValueError("repo patch authority client requires explicit Ed25519 key material")
        if not self.client_key_id or not self.authority_key_id:
            raise ValueError("repo patch authority client requires explicit key ids")
        if timeout_seconds <= 0 or not 1 <= request_ttl_seconds <= 60:
            raise ValueError("repo patch authority client timing configuration is invalid")
        if not 1024 <= max_frame_bytes <= MAX_FRAME_BYTES:
            raise ValueError("repo patch authority client frame limit is invalid")
        _validate_private_key(self.client_private_key_pem, self.client_key_id, CLIENT_REQUEST_SIGNING_PROFILE)

    def preflight(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Run a signed, non-mutating disposable-worktree preflight."""

        response = self._submit(
            operation="preflight",
            decision=decision,
            evaluation=evaluation,
            gate=None,
            preflight_receipt=None,
            idempotency_key=idempotency_key,
        )
        result = response.get("execution_result")
        receipt = result.get("preflight_receipt") if isinstance(result, dict) else None
        if response.get("status") != "completed" or not isinstance(receipt, dict):
            rejection = response.get("rejection")
            code = rejection.get("code") if isinstance(rejection, dict) else "invalid_preflight_response"
            raise RepoPatchAuthorityError(f"repo patch authority preflight rejected: {code}")
        validate_preflight_receipt(receipt)
        return receipt

    def execute(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict[str, Any],
        idempotency_key: str,
        preflight_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit one signed authority request and return its verified response body."""

        validate_preflight_receipt(preflight_receipt)
        return self._submit(
            operation="execute",
            decision=decision,
            evaluation=evaluation,
            gate=gate,
            preflight_receipt=preflight_receipt,
            idempotency_key=idempotency_key,
        )

    def _submit(
        self,
        *,
        operation: str,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict[str, Any] | None,
        preflight_receipt: dict[str, Any] | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if HSAI_EXECUTION_CONTEXT_KEY in decision.execution_plan.get("parameters", {}):
            raise RepoPatchAuthorityError("authority request must not carry an execution permit")
        now = self.clock().astimezone(timezone.utc)
        request_body = {
            "schema_version": AUTHORITY_REQUEST_VERSION,
            "operation": operation,
            "request_id": f"authority_request_{secrets.token_hex(32)}",
            "idempotency_key": idempotency_key,
            "issued_at": _format_time(now),
            "expires_at": _format_time(now + timedelta(seconds=self.request_ttl_seconds)),
            "client_key_id": self.client_key_id,
            "decision": decision.to_dict(),
            "evaluation": asdict(evaluation),
            "hsai_gate": gate,
            "preflight_receipt": preflight_receipt,
        }
        validate_authority_request_operation(request_body)
        request = {
            "body": request_body,
            "authorization_proof": build_ed25519_signature_proof(
                request_body,
                key_id=self.client_key_id,
                private_key_pem=self.client_private_key_pem,
                signing_profile=CLIENT_REQUEST_SIGNING_PROFILE,
            ),
        }
        validate_payload("repo-patch-authority-request.schema.json", request)

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.connect(str(self.socket_path))
                send_json_frame(connection, request, max_frame_bytes=self.max_frame_bytes)
                response = receive_json_frame(connection, max_frame_bytes=self.max_frame_bytes)
        except (OSError, TimeoutError, ValueError) as exc:
            raise RepoPatchAuthorityError(f"repo patch authority transport failed: {type(exc).__name__}") from exc

        try:
            validate_payload("repo-patch-authority-response.schema.json", response)
            response_body = response["body"]
            proof = response["authorization_proof"]
        except (KeyError, TypeError, ValueError) as exc:
            raise RepoPatchAuthorityError("repo patch authority response contract rejected") from exc
        if proof.get("key_id") != self.authority_key_id:
            raise RepoPatchAuthorityError("repo patch authority response key id mismatch")
        if proof.get("signing_profile") != AUTHORITY_RESPONSE_SIGNING_PROFILE:
            raise RepoPatchAuthorityError("repo patch authority response signing profile mismatch")
        if not verify_ed25519_signature_proof(
            response_body,
            proof,
            public_key_pem=self.authority_public_key_pem,
        ):
            raise RepoPatchAuthorityError("repo patch authority response signature rejected")
        if response_body["request_id"] != request_body["request_id"]:
            raise RepoPatchAuthorityError("repo patch authority response request id mismatch")
        if response_body["idempotency_key"] != idempotency_key:
            raise RepoPatchAuthorityError("repo patch authority response idempotency mismatch")
        try:
            response_issued = _parse_time(response_body["issued_at"])
            response_expiry = _parse_time(response_body["expires_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RepoPatchAuthorityError("repo patch authority response time rejected") from exc
        response_now = self.clock().astimezone(timezone.utc)
        if not (
            response_issued <= response_now + timedelta(seconds=5)
            and response_issued < response_expiry
            and response_expiry - response_issued <= timedelta(seconds=60)
            and response_now <= response_expiry
        ):
            raise RepoPatchAuthorityError("repo patch authority response expired")
        return {
            **response_body,
            "authorization_proof": proof,
        }


def validate_authority_request_operation(body: dict[str, Any]) -> None:
    """Enforce operation-specific request semantics unsupported by the minimal schema validator."""

    operation = body.get("operation")
    gate = body.get("hsai_gate")
    receipt = body.get("preflight_receipt")
    if operation == "preflight":
        if gate is not None or receipt is not None:
            raise ValueError("repo patch authority preflight must not carry an HSAI gate or preflight receipt")
        return
    if operation == "execute":
        if not isinstance(gate, dict) or not isinstance(receipt, dict):
            raise ValueError("repo patch authority execute requires an HSAI gate and preflight receipt")
        validate_preflight_receipt(receipt)
        return
    raise ValueError("repo patch authority operation is invalid")


def validate_preflight_receipt(receipt: dict[str, Any]) -> None:
    """Validate the exact non-mutating disposable-worktree receipt contract."""

    required = {
        "state_slice",
        "base_commit",
        "base_tree",
        "target_path",
        "target_preimage_digest",
        "target_postimage_digest",
        "authorized_diff_digest",
        "changed_paths",
        "test_results",
    }
    if set(receipt) != required:
        raise ValueError("repo patch preflight receipt fields rejected")
    if receipt.get("state_slice") != PREFLIGHT_RECEIPT_STATE_SLICE:
        raise ValueError("repo patch preflight receipt state slice rejected")
    if not isinstance(receipt.get("base_commit"), str) or not _GIT_OBJECT_PATTERN.fullmatch(receipt["base_commit"]):
        raise ValueError("repo patch preflight receipt base commit rejected")
    if not isinstance(receipt.get("base_tree"), str) or not _GIT_OBJECT_PATTERN.fullmatch(receipt["base_tree"]):
        raise ValueError("repo patch preflight receipt base tree rejected")
    target_path = receipt.get("target_path")
    if not isinstance(target_path, str):
        raise ValueError("repo patch preflight receipt target path rejected")
    portable_target = Path(target_path)
    if (
        portable_target.is_absolute()
        or ".." in portable_target.parts
        or portable_target.as_posix() != target_path
        or target_path in {"", "."}
    ):
        raise ValueError("repo patch preflight receipt target path rejected")
    for field in ("target_preimage_digest", "target_postimage_digest", "authorized_diff_digest"):
        value = receipt.get(field)
        if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
            raise ValueError(f"repo patch preflight receipt {field} rejected")
    changed_paths = receipt.get("changed_paths")
    if changed_paths != [target_path]:
        raise ValueError("repo patch preflight receipt changed paths rejected")
    test_results = receipt.get("test_results")
    if not isinstance(test_results, list) or not test_results:
        raise ValueError("repo patch preflight receipt requires test results")
    for result in test_results:
        if not isinstance(result, dict) or set(result) != {
            "argv",
            "returncode",
            "stdout_digest",
            "stderr_digest",
        }:
            raise ValueError("repo patch preflight test result fields rejected")
        argv = result.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(value, str) or not value for value in argv):
            raise ValueError("repo patch preflight test argv rejected")
        if not isinstance(result.get("returncode"), int) or isinstance(result.get("returncode"), bool):
            raise ValueError("repo patch preflight test return code rejected")
        for field in ("stdout_digest", "stderr_digest"):
            value = result.get(field)
            if not isinstance(value, str) or not _DIGEST_PATTERN.fullmatch(value):
                raise ValueError(f"repo patch preflight test {field} rejected")


def send_json_frame(
    connection: socket.socket,
    payload: dict[str, Any],
    *,
    max_frame_bytes: int = MAX_FRAME_BYTES,
) -> None:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if not encoded or len(encoded) > max_frame_bytes:
        raise RepoPatchAuthorityError("repo patch authority frame size rejected")
    connection.sendall(struct.pack(">I", len(encoded)) + encoded)


def receive_json_frame(
    connection: socket.socket,
    *,
    max_frame_bytes: int = MAX_FRAME_BYTES,
) -> dict[str, Any]:
    header = _receive_exact(connection, 4)
    frame_length = struct.unpack(">I", header)[0]
    if frame_length == 0 or frame_length > max_frame_bytes:
        raise RepoPatchAuthorityError("repo patch authority frame size rejected")
    raw = _receive_exact(connection, frame_length)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, DuplicateJsonKeyError) as exc:
        raise RepoPatchAuthorityError("repo patch authority JSON frame rejected") from exc
    if not isinstance(payload, dict):
        raise RepoPatchAuthorityError("repo patch authority JSON frame must be an object")
    return payload


def _receive_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise RepoPatchAuthorityError("repo patch authority frame ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _validate_private_key(private_key_pem: str, key_id: str, profile: str) -> None:
    build_ed25519_signature_proof(
        {"key_validation": profile},
        key_id=key_id,
        private_key_pem=private_key_pem,
        signing_profile=profile,
    )


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("repo patch authority timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)
