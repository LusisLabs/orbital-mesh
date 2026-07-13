from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, cast

from .contracts import Decision, EvaluationResult
from .json_store import LockedJsonFile
from .perennial.signing import build_hmac_signature_proof, verify_hmac_signature_proof
from .repo_patch_permit_validation import validate_repo_patch_execution_permit_semantics
from .schema_validation import validate_payload


REPO_PATCH_EXECUTION_PERMIT_VERSION = "mesh.repo_patch_execution_permit.v1"
REPO_PATCH_EXECUTION_TRANSACTION_VERSION = "mesh.repo_patch_execution_transaction.v1"
HSAI_EXECUTION_CONTEXT_KEY = "_mesh_hsai_admission_context"
GENESIS_LEDGER_TIP = "sha256:" + ("0" * 64)
REPO_PATCH_PERMIT_SIGNING_PROFILE = "mesh-repo-patch-execution-permit-hmac-sha256-v1"
TERMINAL_STATES = frozenset({"committed", "aborted", "recovery_required"})
MUTATION_STATES = frozenset({"prepared", "claimed", "applying", "applied", "verifying"})
ALLOWED_TRANSITIONS = {
    "issued": frozenset({"prepared"}),
    "prepared": frozenset({"claimed", "aborted", "recovery_required"}),
    "claimed": frozenset({"applying", "aborted", "recovery_required"}),
    "applying": frozenset({"applied", "aborted", "recovery_required"}),
    "applied": frozenset({"verifying", "aborted", "recovery_required"}),
    "verifying": frozenset({"committed", "aborted", "recovery_required"}),
}


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_actuation_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(parameters)
    payload.pop(HSAI_EXECUTION_CONTEXT_KEY, None)
    return payload


def repo_patch_target_binding(parameters: dict[str, Any]) -> tuple[Path, Path, str]:
    repo_path = Path(str(parameters["repo_path"]))
    if not repo_path.is_absolute() or repo_path.is_symlink():
        raise ValueError("repo patch root must be an absolute non-symlink path")
    repo_path = repo_path.resolve()
    patch_template = parameters.get("patch_template")
    if not isinstance(patch_template, dict):
        raise ValueError("repo patch template is missing")
    raw_target = Path(str(patch_template.get("target_file") or ""))
    unresolved_target = raw_target if raw_target.is_absolute() else repo_path / raw_target
    if unresolved_target.is_symlink():
        raise ValueError("repo patch target must not be a symlink")
    target_path = unresolved_target.resolve()
    try:
        relative_target = target_path.relative_to(repo_path)
    except ValueError as exc:
        raise ValueError("repo patch target escapes repo scope") from exc
    if str(relative_target) not in {str(Path(path)) for path in parameters.get("allowed_paths", [])}:
        raise ValueError("repo patch target falls outside allowed patch scope")
    if not target_path.is_file():
        raise ValueError("repo patch target must be an existing regular file")
    return repo_path, target_path, file_digest(target_path)


def repo_patch_postimage(parameters: dict[str, Any], target_path: Path) -> tuple[bytes, str]:
    patch_template = parameters.get("patch_template")
    if not isinstance(patch_template, dict):
        raise ValueError("repo patch template is missing")
    try:
        original = target_path.read_text(encoding="utf-8")
        find_text = str(patch_template["find"])
        replace_text = str(patch_template["replace"])
    except (KeyError, OSError, UnicodeError) as exc:
        raise ValueError(f"repo patch postimage binding failed: {exc}") from exc
    if find_text not in original:
        raise ValueError("patch anchor not found in target file")
    postimage = original.replace(find_text, replace_text, 1).encode("utf-8")
    return postimage, bytes_digest(postimage)


