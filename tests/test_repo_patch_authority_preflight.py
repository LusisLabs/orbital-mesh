from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import threading
import unittest
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.actuators.repo_patch_authority_service import RepoPatchAuthorityService
from shared.mesh_runtime import Decision, EvaluationResult
from shared.mesh_runtime.hsai_bridge import (
    attach_hsai_execution_context,
    build_hsai_admission_request_v2,
    decision_digest,
    evaluate_hsai_gate,
    local_hsai_allow_decision,
)
from shared.mesh_runtime.repo_patch_authority import (
    AUTHORITY_RESPONSE_SIGNING_PROFILE,
    PREFLIGHT_RECEIPT_STATE_SLICE,
    RepoPatchAuthorityClient,
    RepoPatchAuthorityError,
    validate_authority_request_operation,
)
from shared.mesh_runtime.repo_patch_permits import write_immutable_backup


CLIENT_KEY_ID = "mesh-preflight-test-client"
AUTHORITY_KEY_ID = "mesh-preflight-test-authority"
PERMIT_SIGNING_KEY = "mesh-preflight-test-permit-key"
AUTHORIZED_COMMAND = (
    "python3",
    "-c",
    "assert 'new' in __import__('pathlib').Path('app/search.py').read_text()",
)
_DEFAULT_ADAPTER = object()


class _EligibleHsaiAdapter:
    authority_eligible = True
    adapter_identity = "mesh.test.hsai.authority-eligible.v1"

    def admit(self, request: dict[str, Any]) -> dict[str, Any]:
        decision = local_hsai_allow_decision(request)
        if not isinstance(decision, dict):
            raise AssertionError("test HSAI adapter returned a non-object decision")
        decision["created_at"] = request["created_at"]
        decision["decision_digest"] = decision_digest(decision)
        return decision


class _DenyingHsaiAdapter(_EligibleHsaiAdapter):
    adapter_identity = "mesh.test.hsai.authority-denying.v1"

    def admit(self, request: dict[str, Any]) -> dict[str, Any]:
        decision = super().admit(request)
        decision["decision"] = "deny"
        decision["accepted_claims"] = []
        decision["reason_codes"] = ["authority_side_denial"]
        decision["decision_digest"] = decision_digest(decision)
        return decision


class _UnavailableHsaiAdapter(_EligibleHsaiAdapter):
    adapter_identity = "mesh.test.hsai.authority-unavailable.v1"

    def admit(self, request: dict[str, Any]) -> dict[str, Any]:
        del request
        raise RuntimeError("injected authority-side HSAI outage")


