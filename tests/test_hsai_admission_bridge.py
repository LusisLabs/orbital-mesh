from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from services.actuators.repo_patch import RepoPatchAdapter
from services.orchestrator.adapters_common import CliExecutionResult
from services.orchestrator.goose_adapter import NativeGooseAdapter
from services.orchestrator.hermes_adapter import NativeHermesAdapter
from services.orchestrator.hsai_bridge_adapter import LocalHsaiAdmissionAdapter, SubprocessHsaiAdmissionAdapter
from services.orchestrator.service import OrchestratorService
from shared.mesh_runtime import Decision, EvaluationResult, RuntimeConfig, SchemaValidationError, validate_payload
from shared.mesh_runtime.hsai_bridge import (
    attach_hsai_execution_context,
    build_combined_proof_packet,
    build_hsai_admission_request,
    evaluate_hsai_gate,
    local_hsai_allow_decision,
    load_hsai_formal_backend_run_metadata,
    repo_patch_admission_failure,
    validate_combined_proof_packet,
    validate_hsai_decision,
    validate_hsai_execution_context,
    verify_combined_proof_packet_payload,
)
from shared.mesh_runtime.repo_patch_permits import RepoPatchPermitStore, canonical_digest
from shared.mesh_runtime.repo_patch_authority import RepoPatchAuthorityError


REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_HSAI_BRIDGE_FIXTURES = REPO_ROOT / "fixtures" / "hsai_bridge"
HSAI_FORMAL_BACKEND_BUNDLE_FIXTURE = GOLDEN_HSAI_BRIDGE_FIXTURES / "formal_backend_notrun_bundle"
TEST_PERMIT_SIGNING_KEY = "test-repo-patch-permit-signing-key"
TEST_PERMIT_SIGNING_KEY_ID = "test-repo-patch-permit-key"
TEST_PERMIT_ISSUER = "mesh.test.orchestrator"
TEST_PERMIT_EXECUTOR_AUDIENCE = "mesh.test.repo_patch_actuator"


class SimulatedAuthorityCrash(BaseException):
    pass


class CountingExecutionAdapter:
    def __init__(self, status: str = "succeeded") -> None:
        self.calls = 0
        self.status = status

    def execute_decision(self, decision: Decision, idempotency_key: str) -> CliExecutionResult:
        self.calls += 1
        return CliExecutionResult(
            status=self.status,
            external_refs=_review_only_refs(),
            failure=None if self.status == "succeeded" else {"reason": "executor_failed"},
        )

    def open_execution_incident(self, decision: Decision, failure_reason: str) -> dict[str, str]:
        return {"incident_id": "inc_hsai_bridge"}


class RecordingHsaiAdapter:
    authority_eligible = True
    adapter_identity = "mesh.test.recording-hsai-adapter.v1"

    def __init__(self, mode: str = "allow") -> None:
        self.mode = mode
        self.calls = 0
        self.requests: list[dict] = []

    def admit(self, request: dict) -> dict:
        self.calls += 1
        self.requests.append(request)
        if self.mode == "unavailable":
            raise RuntimeError("hsai down")
        if self.mode == "malformed":
            return {"schema_version": "wrong"}
        if self.mode == "missing_decision_schema_version":
            decision = local_hsai_allow_decision(request)
            decision.pop("schema_version", None)
            return decision
        decision = local_hsai_allow_decision(request)
        if self.mode == "deny":
            decision["decision"] = "deny"
            decision["accepted_claims"] = []
            decision["reason_codes"] = ["candidate_evidence_denied"]
            decision["decision_digest"] = _decision_digest(decision)
        if self.mode == "old_run":
            old_request = dict(request)
            old_request["mesh_run_id"] = "run_old"
            decision = local_hsai_allow_decision(old_request)
        if self.mode == "old_action":
            old_request = dict(request)
            old_request["mesh_action_id"] = "action_old"
            decision = local_hsai_allow_decision(old_request)
        if self.mode == "request_digest_mismatch":
            decision["request_digest"] = "sha256:" + ("0" * 64)
            decision["decision_digest"] = _decision_digest(decision)
        if self.mode == "candidate_mismatch":
            decision["candidate_digest"] = "sha256:" + ("1" * 64)
            decision["decision_digest"] = _decision_digest(decision)
        if self.mode == "run_field_mismatch":
            decision["mesh_run_id"] = "run_stale"
            decision["decision_digest"] = _decision_digest(decision)
        if self.mode == "action_field_mismatch":
            decision["mesh_action_id"] = "action_stale"
            decision["decision_digest"] = _decision_digest(decision)
        if self.mode == "policy_mismatch":
            decision["admission_policy_id"] = "mesh_policy://stale"
            decision["decision_digest"] = _decision_digest(decision)
        if self.mode == "unsupported_decision_schema_version":
            decision["schema_version"] = "mesh.hsai_admission_decision.v2"
            decision["decision_digest"] = _decision_digest(decision)
        if self.mode == "drops_nonclaims":
            decision["enforced_nonclaims"] = decision["enforced_nonclaims"][:-1]
            decision["decision_digest"] = _decision_digest(decision)
        return decision


class RecordingSubprocessHsaiAdapter(SubprocessHsaiAdmissionAdapter):
    def __init__(self, command: str) -> None:
        super().__init__(command)
        self.requests: list[dict] = []
        self.decisions: list[dict] = []

    def admit(self, request: dict) -> dict:
        decision = super().admit(request)
        self.requests.append(request)
        self.decisions.append(decision)
        return decision


class RecordingAuthorityClient:
    def __init__(self, *, mutate: bool = False) -> None:
        self.calls = 0
        self.preflight_calls = 0
        self.mutate = mutate

    def preflight(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        idempotency_key: str,
    ) -> dict:
        del evaluation, idempotency_key
        self.preflight_calls += 1
        target = decision.execution_plan["parameters"]["patch_template"]["target_file"]
        declared_commands = decision.execution_plan["parameters"]["test_commands"]
        return {
            "state_slice": "mesh.repo_patch_disposable_worktree.v1",
            "base_commit": "a" * 40,
            "base_tree": "b" * 40,
            "target_path": target,
            "target_preimage_digest": "sha256:" + ("1" * 64),
            "target_postimage_digest": "sha256:" + ("2" * 64),
            "authorized_diff_digest": "sha256:" + ("3" * 64),
            "changed_paths": [target],
            "test_results": [
                {
                    "argv": ["/usr/bin/" + shlex.split(command)[0], *shlex.split(command)[1:]],
                    "returncode": 0,
                    "stdout_digest": "sha256:" + ("4" * 64),
                    "stderr_digest": "sha256:" + ("5" * 64),
                }
                for command in declared_commands
            ],
        }

    def execute(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict,
        idempotency_key: str,
        preflight_receipt: dict,
    ) -> dict:
        del evaluation, gate, preflight_receipt
        self.calls += 1
        patched_files: list[str] = []
        if self.mutate:
            parameters = decision.execution_plan["parameters"]
            repo = Path(parameters["repo_path"])
            template = parameters["patch_template"]
            target = repo / template["target_file"]
            target.write_text(
                target.read_text(encoding="utf-8").replace(template["find"], template["replace"], 1),
                encoding="utf-8",
            )
            patched_files.append(template["target_file"])
        return {
            "schema_version": "mesh.repo_patch_authority_response.v1",
            "request_id": f"authority_request_{self.calls}",
            "idempotency_key": idempotency_key,
            "status": "completed",
            "execution_result": {
                "status": "succeeded",
                "external_refs": {"patched_files": patched_files, "test_results": []},
                "failure": None,
                "retryable": False,
            },
            "receipt": {
                "state_slice": "mesh.repo_patch_authority_service.v1",
                "execution_result_digest": "sha256:" + ("1" * 64),
            },
            "rejection": None,
            "issued_at": "2026-07-12T00:00:00Z",
            "expires_at": "2026-07-12T00:00:30Z",
            "authorization_proof": {
                "signing_profile": "mesh-repo-patch-authority-response-ed25519-v1",
                "algorithm": "ed25519",
                "key_id": "mesh-repo-patch-authority",
                "signature": "a" * 128,
                "payload_sha256": "b" * 64,
                "public_key_pem": "test-public-key",
                "status": "verified",
                "verifier": "orbital_mesh_ed25519_v1",
            },
        }