class RepoPatchPermitStore:
    def __init__(
        self,
        state_directory: str | Path,
        *,
        signing_key: str | None = None,
        signing_key_id: str = "repo-patch-permit-hmac",
        issuer: str = "mesh.orchestrator",
        executor_audience: str = "mesh.repo_patch_actuator",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.state_directory = Path(state_directory).resolve()
        self.path = self.state_directory / "repo_patch_authority_ledger.json"
        self.backup_directory = self.state_directory / "repo_patch_backups"
        self.signing_key = (signing_key or "").strip()
        self.signing_key_id = signing_key_id.strip()
        self.issuer = issuer.strip()
        self.executor_audience = executor_audience.strip()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def issue(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict[str, Any],
        idempotency_key: str,
        *,
        ttl_seconds: int = 300,
        permit_id: str | None = None,
        authority_nonce: str | None = None,
    ) -> dict[str, Any]:
        self._require_authority_configuration()
        from .hsai_bridge import validate_bridge_gate

        validate_bridge_gate(
            gate,
            expected_decision=decision,
            expected_evaluation=evaluation,
            require_mesh_policy_approved=True,
        )
        if not 1 <= ttl_seconds <= 300:
            raise ValueError("repo patch permit ttl must be between 1 and 300 seconds")
        if not gate.get("allowed") or gate.get("decision", {}).get("decision") != "allow":
            raise ValueError("repo patch permit requires an allowed HSAI decision")
        if gate.get("authority_eligible") is not True:
            raise ValueError("repo patch permit requires an authority-eligible HSAI adapter")
        if not evaluation.passed or evaluation.final_recommendation != "execute":
            raise ValueError("repo patch permit requires Mesh execute approval")
        expected_idempotency_key = f"{decision.decision_id}:{decision.execution_plan['action']}"
        if idempotency_key != expected_idempotency_key:
            raise ValueError("repo patch permit idempotency key mismatch")
        parameters = canonical_actuation_parameters(dict(decision.execution_plan["parameters"]))
        repo_path, target_path, target_preimage_digest = repo_patch_target_binding(parameters)
        _, target_postimage_digest = repo_patch_postimage(parameters, target_path)
        now = self.clock().astimezone(timezone.utc)
        expires_at = now + timedelta(seconds=ttl_seconds)
        request = dict(gate["request"])
        admission_decision = dict(gate["decision"])
        with LockedJsonFile(self.path, recover_corrupt_input=False) as ledger:
            permits = ledger.setdefault("permits", {})
            nonces = ledger.setdefault("consumed_nonces", {})
            idempotency = ledger.setdefault("idempotency", {})
            fenced_roots = ledger.setdefault("fenced_roots", {})
            if str(repo_path) in fenced_roots:
                raise ValueError("repo patch root is fenced pending authority recovery")
            tip_before = str(ledger.get("tip") or GENESIS_LEDGER_TIP)
            existing_permit_id = idempotency.get(idempotency_key)
            if existing_permit_id is not None:
                existing_record = permits.get(existing_permit_id)
                existing_permit = existing_record.get("permit") if isinstance(existing_record, dict) else None
                if not isinstance(existing_permit, dict):
                    raise ValueError("repo patch idempotency entry is corrupt")
                if existing_permit["canonical_actuation_payload_digest"] != canonical_digest(parameters):
                    raise ValueError("repo patch idempotency binding mismatch")
                return deepcopy(existing_permit)
            selected_permit_id = permit_id or f"permit_{secrets.token_hex(32)}"
            if selected_permit_id in permits:
                raise ValueError("repo patch permit id already exists")
            nonce = authority_nonce or secrets.token_hex(32)
            if nonce in nonces:
                raise ValueError("repo patch permit nonce already exists")
            permit = {
                "schema_version": REPO_PATCH_EXECUTION_PERMIT_VERSION,
                "transaction_version": REPO_PATCH_EXECUTION_TRANSACTION_VERSION,
                "permit_id": selected_permit_id,
                "authority_scope": "local_disposable_repo_patch_only",
                "issuer": self.issuer,
                "executor_audience": self.executor_audience,
                "tenant": request["actor_ref"]["team_id"],
                "mesh_run_id": request["mesh_run_id"],
                "mesh_action_id": request["mesh_action_id"],
                "action_kind": request["action_kind"],
                "authority_nonce": nonce,
                "idempotency_key": idempotency_key,
                "hsai_request_digest": gate["request_digest"],
                "hsai_decision_digest": gate["decision_digest"],
                "candidate_payload_digest": gate["candidate_digest"],
                "action_proposal_digest": request["action_proposal_digest"],
                "evidence_packet_digest": request["evidence_packet_digest"],
                "mesh_policy_id": request["mesh_policy_id"],
                "policy_snapshot_digest": canonical_digest(asdict(evaluation)),
                "canonical_actuation_payload_digest": canonical_digest(parameters),
                "repo_path": str(repo_path),
                "target_path": str(target_path),
                "target_preimage_digest": target_preimage_digest,
                "target_postimage_digest": target_postimage_digest,
                "requested_claims": list(request["requested_claims"]),
                "accepted_claims": list(admission_decision.get("accepted_claims") or []),
                "explicit_nonclaims": list(request["explicit_nonclaims"]),
                "enforced_nonclaims": list(admission_decision.get("enforced_nonclaims") or []),
                "expected_ledger_tip_before": tip_before,
                "issued_at": _format_time(now),
                "not_before": _format_time(now),
                "expires_at": _format_time(expires_at),
            }
            entry_digest = canonical_digest({"tip_before": tip_before, "permit": permit})
            permit["authority_entry_digest"] = entry_digest
            permit["ledger_tip_after"] = canonical_digest({"tip_before": tip_before, "entry_digest": entry_digest})
            permit["permit_digest"] = _permit_digest(permit)
            permit["authorization_proof"] = build_hmac_signature_proof(
                _permit_signed_payload(permit),
                key_id=self.signing_key_id,
                secret=self.signing_key,
                signing_profile=REPO_PATCH_PERMIT_SIGNING_PROFILE,
            )
            validate_payload("repo-patch-execution-permit.schema.json", permit)
            validate_repo_patch_execution_permit_semantics(permit)
            permits[selected_permit_id] = {
                "permit": permit,
                "state": "issued",
                "state_history": [{"state": "issued", "recorded_at": _format_time(now)}],
            }
            idempotency[idempotency_key] = selected_permit_id
            ledger["tip"] = permit["ledger_tip_after"]
            return deepcopy(permit)

    def consume(
        self,
        permit: dict[str, Any],
        decision: Decision,
        idempotency_key: str,
        actuation_parameters: dict[str, Any],
        *,
        failpoint: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        self._validate_permit(permit, decision, idempotency_key, actuation_parameters)
        now = self.clock().astimezone(timezone.utc)
        with LockedJsonFile(self.path, recover_corrupt_input=False) as ledger:
            records = ledger.get("permits")
            if not isinstance(records, dict):
                raise ValueError("repo patch authority ledger is missing permits")
            record = records.get(permit["permit_id"])
            if not isinstance(record, dict) or record.get("permit") != permit:
                raise ValueError("repo patch permit is not present in the authority ledger")
            if record.get("state") != "prepared":
                raise ValueError("repo patch permit is not prepared or was already claimed")
            nonces = ledger.setdefault("consumed_nonces", {})
            if permit["authority_nonce"] in nonces:
                raise ValueError("repo patch authority nonce already consumed")
            self._transition_record(record, "prepared", "claimed", now, None, None)
            nonces[permit["authority_nonce"]] = permit["permit_id"]
        if failpoint is not None:
            failpoint("claimed")
        return {
            "permit_id": permit["permit_id"],
            "permit_digest": permit["permit_digest"],
            "authority_entry_digest": permit["authority_entry_digest"],
            "ledger_tip_after": permit["ledger_tip_after"],
            "target_preimage_digest": permit["target_preimage_digest"],
            "target_postimage_digest": permit["target_postimage_digest"],
            "transaction_version": REPO_PATCH_EXECUTION_TRANSACTION_VERSION,
        }

    def record_transition(
        self,
        permit_id: str,
        expected_state: str,
        new_state: str,
        *,
        details: dict[str, Any] | None = None,
        terminal_result: dict[str, Any] | None = None,
        failpoint: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if new_state not in ALLOWED_TRANSITIONS.get(expected_state, frozenset()):
            raise ValueError(f"invalid repo patch authority transition: {expected_state}->{new_state}")
        if new_state in TERMINAL_STATES and terminal_result is None:
            raise ValueError("terminal repo patch transition requires a stored result")
        if new_state not in TERMINAL_STATES and terminal_result is not None:
            raise ValueError("non-terminal repo patch transition cannot store a terminal result")
        now = self.clock().astimezone(timezone.utc)
        with LockedJsonFile(self.path, recover_corrupt_input=False) as ledger:
            records = ledger.get("permits")
            if not isinstance(records, dict):
                raise ValueError("repo patch authority ledger is missing permits")
            record = records.get(permit_id)
            if not isinstance(record, dict):
                raise ValueError("repo patch permit is not present in the authority ledger")
            self._transition_record(record, expected_state, new_state, now, details, terminal_result)
            result = deepcopy(record)
        if failpoint is not None:
            failpoint(new_state)
        return result

    def terminal_result_for_idempotency(self, idempotency_key: str) -> dict[str, Any] | None:
        with LockedJsonFile(self.path, recover_corrupt_input=False) as ledger:
            permit_id = ledger.get("idempotency", {}).get(idempotency_key)
            record = ledger.get("permits", {}).get(permit_id) if permit_id else None
            if not isinstance(record, dict) or record.get("state") not in TERMINAL_STATES:
                return None
            result = record.get("terminal_result")
            if not isinstance(result, dict):
                raise ValueError("terminal repo patch authority record is missing its result")
            return deepcopy(result)

    def terminal_result_for_replay(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        expected_key = f"{decision.decision_id}:{decision.execution_plan['action']}"
        if idempotency_key != expected_key:
            raise ValueError("repo patch terminal replay idempotency mismatch")
        parameters = canonical_actuation_parameters(dict(decision.execution_plan["parameters"]))
        request = gate.get("request")
        if not isinstance(request, dict):
            raise ValueError("repo patch terminal replay gate request is missing")
        with LockedJsonFile(self.path, recover_corrupt_input=False) as ledger:
            permit_id = ledger.get("idempotency", {}).get(idempotency_key)
            record = ledger.get("permits", {}).get(permit_id) if permit_id else None
            if not isinstance(record, dict) or record.get("state") not in TERMINAL_STATES:
                return None
            permit = record.get("permit")
            result = record.get("terminal_result")
            if not isinstance(permit, dict) or not isinstance(result, dict):
                raise ValueError("terminal repo patch authority record is incomplete")
            expected_bindings = {
                "mesh_action_id": decision.decision_id,
                "mesh_run_id": request.get("mesh_run_id"),
                "idempotency_key": idempotency_key,
                "hsai_request_digest": gate.get("request_digest"),
                "hsai_decision_digest": gate.get("decision_digest"),
                "candidate_payload_digest": gate.get("candidate_digest"),
                "action_proposal_digest": request.get("action_proposal_digest"),
                "evidence_packet_digest": request.get("evidence_packet_digest"),
                "mesh_policy_id": request.get("mesh_policy_id"),
                "policy_snapshot_digest": canonical_digest(asdict(evaluation)),
                "canonical_actuation_payload_digest": canonical_digest(parameters),
            }
            mismatched = [field for field, expected in expected_bindings.items() if permit.get(field) != expected]
            if mismatched:
                raise ValueError(f"repo patch terminal replay binding mismatch: {sorted(mismatched)}")
            return deepcopy(result)

    def abort_with_restoration(
        self,
        permit: dict[str, Any],
        expected_state: str,
        reason: str,
        *,
        test_results: list[dict[str, Any]] | None = None,
        failpoint: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        try:
            with LockedJsonFile(self.path, recover_corrupt_input=False) as ledger:
                record = ledger.get("permits", {}).get(permit["permit_id"])
                if not isinstance(record, dict) or record.get("state") != expected_state:
                    raise ValueError("repo patch authority restoration state changed concurrently")
                details = deepcopy(record.get("transaction"))
            if not isinstance(details, dict):
                raise ValueError("authority transaction metadata is missing")
            backup_path = self._validated_backup_path(details, permit)
            target_path = Path(str(permit["target_path"]))
            if target_path.is_symlink():
                raise ValueError("repo patch restoration target became a symlink")
            current_digest = file_digest(target_path)
            if current_digest not in {
                permit["target_preimage_digest"],
                permit["target_postimage_digest"],
            }:
                raise ValueError("target state does not match the authorized preimage or postimage")
            _atomic_replace_bytes(target_path, backup_path.read_bytes())
            if file_digest(target_path) != permit["target_preimage_digest"]:
                raise ValueError("restored target does not match the authorized preimage")
        except (KeyError, OSError, TypeError, ValueError) as exc:
            recovery = self._fence_recovery(permit["permit_id"], expected_state, permit, str(exc), failpoint)
            return cast(dict[str, Any], recovery["result"])
        terminal = _aborted_result(permit, reason, backup_path, test_results=test_results)
        self.record_transition(
            permit["permit_id"],
            expected_state,
            "aborted",
            details={"restored": True, "restored_at": _format_time(self.clock())},
            terminal_result=terminal,
            failpoint=failpoint,
        )
        return terminal

    def recover_incomplete_actions(
        self,
        *,
        failpoint: Callable[[str], None] | None = None,
    ) -> list[dict[str, Any]]:
        with LockedJsonFile(self.path, recover_corrupt_input=False) as ledger:
            records = ledger.get("permits", {})
            if not isinstance(records, dict):
                raise ValueError("repo patch authority ledger is missing permits")
            candidates = [
                (permit_id, deepcopy(record))
                for permit_id, record in records.items()
                if isinstance(record, dict) and record.get("state") in MUTATION_STATES
            ]
        recovered: list[dict[str, Any]] = []
        for permit_id, record in candidates:
            state = str(record["state"])
            permit = record.get("permit")
            details = record.get("transaction")
            if not isinstance(permit, dict) or not isinstance(details, dict):
                recovered.append(self._fence_recovery(permit_id, state, permit, "authority transaction metadata is missing", failpoint))
                continue
            try:
                backup_path = self._validated_backup_path(details, permit)
                target_path = Path(str(permit["target_path"]))
                if target_path.is_symlink():
                    raise ValueError("repo patch recovery target became a symlink")
                target_digest = file_digest(target_path)
                if target_digest not in {
                    permit["target_preimage_digest"],
                    permit["target_postimage_digest"],
                }:
                    raise ValueError("target state does not match the authorized preimage or postimage")
                _atomic_replace_bytes(target_path, backup_path.read_bytes())
                if file_digest(target_path) != permit["target_preimage_digest"]:
                    raise ValueError("restored target does not match the authorized preimage")
            except (KeyError, OSError, TypeError, ValueError) as exc:
                recovered.append(self._fence_recovery(permit_id, state, permit, str(exc), failpoint))
                continue
            terminal = _aborted_result(
                permit,
                "incomplete repo patch authority transaction restored during recovery",
                backup_path,
            )
            self.record_transition(
                permit_id,
                state,
                "aborted",
                details={"recovered_at": _format_time(self.clock()), "restored": True},
                terminal_result=terminal,
                failpoint=failpoint,
            )
            recovered.append({"permit_id": permit_id, "state": "aborted", "result": terminal})
        return recovered

    def _validate_permit(
        self,
        permit: dict[str, Any],
        decision: Decision,
        idempotency_key: str,
        actuation_parameters: dict[str, Any],
    ) -> None:
        self._require_authority_configuration()
        validate_payload("repo-patch-execution-permit.schema.json", permit)
        validate_repo_patch_execution_permit_semantics(permit)
        if permit.get("issuer") != self.issuer:
            raise ValueError("repo patch permit issuer mismatch")
        if permit.get("executor_audience") != self.executor_audience:
            raise ValueError("repo patch permit executor audience mismatch")
        authorization_proof = permit.get("authorization_proof")
        if not isinstance(authorization_proof, dict):
            raise ValueError("repo patch permit authorization proof missing")
        if authorization_proof.get("key_id") != self.signing_key_id:
            raise ValueError("repo patch permit signing key id mismatch")
        if authorization_proof.get("signing_profile") != REPO_PATCH_PERMIT_SIGNING_PROFILE:
            raise ValueError("repo patch permit signing profile mismatch")
        if not verify_hmac_signature_proof(_permit_signed_payload(permit), authorization_proof, secret=self.signing_key):
            raise ValueError("repo patch permit HMAC verification failed")
        if permit.get("permit_digest") != _permit_digest(permit):
            raise ValueError("repo patch permit digest mismatch")
        parameters = canonical_actuation_parameters(actuation_parameters)
        repo_path, target_path, current_preimage_digest = repo_patch_target_binding(parameters)
        now = self.clock().astimezone(timezone.utc)
        if now < _parse_time(str(permit["not_before"])):
            raise ValueError("repo patch permit is not active yet")
        if now > _parse_time(str(permit["expires_at"])):
            raise ValueError("repo patch permit expired")
        if permit["idempotency_key"] != idempotency_key:
            raise ValueError("repo patch permit idempotency key mismatch")
        if idempotency_key != f"{decision.decision_id}:{decision.execution_plan['action']}":
            raise ValueError("repo patch decision idempotency binding mismatch")
        if permit["mesh_action_id"] != decision.decision_id:
            raise ValueError("repo patch permit action mismatch")
        if permit["canonical_actuation_payload_digest"] != canonical_digest(parameters):
            raise ValueError("repo patch permit actuation payload mismatch")
        if permit["repo_path"] != str(repo_path) or permit["target_path"] != str(target_path):
            raise ValueError("repo patch permit target path mismatch")
        if permit["target_preimage_digest"] != current_preimage_digest:
            raise ValueError("repo patch permit target preimage mismatch")
        _, current_postimage_digest = repo_patch_postimage(parameters, target_path)
        if permit["target_postimage_digest"] != current_postimage_digest:
            raise ValueError("repo patch permit target postimage mismatch")
        context = decision.execution_plan["parameters"].get(HSAI_EXECUTION_CONTEXT_KEY)
        if not isinstance(context, dict):
            raise ValueError("repo patch permit missing HSAI execution context")
        request = context.get("request")
        if not isinstance(request, dict) or permit["tenant"] != request.get("actor_ref", {}).get("team_id"):
            raise ValueError("repo patch permit tenant mismatch")
        for permit_field, context_field in (
            ("hsai_request_digest", "request_digest"),
            ("hsai_decision_digest", "decision_digest"),
            ("candidate_payload_digest", "candidate_digest"),
        ):
            if permit[permit_field] != context.get(context_field):
                raise ValueError(f"repo patch permit {permit_field} mismatch")

    def _transition_record(
        self,
        record: dict[str, Any],
        expected_state: str,
        new_state: str,
        now: datetime,
        details: dict[str, Any] | None,
        terminal_result: dict[str, Any] | None,
    ) -> None:
        if record.get("state") != expected_state:
            raise ValueError(f"repo patch authority state mismatch: expected {expected_state}, got {record.get('state')}")
        record["state"] = new_state
        history = record.setdefault("state_history", [])
        history.append({"state": new_state, "recorded_at": _format_time(now)})
        if details:
            transaction = record.setdefault("transaction", {})
            transaction.update(deepcopy(details))
        if terminal_result is not None:
            record["terminal_result"] = deepcopy(terminal_result)

    def _validated_backup_path(self, details: dict[str, Any], permit: dict[str, Any]) -> Path:
        backup_path = Path(str(details.get("backup_path") or "")).resolve()
        try:
            backup_path.relative_to(self.backup_directory.resolve())
        except ValueError as exc:
            raise ValueError("authority backup escapes the configured backup directory") from exc
        if not backup_path.is_file():
            raise ValueError("authority backup is missing")
        if file_digest(backup_path) != permit["target_preimage_digest"]:
            raise ValueError("authority backup does not match the authorized preimage")
        return backup_path

    def _fence_recovery(
        self,
        permit_id: str,
        expected_state: str,
        permit: Any,
        reason: str,
        failpoint: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        repo_path = str(permit.get("repo_path") or "") if isinstance(permit, dict) else ""
        terminal = {
            "status": "failed",
            "external_refs": {"permit_id": permit_id, "root_fenced": bool(repo_path)},
            "failure": {"reason": f"repo patch recovery required: {reason}"},
            "retryable": False,
        }
        now = self.clock().astimezone(timezone.utc)
        with LockedJsonFile(self.path, recover_corrupt_input=False) as ledger:
            record = ledger.get("permits", {}).get(permit_id)
            if not isinstance(record, dict) or record.get("state") != expected_state:
                raise ValueError("repo patch authority recovery state changed concurrently")
            self._transition_record(
                record,
                expected_state,
                "recovery_required",
                now,
                {"recovery_failure": reason},
                terminal,
            )
            if repo_path:
                ledger.setdefault("fenced_roots", {})[repo_path] = {
                    "permit_id": permit_id,
                    "reason": reason,
                    "fenced_at": _format_time(now),
                }
        if failpoint is not None:
            failpoint("recovery_required")
        return {"permit_id": permit_id, "state": "recovery_required", "result": terminal}

    def _require_authority_configuration(self) -> None:
        if not self.signing_key:
            raise ValueError("repo patch permit signing key is required for mutable authority")
        if not self.signing_key_id:
            raise ValueError("repo patch permit signing key id is required")
        if not self.issuer:
            raise ValueError("repo patch permit issuer is required")
        if not self.executor_audience:
            raise ValueError("repo patch permit executor audience is required")


def write_immutable_backup(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
            raise ValueError("authority backup path already exists with different content")
        return
    try:
        with path.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o400)
        _fsync_directory(path.parent)
    except BaseException:
        if path.exists() and path.read_bytes() != content:
            path.unlink(missing_ok=True)
        raise


def atomic_replace_bytes(path: Path, content: bytes) -> None:
    _atomic_replace_bytes(path, content)


def _atomic_replace_bytes(path: Path, content: bytes) -> None:
    mode = path.stat().st_mode & 0o777
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_name, mode)
        os.replace(temporary_name, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _aborted_result(
    permit: dict[str, Any], reason: str, backup_path: Path, *, test_results: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "status": "failed",
        "external_refs": {
            "permit_id": permit["permit_id"],
            "backup_path": str(backup_path),
            "test_results": list(test_results or []),
            "target_restored": True,
        },
        "failure": {"reason": reason},
        "retryable": False,
    }


def _permit_digest(permit: dict[str, Any]) -> str:
    payload = dict(permit)
    payload.pop("permit_digest", None)
    payload.pop("authorization_proof", None)
    return canonical_digest(payload)


def _permit_signed_payload(permit: dict[str, Any]) -> dict[str, Any]:
    payload = dict(permit)
    payload.pop("authorization_proof", None)
    return payload


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