class RepoPatchAuthorityPreflightTests(unittest.TestCase):
    client_private_key: str
    client_public_key: str
    authority_private_key: str
    authority_public_key: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.client_private_key, cls.client_public_key = _ed25519_key_pair()
        cls.authority_private_key, cls.authority_public_key = _ed25519_key_pair()

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.socket_path = self.root / "socket" / "authority.sock"
        self.state_directory = self.root / "authority-state"

    def test_signed_two_phase_flow_preflights_without_mutation_then_executes(self) -> None:
        repo = _git_repo(self.root / "repo")
        decision = _decision(repo)
        evaluation = _evaluation(decision.decision_id)
        service = self._service()
        client = self._client()
        idempotency_key = _idempotency_key(decision)

        with patch.object(service.actuator, "execute_patch", side_effect=AssertionError("actuator must not reapply")):
            with _running_service(service, expected_connections=2):
                receipt = client.preflight(decision, evaluation, idempotency_key)
                self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")
                self.assertFalse((self.state_directory / "repo_patch_authority_ledger.json").exists())
                self.assertEqual(list((self.state_directory / "repo_patch_preflight_worktrees").iterdir()), [])
                gate = _gate(decision, evaluation, receipt)
                response = client.execute(decision, evaluation, gate, idempotency_key, receipt)

        self.assertEqual(receipt["state_slice"], PREFLIGHT_RECEIPT_STATE_SLICE)
        self.assertEqual(receipt["target_path"], "app/search.py")
        self.assertEqual(receipt["changed_paths"], ["app/search.py"])
        self.assertRegex(receipt["base_commit"], r"^[0-9a-f]{40,64}$")
        self.assertRegex(receipt["base_tree"], r"^[0-9a-f]{40,64}$")
        for field in ("target_preimage_digest", "target_postimage_digest", "authorized_diff_digest"):
            self.assertRegex(receipt[field], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(len(receipt["test_results"]), 1)
        test_result = receipt["test_results"][0]
        self.assertEqual(set(test_result), {"argv", "returncode", "stdout_digest", "stderr_digest"})
        self.assertTrue(Path(test_result["argv"][0]).is_absolute())
        self.assertEqual(test_result["argv"][1:], list(AUTHORIZED_COMMAND[1:]))
        self.assertEqual(test_result["returncode"], 0)
        self.assertRegex(test_result["stdout_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(test_result["stderr_digest"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["execution_result"]["status"], "succeeded")
        self.assertEqual(response["authorization_proof"]["key_id"], AUTHORITY_KEY_ID)
        self.assertEqual(
            response["authorization_proof"]["signing_profile"],
            AUTHORITY_RESPONSE_SIGNING_PROFILE,
        )
        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'new'\n")
        self.assertEqual(list((self.state_directory / "repo_patch_preflight_worktrees").iterdir()), [])
        lifecycle = json.loads((self.state_directory / "repo_patch_authority_store.json").read_text(encoding="utf-8"))
        self.assertEqual(len(lifecycle["records"]), 2)
        self.assertTrue(all(record["state"] == "terminal" for record in lifecycle["records"].values()))
        self.assertTrue(
            all(
                [event["event_type"] for event in events]
                == ["issued", "leased_for_dispatch", "marked_dispatched", "terminal_completed"]
                for events in lifecycle["events"].values()
            )
        )

    def test_terminal_preflight_replay_does_not_dispatch_a_second_worktree(self) -> None:
        repo = _git_repo(self.root / "repo")
        decision = _decision(repo)
        evaluation = _evaluation(decision.decision_id)
        service = self._service()
        client = self._client()

        with _running_service(service, expected_connections=2):
            first = client.preflight(decision, evaluation, _idempotency_key(decision))
            second = client.preflight(decision, evaluation, _idempotency_key(decision))

        self.assertEqual(first, second)
        lifecycle = json.loads((self.state_directory / "repo_patch_authority_store.json").read_text(encoding="utf-8"))
        self.assertEqual(len(lifecycle["records"]), 1)
        events = next(iter(lifecycle["events"].values()))
        self.assertEqual(
            [event["event_type"] for event in events],
            ["issued", "leased_for_dispatch", "marked_dispatched", "terminal_completed"],
        )
        self.assertEqual(list((self.state_directory / "repo_patch_preflight_worktrees").iterdir()), [])

    def test_execute_rejects_forged_client_allow_against_authority_side_denial(self) -> None:
        repo = _git_repo(self.root / "repo")
        decision = _decision(repo)
        evaluation = _evaluation(decision.decision_id)
        client = self._client()
        service = self._service(hsai_adapter=_DenyingHsaiAdapter())

        with _running_service(service, expected_connections=2):
            receipt = client.preflight(decision, evaluation, _idempotency_key(decision))
            forged_allow = _gate(decision, evaluation, receipt)
            response = client.execute(decision, evaluation, forged_allow, _idempotency_key(decision), receipt)

        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["rejection"]["code"], "hsai_authority_gate_mismatch")
        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_execute_rejects_unavailable_authority_side_adapter(self) -> None:
        repo = _git_repo(self.root / "repo")
        decision = _decision(repo)
        evaluation = _evaluation(decision.decision_id)
        client = self._client()
        service = self._service(hsai_adapter=None)

        with _running_service(service, expected_connections=2):
            receipt = client.preflight(decision, evaluation, _idempotency_key(decision))
            response = client.execute(
                decision,
                evaluation,
                _gate(decision, evaluation, receipt),
                _idempotency_key(decision),
                receipt,
            )

        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["rejection"]["code"], "hsai_authority_adapter_unavailable")
        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_execute_rejects_authority_side_adapter_outage(self) -> None:
        repo = _git_repo(self.root / "repo")
        decision = _decision(repo)
        evaluation = _evaluation(decision.decision_id)
        client = self._client()
        service = self._service(hsai_adapter=_UnavailableHsaiAdapter())

        with _running_service(service, expected_connections=2):
            receipt = client.preflight(decision, evaluation, _idempotency_key(decision))
            response = client.execute(
                decision,
                evaluation,
                _gate(decision, evaluation, receipt),
                _idempotency_key(decision),
                receipt,
            )

        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["rejection"]["code"], "hsai_authority_adapter_unavailable")
        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_dispatched_nonterminal_retry_becomes_unknown_without_repromotion(self) -> None:
        repo = _git_repo(self.root / "repo")
        decision = _decision(repo)
        evaluation = _evaluation(decision.decision_id)
        client = self._client()
        service = self._service()
        idempotency_key = _idempotency_key(decision)

        with _running_service(service, expected_connections=1):
            receipt = client.preflight(decision, evaluation, idempotency_key)
        gate = _gate(decision, evaluation, receipt)
        lifecycle_body = {
            "operation": "execute",
            "idempotency_key": idempotency_key,
            "decision": decision.to_dict(),
            "evaluation": asdict(evaluation),
            "hsai_gate": gate,
            "preflight_receipt": receipt,
        }
        issued = service._issue_authority_lifecycle(
            lifecycle_body,
            client_key_id=CLIENT_KEY_ID,
            peer_uid=os.geteuid(),
            peer_gid=os.getegid(),
        )
        leased = service.authority_store.lease_for_dispatch(
            str(issued["authority_id"]),
            expected_version=int(issued["version"]),
            lease_id="simulated-crash-lease",
        )
        service.authority_store.mark_dispatched(
            str(leased["authority_id"]),
            expected_version=int(leased["version"]),
            lease_id="simulated-crash-lease",
        )

        with patch.object(service.workspace_manager, "prepare", side_effect=AssertionError("must not prepare")):
            with _running_service(service, expected_connections=1):
                response = client.execute(decision, evaluation, gate, idempotency_key, receipt)

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["execution_result"]["failure"]["reason"], "authority_outcome_unknown_after_dispatch")
        self.assertTrue(response["execution_result"]["external_refs"]["recovery_required"])
        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")
        reconciliation = service.authority_store.read_for_reconciliation(str(issued["authority_id"]))
        assert reconciliation is not None
        self.assertEqual(reconciliation["record"]["terminal_outcome"], "unknown")

    def test_dispatched_retry_reconciles_committed_permit_after_restart(self) -> None:
        repo = _git_repo(self.root / "repo")
        target = repo / "app/search.py"
        decision = _decision(repo)
        evaluation = _evaluation(decision.decision_id)
        client = self._client()
        service = self._service()
        idempotency_key = _idempotency_key(decision)

        with _running_service(service, expected_connections=1):
            receipt = client.preflight(decision, evaluation, idempotency_key)
        gate = _gate(decision, evaluation, receipt)
        dispatched = self._dispatch_execution_lifecycle(
            service,
            decision,
            evaluation,
            gate,
            receipt,
            idempotency_key=idempotency_key,
            lease_id="committed-crash-lease",
        )
        permit, _ = self._prepare_execution_permit(
            service,
            decision,
            evaluation,
            gate,
            idempotency_key=idempotency_key,
        )
        admitted_decision = attach_hsai_execution_context(decision, gate, permit)
        authority_receipt = service.permit_store.consume(
            permit,
            admitted_decision,
            idempotency_key,
            dict(decision.execution_plan["parameters"]),
        )
        service.permit_store.record_transition(str(permit["permit_id"]), "claimed", "applying")
        target.write_text("VALUE = 'new'\n", encoding="utf-8")
        service.permit_store.record_transition(str(permit["permit_id"]), "applying", "applied")
        service.permit_store.record_transition(str(permit["permit_id"]), "applied", "verifying")
        committed_result = {
            "status": "succeeded",
            "external_refs": {
                "authority_receipt": authority_receipt,
                "patched_files": [str(target)],
            },
            "retryable": False,
        }
        service.permit_store.record_transition(
            str(permit["permit_id"]),
            "verifying",
            "committed",
            terminal_result=committed_result,
        )

        restarted_service = self._service()
        self.assertEqual(
            restarted_service.permit_store.terminal_result_for_replay(
                decision,
                evaluation,
                gate,
                idempotency_key,
            ),
            committed_result,
        )
        with patch.object(
            restarted_service.workspace_manager,
            "prepare",
            side_effect=AssertionError("committed replay must not prepare a new worktree"),
        ):
            with _running_service(restarted_service, expected_connections=1):
                response = client.execute(decision, evaluation, gate, idempotency_key, receipt)

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["execution_result"], committed_result)
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'new'\n")
        reconciliation = restarted_service.authority_store.read_for_reconciliation(str(dispatched["authority_id"]))
        assert reconciliation is not None
        self.assertEqual(reconciliation["record"]["terminal_outcome"], "succeeded")

    def test_dispatched_retry_reconciles_aborted_permit_after_restart(self) -> None:
        repo = _git_repo(self.root / "repo")
        target = repo / "app/search.py"
        decision = _decision(repo)
        evaluation = _evaluation(decision.decision_id)
        client = self._client()
        service = self._service()
        idempotency_key = _idempotency_key(decision)

        with _running_service(service, expected_connections=1):
            receipt = client.preflight(decision, evaluation, idempotency_key)
        gate = _gate(decision, evaluation, receipt)
        dispatched = self._dispatch_execution_lifecycle(
            service,
            decision,
            evaluation,
            gate,
            receipt,
            idempotency_key=idempotency_key,
            lease_id="aborted-crash-lease",
        )
        permit, _ = self._prepare_execution_permit(
            service,
            decision,
            evaluation,
            gate,
            idempotency_key=idempotency_key,
        )
        target.write_text("VALUE = 'new'\n", encoding="utf-8")
        aborted_result = service.permit_store.abort_with_restoration(
            permit,
            "prepared",
            "simulated post-dispatch abort before lifecycle completion",
        )

        restarted_service = self._service()
        self.assertEqual(
            restarted_service.permit_store.terminal_result_for_replay(
                decision,
                evaluation,
                gate,
                idempotency_key,
            ),
            aborted_result,
        )
        with patch.object(
            restarted_service.workspace_manager,
            "prepare",
            side_effect=AssertionError("aborted replay must not prepare a new worktree"),
        ):
            with _running_service(restarted_service, expected_connections=1):
                response = client.execute(decision, evaluation, gate, idempotency_key, receipt)

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["execution_result"], aborted_result)
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'old'\n")
        reconciliation = restarted_service.authority_store.read_for_reconciliation(str(dispatched["authority_id"]))
        assert reconciliation is not None
        self.assertEqual(reconciliation["record"]["terminal_outcome"], "failed")

    def test_preflight_requires_at_least_one_policy_authorized_command(self) -> None:
        repo = _git_repo(self.root / "repo")
        decision = _decision(repo, test_commands=[])
        evaluation = _evaluation(decision.decision_id)
        service = self._service()

        with _running_service(service, expected_connections=1):
            with self.assertRaisesRegex(RepoPatchAuthorityError, "preflight_rejected"):
                self._client().preflight(decision, evaluation, _idempotency_key(decision))

        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")
        workspace_root = self.state_directory / "repo_patch_preflight_worktrees"
        self.assertFalse(workspace_root.exists())

    def test_execute_recomputes_preflight_and_rejects_clean_source_drift(self) -> None:
        repo = _git_repo(self.root / "repo")
        decision = _decision(repo)
        evaluation = _evaluation(decision.decision_id)
        client = self._client()
        service = self._service()
        idempotency_key = _idempotency_key(decision)

        with _running_service(service, expected_connections=2):
            receipt = client.preflight(decision, evaluation, idempotency_key)
            gate = _gate(decision, evaluation, receipt)
            target = repo / "app/search.py"
            target.write_text("# external commit\nVALUE = 'old'\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "app/search.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "external drift"], check=True)
            response = client.execute(decision, evaluation, gate, idempotency_key, receipt)

        self.assertEqual(response["status"], "rejected")
        self.assertEqual(response["rejection"]["code"], "preflight_drift_rejected")
        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "# external commit\nVALUE = 'old'\n")
        self.assertFalse((self.state_directory / "repo_patch_authority_ledger.json").exists())
        self.assertEqual(list((self.state_directory / "repo_patch_preflight_worktrees").iterdir()), [])

    def test_operation_semantics_require_nullable_preflight_fields_and_execute_receipt(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not carry"):
            validate_authority_request_operation(
                {"operation": "preflight", "hsai_gate": {"allowed": True}, "preflight_receipt": None}
            )
        with self.assertRaisesRegex(ValueError, "requires"):
            validate_authority_request_operation(
                {"operation": "execute", "hsai_gate": {}, "preflight_receipt": None}
            )

    def _service(self, *, hsai_adapter: object = _DEFAULT_ADAPTER) -> RepoPatchAuthorityService:
        resolved_adapter = _EligibleHsaiAdapter() if hsai_adapter is _DEFAULT_ADAPTER else hsai_adapter
        return RepoPatchAuthorityService(
            self.socket_path,
            self.state_directory,
            authority_private_key_pem=self.authority_private_key,
            authority_key_id=AUTHORITY_KEY_ID,
            client_public_keys={CLIENT_KEY_ID: self.client_public_key},
            allowed_uids={os.geteuid()},
            permit_signing_key=PERMIT_SIGNING_KEY,
            allowed_test_commands=(AUTHORIZED_COMMAND,),
            hsai_admission_adapter=resolved_adapter,
        )

    def _dispatch_execution_lifecycle(
        self,
        service: RepoPatchAuthorityService,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict[str, Any],
        receipt: dict[str, Any],
        *,
        idempotency_key: str,
        lease_id: str,
    ) -> dict[str, Any]:
        issued = service._issue_authority_lifecycle(
            {
                "operation": "execute",
                "idempotency_key": idempotency_key,
                "decision": decision.to_dict(),
                "evaluation": asdict(evaluation),
                "hsai_gate": gate,
                "preflight_receipt": receipt,
            },
            client_key_id=CLIENT_KEY_ID,
            peer_uid=os.geteuid(),
            peer_gid=os.getegid(),
        )
        leased = service.authority_store.lease_for_dispatch(
            str(issued["authority_id"]),
            expected_version=int(issued["version"]),
            lease_id=lease_id,
        )
        return service.authority_store.mark_dispatched(
            str(leased["authority_id"]),
            expected_version=int(leased["version"]),
            lease_id=lease_id,
        )

    def _prepare_execution_permit(
        self,
        service: RepoPatchAuthorityService,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict[str, Any],
        *,
        idempotency_key: str,
    ) -> tuple[dict[str, Any], Path]:
        permit = service.permit_store.issue(decision, evaluation, gate, idempotency_key)
        target = Path(str(permit["target_path"]))
        backup_path = service.permit_store.backup_directory / f"{permit['permit_id']}.bak"
        write_immutable_backup(backup_path, target.read_bytes())
        service.permit_store.record_transition(
            str(permit["permit_id"]),
            "issued",
            "prepared",
            details={
                "backup_path": str(backup_path),
                "repo_path": str(permit["repo_path"]),
                "target_path": str(target),
            },
        )
        return permit, backup_path

    def _client(self) -> RepoPatchAuthorityClient:
        return RepoPatchAuthorityClient(
            self.socket_path,
            client_private_key_pem=self.client_private_key,
            client_key_id=CLIENT_KEY_ID,
            authority_public_key_pem=self.authority_public_key,
            authority_key_id=AUTHORITY_KEY_ID,
        )


@contextmanager
def _running_service(service: RepoPatchAuthorityService, *, expected_connections: int) -> Iterator[None]:
    service.start()
    failures: list[BaseException] = []

    def serve_expected_connections() -> None:
        try:
            for _ in range(expected_connections):
                service.serve_once()
        except BaseException as exc:
            failures.append(exc)

    thread = threading.Thread(target=serve_expected_connections, daemon=True)
    thread.start()
    try:
        yield
        thread.join(timeout=15)
        if thread.is_alive():
            raise AssertionError("authority service did not process expected preflight connections")
        if failures:
            raise AssertionError(f"authority service thread failed: {failures!r}")
    finally:
        service.close()


def _decision(repo: Path, *, test_commands: list[str] | None = None) -> Decision:
    configured_commands = [shlex.join(AUTHORIZED_COMMAND)] if test_commands is None else test_commands
    return Decision(
        decision_id="decision-authority-preflight",
        trigger_id="trigger-authority-preflight",
        summary="Patch a disposable search service",
        decision_type="investigate_and_patch",
        autonomy_tier="approval_required",
        reasoning={
            "primary_hypothesis": "fixture value needs replacement",
            "evidence": ["local disposable fixture"],
            "alternatives_considered": ["leave unchanged"],
        },
        expected_outcome={
            "target_metrics": {"p95_latency_ms": "unchanged", "error_rate": "unchanged"},
            "time_to_effect": "local",
        },
        risk={"level": "medium", "blast_radius": "disposable repo", "customer_impact_if_wrong": "none"},
        confidence=0.99,
        execution_plan={
            "system": "repo_patch_service",
            "action": "investigate_and_patch",
            "parameters": {
                "repo_path": str(repo),
                "allowed_paths": ["app/search.py"],
                "patch_template": {
                    "target_file": "app/search.py",
                    "find": "old",
                    "replace": "new",
                },
                "test_commands": configured_commands,
                "mesh_run_id": "run-authority-preflight",
                "mesh_policy_id": "mesh_policy://repo-patch/authority-preflight-test",
                "actor_ref": {"actor_id": "operator.test", "team_id": "team.test"},
            },
            "rollback_plan": "restore the immutable backup",
        },
    )


def _evaluation(decision_id: str) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id="evaluation-authority-preflight",
        decision_id=decision_id,
        passed=True,
        final_recommendation="execute",
        stage_results={
            "schema_validation": {"passed": True},
            "policy_validation": {
                "passed": True,
                "policy_id": "mesh_policy://repo-patch/authority-preflight-test",
            },
            "contract_checks": {"passed": True},
            "trajectory_quality": {"passed": True},
            "behavioral_scores": {"passed": True},
            "verifier": {"passed": True},
            "business_rules": {"passed": True},
            "execution_readiness": {"passed": True},
        },
        blocking_reasons=[],
        review_route=None,
    )


def _gate(
    decision: Decision,
    evaluation: EvaluationResult,
    preflight_receipt: dict[str, Any],
) -> dict[str, Any]:
    gate = evaluate_hsai_gate(
        build_hsai_admission_request_v2(decision, evaluation, preflight_receipt),
        _EligibleHsaiAdapter(),
    )
    if not isinstance(gate, dict):
        raise AssertionError("test HSAI gate returned a non-object result")
    return gate


def _git_repo(path: Path) -> Path:
    target = path / "app/search.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 'old'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Mesh Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "mesh@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "app/search.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return path.resolve()


def _idempotency_key(decision: Decision) -> str:
    return f"{decision.decision_id}:{decision.execution_plan['action']}"


def _ed25519_key_pair() -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


if __name__ == "__main__":
    unittest.main()