class UnknownOutcomeAuthorityClient:
    def __init__(self) -> None:
        self.calls = 0

    def preflight(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        idempotency_key: str,
    ) -> dict:
        return RecordingAuthorityClient().preflight(decision, evaluation, idempotency_key)

    def execute(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict,
        idempotency_key: str,
        preflight_receipt: dict,
    ) -> dict:
        del decision, evaluation, gate, idempotency_key, preflight_receipt
        self.calls += 1
        raise RepoPatchAuthorityError("simulated response loss after dispatch")


class HsaiAdmissionBridgeTests(unittest.TestCase):
    def test_golden_bridge_fixtures_validate_allow_and_deny_contracts(self) -> None:
        allow_request = _golden_fixture("golden_allow_request.json")
        allow_decision = _golden_fixture("golden_allow_decision.json")
        deny_request = _golden_fixture("golden_deny_request.json")
        deny_decision = _golden_fixture("golden_deny_decision.json")

        validate_hsai_decision(allow_request, allow_decision)
        validate_hsai_decision(deny_request, deny_decision)

        self.assertEqual(allow_request["schema_version"], "mesh.hsai_admission_request.v1")
        self.assertEqual(allow_decision["schema_version"], "mesh.hsai_admission_decision.v1")
        self.assertEqual(allow_decision["decision"], "allow")
        self.assertEqual(allow_decision["reason_codes"], [])
        self.assertEqual(deny_request["schema_version"], "mesh.hsai_admission_request.v1")
        self.assertEqual(deny_decision["schema_version"], "mesh.hsai_admission_decision.v1")
        self.assertEqual(deny_decision["decision"], "deny")
        self.assertEqual(deny_decision["reason_codes"], ["missing_explicit_nonclaims"])

    def test_verify_combined_proof_packet_accepts_golden_allow_contract(self) -> None:
        request = _golden_fixture("golden_allow_request.json")
        decision = _golden_fixture("golden_allow_decision.json")
        gate = _golden_gate(request, decision)
        proof = build_combined_proof_packet(
            gate,
            mesh_policy_approved=True,
            action_execution_result={
                "status": "executed",
                "executor": "native_hermes",
                "result_digest": "sha256:" + ("5" * 64),
            },
            executor_receipt_digest="sha256:" + ("6" * 64),
            created_at="2026-07-02T00:02:00Z",
        )

        result = verify_combined_proof_packet_payload(packet=proof, request=request, decision=decision)

        self.assertEqual(result["schema_version"], "mesh.combined_proof_packet_verification.v1")
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["hsai_decision"], "allow")

    def test_verify_combined_proof_packet_rejects_claim_adequacy_drift(self) -> None:
        request = _golden_fixture("golden_allow_request.json")
        decision = _golden_fixture("golden_allow_decision.json")
        drifted_decision = dict(decision)
        drifted_decision["accepted_claims"] = []
        drifted_decision["decision_digest"] = _decision_digest(drifted_decision)
        gate = _golden_gate(request, drifted_decision)
        proof = build_combined_proof_packet(
            gate,
            mesh_policy_approved=True,
            action_execution_result={
                "status": "executed",
                "executor": "native_hermes",
                "result_digest": "sha256:" + ("5" * 64),
            },
            executor_receipt_digest="sha256:" + ("6" * 64),
            created_at="2026-07-02T00:02:00Z",
        )

        result = verify_combined_proof_packet_payload(packet=proof, request=request, decision=drifted_decision)

        self.assertEqual(result["status"], "fail")
        self.assertIn("allowed HSAI decision must preserve accepted claims", result["issues"])

    def test_mesh_verify_proof_packet_cli_accepts_golden_allow_contract(self) -> None:
        request = _golden_fixture("golden_allow_request.json")
        decision = _golden_fixture("golden_allow_decision.json")
        gate = _golden_gate(request, decision)
        proof = build_combined_proof_packet(
            gate,
            mesh_policy_approved=True,
            action_execution_result={
                "status": "executed",
                "executor": "native_hermes",
                "result_digest": "sha256:" + ("5" * 64),
            },
            executor_receipt_digest="sha256:" + ("6" * 64),
            created_at="2026-07-02T00:02:00Z",
        )
        with tempfile.TemporaryDirectory() as tmp:
            packet_path = Path(tmp) / "combined-proof-packet.json"
            packet_path.write_text(json.dumps(proof, sort_keys=True), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    "scripts/mesh.py",
                    "verify-proof-packet",
                    "--packet",
                    str(packet_path),
                    "--request",
                    str(GOLDEN_HSAI_BRIDGE_FIXTURES / "golden_allow_request.json"),
                    "--decision",
                    str(GOLDEN_HSAI_BRIDGE_FIXTURES / "golden_allow_decision.json"),
                    "--json",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                check=False,
                text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")

    def test_mesh_verify_proof_packet_cli_accepts_golden_deny_contract(self) -> None:
        request = _golden_fixture("golden_deny_request.json")
        decision = _golden_fixture("golden_deny_decision.json")
        gate = _golden_gate(request, decision)
        proof = build_combined_proof_packet(
            gate,
            mesh_policy_approved=True,
            action_execution_result={
                "status": "blocked",
                "executor": "native_hermes",
                "reason": "hsai_admission_blocked",
                "hsai_reason_codes": ["missing_explicit_nonclaims"],
                "mesh_blocking_reasons": [],
            },
            executor_receipt_digest=None,
            created_at="2026-07-02T00:03:00Z",
        )

        payload = _verify_packet_with_cli(proof, request, decision)

        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["hsai_decision"], "deny")

    def test_mesh_verify_hsai_bridge_fixtures_cli_accepts_repo_fixtures(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/mesh.py",
                "verify-hsai-bridge-fixtures",
                "--json",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["checks"]["allow_contract"]["status"], "pass")
        self.assertEqual(payload["checks"]["deny_contract"]["status"], "pass")
        self.assertEqual(payload["checks"]["allow_packet"]["status"], "pass")
        self.assertEqual(payload["checks"]["deny_packet"]["status"], "pass")
        self.assertEqual(payload["checks"]["formal_backend_bundle"]["status"], "pass")

    def test_committed_hsai_formal_backend_bundle_fixture_loads(self) -> None:
        metadata = load_hsai_formal_backend_run_metadata(HSAI_FORMAL_BACKEND_BUNDLE_FIXTURE)

        self.assertEqual(metadata["backend"], "hsai-formal-backend-run-bundle")
        self.assertEqual(metadata["backend_run_id"], "hsai-formal-run-1")
        self.assertEqual(metadata["execution_mode"], "NotRun")
        self.assertEqual(metadata["exit_status"], "NotRun")
        self.assertEqual(metadata["checker_status"], "NotRun")
        self.assertEqual(metadata["state_slice"], "phase-276-hsai-gateway-formal-backend-run-inert-artifact-metadata")
        self.assertIn("not accepted evidence", metadata["nonclaims"])
        self.assertIn("not formal proof evidence", metadata["nonclaims"])
        self.assertIn("not formal proof", metadata["nonclaim"])

    def test_local_adapter_binds_committed_hsai_formal_backend_bundle_fixture(self) -> None:
        adapter = CountingExecutionAdapter()
        hsai = LocalHsaiAdmissionAdapter(formal_backend_bundle_path=str(HSAI_FORMAL_BACKEND_BUNDLE_FIXTURE))
        execution = self._service(adapter, hsai).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("authority-eligible HSAI adapter", execution.failure["reason"])
        metadata = execution.external_refs["combined_proof_packet"]["audit_export_metadata"]["formal_evidence_metadata"]
        self.assertEqual(metadata["backend_run_id"], "hsai-formal-run-1")
        self.assertEqual(metadata["execution_mode"], "NotRun")
        self.assertIn("not accepted evidence", metadata["nonclaims"])

    def test_local_metadata_subprocess_cannot_authorize_repo_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _write_disposable_patch_repo(Path(tmp) / "repo")
            hsai = RecordingSubprocessHsaiAdapter(f"{sys.executable} scripts/hsai_admission_adapter.py")
            service = OrchestratorService(
                hsai_admission_adapter=hsai,
                config=_authority_config(Path(tmp) / "state", orchestration_mode="native_hermes"),
            )

            execution = service.execute(
                _decision(
                    parameters={
                        "repo_path": str(repo),
                        "test_commands": ["python3 -m py_compile app/search.py"],
                    }
                ),
                _evaluation(),
            )

            proof = execution.external_refs["combined_proof_packet"]
            payload = _verify_packet_with_cli(proof, hsai.requests[0], hsai.decisions[0])

            self.assertEqual(execution.status, "rejected")
            self.assertIn("authority-eligible HSAI adapter", execution.failure["reason"])
            self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")
            self.assertEqual(proof["hsai_decision"], "allow")
            self.assertEqual(proof["action_execution_result"]["status"], "blocked")
            self.assertEqual(payload["status"], "pass")

    def test_subprocess_hsai_deny_end_to_end_blocks_patch_and_verifies_packet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _write_disposable_patch_repo(Path(tmp) / "repo")
            hsai = RecordingSubprocessHsaiAdapter(f"{sys.executable} scripts/hsai_admission_adapter.py")
            service = OrchestratorService(
                hsai_admission_adapter=hsai,
                config=_authority_config(Path(tmp) / "state", orchestration_mode="native_hermes"),
            )

            execution = service.execute(
                _decision(
                    parameters={
                        "repo_path": str(repo),
                        "test_commands": ["python3 -m py_compile app/search.py"],
                        "explicit_nonclaims": [],
                    }
                ),
                _evaluation(),
            )

            proof = execution.external_refs["combined_proof_packet"]
            payload = _verify_packet_with_cli(proof, hsai.requests[0], hsai.decisions[0])

            self.assertEqual(execution.status, "rejected")
            self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")
            self.assertEqual(execution.failure["reason"], "hsai_admission_blocked")
            self.assertEqual(proof["hsai_decision"], "deny")
            self.assertEqual(proof["action_execution_result"]["status"], "blocked")
            self.assertEqual(proof["action_execution_result"]["hsai_reason_codes"], ["missing_explicit_nonclaims"])
            self.assertEqual(payload["status"], "pass")

    def test_hsai_allow_and_mesh_approve_executes_and_emits_combined_proof_packet(self) -> None:
        adapter = CountingExecutionAdapter()
        hsai = RecordingHsaiAdapter()
        execution = self._service(adapter, hsai).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "succeeded")
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(hsai.calls, 1)
        proof = execution.external_refs["combined_proof_packet"]
        validate_payload("combined-proof-packet.schema.json", proof)
        self.assertEqual(proof["hsai_decision"], "allow")
        self.assertEqual(proof["action_execution_result"]["status"], "executed")
        self.assertIsNotNone(proof["executor_receipt_digest"])
        self.assertEqual(proof["mesh_run_id"], "run_hsai_bridge")
        self.assertEqual(proof["mesh_action_id"], "dec_repo_patch")
        self.assertEqual(proof["mesh_policy_id"], "mesh_policy://repo-patch/test")
        self.assertTrue(proof["hsai_request_digest"].startswith("sha256:"))
        self.assertTrue(proof["hsai_decision_digest"].startswith("sha256:"))
        self.assertTrue(proof["hsai_candidate_digest"].startswith("sha256:"))
        self.assertEqual(proof["nonclaims"], hsai.requests[0]["explicit_nonclaims"])
        self.assertNotIn("accepted_claims", proof)

    def test_local_adapter_binds_hsai_formal_backend_bundle_metadata(self) -> None:
        adapter = CountingExecutionAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            bundle_root = _write_formal_backend_bundle(Path(tmp))
            hsai = LocalHsaiAdmissionAdapter(formal_backend_bundle_path=str(bundle_root))
            execution = self._service(adapter, hsai).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("authority-eligible HSAI adapter", execution.failure["reason"])
        proof = execution.external_refs["combined_proof_packet"]
        metadata = proof["audit_export_metadata"]["formal_evidence_metadata"]
        self.assertEqual(metadata["backend"], "hsai-formal-backend-run-bundle")
        self.assertEqual(metadata["backend_run_id"], "hsai-formal-run-1")
        self.assertEqual(metadata["execution_mode"], "NotRun")
        self.assertEqual(metadata["exit_status"], "NotRun")
        self.assertEqual(metadata["checker_status"], "NotRun")
        self.assertEqual(metadata["state_slice"], "phase-276-hsai-gateway-formal-backend-run-inert-artifact-metadata")
        self.assertIn("not accepted evidence", metadata["nonclaims"])
        self.assertIn("not formal proof evidence", metadata["nonclaims"])
        self.assertIn("not formal proof", metadata["nonclaim"])

    def test_subprocess_adapter_binds_hsai_formal_backend_bundle_metadata(self) -> None:
        adapter = CountingExecutionAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            bundle_root = _write_formal_backend_bundle(Path(tmp))
            command = f"{sys.executable} scripts/hsai_admission_adapter.py"
            hsai = SubprocessHsaiAdmissionAdapter(command)
            with patch.dict(os.environ, {"MESH_HSAI_FORMAL_BACKEND_RUN_BUNDLE_PATH": str(bundle_root)}):
                execution = self._service(adapter, hsai).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("authority-eligible HSAI adapter", execution.failure["reason"])
        metadata = execution.external_refs["combined_proof_packet"]["audit_export_metadata"]["formal_evidence_metadata"]
        self.assertEqual(metadata["backend"], "hsai-formal-backend-run-bundle")
        self.assertEqual(metadata["backend_run_id"], "hsai-formal-run-1")
        self.assertEqual(metadata["execution_mode"], "NotRun")

    def test_hsai_formal_backend_bundle_sidecar_drift_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            bundle_root = _write_formal_backend_bundle(Path(tmp))
            sidecar = bundle_root / "gateway-formal-backend-run/run-summary.json.sha256"
            sidecar.write_text("0" * 64, encoding="utf-8")
            execution = self._service(
                adapter,
                LocalHsaiAdmissionAdapter(formal_backend_bundle_path=str(bundle_root)),
            ).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(execution.external_refs["hsai_admission"]["decision"], "error")
        self.assertIn("HSAI formal backend sidecar digest mismatch", execution.failure["blocking_reasons"][0])

    def test_hsai_formal_backend_bundle_level2_escalation_blocks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle_root = _write_formal_backend_bundle(Path(tmp), run_summary_overrides={"creates_level2_evidence": True})

            with self.assertRaisesRegex(ValueError, "creates_level2_evidence"):
                load_hsai_formal_backend_run_metadata(bundle_root)

    def test_hsai_deny_blocks_even_when_mesh_policy_approves(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("deny")).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(execution.failure["reason"], "hsai_admission_blocked")
        self.assertEqual(execution.external_refs["combined_proof_packet"]["hsai_decision"], "deny")
        self.assertIsNone(execution.external_refs["combined_proof_packet"]["executor_receipt_digest"])
        self.assertEqual(execution.external_refs["combined_proof_packet"]["action_execution_result"]["status"], "blocked")

    def test_mesh_policy_deny_blocks_even_when_hsai_allows(self) -> None:
        adapter = CountingExecutionAdapter()
        hsai = RecordingHsaiAdapter()
        execution = self._service(adapter, hsai).execute(_decision(), _evaluation(passed=False))

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(hsai.calls, 1)
        self.assertEqual(execution.failure["reason"], "mesh_policy_blocked")
        self.assertFalse(execution.external_refs["combined_proof_packet"]["audit_export_metadata"]["mesh_policy_approved"])

    def test_hsai_unavailable_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("unavailable")).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(execution.external_refs["hsai_admission"]["decision"], "error")
        self.assertIn("hsai_unavailable", execution.failure["blocking_reasons"][0])

    def test_malformed_hsai_response_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("malformed")).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(execution.external_refs["hsai_admission"]["decision"], "error")
        self.assertIn("hsai_malformed_or_mismatched", execution.failure["blocking_reasons"][0])

    def test_request_digest_mismatch_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("request_digest_mismatch")).execute(
            _decision(),
            _evaluation(),
        )

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(execution.external_refs["hsai_admission"]["decision"], "error")
        self.assertIn("hsai request digest mismatch", execution.failure["blocking_reasons"][0])

    def test_candidate_digest_mismatch_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("candidate_mismatch")).execute(
            _decision(),
            _evaluation(),
        )

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(execution.external_refs["hsai_admission"]["decision"], "error")
        self.assertIn("hsai candidate digest mismatch", execution.failure["blocking_reasons"][0])

    def test_old_decision_for_different_mesh_run_is_rejected(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("old_run")).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("hsai request digest mismatch", execution.failure["blocking_reasons"][0])

    def test_decision_run_binding_field_mismatch_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("run_field_mismatch")).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("hsai mesh run id mismatch", execution.failure["blocking_reasons"][0])

    def test_old_decision_for_different_mesh_action_is_rejected(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("old_action")).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("hsai request digest mismatch", execution.failure["blocking_reasons"][0])

    def test_decision_action_binding_field_mismatch_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("action_field_mismatch")).execute(
            _decision(),
            _evaluation(),
        )

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("hsai mesh action id mismatch", execution.failure["blocking_reasons"][0])

    def test_policy_mismatch_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("policy_mismatch")).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("hsai policy id mismatch", execution.failure["blocking_reasons"][0])

    def test_unsupported_decision_schema_version_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("unsupported_decision_schema_version")).execute(
            _decision(),
            _evaluation(),
        )

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("schema_version", execution.failure["blocking_reasons"][0])

    def test_missing_decision_schema_version_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("missing_decision_schema_version")).execute(
            _decision(),
            _evaluation(),
        )

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("schema_version", execution.failure["blocking_reasons"][0])

    def test_hsai_decision_cannot_drop_required_nonclaims(self) -> None:
        adapter = CountingExecutionAdapter()
        execution = self._service(adapter, RecordingHsaiAdapter("drops_nonclaims")).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertIn("hsai enforced nonclaims missing", execution.failure["blocking_reasons"][0])

    def test_missing_nonclaims_blocks_fail_closed(self) -> None:
        adapter = CountingExecutionAdapter()
        decision = _decision(parameters={"explicit_nonclaims": []})
        execution = self._service(adapter, RecordingHsaiAdapter()).execute(decision, _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(execution.external_refs["hsai_admission"]["decision"], "deny")
        self.assertIn("missing_explicit_nonclaims", execution.failure["blocking_reasons"])

    def test_request_schema_version_validation_fails_closed(self) -> None:
        request = build_hsai_admission_request(_decision(), _evaluation())
        request["schema_version"] = "mesh.hsai_admission_request.v2"

        with self.assertRaises(SchemaValidationError):
            validate_payload("hsai-admission-request.schema.json", request)

    def test_missing_request_schema_version_validation_fails_closed(self) -> None:
        request = build_hsai_admission_request(_decision(), _evaluation())
        request.pop("schema_version")

        with self.assertRaises(SchemaValidationError):
            validate_payload("hsai-admission-request.schema.json", request)

    def test_unsupported_combined_proof_schema_version_fails_validation(self) -> None:
        gate = evaluate_hsai_gate(build_hsai_admission_request(_decision(), _evaluation()), RecordingHsaiAdapter())
        proof = build_combined_proof_packet(
            gate,
            mesh_policy_approved=True,
            action_execution_result={"status": "executed", "executor": "native", "result_digest": "sha256:" + ("1" * 64)},
            executor_receipt_digest="sha256:" + ("2" * 64),
        )
        proof["schema_version"] = "mesh.combined_proof_packet.v2"

        with self.assertRaises(SchemaValidationError):
            validate_combined_proof_packet(gate, proof)

    def test_missing_combined_proof_schema_version_fails_validation(self) -> None:
        gate = evaluate_hsai_gate(build_hsai_admission_request(_decision(), _evaluation()), RecordingHsaiAdapter())
        proof = build_combined_proof_packet(
            gate,
            mesh_policy_approved=True,
            action_execution_result={"status": "executed", "executor": "native", "result_digest": "sha256:" + ("1" * 64)},
            executor_receipt_digest="sha256:" + ("2" * 64),
        )
        proof.pop("schema_version")

        with self.assertRaises(SchemaValidationError):
            validate_combined_proof_packet(gate, proof)

    def test_combined_proof_packet_rejects_nonclaim_upgrade_to_claims(self) -> None:
        gate = evaluate_hsai_gate(build_hsai_admission_request(_decision(), _evaluation()), RecordingHsaiAdapter())
        proof = build_combined_proof_packet(
            gate,
            mesh_policy_approved=True,
            action_execution_result={"status": "executed", "executor": "native", "result_digest": "sha256:" + ("1" * 64)},
            executor_receipt_digest="sha256:" + ("2" * 64),
        )
        proof["action_execution_result"]["accepted_claims"] = ["production_certification"]

        with self.assertRaises(ValueError):
            validate_combined_proof_packet(gate, proof)

    def test_combined_proof_packet_requires_export_assertions(self) -> None:
        gate = evaluate_hsai_gate(build_hsai_admission_request(_decision(), _evaluation()), RecordingHsaiAdapter())
        proof = build_combined_proof_packet(
            gate,
            mesh_policy_approved=True,
            action_execution_result={"status": "executed", "executor": "native", "result_digest": "sha256:" + ("1" * 64)},
            executor_receipt_digest="sha256:" + ("2" * 64),
        )
        proof["audit_export_metadata"]["included_in_execution_external_refs"] = False

        with self.assertRaises(ValueError):
            validate_combined_proof_packet(gate, proof)

    def test_native_repo_patch_adapters_are_review_only(self) -> None:
        adapter_classes = (NativeGooseAdapter, NativeHermesAdapter)
        for adapter_class in adapter_classes:
            with self.subTest(adapter=adapter_class.__name__), tempfile.TemporaryDirectory() as tmp:
                adapter = adapter_class(config=RuntimeConfig(state_directory=tmp))
                result = adapter.execute_decision(_decision(), "dec_repo_patch:investigate_and_patch")

            self.assertEqual(result.status, "succeeded")
            self.assertTrue(result.external_refs["repo_patch_review_only"])
            self.assertFalse(result.external_refs["repo_patch_authority_invoked"])
            self.assertFalse(hasattr(adapter, "repo_patch"))

    def test_shared_repo_patch_guard_failure_shape(self) -> None:
        failure = repo_patch_admission_failure(_decision())

        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["failure"]["reason"], "hsai_admission_context_invalid")
        self.assertFalse(failure["retryable"])

    def test_native_review_does_not_consume_attached_hsai_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gate = evaluate_hsai_gate(build_hsai_admission_request(_decision(), _evaluation()), RecordingHsaiAdapter())
            native = NativeGooseAdapter(config=RuntimeConfig(state_directory=tmp))
            result = native.execute_decision(
                attach_hsai_execution_context(_decision(), gate),
                "dec_repo_patch:investigate_and_patch",
            )

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.external_refs["repo_patch_review_only"])
        self.assertFalse(result.external_refs["repo_patch_authority_invoked"])

    def test_hsai_execution_context_binds_current_decision_payload(self) -> None:
        decision = _decision()
        gate = evaluate_hsai_gate(build_hsai_admission_request(decision, _evaluation()), RecordingHsaiAdapter())
        execution = self._service(CountingExecutionAdapter(), RecordingHsaiAdapter()).execute(decision, _evaluation())

        self.assertEqual(execution.status, "succeeded")
        context_decision = _decision(
            parameters={
                "_mesh_hsai_admission_context": {
                    "schema_version": "mesh.hsai_execution_context.v1",
                    "request": gate["request"],
                    "decision": gate["decision"],
                    "request_digest": gate["request_digest"],
                    "decision_digest": gate["decision_digest"],
                    "candidate_digest": gate["candidate_digest"],
                },
                "mesh_action_id": "different_action",
            }
        )
        with self.assertRaises(ValueError):
            validate_hsai_execution_context(context_decision)

    def test_hsai_execution_context_schema_version_fails_closed(self) -> None:
        gate = evaluate_hsai_gate(build_hsai_admission_request(_decision(), _evaluation()), RecordingHsaiAdapter())
        context_decision = attach_hsai_execution_context(_decision(), gate)
        payload = context_decision.to_dict()
        payload["execution_plan"]["parameters"]["_mesh_hsai_admission_context"]["schema_version"] = (
            "mesh.hsai_execution_context.v2"
        )
        failure = repo_patch_admission_failure(Decision.from_dict(payload))

        self.assertIsNotNone(failure)
        assert failure is not None
        self.assertEqual(failure["failure"]["reason"], "hsai_admission_context_invalid")
        self.assertIn("unsupported HSAI execution context", failure["failure"]["detail"])

    def test_repo_patch_replay_guard_reuses_terminal_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = CountingExecutionAdapter()
            hsai = RecordingHsaiAdapter()
            authority = RecordingAuthorityClient()
            service = OrchestratorService(
                adapter=adapter,
                hsai_admission_adapter=hsai,
                config=_authority_config(tmp, orchestration_mode="native"),
                repo_patch_authority_client=authority,
            )

            first = service.execute(_decision(), _evaluation())
            second = service.execute(_decision(), _evaluation())

        self.assertEqual(first.status, "succeeded")
        self.assertEqual(second.status, "succeeded")
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(hsai.calls, 1)
        self.assertEqual(authority.preflight_calls, 1)
        self.assertEqual(authority.calls, 1)
        self.assertTrue(second.external_refs["idempotency_replayed"])
        self.assertEqual(second.external_refs["combined_proof_packet"]["hsai_decision"], "allow")

    def test_repo_patch_approval_dispatches_authority_once_and_binds_signed_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = CountingExecutionAdapter()
            authority = RecordingAuthorityClient()
            execution = OrchestratorService(
                adapter=adapter,
                hsai_admission_adapter=RecordingHsaiAdapter(),
                config=_authority_config(tmp, orchestration_mode="native"),
                repo_patch_authority_client=authority,
            ).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "succeeded")
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(authority.preflight_calls, 1)
        self.assertEqual(authority.calls, 1)
        authority_ref = execution.external_refs["repo_patch_authority"]
        self.assertEqual(authority_ref["state_slice"], "mesh.repo_patch_authority_orchestration.v1")
        self.assertEqual(authority_ref["status"], "completed")
        self.assertEqual(authority_ref["receipt"]["state_slice"], "mesh.repo_patch_authority_service.v1")
        self.assertEqual(authority_ref["authorization_proof"]["status"], "verified")
        proof = execution.external_refs["combined_proof_packet"]
        self.assertEqual(proof["action_execution_result"]["result_digest"], proof["executor_receipt_digest"])

    def test_repo_patch_malformed_review_contract_blocks_before_authority(self) -> None:
        class MalformedReviewAdapter(CountingExecutionAdapter):
            def execute_decision(self, decision: Decision, idempotency_key: str) -> CliExecutionResult:
                result = super().execute_decision(decision, idempotency_key)
                result.external_refs["repo_patch_authority_invoked"] = True
                return result

        with tempfile.TemporaryDirectory() as tmp:
            adapter = MalformedReviewAdapter()
            authority = RecordingAuthorityClient()
            execution = OrchestratorService(
                adapter=adapter,
                hsai_admission_adapter=RecordingHsaiAdapter(),
                config=_authority_config(tmp, orchestration_mode="native"),
                repo_patch_authority_client=authority,
            ).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(execution.failure["reason"], "repo_patch_review_contract_rejected")
        self.assertEqual(authority.calls, 0)

    def test_repo_patch_unknown_after_dispatch_never_retries_or_falls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            authority = UnknownOutcomeAuthorityClient()
            config = _authority_config(tmp, orchestration_mode="native")
            config.max_transient_retries = 5
            execution = OrchestratorService(
                adapter=CountingExecutionAdapter(),
                hsai_admission_adapter=RecordingHsaiAdapter(),
                config=config,
                repo_patch_authority_client=authority,
            ).execute(_decision(), _evaluation())

        self.assertEqual(execution.status, "failed")
        self.assertEqual(execution.failure["reason"], "outcome_unknown_after_dispatch")
        self.assertEqual(authority.calls, 1)
        self.assertEqual(execution.external_refs["idempotency_guard"], "remote_command_dispatched_without_outcome")

    def test_repo_patch_parameter_credentials_block_before_review_and_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = CountingExecutionAdapter()
            authority = RecordingAuthorityClient()
            execution = OrchestratorService(
                adapter=adapter,
                hsai_admission_adapter=RecordingHsaiAdapter(),
                config=_authority_config(tmp, orchestration_mode="native"),
                repo_patch_authority_client=authority,
            ).execute(_decision(parameters={"api_key": "must-not-cross-boundary"}), _evaluation())

        self.assertEqual(execution.status, "rejected")
        self.assertEqual(execution.failure["reason"], "repo_patch_parameter_credentials_rejected")
        self.assertEqual(adapter.calls, 0)
        self.assertEqual(authority.calls, 0)

    def test_non_repo_action_ignores_absent_authority_configuration(self) -> None:
        payload = _decision().to_dict()
        payload["decision_type"] = "reduce_rollout"
        payload["execution_plan"].update(
            {
                "system": "feature_flag_service",
                "action": "set_rollout",
                "parameters": {"flag_key": "search-v2", "percentage": 10},
            }
        )
        decision = Decision.from_dict(payload)
        evaluation_payload = deepcopy(_evaluation().__dict__)
        evaluation_payload["decision_id"] = decision.decision_id
        adapter = CountingExecutionAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            execution = OrchestratorService(
                adapter=adapter,
                hsai_admission_adapter=RecordingHsaiAdapter(),
                config=RuntimeConfig(orchestration_mode="native", state_directory=tmp),
            ).execute(decision, EvaluationResult(**evaluation_payload))

        self.assertEqual(execution.status, "succeeded")
        self.assertEqual(adapter.calls, 1)

    def test_raw_repo_patch_api_has_no_production_callsites(self) -> None:
        root = Path(__file__).resolve().parents[1]
        expected_callsite_files: set[Path] = set()
        actual_callsite_files = {
            path
            for path in (root / "services").rglob("*.py")
            if path != root / "services/actuators/repo_patch.py" and "execute_patch(" in path.read_text()
        }

        self.assertEqual(actual_callsite_files, expected_callsite_files)
        orchestrator_sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (root / "services/orchestrator").glob("*.py")
        )
        self.assertNotIn("RepoPatchAdapter", orchestrator_sources)
        self.assertNotIn("RepoPatchPermitStore", orchestrator_sources)
        self.assertNotIn("attach_hsai_execution_context", orchestrator_sources)

    def test_evidence_carrying_authority_blocks_500_deterministic_tamper_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            state = root / "state"
            decision = _decision(parameters={"repo_path": str(repo), "test_commands": []})
            evaluation = _evaluation()
            gate = evaluate_hsai_gate(build_hsai_admission_request(decision, evaluation), RecordingHsaiAdapter())
            idempotency_key = "dec_repo_patch:investigate_and_patch"
            permit = _permit_store(state).issue(
                decision,
                evaluation,
                gate,
                idempotency_key,
                permit_id="permit_" + ("a" * 64),
                authority_nonce="b" * 64,
            )
            admitted = attach_hsai_execution_context(decision, gate, permit)
            actuator = _authority_actuator(state)
            original = (repo / "app/search.py").read_text(encoding="utf-8")
            blocked = 0

            digest_fields = (
                "hsai_request_digest",
                "hsai_decision_digest",
                "candidate_payload_digest",
                "action_proposal_digest",
                "evidence_packet_digest",
                "policy_snapshot_digest",
                "canonical_actuation_payload_digest",
                "target_preimage_digest",
                "authority_entry_digest",
                "ledger_tip_after",
            )
            for case_index in range(500):
                mode = case_index % 3
                candidate_payload = admitted.to_dict()
                context = candidate_payload["execution_plan"]["parameters"]["_mesh_hsai_admission_context"]
                resolved_parameters = None
                if mode == 0:
                    candidate_permit = context["execution_permit"]
                    field = digest_fields[(case_index // 3) % len(digest_fields)]
                    candidate_permit[field] = "sha256:" + hashlib.sha256(
                        f"evidence-carrying-mesh-authority-trial/v1:{case_index}".encode("utf-8")
                    ).hexdigest()
                    permit_without_digest = dict(candidate_permit)
                    permit_without_digest.pop("permit_digest", None)
                    permit_without_digest.pop("authorization_proof", None)
                    candidate_permit["permit_digest"] = canonical_digest(permit_without_digest)
                elif mode == 1:
                    field = ("request_digest", "decision_digest", "candidate_digest")[(case_index // 3) % 3]
                    context[field] = "sha256:" + hashlib.sha256(
                        f"evidence-carrying-context-tamper/v1:{case_index}".encode("utf-8")
                    ).hexdigest()
                else:
                    resolved_parameters = deepcopy(candidate_payload["execution_plan"]["parameters"])
                    resolved_parameters["patch_template"]["replace"] = f"new_{case_index}"
                result = actuator.execute_patch(
                    Decision.from_dict(candidate_payload),
                    idempotency_key,
                    resolved_parameters=resolved_parameters,
                )
                blocked += result["status"] == "failed"

            self.assertEqual(blocked, 500)
            self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), original)

    def test_evidence_carrying_authority_blocks_12_direct_bypass_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            target = repo / "app/search.py"
            original = target.read_text(encoding="utf-8")
            actuator = RepoPatchAdapter(root / "state")
            base = _decision(parameters={"repo_path": str(repo), "test_commands": []}).execution_plan["parameters"]
            results = []
            for case_index in range(12):
                direct_parameters = deepcopy(base)
                direct_parameters["patch_template"]["replace"] = f"bypass_{case_index}"
                results.append(actuator.execute_patch(direct_parameters, f"direct_{case_index}"))

            self.assertTrue(all(result["status"] == "failed" for result in results))
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_evidence_carrying_authority_allows_one_of_16_concurrent_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            state = root / "state"
            decision = _decision(parameters={"repo_path": str(repo), "test_commands": []})
            evaluation = _evaluation()
            gate = evaluate_hsai_gate(build_hsai_admission_request(decision, evaluation), RecordingHsaiAdapter())
            idempotency_key = "dec_repo_patch:investigate_and_patch"
            permit = _permit_store(state).issue(decision, evaluation, gate, idempotency_key)
            admitted = attach_hsai_execution_context(decision, gate, permit)
            actuator = _authority_actuator(state)

            with ThreadPoolExecutor(max_workers=16) as pool:
                results = list(pool.map(lambda _: actuator.execute_patch(admitted, idempotency_key), range(16)))

            self.assertEqual(sum(result["status"] == "succeeded" for result in results), 1)
            self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'new'\n")

    def test_evidence_carrying_authority_rejects_stale_target_preimage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            state = root / "state"
            decision = _decision(parameters={"repo_path": str(repo), "test_commands": []})
            evaluation = _evaluation()
            gate = evaluate_hsai_gate(build_hsai_admission_request(decision, evaluation), RecordingHsaiAdapter())
            idempotency_key = "dec_repo_patch:investigate_and_patch"
            permit = _permit_store(state).issue(decision, evaluation, gate, idempotency_key)
            admitted = attach_hsai_execution_context(decision, gate, permit)
            target = repo / "app/search.py"
            target.write_text("VALUE = 'external-change'\n", encoding="utf-8")

            result = _authority_actuator(state).execute_patch(admitted, idempotency_key)

            self.assertEqual(result["status"], "failed")
            self.assertIn("target preimage mismatch", result["failure"]["reason"])
            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'external-change'\n")

    def test_evidence_carrying_authority_issues_authenticated_permit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            decision = _decision(parameters={"repo_path": str(repo), "test_commands": []})
            evaluation = _evaluation()
            gate = evaluate_hsai_gate(build_hsai_admission_request(decision, evaluation), RecordingHsaiAdapter())

            permit = _permit_store(root / "state").issue(
                decision,
                evaluation,
                gate,
                "dec_repo_patch:investigate_and_patch",
            )

            self.assertEqual(permit["issuer"], TEST_PERMIT_ISSUER)
            self.assertEqual(permit["executor_audience"], TEST_PERMIT_EXECUTOR_AUDIENCE)
            self.assertEqual(permit["authorization_proof"]["key_id"], TEST_PERMIT_SIGNING_KEY_ID)
            self.assertEqual(permit["authorization_proof"]["algorithm"], "hmac-sha256")
            self.assertEqual(
                permit["authorization_proof"]["signing_profile"],
                "mesh-repo-patch-execution-permit-hmac-sha256-v1",
            )

    def test_evidence_carrying_authority_rejects_authenticated_permit_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            state = root / "state"
            decision = _decision(parameters={"repo_path": str(repo), "test_commands": []})
            evaluation = _evaluation()
            gate = evaluate_hsai_gate(build_hsai_admission_request(decision, evaluation), RecordingHsaiAdapter())
            idempotency_key = "dec_repo_patch:investigate_and_patch"
            permit = _permit_store(state).issue(decision, evaluation, gate, idempotency_key)
            admitted = attach_hsai_execution_context(decision, gate, permit)
            target = repo / "app/search.py"
            original = target.read_text(encoding="utf-8")

            mutations = {
                "issuer": lambda candidate: candidate.update({"issuer": "mesh.attacker"}),
                "executor_audience": lambda candidate: candidate.update(
                    {"executor_audience": "mesh.attacker.actuator"}
                ),
                "key_id": lambda candidate: candidate["authorization_proof"].update(
                    {"key_id": "attacker-key"}
                ),
                "signature": lambda candidate: candidate["authorization_proof"].update(
                    {"signature": "0" * 64}
                ),
            }
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    payload = admitted.to_dict()
                    candidate_permit = payload["execution_plan"]["parameters"]["_mesh_hsai_admission_context"][
                        "execution_permit"
                    ]
                    mutate(candidate_permit)
                    result = _authority_actuator(state).execute_patch(
                        Decision.from_dict(payload),
                        idempotency_key,
                    )
                    self.assertEqual(result["status"], "failed")
                    self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_evidence_carrying_authority_rejects_wrong_verifier_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            state = root / "state"
            decision = _decision(parameters={"repo_path": str(repo), "test_commands": []})
            evaluation = _evaluation()
            gate = evaluate_hsai_gate(build_hsai_admission_request(decision, evaluation), RecordingHsaiAdapter())
            idempotency_key = "dec_repo_patch:investigate_and_patch"
            permit = _permit_store(state).issue(decision, evaluation, gate, idempotency_key)
            admitted = attach_hsai_execution_context(decision, gate, permit)

            result = RepoPatchAdapter(
                config=_authority_config(
                    state,
                    repo_patch_permit_signing_key="wrong-verifier-key",
                )
            ).execute_patch(admitted, idempotency_key)

            self.assertEqual(result["status"], "failed")
            self.assertIn("HMAC verification failed", result["failure"]["reason"])
            self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_durable_transaction_recovers_each_named_crash_boundary(self) -> None:
        crash_boundaries = ("prepared", "claimed", "applying", "applied", "verifying", "committed")
        for crash_boundary in crash_boundaries:
            with self.subTest(crash_boundary=crash_boundary), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                repo = _write_disposable_patch_repo(root / "repo")
                state = root / "state"
                decision = _decision(parameters={"repo_path": str(repo), "test_commands": []})
                evaluation = _evaluation()
                gate = evaluate_hsai_gate(
                    build_hsai_admission_request(decision, evaluation),
                    RecordingHsaiAdapter(),
                )
                idempotency_key = "dec_repo_patch:investigate_and_patch"
                permit = _permit_store(state).issue(decision, evaluation, gate, idempotency_key)
                admitted = attach_hsai_execution_context(decision, gate, permit)

                def crash(state_name: str) -> None:
                    if state_name == crash_boundary:
                        raise SimulatedAuthorityCrash(state_name)

                with self.assertRaises(SimulatedAuthorityCrash):
                    RepoPatchAdapter(
                        config=_authority_config(state),
                        allowed_test_commands=(),
                        failpoint=crash,
                    ).execute_patch(admitted, idempotency_key)

                recovered = RepoPatchAdapter(
                    config=_authority_config(state),
                    allowed_test_commands=(),
                ).recover_incomplete_actions()
                terminal = _permit_store(state).terminal_result_for_idempotency(idempotency_key)
                if crash_boundary == "committed":
                    self.assertEqual(recovered, [])
                    self.assertEqual(terminal["status"], "succeeded")
                    self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'new'\n")
                else:
                    self.assertEqual(len(recovered), 1)
                    self.assertEqual(recovered[0]["state"], "aborted")
                    self.assertEqual(terminal["status"], "failed")
                    self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_repo_patch_orchestration_requires_external_authority_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            service = OrchestratorService(
                adapter=CountingExecutionAdapter(),
                hsai_admission_adapter=RecordingHsaiAdapter(),
                config=RuntimeConfig(orchestration_mode="native", state_directory=str(root / "state")),
            )

            result = service.execute(
                _decision(parameters={"repo_path": str(repo), "test_commands": []}),
                _evaluation(),
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.failure["reason"], "repo_patch_authority_configuration_rejected")
            self.assertIn("socket path is required", result.failure["detail"])
            self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_evidence_carrying_authority_has_zero_false_rejects_over_256_benign_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            app = repo / "app"
            app.mkdir(parents=True)
            service = OrchestratorService(
                hsai_admission_adapter=RecordingHsaiAdapter(),
                config=_authority_config(root / "state", orchestration_mode="native_hermes"),
                repo_patch_authority_client=RecordingAuthorityClient(mutate=True),
            )
            succeeded = 0
            for case_index in range(256):
                relative_target = f"app/case_{case_index}.py"
                (repo / relative_target).write_text("VALUE = 'old'\n", encoding="utf-8")
                decision_payload = _decision(
                    parameters={
                        "repo_path": str(repo),
                        "allowed_paths": [relative_target],
                        "patch_template": {
                            "target_file": relative_target,
                            "find": "old",
                            "replace": "new",
                        },
                        "test_commands": [f"python3 -m py_compile {relative_target}"],
                        "mesh_run_id": f"run_benign_{case_index}",
                    }
                ).to_dict()
                decision_payload["decision_id"] = f"dec_benign_{case_index}"
                decision = Decision.from_dict(decision_payload)
                evaluation_payload = deepcopy(_evaluation().__dict__)
                evaluation_payload["evaluation_id"] = f"eval_benign_{case_index}"
                evaluation_payload["decision_id"] = decision.decision_id
                result = service.execute(decision, EvaluationResult(**evaluation_payload))
                succeeded += result.status == "succeeded"

            self.assertEqual(succeeded, 256)
            self.assertTrue(all("VALUE = 'new'" in path.read_text(encoding="utf-8") for path in app.glob("*.py")))

    def test_evidence_carrying_authority_real_actuation_replay_reuses_terminal_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            service = OrchestratorService(
                hsai_admission_adapter=RecordingHsaiAdapter(),
                config=_authority_config(root / "state", orchestration_mode="native_hermes"),
                repo_patch_authority_client=RecordingAuthorityClient(mutate=True),
            )
            decision = _decision(
                parameters={
                    "repo_path": str(repo),
                    "test_commands": ["python3 -m py_compile app/search.py"],
                }
            )

            first = service.execute(decision, _evaluation())
            second = service.execute(decision, _evaluation())

            self.assertEqual(first.status, "succeeded")
            self.assertEqual(second.status, "succeeded")
            self.assertTrue(second.external_refs["idempotency_replayed"])
            self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'new'\n")

    def test_legacy_local_authority_ledger_cannot_trigger_orchestration_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _write_disposable_patch_repo(root / "repo")
            state = root / "state"
            state.mkdir()
            (state / "repo_patch_authority_ledger.json").write_text("{not-json", encoding="utf-8")
            service = OrchestratorService(
                hsai_admission_adapter=RecordingHsaiAdapter(),
                config=_authority_config(state, orchestration_mode="native_hermes"),
            )

            result = service.execute(
                _decision(parameters={"repo_path": str(repo), "test_commands": []}),
                _evaluation(),
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.failure["reason"], "repo_patch_authority_configuration_rejected")
            self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def _service(self, adapter: CountingExecutionAdapter, hsai: object) -> OrchestratorService:
        self.addCleanup(lambda: None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return OrchestratorService(
            adapter=adapter,
            hsai_admission_adapter=hsai,
            config=_authority_config(tmp.name, orchestration_mode="native"),
            repo_patch_authority_client=RecordingAuthorityClient(),
        )


def _authority_config(
    state_directory: str | Path,
    *,
    orchestration_mode: str = "native_hermes",
    repo_patch_permit_signing_key: str = TEST_PERMIT_SIGNING_KEY,
) -> RuntimeConfig:
    return RuntimeConfig(
        orchestration_mode=orchestration_mode,
        state_directory=str(state_directory),
        repo_patch_permit_signing_key=repo_patch_permit_signing_key,
        repo_patch_permit_signing_key_id=TEST_PERMIT_SIGNING_KEY_ID,
        repo_patch_permit_issuer=TEST_PERMIT_ISSUER,
        repo_patch_permit_executor_audience=TEST_PERMIT_EXECUTOR_AUDIENCE,
    )


def _permit_store(state_directory: str | Path) -> RepoPatchPermitStore:
    return RepoPatchPermitStore(
        state_directory,
        signing_key=TEST_PERMIT_SIGNING_KEY,
        signing_key_id=TEST_PERMIT_SIGNING_KEY_ID,
        issuer=TEST_PERMIT_ISSUER,
        executor_audience=TEST_PERMIT_EXECUTOR_AUDIENCE,
    )


def _authority_actuator(state_directory: str | Path) -> RepoPatchAdapter:
    return RepoPatchAdapter(config=_authority_config(state_directory))


def _review_only_refs() -> dict[str, object]:
    return {
        "hermes_review": {
            "mode": "test",
            "approved": True,
            "summary": "bounded repo-patch review completed without actuation",
            "risk_flags": [],
            "next_action": "authority_service_review_required",
            "repo_patch_review_only": True,
            "final_parameters_unchanged": True,
            "authority_invoked": False,
            "authority_credentials_forwarded": False,
        },
        "repo_patch_review_only": True,
        "repo_patch_final_parameters_unchanged": True,
        "repo_patch_authority_invoked": False,
        "repo_patch_authority_credentials_forwarded": False,
        "repo_patch_review_state_slice": "mesh.repo_patch_review_only_boundary.v1",
    }


def _golden_fixture(name: str) -> dict:
    with (GOLDEN_HSAI_BRIDGE_FIXTURES / name).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"golden HSAI bridge fixture must be a JSON object: {name}")
    return payload


def _golden_gate(request: dict, decision: dict) -> dict:
    validate_hsai_decision(request, decision)
    return {
        "allowed": decision["decision"] == "allow",
        "request": request,
        "decision": decision,
        "request_digest": decision["request_digest"],
        "decision_digest": decision["decision_digest"],
        "candidate_digest": decision["candidate_digest"],
        "reason_codes": list(decision.get("reason_codes") or []),
    }


def _verify_packet_with_cli(packet: dict, request: dict, decision: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        packet_path = tmp_path / "combined-proof-packet.json"
        request_path = tmp_path / "hsai-admission-request.json"
        decision_path = tmp_path / "hsai-admission-decision.json"
        packet_path.write_text(json.dumps(packet, sort_keys=True), encoding="utf-8")
        request_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")
        decision_path.write_text(json.dumps(decision, sort_keys=True), encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "scripts/mesh.py",
                "verify-proof-packet",
                "--packet",
                str(packet_path),
                "--request",
                str(request_path),
                "--decision",
                str(decision_path),
                "--json",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
            text=True,
        )

    if result.returncode != 0:
        raise AssertionError(f"mesh verify-proof-packet failed: stdout={result.stdout} stderr={result.stderr}")
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict):
        raise AssertionError("mesh verify-proof-packet returned non-object JSON")
    return payload


def _write_disposable_patch_repo(repo: Path) -> Path:
    app_dir = repo / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "search.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    return repo


def _decision(parameters: dict | None = None) -> Decision:
    base_parameters = {
        "repo_path": str(REPO_ROOT / "fixtures" / "codebases" / "search_service"),
        "allowed_paths": ["app/search.py"],
        "patch_template": {
            "target_file": "app/search.py",
            "find": "old",
            "replace": "new",
        },
        "test_commands": ["python3 -m unittest"],
        "mesh_run_id": "run_hsai_bridge",
        "mesh_policy_id": "mesh_policy://repo-patch/test",
        "actor_ref": {"actor_id": "operator.test", "team_id": "team.test"},
    }
    base_parameters.update(parameters or {})
    return Decision(
        decision_id="dec_repo_patch",
        trigger_id="trig_repo_patch",
        summary="Patch the search service",
        decision_type="investigate_and_patch",
        autonomy_tier="approval_required",
        reasoning={
            "primary_hypothesis": "timeout too high",
            "evidence": ["unit fixture"],
            "alternatives_considered": ["open incident only"],
        },
        expected_outcome={"target_metrics": {"p95_latency_ms": "<= current", "error_rate": "<= current"}, "time_to_effect": "local"},
        risk={"level": "medium", "blast_radius": "repo_patch", "customer_impact_if_wrong": "local revert"},
        confidence=0.8,
        execution_plan={
            "system": "repo_patch_service",
            "action": "investigate_and_patch",
            "parameters": base_parameters,
            "rollback_plan": "restore backup and rerun tests",
        },
    )


def _evaluation(passed: bool = True) -> EvaluationResult:
    return EvaluationResult(
        evaluation_id="eval_repo_patch",
        decision_id="dec_repo_patch",
        passed=passed,
        final_recommendation="execute" if passed else "human_review",
        stage_results={"policy_validation": {"passed": passed, "policy_id": "mesh_policy://repo-patch/test"}},
        blocking_reasons=[] if passed else ["mesh policy denied repo patch"],
        review_route=None if passed else "human_review",
    )


def _write_formal_backend_bundle(root: Path, *, run_summary_overrides: dict | None = None) -> Path:
    bundle_dir = root / "gateway-formal-backend-run"
    bundle_dir.mkdir()
    nonclaims = [
        "not attestation evidence",
        "not proof",
        "not live provider evidence",
        "not accepted Evidence Ledger mutation",
        "not benchmark evidence",
        "not SOTA status",
        "not breakthrough status",
        "not production readiness",
        "not semantic correctness",
        "not authority to execute an action",
        "not formal proof evidence",
        "no formal backend was run",
        "metadata adapter only",
        "not full security",
        "not Level2+ evidence",
        "not score-axis population",
        "not proof of HSAI",
        "not source proof",
        "correspondence metadata only",
        "backend adapter metadata only",
        "not backend checked",
        "not proof artifact evidence",
        "candidate metadata only",
        "backend run artifact metadata only",
        "backend not run",
        "no proof artifact retained",
        "no checker transcript retained",
        "not accepted evidence",
    ]
    run_summary = {
        "schema_version": "hsai-gateway-formal-backend-run-artifact:v1",
        "run_id": "hsai-formal-run-1",
        "state_slice": "phase-276-hsai-gateway-formal-backend-run-inert-artifact-metadata",
        "adapter_request_digest": "hsai-hash-adapter-request",
        "adapter_report_digest": "hsai-hash-adapter-report",
        "correspondence_certificate_digest": "hsai-hash-correspondence-certificate",
        "output_manifest_digest": "hsai-hash-output-manifest",
        "backend_kind": "RustToLean",
        "tool_name": "lean",
        "tool_version": "not-run",
        "toolchain_lock_digest": "hsai-hash-toolchain-lock",
        "execution_mode": "NotRun",
        "started_at_unix": None,
        "finished_at_unix": None,
        "exit_status": "NotRun",
        "checker_status": "NotRun",
        "proof_obligations_requested": ["GatewayProposalDigestDeterministic"],
        "proof_obligations_discharged": [],
        "proof_obligations_not_discharged": [],
        "modeled_assumptions_digest": "hsai-hash-model-assumptions",
        "unsupported_rust_features_digest": "hsai-hash-unsupported-rust-features",
        "candidate_proof_artifact_ref": None,
        "candidate_checker_transcript_ref": None,
        "candidate_tool_log_summary_digest": None,
        "claim_boundary": "local gateway formal backend-run artifact metadata only",
        "creates_accepted_evidence": False,
        "creates_level2_evidence": False,
        "populates_score_axes": False,
        "grants_authority": False,
        "semantic_correctness_claimed": False,
        "production_readiness_claimed": False,
        "sota_claimed": False,
        "full_security_claimed": False,
        "claim_text": [],
        "nonclaims": nonclaims,
    }
    run_summary.update(run_summary_overrides or {})
    files: dict[str, bytes] = {
        "adapter-request.json": _json_bytes({"schema_version": "hsai-gateway-formal-backend-adapter-request:v1"}),
        "adapter-report.json": _json_bytes({"schema_version": "hsai-gateway-formal-backend-adapter-report:v1"}),
        "run-summary.json": _json_bytes(run_summary),
        "correspondence-certificate-digest.json": _json_bytes("hsai-hash-correspondence-certificate"),
        "correspondence-output-manifest-digest.json": _json_bytes("hsai-hash-output-manifest"),
        "source-digests.json": _json_bytes([{"path": "crates/hsai-agent-admission/src/lib.rs", "sha256": "abc"}]),
        "toolchain-lock.json": _json_bytes(
            {"backend_kind": "RustToLean", "tool_name": "lean", "tool_version": "not-run", "toolchain_lock_digest": "hsai-hash-toolchain-lock"}
        ),
        "model-assumptions.json": _json_bytes(["metadata only"]),
        "unsupported-rust-features.json": _json_bytes(["backend not run"]),
        "proof-obligations.json": _json_bytes(["GatewayProposalDigestDeterministic"]),
        "redaction-report.json": _json_bytes(
            {
                "retains_credentials_or_secrets": False,
                "retains_proof_assistant_cache": False,
                "retains_raw_prover_logs": False,
                "retains_raw_checker_transcripts": False,
                "retains_raw_smt_solver_traces": False,
                "retains_raw_external_repo_source": False,
                "retains_accepted_evidence_ledger_json": False,
                "retains_benchmark_outputs": False,
                "retains_live_provider_responses": False,
                "retains_generated_proof_artifacts": False,
                "retains_generated_checker_artifacts": False,
                "materializes_optional_attachments": False,
            }
        ),
        "nonclaims.md": "\n".join(f"- {nonclaim}" for nonclaim in nonclaims).encode("utf-8"),
    }
    declared_paths = [f"gateway-formal-backend-run/{name}" for name in ["manifest.json", *files.keys()]]
    manifest_declared_file_digests = {
        f"gateway-formal-backend-run/{name}": hashlib.sha256(content).hexdigest()
        for name, content in files.items()
    }
    manifest = {
        "schema_version": "hsai-gateway-formal-backend-run-output-v1",
        "bundle_id": "mesh-hsai-formal-bundle",
        "state_slice": "phase-276-hsai-gateway-formal-backend-run-inert-artifact-metadata",
        "created_at_unix": 1,
        "adapter_request_digest": "hsai-hash-adapter-request",
        "adapter_report_digest": "hsai-hash-adapter-report",
        "run_summary_digest": "hsai-hash-run-summary",
        "correspondence_certificate_digest": "hsai-hash-correspondence-certificate",
        "correspondence_output_manifest_digest": "hsai-hash-output-manifest",
        "source_digests_digest": "hsai-hash-source-digests",
        "toolchain_lock_file_digest": "hsai-hash-toolchain-lock-file",
        "model_assumptions_digest": "hsai-hash-model-assumptions",
        "unsupported_rust_features_digest": "hsai-hash-unsupported-rust-features",
        "proof_obligations_digest": "hsai-hash-proof-obligations",
        "redaction_report_digest": "hsai-hash-redaction-report",
        "nonclaims_digest": "hsai-hash-nonclaims",
        "declared_files": declared_paths,
        "declared_file_digests": manifest_declared_file_digests,
        "claim_boundary": "local gateway formal backend-run artifact metadata only",
        "creates_accepted_evidence": False,
        "creates_level2_evidence": False,
        "populates_score_axes": False,
        "grants_authority": False,
        "nonclaims": nonclaims,
    }
    files["manifest.json"] = _json_bytes(manifest)
    for name, content in files.items():
        path = bundle_dir / name
        path.write_bytes(content)
        (bundle_dir / f"{name}.sha256").write_text(hashlib.sha256(content).hexdigest(), encoding="utf-8")
    return root


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _decision_digest(decision: dict) -> str:
    from shared.mesh_runtime.hsai_bridge import decision_digest

    return decision_digest(decision)


if __name__ == "__main__":
    unittest.main()
