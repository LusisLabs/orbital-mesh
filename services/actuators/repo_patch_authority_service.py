"""Out-of-process authority service for evidence-carrying repo-patch actions."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import secrets
import socket
import stat
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from services.actuators.repo_patch import RepoPatchAdapter
from services.actuators.repo_patch_workspace import (
    PreparedPatchReceipt,
    PreparedRepoPatch,
    RepoPatchWorkspaceManager,
)
from shared.mesh_runtime import Decision, EvaluationResult, RuntimeConfig
from shared.mesh_runtime.hsai_bridge import (
    HSAI_EXECUTION_CONTEXT_KEY,
    HsaiAdmissionAdapter,
    attach_hsai_execution_context,
    build_hsai_admission_request_v2,
    evaluate_hsai_gate,
    validate_bridge_gate,
)
from shared.mesh_runtime.perennial.signing import (
    build_ed25519_signature_proof,
    verify_ed25519_signature_proof,
)
from shared.mesh_runtime.repo_patch_authority import (
    AUTHORITY_REQUEST_VERSION,
    AUTHORITY_RESPONSE_SIGNING_PROFILE,
    AUTHORITY_RESPONSE_VERSION,
    CLIENT_REQUEST_SIGNING_PROFILE,
    RepoPatchAuthorityError,
    receive_json_frame,
    send_json_frame,
    validate_authority_request_operation,
)
from shared.mesh_runtime.repo_patch_authority_store import (
    AuthorityConflictError,
    AuthorityStateError,
    AuthorityStoreError,
    FileRepoPatchAuthorityStore,
    PostgresRepoPatchAuthorityStore,
    RepoPatchAuthorityStore,
    canonical_authority_digest,
)
from shared.mesh_runtime.repo_patch_permits import (
    RepoPatchPermitStore,
    canonical_digest,
    file_digest,
    write_immutable_backup,
)
from shared.mesh_runtime.repo_patch_test_policy import RepoPatchTestCommandPolicy
from shared.mesh_runtime.schema_validation import SchemaValidationError, validate_payload


AUTHORITY_STATE_SLICE = "mesh.repo_patch_authority_service.v1"
PREFLIGHT_STATE_SLICE = "mesh.repo_patch_disposable_worktree.v1"
AUTHORITY_LIFECYCLE_STATE_SLICE = "mesh.repo_patch_authority_store_lifecycle.v1"


class RepoPatchAuthorityService:
    """Unix-domain authority that alone attaches and consumes repo-patch permits."""

    def __init__(
        self,
        socket_path: str | Path,
        state_directory: str | Path,
        *,
        authority_private_key_pem: str,
        authority_key_id: str,
        client_public_keys: dict[str, str],
        allowed_uids: set[int] | frozenset[int],
        permit_signing_key: str,
        permit_signing_key_id: str = "repo-patch-permit-hmac",
        permit_issuer: str = "mesh.repo_patch_authority_service",
        permit_executor_audience: str = "mesh.repo_patch_actuator",
        allowed_test_commands: Sequence[Sequence[str]] = (),
        socket_gid: int | None = None,
        max_frame_bytes: int = 1024 * 1024,
        connection_timeout_seconds: float = 10.0,
        response_ttl_seconds: int = 30,
        clock: Callable[[], datetime] | None = None,
        authority_store: RepoPatchAuthorityStore | None = None,
        hsai_admission_adapter: HsaiAdmissionAdapter | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.state_directory = Path(state_directory)
        if not self.socket_path.is_absolute() or not self.state_directory.is_absolute():
            raise ValueError("authority socket and state paths must be absolute")
        self.authority_private_key_pem = authority_private_key_pem.strip()
        self.authority_key_id = authority_key_id.strip()
        self.client_public_keys = {key.strip(): value.strip() for key, value in client_public_keys.items()}
        self.allowed_uids = frozenset(allowed_uids)
        self.permit_signing_key = permit_signing_key.strip()
        self.allowed_test_commands = tuple(tuple(str(argument) for argument in command) for command in allowed_test_commands)
        self.socket_gid = socket_gid
        self.max_frame_bytes = max_frame_bytes
        self.connection_timeout_seconds = connection_timeout_seconds
        self.response_ttl_seconds = response_ttl_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.authority_store = authority_store or FileRepoPatchAuthorityStore(
            self.state_directory,
            clock=self.clock,
        )
        self.hsai_admission_adapter = hsai_admission_adapter
        self._listener: socket.socket | None = None
        if not self.authority_private_key_pem or not self.authority_key_id:
            raise ValueError("authority service requires explicit Ed25519 authority key material")
        if not self.client_public_keys or any(not key or not value for key, value in self.client_public_keys.items()):
            raise ValueError("authority service requires pinned client public keys")
        if not self.allowed_uids or any(uid < 0 for uid in self.allowed_uids):
            raise ValueError("authority service requires at least one allowed peer uid")
        if socket_gid is not None and socket_gid < 0:
            raise ValueError("authority service socket gid must be non-negative")
        if not self.permit_signing_key:
            raise ValueError("authority service requires explicit permit signing key material")
        if connection_timeout_seconds <= 0 or not 1 <= response_ttl_seconds <= 60:
            raise ValueError("authority service timing configuration is invalid")
        if not 1024 <= max_frame_bytes <= 1024 * 1024:
            raise ValueError("authority service frame limit is invalid")
        build_ed25519_signature_proof(
            {"key_validation": AUTHORITY_STATE_SLICE},
            key_id=self.authority_key_id,
            private_key_pem=self.authority_private_key_pem,
            signing_profile=AUTHORITY_RESPONSE_SIGNING_PROFILE,
        )
        config = RuntimeConfig(
            state_directory=str(self.state_directory),
            repo_patch_permit_signing_key=self.permit_signing_key,
            repo_patch_permit_signing_key_id=permit_signing_key_id,
            repo_patch_permit_issuer=permit_issuer,
            repo_patch_permit_executor_audience=permit_executor_audience,
        )
        self.permit_store = RepoPatchPermitStore(
            self.state_directory,
            signing_key=self.permit_signing_key,
            signing_key_id=permit_signing_key_id,
            issuer=permit_issuer,
            executor_audience=permit_executor_audience,
        )
        self.actuator = RepoPatchAdapter(config=config, allowed_test_commands=self.allowed_test_commands)
        self.workspace_manager = RepoPatchWorkspaceManager(self.state_directory / "repo_patch_preflight_worktrees")
        self.test_command_policy = RepoPatchTestCommandPolicy(self.allowed_test_commands)

    def start(self) -> None:
        if self._listener is not None:
            raise RuntimeError("authority service is already started")
        _prepare_protected_directory(self.socket_path.parent, exact_mode=0o750, required_gid=self.socket_gid)
        _prepare_protected_directory(self.state_directory, exact_mode=0o700)
        self.actuator.recover_incomplete_actions()
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise PermissionError("authority socket path already exists")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.socket_path))
            if self.socket_gid is not None:
                os.chown(self.socket_path, -1, self.socket_gid)
            os.chmod(self.socket_path, 0o660)
            _verify_socket_file(self.socket_path, required_gid=self.socket_gid)
            listener.listen(16)
        except Exception:
            listener.close()
            self._remove_owned_socket()
            raise
        self._listener = listener

    def serve_once(self) -> None:
        if self._listener is None:
            raise RuntimeError("authority service is not started")
        connection, _ = self._listener.accept()
        with connection:
            connection.settimeout(self.connection_timeout_seconds)
            try:
                peer_uid, peer_gid = _peer_credentials(connection)
            except OSError:
                peer_uid, peer_gid = -1, -1
            self.handle_connection(connection, peer_uid=peer_uid, peer_gid=peer_gid)

    def serve_forever(self) -> None:
        while self._listener is not None:
            try:
                self.serve_once()
            except (ConnectionError, OSError, RepoPatchAuthorityError, TimeoutError):
                if self._listener is None:
                    return

    def handle_connection(self, connection: socket.socket, *, peer_uid: int, peer_gid: int) -> None:
        request: dict[str, Any] = {}
        try:
            request = receive_json_frame(connection, max_frame_bytes=self.max_frame_bytes)
            response = self.handle_request(request, peer_uid=peer_uid, peer_gid=peer_gid)
        except Exception:
            response = self._signed_rejection(
                request,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                code="invalid_request_frame",
            )
        try:
            send_json_frame(connection, response, max_frame_bytes=self.max_frame_bytes)
        except (OSError, RepoPatchAuthorityError):
            return

    def handle_request(self, request: dict[str, Any], *, peer_uid: int, peer_gid: int) -> dict[str, Any]:
        if peer_uid not in self.allowed_uids:
            return self._signed_rejection(request, peer_uid=peer_uid, peer_gid=peer_gid, code="peer_identity_rejected")
        try:
            validate_payload("repo-patch-authority-request.schema.json", request)
            body = request["body"]
            proof = request["authorization_proof"]
            if body.get("schema_version") != AUTHORITY_REQUEST_VERSION:
                raise ValueError("request version mismatch")
            client_key_id = str(body.get("client_key_id") or "")
            if proof.get("key_id") != client_key_id or proof.get("signing_profile") != CLIENT_REQUEST_SIGNING_PROFILE:
                return self._signed_rejection(
                    request,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    code="client_signature_rejected",
                )
            pinned_public_key = self.client_public_keys.get(client_key_id)
            if not pinned_public_key or not verify_ed25519_signature_proof(
                body,
                proof,
                public_key_pem=pinned_public_key,
            ):
                return self._signed_rejection(
                    request,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    code="client_signature_rejected",
                )
            if not self._request_time_is_valid(body):
                return self._signed_rejection(request, peer_uid=peer_uid, peer_gid=peer_gid, code="request_time_rejected")
            validate_authority_request_operation(body)
            decision = Decision.from_dict(body["decision"])
            evaluation = _evaluation_from_payload(body["evaluation"])
            if HSAI_EXECUTION_CONTEXT_KEY in decision.execution_plan.get("parameters", {}):
                return self._signed_rejection(
                    request,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    code="pre_attached_permit_rejected",
                )
            idempotency_key = str(body["idempotency_key"])
            operation = str(body["operation"])
            try:
                lifecycle_record = self._issue_authority_lifecycle(
                    body,
                    client_key_id=client_key_id,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                )
                if lifecycle_record.get("state") == "terminal":
                    return self._signed_terminal_replay(
                        request,
                        lifecycle_record,
                        peer_uid=peer_uid,
                        peer_gid=peer_gid,
                    )
                if lifecycle_record.get("state") == "dispatched":
                    if operation == "execute":
                        lifecycle_record = self._reconcile_dispatched_lifecycle(
                            lifecycle_record,
                            decision,
                            evaluation,
                            body["hsai_gate"],
                            idempotency_key,
                            client_key_id=client_key_id,
                        )
                    else:
                        lifecycle_record = self._terminalize_dispatched_unknown(
                            lifecycle_record,
                            client_key_id=client_key_id,
                        )
                    return self._signed_terminal_replay(
                        request,
                        lifecycle_record,
                        peer_uid=peer_uid,
                        peer_gid=peer_gid,
                    )
                if lifecycle_record.get("state") not in {"issued", "leased"}:
                    raise AuthorityStateError("authority lifecycle state is not recoverable for dispatch")
                lease_id = f"authority_lease_{secrets.token_hex(32)}"
                lifecycle_record = self.authority_store.lease_for_dispatch(
                    str(lifecycle_record["authority_id"]),
                    expected_version=int(lifecycle_record["version"]),
                    lease_id=lease_id,
                )
            except (AuthorityConflictError, AuthorityStateError, AuthorityStoreError, KeyError, TypeError, ValueError):
                return self._signed_rejection(
                    request,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    code="authority_lifecycle_conflict",
                )
            try:
                return self._handle_leased_request(
                    request,
                    body,
                    decision,
                    evaluation,
                    operation=operation,
                    idempotency_key=idempotency_key,
                    client_key_id=client_key_id,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    lifecycle_record=lifecycle_record,
                    lease_id=lease_id,
                )
            except (KeyError, OSError, SchemaValidationError, TypeError, ValueError):
                return self._complete_lifecycle_rejection(
                    request,
                    lifecycle_record=lifecycle_record,
                    lease_id=lease_id,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    client_key_id=client_key_id,
                    code="authority_policy_rejected",
                    outcome="rejected",
                )
            except Exception:
                return self._complete_lifecycle_rejection(
                    request,
                    lifecycle_record=lifecycle_record,
                    lease_id=lease_id,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    client_key_id=client_key_id,
                    code="authority_internal_failure",
                    outcome="failed",
                )
        except (KeyError, OSError, SchemaValidationError, TypeError, ValueError):
            return self._signed_rejection(request, peer_uid=peer_uid, peer_gid=peer_gid, code="authority_policy_rejected")
        except Exception:
            return self._signed_rejection(request, peer_uid=peer_uid, peer_gid=peer_gid, code="authority_internal_failure")

    def _issue_authority_lifecycle(
        self,
        body: dict[str, Any],
        *,
        client_key_id: str,
        peer_uid: int,
        peer_gid: int,
    ) -> dict[str, Any]:
        operation = str(body["operation"])
        idempotency_key = str(body["idempotency_key"])
        adapter_identity = (
            str(getattr(self.hsai_admission_adapter, "adapter_identity", "") or "")
            if operation == "execute"
            else None
        )
        identity = {
            "state_slice": AUTHORITY_LIFECYCLE_STATE_SLICE,
            "operation": operation,
            "client_key_id": client_key_id,
            "idempotency_key": idempotency_key,
        }
        identity_digest = canonical_authority_digest(identity).removeprefix("sha256:")
        action_binding = {
            **identity,
            "peer_uid": peer_uid,
            "peer_gid": peer_gid,
            "decision_digest": canonical_authority_digest(body["decision"]),
            "evaluation_digest": canonical_authority_digest(body["evaluation"]),
            "hsai_gate_digest": canonical_authority_digest(body["hsai_gate"]),
            "preflight_receipt_digest": canonical_authority_digest(body["preflight_receipt"]),
            "hsai_adapter_identity": adapter_identity,
        }
        return self.authority_store.issue_or_get(
            authority_id=f"repo_patch_authority_{identity_digest}",
            idempotency_key=f"{idempotency_key}:{operation}",
            nonce=canonical_authority_digest({"authority_identity": identity}).removeprefix("sha256:"),
            action_binding=action_binding,
        )

    def _handle_leased_request(
        self,
        request: dict[str, Any],
        body: dict[str, Any],
        decision: Decision,
        evaluation: EvaluationResult,
        *,
        operation: str,
        idempotency_key: str,
        client_key_id: str,
        peer_uid: int,
        peer_gid: int,
        lifecycle_record: dict[str, Any],
        lease_id: str,
    ) -> dict[str, Any]:
        if operation == "preflight":
            dispatched = self._mark_lifecycle_dispatched(lifecycle_record, lease_id)
            try:
                current_preflight = self._run_preflight(
                    decision,
                    evaluation,
                    idempotency_key=idempotency_key,
                    request_id=str(body["request_id"]),
                )
            except (KeyError, OSError, TypeError, ValueError):
                return self._complete_lifecycle_rejection(
                    request,
                    lifecycle_record=dispatched,
                    lease_id=lease_id,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    client_key_id=client_key_id,
                    code="preflight_rejected",
                    outcome="rejected",
                )
            return self._complete_lifecycle_response(
                request,
                lifecycle_record=dispatched,
                lease_id=lease_id,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                client_key_id=client_key_id,
                status="completed",
                execution_result={
                    "status": "preflighted",
                    "preflight_receipt": current_preflight,
                    "external_refs": {},
                    "retryable": False,
                },
                rejection=None,
                outcome="succeeded",
            )

        gate = body["hsai_gate"]
        current_request = self._current_hsai_request(decision, evaluation, gate, body["preflight_receipt"])
        adapter = self.hsai_admission_adapter
        adapter_identity = str(getattr(adapter, "adapter_identity", "") or "") if adapter is not None else ""
        if adapter is None or getattr(adapter, "authority_eligible", False) is not True or not adapter_identity:
            return self._complete_lifecycle_rejection(
                request,
                lifecycle_record=lifecycle_record,
                lease_id=lease_id,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                client_key_id=client_key_id,
                code="hsai_authority_adapter_unavailable",
                outcome="rejected",
            )
        authority_gate = evaluate_hsai_gate(current_request, adapter)
        validate_bridge_gate(
            authority_gate,
            expected_decision=decision,
            expected_evaluation=evaluation,
            require_mesh_policy_approved=True,
        )
        authority_reason_codes = authority_gate.get("reason_codes")
        if isinstance(authority_reason_codes, list) and any(
            isinstance(reason, str) and reason.startswith("hsai_unavailable:")
            for reason in authority_reason_codes
        ):
            return self._complete_lifecycle_rejection(
                request,
                lifecycle_record=lifecycle_record,
                lease_id=lease_id,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                client_key_id=client_key_id,
                code="hsai_authority_adapter_unavailable",
                outcome="rejected",
            )
        if gate.get("allowed") is not True or gate.get("authority_eligible") is not True:
            return self._complete_lifecycle_rejection(
                request,
                lifecycle_record=lifecycle_record,
                lease_id=lease_id,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                client_key_id=client_key_id,
                code="admission_rejected",
                outcome="rejected",
            )
        for field in (
            "allowed",
            "authority_eligible",
            "request",
            "request_digest",
            "candidate_digest",
            "reason_codes",
        ):
            if gate.get(field) != authority_gate.get(field):
                return self._complete_lifecycle_rejection(
                    request,
                    lifecycle_record=lifecycle_record,
                    lease_id=lease_id,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    client_key_id=client_key_id,
                    code="hsai_authority_gate_mismatch",
                    outcome="rejected",
                )
        submitted_decision = dict(gate.get("decision") or {})
        current_decision = dict(authority_gate.get("decision") or {})
        for volatile_field in ("created_at", "decision_digest"):
            submitted_decision.pop(volatile_field, None)
            current_decision.pop(volatile_field, None)
        if submitted_decision != current_decision:
            return self._complete_lifecycle_rejection(
                request,
                lifecycle_record=lifecycle_record,
                lease_id=lease_id,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                client_key_id=client_key_id,
                code="hsai_authority_gate_mismatch",
                outcome="rejected",
            )
        if authority_gate.get("allowed") is not True or authority_gate.get("authority_eligible") is not True:
            return self._complete_lifecycle_rejection(
                request,
                lifecycle_record=lifecycle_record,
                lease_id=lease_id,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                client_key_id=client_key_id,
                code="admission_rejected",
                outcome="rejected",
            )

        dispatched = self._mark_lifecycle_dispatched(lifecycle_record, lease_id)
        terminal_result = self.permit_store.terminal_result_for_replay(
            decision,
            evaluation,
            authority_gate,
            idempotency_key,
        )
        if terminal_result is not None:
            outcome = "succeeded" if terminal_result.get("status") == "succeeded" else "failed"
            return self._complete_lifecycle_response(
                request,
                lifecycle_record=dispatched,
                lease_id=lease_id,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                client_key_id=client_key_id,
                status="completed",
                execution_result=terminal_result,
                rejection=None,
                outcome=outcome,
            )

        try:
            prepared = self._prepare_verified_patch(
                decision,
                evaluation,
                idempotency_key=idempotency_key,
                request_id=str(body["request_id"]),
            )
        except (KeyError, OSError, TypeError, ValueError):
            return self._complete_lifecycle_rejection(
                request,
                lifecycle_record=dispatched,
                lease_id=lease_id,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                client_key_id=client_key_id,
                code="preflight_drift_rejected",
                outcome="rejected",
            )
        with prepared:
            current_preflight = _preflight_receipt_payload(prepared.receipt())
            if current_preflight != body["preflight_receipt"]:
                return self._complete_lifecycle_rejection(
                    request,
                    lifecycle_record=dispatched,
                    lease_id=lease_id,
                    peer_uid=peer_uid,
                    peer_gid=peer_gid,
                    client_key_id=client_key_id,
                    code="preflight_drift_rejected",
                    outcome="rejected",
                )
            execution_result = self._promote_verified_patch(
                prepared,
                current_preflight,
                decision,
                evaluation,
                authority_gate,
                idempotency_key,
            )
        outcome = "succeeded" if execution_result.get("status") == "succeeded" else "failed"
        return self._complete_lifecycle_response(
            request,
            lifecycle_record=dispatched,
            lease_id=lease_id,
            peer_uid=peer_uid,
            peer_gid=peer_gid,
            client_key_id=client_key_id,
            status="completed",
            execution_result=execution_result,
            rejection=None,
            outcome=outcome,
        )

    def _reconcile_dispatched_lifecycle(
        self,
        lifecycle_record: dict[str, Any],
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict[str, Any],
        idempotency_key: str,
        *,
        client_key_id: str,
    ) -> dict[str, Any]:
        terminal_result = self.permit_store.terminal_result_for_replay(
            decision,
            evaluation,
            gate,
            idempotency_key,
        )
        if terminal_result is None:
            return self._terminalize_dispatched_unknown(
                lifecycle_record,
                client_key_id=client_key_id,
            )
        outcome = "succeeded" if terminal_result.get("status") == "succeeded" else "failed"
        return self._terminalize_dispatched(
            lifecycle_record,
            client_key_id=client_key_id,
            execution_result=terminal_result,
            outcome=outcome,
        )

    def _terminalize_dispatched_unknown(
        self,
        lifecycle_record: dict[str, Any],
        *,
        client_key_id: str,
    ) -> dict[str, Any]:
        return self._terminalize_dispatched(
            lifecycle_record,
            client_key_id=client_key_id,
            execution_result={
                "status": "failed",
                "external_refs": {
                    "authority_outcome": "unknown_after_dispatch",
                    "recovery_required": True,
                },
                "failure": {"reason": "authority_outcome_unknown_after_dispatch"},
                "retryable": False,
            },
            outcome="unknown",
        )

    def _terminalize_dispatched(
        self,
        lifecycle_record: dict[str, Any],
        *,
        client_key_id: str,
        execution_result: dict[str, Any],
        outcome: str,
    ) -> dict[str, Any]:
        lease_id = lifecycle_record.get("lease_id")
        if not isinstance(lease_id, str) or not lease_id:
            raise AuthorityStateError("dispatched authority lifecycle is missing its fencing lease")
        return self.authority_store.complete_terminal(
            str(lifecycle_record["authority_id"]),
            expected_version=int(lifecycle_record["version"]),
            lease_id=lease_id,
            outcome=outcome,
            result={
                "status": "completed",
                "execution_result": execution_result,
                "rejection": None,
                "authenticated_client_key_id": client_key_id,
            },
        )

    def _current_hsai_request(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict[str, Any],
        preflight_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        request = gate.get("request")
        if not isinstance(request, dict):
            raise ValueError("authority HSAI gate request is missing")
        created_at = str(request.get("created_at") or "")
        if request.get("schema_version") != "mesh.hsai_admission_request.v2":
            raise ValueError("authority execute requires an HSAI v2 request bound to preflight evidence")
        current_request = build_hsai_admission_request_v2(
            decision,
            evaluation,
            preflight_receipt,
            created_at=created_at,
        )
        if not isinstance(current_request, dict):
            raise ValueError("authority HSAI request builder returned a non-object")
        return current_request

    def _mark_lifecycle_dispatched(
        self,
        lifecycle_record: dict[str, Any],
        lease_id: str,
    ) -> dict[str, Any]:
        return self.authority_store.mark_dispatched(
            str(lifecycle_record["authority_id"]),
            expected_version=int(lifecycle_record["version"]),
            lease_id=lease_id,
        )

    def _complete_lifecycle_rejection(
        self,
        request: dict[str, Any],
        *,
        lifecycle_record: dict[str, Any],
        lease_id: str,
        peer_uid: int,
        peer_gid: int,
        client_key_id: str,
        code: str,
        outcome: str,
    ) -> dict[str, Any]:
        return self._complete_lifecycle_response(
            request,
            lifecycle_record=lifecycle_record,
            lease_id=lease_id,
            peer_uid=peer_uid,
            peer_gid=peer_gid,
            client_key_id=client_key_id,
            status="rejected",
            execution_result={
                "status": "failed",
                "external_refs": {},
                "failure": {"reason": code},
                "retryable": False,
            },
            rejection={"code": code, "retryable": False},
            outcome=outcome,
        )

    def _complete_lifecycle_response(
        self,
        request: dict[str, Any],
        *,
        lifecycle_record: dict[str, Any],
        lease_id: str,
        peer_uid: int,
        peer_gid: int,
        client_key_id: str,
        status: str,
        execution_result: dict[str, Any],
        rejection: dict[str, Any] | None,
        outcome: str,
    ) -> dict[str, Any]:
        terminal_result = {
            "status": status,
            "execution_result": execution_result,
            "rejection": rejection,
            "authenticated_client_key_id": client_key_id,
        }
        try:
            self.authority_store.complete_terminal(
                str(lifecycle_record["authority_id"]),
                expected_version=int(lifecycle_record["version"]),
                lease_id=lease_id,
                outcome=outcome,
                result=terminal_result,
            )
        except (AuthorityConflictError, AuthorityStateError, AuthorityStoreError, KeyError, TypeError, ValueError):
            return self._signed_rejection(
                request,
                peer_uid=peer_uid,
                peer_gid=peer_gid,
                code="authority_lifecycle_completion_failed",
            )
        return self._signed_response(
            request,
            peer_uid=peer_uid,
            peer_gid=peer_gid,
            status=status,
            execution_result=execution_result,
            rejection=rejection,
            authenticated_client_key_id=client_key_id,
        )

    def _signed_terminal_replay(
        self,
        request: dict[str, Any],
        lifecycle_record: dict[str, Any],
        *,
        peer_uid: int,
        peer_gid: int,
    ) -> dict[str, Any]:
        terminal = lifecycle_record.get("terminal_result")
        if not isinstance(terminal, dict):
            raise AuthorityStoreError("terminal authority lifecycle result is missing")
        status = terminal.get("status")
        execution_result = terminal.get("execution_result")
        rejection = terminal.get("rejection")
        client_key_id = terminal.get("authenticated_client_key_id")
        if (
            status not in {"completed", "rejected"}
            or not isinstance(execution_result, dict)
            or (rejection is not None and not isinstance(rejection, dict))
            or not isinstance(client_key_id, str)
        ):
            raise AuthorityStoreError("terminal authority lifecycle result is malformed")
        return self._signed_response(
            request,
            peer_uid=peer_uid,
            peer_gid=peer_gid,
            status=status,
            execution_result=execution_result,
            rejection=rejection,
            authenticated_client_key_id=client_key_id,
        )

    def _promote_verified_patch(
        self,
        prepared: PreparedRepoPatch,
        preflight_receipt: dict[str, Any],
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        permit = self.permit_store.issue(decision, evaluation, gate, idempotency_key)
        admitted_decision = attach_hsai_execution_context(decision, gate, permit)
        parameters = dict(decision.execution_plan["parameters"])
        target_path = Path(str(permit["target_path"]))
        if file_digest(target_path) != permit["target_preimage_digest"]:
            raise ValueError("repo patch source preimage changed before durable preparation")
        backup_name = hashlib.sha256(str(permit["permit_id"]).encode("utf-8")).hexdigest() + ".bak"
        backup_path = self.permit_store.backup_directory / backup_name
        write_immutable_backup(backup_path, prepared.original_bytes)
        self.permit_store.record_transition(
            str(permit["permit_id"]),
            "issued",
            "prepared",
            details={
                "backup_path": str(backup_path),
                "repo_path": str(prepared.source_repo),
                "target_path": str(target_path),
            },
        )
        try:
            authority_receipt = self.permit_store.consume(
                permit,
                admitted_decision,
                idempotency_key,
                parameters,
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            aborted = self.permit_store.abort_with_restoration(
                permit,
                "prepared",
                f"repo patch permit consumption rejected: {exc}",
            )
            if not isinstance(aborted, dict):
                raise ValueError("repo patch permit abort returned a non-object")
            return aborted
        self.permit_store.record_transition(str(permit["permit_id"]), "claimed", "applying")
        try:
            promoted = prepared.promote()
        except (OSError, TypeError, ValueError) as exc:
            aborted = self.permit_store.abort_with_restoration(
                permit,
                "applying",
                f"verified worktree promotion rejected: {exc}",
            )
            if not isinstance(aborted, dict):
                raise ValueError("repo patch promotion abort returned a non-object")
            return aborted
        self.permit_store.record_transition(str(permit["permit_id"]), "applying", "applied")
        if (
            promoted.target_postimage_digest != preflight_receipt["target_postimage_digest"]
            or file_digest(target_path) != permit["target_postimage_digest"]
        ):
            aborted = self.permit_store.abort_with_restoration(
                permit,
                "applied",
                "verified worktree promotion postimage mismatch",
            )
            if not isinstance(aborted, dict):
                raise ValueError("repo patch postimage abort returned a non-object")
            return aborted
        self.permit_store.record_transition(str(permit["permit_id"]), "applied", "verifying")
        authority_receipt["target_postimage_digest"] = promoted.target_postimage_digest
        result = {
            "status": "succeeded",
            "external_refs": {
                "authority_receipt": authority_receipt,
                "backup_path": str(backup_path),
                "patched_files": [promoted.target_path],
                "preflight_receipt": preflight_receipt,
                "test_results": preflight_receipt["test_results"],
            },
            "retryable": False,
        }
        self.permit_store.record_transition(
            str(permit["permit_id"]),
            "verifying",
            "committed",
            details={"committed_postimage_digest": promoted.target_postimage_digest},
            terminal_result=result,
        )
        return result

    def _run_preflight(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        *,
        idempotency_key: str,
        request_id: str,
    ) -> dict[str, Any]:
        with self._prepare_verified_patch(
            decision,
            evaluation,
            idempotency_key=idempotency_key,
            request_id=request_id,
        ) as prepared:
            return _preflight_receipt_payload(prepared.receipt())

    def _prepare_verified_patch(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        *,
        idempotency_key: str,
        request_id: str,
    ) -> PreparedRepoPatch:
        if evaluation.decision_id != decision.decision_id or not evaluation.passed:
            raise ValueError("repo patch preflight evaluation rejected")
        if evaluation.final_recommendation != "execute":
            raise ValueError("repo patch preflight requires an execute recommendation")
        plan = decision.execution_plan
        if plan.get("system") != "repo_patch_service" or plan.get("action") != "investigate_and_patch":
            raise ValueError("repo patch preflight action rejected")
        if idempotency_key != f"{decision.decision_id}:{plan['action']}":
            raise ValueError("repo patch preflight idempotency binding rejected")
        parameters = plan.get("parameters")
        if not isinstance(parameters, dict):
            raise ValueError("repo patch preflight parameters rejected")
        test_commands = parameters.get("test_commands")
        if not isinstance(test_commands, list) or any(not isinstance(command, str) for command in test_commands):
            raise ValueError("repo patch preflight test commands rejected")
        authorized_commands = self.test_command_policy.authorize(test_commands)
        patch_template = parameters.get("patch_template")
        allowed_paths = parameters.get("allowed_paths")
        if not isinstance(patch_template, dict) or not isinstance(allowed_paths, list) or any(
            not isinstance(path, str) for path in allowed_paths
        ):
            raise ValueError("repo patch preflight patch scope rejected")
        executed_commands = [[command.executable_path, *command.argv[1:]] for command in authorized_commands]
        prepared = self.workspace_manager.prepare(
            repo_path=parameters["repo_path"],
            target_file=patch_template["target_file"],
            allowed_paths=allowed_paths,
            find_text=patch_template["find"],
            replace_text=patch_template["replace"],
            workspace_id=f"{idempotency_key}:{request_id}",
        )
        try:
            prepared.verify(executed_commands)
            return prepared
        except BaseException:
            prepared.close()
            raise

    def close(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.close()
        self._remove_owned_socket()

    def __enter__(self) -> RepoPatchAuthorityService:
        self.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request_time_is_valid(self, body: dict[str, Any]) -> bool:
        try:
            issued_at = _parse_time(str(body["issued_at"]))
            expires_at = _parse_time(str(body["expires_at"]))
        except (KeyError, TypeError, ValueError):
            return False
        now = self.clock().astimezone(timezone.utc)
        return bool(
            issued_at <= now + timedelta(seconds=5)
            and issued_at < expires_at
            and expires_at - issued_at <= timedelta(seconds=60)
            and now <= expires_at
        )

    def _signed_rejection(
        self,
        request: dict[str, Any],
        *,
        peer_uid: int,
        peer_gid: int,
        code: str,
    ) -> dict[str, Any]:
        return self._signed_response(
            request,
            peer_uid=peer_uid,
            peer_gid=peer_gid,
            status="rejected",
            execution_result={
                "status": "failed",
                "external_refs": {},
                "failure": {"reason": code},
                "retryable": False,
            },
            rejection={"code": code, "retryable": False},
        )

    def _signed_response(
        self,
        request: dict[str, Any],
        *,
        peer_uid: int,
        peer_gid: int,
        status: str,
        execution_result: dict[str, Any],
        rejection: dict[str, Any] | None,
        authenticated_client_key_id: str | None = None,
    ) -> dict[str, Any]:
        raw_request_body = request.get("body")
        request_body: dict[str, Any] = raw_request_body if isinstance(raw_request_body, dict) else {}
        request_id = str(request_body.get("request_id") or "unavailable")
        idempotency_key = str(request_body.get("idempotency_key") or "unavailable")
        client_key_id = str(request_body.get("client_key_id") or "unavailable")
        now = self.clock().astimezone(timezone.utc)
        receipt = {
            "state_slice": AUTHORITY_STATE_SLICE,
            "authority_key_id": self.authority_key_id,
            "declared_client_key_id": client_key_id,
            "authenticated_client_key_id": authenticated_client_key_id,
            "peer_uid": peer_uid,
            "peer_gid": peer_gid,
            "request_digest": canonical_digest(request_body),
            "execution_result_digest": canonical_digest(execution_result),
            "completed_at": _format_time(now),
        }
        body = {
            "schema_version": AUTHORITY_RESPONSE_VERSION,
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "status": status,
            "execution_result": execution_result,
            "receipt": receipt,
            "rejection": rejection,
            "issued_at": _format_time(now),
            "expires_at": _format_time(now + timedelta(seconds=self.response_ttl_seconds)),
        }
        response = {
            "body": body,
            "authorization_proof": build_ed25519_signature_proof(
                body,
                key_id=self.authority_key_id,
                private_key_pem=self.authority_private_key_pem,
                signing_profile=AUTHORITY_RESPONSE_SIGNING_PROFILE,
            ),
        }
        validate_payload("repo-patch-authority-response.schema.json", response)
        return response

    def _remove_owned_socket(self) -> None:
        try:
            socket_stat = self.socket_path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISSOCK(socket_stat.st_mode) and socket_stat.st_uid == os.geteuid():
            self.socket_path.unlink()


def _peer_credentials(connection: socket.socket) -> tuple[int, int]:
    if sys.platform.startswith("linux"):
        option = getattr(socket, "SO_PEERCRED", None)
        if option is None:
            raise PermissionError("SO_PEERCRED is unavailable")
        raw = connection.getsockopt(socket.SOL_SOCKET, option, struct.calcsize("3i"))
        _, uid, gid = struct.unpack("3i", raw)
        return uid, gid
    if sys.platform == "darwin":
        libc = ctypes.CDLL(None, use_errno=True)
        getpeereid = libc.getpeereid
        getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
        getpeereid.restype = ctypes.c_int
        uid = ctypes.c_uint()
        gid = ctypes.c_uint()
        if getpeereid(connection.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number))
        return int(uid.value), int(gid.value)
    raise PermissionError("Unix peer credential authentication is unsupported on this platform")


def _prepare_protected_directory(path: Path, *, exact_mode: int, required_gid: int | None = None) -> None:
    if path.is_symlink():
        raise PermissionError(f"protected directory must not be a symlink: {path}")
    if not path.exists():
        path.mkdir(parents=True, mode=exact_mode)
        if required_gid is not None:
            os.chown(path, -1, required_gid)
        os.chmod(path, exact_mode)
    directory_stat = path.stat()
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise PermissionError(f"protected path is not a directory: {path}")
    if directory_stat.st_uid != os.geteuid():
        raise PermissionError(f"protected directory owner mismatch: {path}")
    if required_gid is not None and directory_stat.st_gid != required_gid:
        raise PermissionError(f"protected directory group mismatch: {path}")
    if stat.S_IMODE(directory_stat.st_mode) != exact_mode:
        raise PermissionError(f"protected directory mode must be {oct(exact_mode)}: {path}")


def _verify_socket_file(path: Path, *, required_gid: int | None) -> None:
    socket_stat = path.lstat()
    if not stat.S_ISSOCK(socket_stat.st_mode):
        raise PermissionError("authority socket path is not a Unix socket")
    if socket_stat.st_uid != os.geteuid() or stat.S_IMODE(socket_stat.st_mode) != 0o660:
        raise PermissionError("authority socket ownership or mode mismatch")
    if required_gid is not None and socket_stat.st_gid != required_gid:
        raise PermissionError("authority socket group mismatch")


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("authority timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _preflight_receipt_payload(receipt: PreparedPatchReceipt) -> dict[str, Any]:
    test_results: list[dict[str, Any]] = []
    for result in receipt.test_results:
        argv = result.get("argv")
        returncode = result.get("returncode")
        stdout = result.get("stdout")
        stderr = result.get("stderr")
        if (
            not isinstance(argv, list)
            or any(not isinstance(argument, str) for argument in argv)
            or not isinstance(returncode, int)
            or isinstance(returncode, bool)
            or not isinstance(stdout, str)
            or not isinstance(stderr, str)
        ):
            raise ValueError("repo patch preflight result contract rejected")
        test_results.append(
            {
                "argv": argv,
                "returncode": returncode,
                "stdout_digest": _sha256_text(stdout),
                "stderr_digest": _sha256_text(stderr),
            }
        )
    return {
        "state_slice": PREFLIGHT_STATE_SLICE,
        "base_commit": receipt.base_commit,
        "base_tree": receipt.base_tree,
        "target_path": receipt.target_path,
        "target_preimage_digest": receipt.target_preimage_digest,
        "target_postimage_digest": receipt.target_postimage_digest,
        "authorized_diff_digest": receipt.authorized_diff_digest,
        "changed_paths": list(receipt.changed_paths),
        "test_results": test_results,
    }


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evaluation_from_payload(payload: Any) -> EvaluationResult:
    if not isinstance(payload, dict):
        raise ValueError("authority evaluation payload must be an object")
    required = {
        "evaluation_id",
        "decision_id",
        "passed",
        "final_recommendation",
        "stage_results",
        "blocking_reasons",
    }
    allowed = required | {"review_route"}
    if not required.issubset(payload) or set(payload) - allowed:
        raise ValueError("authority evaluation payload fields rejected")
    if not isinstance(payload["evaluation_id"], str) or not isinstance(payload["decision_id"], str):
        raise ValueError("authority evaluation identity fields rejected")
    if not isinstance(payload["passed"], bool) or not isinstance(payload["final_recommendation"], str):
        raise ValueError("authority evaluation verdict fields rejected")
    if not isinstance(payload["stage_results"], dict):
        raise ValueError("authority evaluation stage results rejected")
    if not isinstance(payload["blocking_reasons"], list) or any(
        not isinstance(reason, str) for reason in payload["blocking_reasons"]
    ):
        raise ValueError("authority evaluation blocking reasons rejected")
    review_route = payload.get("review_route")
    if review_route is not None and not isinstance(review_route, str):
        raise ValueError("authority evaluation review route rejected")
    return EvaluationResult(
        evaluation_id=payload["evaluation_id"],
        decision_id=payload["decision_id"],
        passed=payload["passed"],
        final_recommendation=payload["final_recommendation"],
        stage_results=payload["stage_results"],
        blocking_reasons=payload["blocking_reasons"],
        review_route=review_route,
    )


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _required_absolute_path(name: str) -> Path:
    raw = os.environ.get(name, "").strip()
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise RuntimeError(f"{name} must name an explicit absolute path")
    return path


def _read_key_file(path: Path, *, private: bool) -> str:
    if path.is_symlink() or not path.is_file():
        raise PermissionError(f"key path must be a regular non-symlink file: {path}")
    if private and stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise PermissionError(f"private key file must not grant group or other access: {path}")
    return path.read_text(encoding="utf-8").strip()


def _load_client_public_keys(registry_path: Path) -> dict[str, str]:
    if registry_path.is_symlink() or not registry_path.is_file():
        raise PermissionError("client public-key registry must be a regular non-symlink file")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or not registry:
        raise ValueError("client public-key registry must be a non-empty object")
    keys: dict[str, str] = {}
    for key_id, raw_path in registry.items():
        key_path = Path(str(raw_path))
        if not key_path.is_absolute():
            raise ValueError("client public-key registry paths must be absolute")
        keys[str(key_id)] = _read_key_file(key_path, private=False)
    return keys


def _authority_store_from_environment(
    state_directory: Path,
    runtime_config: RuntimeConfig,
) -> RepoPatchAuthorityStore:
    backend = os.environ.get("MESH_REPO_PATCH_AUTHORITY_STORE_BACKEND", "file").strip().lower()
    if backend == "file":
        return FileRepoPatchAuthorityStore(state_directory)
    if backend == "postgres":
        if not runtime_config.database_url:
            raise RuntimeError("Postgres repo-patch authority store requires MESH_DATABASE_URL")
        return PostgresRepoPatchAuthorityStore(runtime_config)
    raise RuntimeError("MESH_REPO_PATCH_AUTHORITY_STORE_BACKEND must be 'file' or 'postgres'")


def main() -> int:
    from services.orchestrator.hsai_bridge_adapter import build_hsai_admission_adapter

    socket_path = _required_absolute_path("MESH_REPO_PATCH_AUTHORITY_SOCKET_PATH")
    state_directory = _required_absolute_path("MESH_REPO_PATCH_AUTHORITY_STATE_DIRECTORY")
    authority_key_path = _required_absolute_path("MESH_REPO_PATCH_AUTHORITY_PRIVATE_KEY_PATH")
    client_keys_path = _required_absolute_path("MESH_REPO_PATCH_AUTHORITY_CLIENT_KEYS_PATH")
    permit_key_path = _required_absolute_path("MESH_REPO_PATCH_AUTHORITY_PERMIT_KEY_PATH")
    authority_key_id = os.environ.get("MESH_REPO_PATCH_AUTHORITY_KEY_ID", "").strip()
    allowed_uid_values = os.environ.get("MESH_REPO_PATCH_AUTHORITY_ALLOWED_UIDS", "").strip()
    if not authority_key_id or not allowed_uid_values:
        raise RuntimeError("authority key id and allowed UIDs must be explicitly configured")
    allowed_uids = {int(value.strip()) for value in allowed_uid_values.split(",") if value.strip()}
    raw_socket_gid = os.environ.get("MESH_REPO_PATCH_AUTHORITY_SOCKET_GID", "").strip()
    socket_gid = int(raw_socket_gid) if raw_socket_gid else None
    raw_allowed_commands = os.environ.get("MESH_REPO_PATCH_ALLOWED_TEST_COMMANDS_JSON", "[]")
    allowed_test_commands = json.loads(raw_allowed_commands)
    if not isinstance(allowed_test_commands, list) or any(
        not isinstance(command, list) or any(not isinstance(argument, str) for argument in command)
        for command in allowed_test_commands
    ):
        raise ValueError("MESH_REPO_PATCH_ALLOWED_TEST_COMMANDS_JSON must be an array of argv arrays")
    runtime_config = RuntimeConfig.from_env()
    hsai_admission_adapter = build_hsai_admission_adapter(runtime_config)
    if (
        getattr(hsai_admission_adapter, "authority_eligible", False) is not True
        or not str(getattr(hsai_admission_adapter, "adapter_identity", "") or "")
    ):
        raise RuntimeError("authority service requires an identity-pinned authority-eligible HSAI adapter")
    service = RepoPatchAuthorityService(
        socket_path,
        state_directory,
        authority_private_key_pem=_read_key_file(authority_key_path, private=True),
        authority_key_id=authority_key_id,
        client_public_keys=_load_client_public_keys(client_keys_path),
        allowed_uids=allowed_uids,
        permit_signing_key=_read_key_file(permit_key_path, private=True),
        allowed_test_commands=allowed_test_commands,
        socket_gid=socket_gid,
        max_frame_bytes=max(
            1024,
            int(os.environ.get("MESH_REPO_PATCH_AUTHORITY_MAX_MESSAGE_BYTES", "1048576")),
        ),
        permit_signing_key_id=os.environ.get(
            "MESH_REPO_PATCH_AUTHORITY_PERMIT_KEY_ID",
            "repo-patch-permit-hmac",
        ).strip(),
        authority_store=_authority_store_from_environment(state_directory, runtime_config),
        hsai_admission_adapter=hsai_admission_adapter,
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
