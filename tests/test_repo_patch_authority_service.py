from __future__ import annotations

import ast
import os
import shlex
import socket
import stat
import struct
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.actuators.repo_patch_authority_service import (
    AUTHORITY_STATE_SLICE,
    RepoPatchAuthorityService,
)
from shared.mesh_runtime import Decision, EvaluationResult
from shared.mesh_runtime.goose_credentials import (
    REPO_PATCH_AUTHORITY_SECRET_ENV_KEYS,
    model_subprocess_env,
)
from shared.mesh_runtime.hsai_bridge import (
    HSAI_EXECUTION_CONTEXT_KEY,
    build_hsai_admission_request_v2,
    evaluate_hsai_gate,
    local_hsai_allow_decision,
)
from shared.mesh_runtime.perennial.signing import (
    build_ed25519_signature_proof,
    verify_ed25519_signature_proof,
)
from shared.mesh_runtime.repo_patch_authority import (
    AUTHORITY_REQUEST_VERSION,
    AUTHORITY_RESPONSE_SIGNING_PROFILE,
    CLIENT_REQUEST_SIGNING_PROFILE,
    MAX_FRAME_BYTES,
    RepoPatchAuthorityClient,
    RepoPatchAuthorityError,
    receive_json_frame,
    send_json_frame,
)
from shared.mesh_runtime.repo_patch_test_policy import AuthorizedTestCommand


REPO_ROOT = Path(__file__).resolve().parents[1]
CLIENT_KEY_ID = "mesh-test-client"
AUTHORITY_KEY_ID = "mesh-test-authority"
PERMIT_KEY = "test-authority-service-permit-hmac-key"
DEFAULT_TEST_COMMAND = ("python3", "-c", "pass")


class _EligibleHsaiAdapter:
    authority_eligible = True
    adapter_identity = "mesh.test.authority-service-hsai-adapter.v1"

    def admit(self, request: dict) -> dict:
        return local_hsai_allow_decision(request)


class _SuccessfulVerifier:
    def verify(
        self,
        *,
        commands: tuple[AuthorizedTestCommand, ...],
        **_: object,
    ) -> tuple[dict[str, object], ...]:
        empty_digest = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        return tuple(
            {
                "argv": [command.executable_path, *command.argv[1:]],
                "returncode": 0,
                "stdout_digest": empty_digest,
                "stderr_digest": empty_digest,
                "stdout_bytes": 0,
                "stderr_bytes": 0,
                "timed_out": False,
                "output_limit_exceeded": False,
            }
            for command in commands
        )


class RepoPatchAuthorityServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client_private_key, cls.client_public_key = _ed25519_key_pair()
        cls.authority_private_key, cls.authority_public_key = _ed25519_key_pair()
        cls.attacker_private_key, cls.attacker_public_key = _ed25519_key_pair()

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.socket_path = self.root / "socket" / "repo-patch-authority.sock"
        self.state_directory = self.root / "authority-state"

    def test_authenticated_peer_receipt_authorized_patch_and_verified_signature(self) -> None:
        repo = _write_repo(self.root / "repo")
        decision, evaluation, gate = _admitted_action(repo)
        service = self._service()

        with _running_service(service, expected_connections=2):
            response = _execute_with_preflight(self._client(), decision, evaluation, gate)

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["execution_result"]["status"], "succeeded")
        self.assertEqual(response["receipt"]["state_slice"], AUTHORITY_STATE_SLICE)
        self.assertEqual(response["receipt"]["authenticated_client_key_id"], CLIENT_KEY_ID)
        self.assertEqual(response["receipt"]["peer_uid"], os.geteuid())
        self.assertEqual(response["receipt"]["peer_gid"], os.getegid())
        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'new'\n")

    def test_raw_authorized_response_is_signed_by_pinned_authority(self) -> None:
        repo = _write_repo(self.root / "repo")
        decision, evaluation, gate = _admitted_action(repo)
        request = self._signed_request(
            decision,
            evaluation,
            None,
            _idempotency_key(decision),
            operation="preflight",
            preflight_receipt=None,
        )
        service = self._service()

        with _running_service(service, expected_connections=1):
            response = _round_trip(self.socket_path, request)

        proof = response["authorization_proof"]
        self.assertEqual(proof["key_id"], AUTHORITY_KEY_ID)
        self.assertEqual(proof["signing_profile"], AUTHORITY_RESPONSE_SIGNING_PROFILE)
        self.assertTrue(
            verify_ed25519_signature_proof(
                response["body"],
                proof,
                public_key_pem=self.authority_public_key,
            )
        )

    def test_forged_client_signature_is_rejected_without_mutation(self) -> None:
        repo = _write_repo(self.root / "repo")
        target = repo / "app/search.py"
        decision, evaluation, gate = _admitted_action(repo)
        request = self._signed_request(
            decision,
            evaluation,
            gate,
            _idempotency_key(decision),
            private_key=self.attacker_private_key,
        )

        with _running_service(self._service(), expected_connections=1):
            response = _round_trip(self.socket_path, request)

        self.assertEqual(response["body"]["status"], "rejected")
        self.assertEqual(response["body"]["rejection"]["code"], "client_signature_rejected")
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'old'\n")
        self.assertFalse((self.state_directory / "repo_patch_authority_ledger.json").exists())

    def test_wrong_pinned_authority_key_is_rejected_client_side(self) -> None:
        repo = _write_repo(self.root / "repo")
        decision, evaluation, gate = _admitted_action(repo)
        client = RepoPatchAuthorityClient(
            self.socket_path,
            client_private_key_pem=self.client_private_key,
            client_key_id=CLIENT_KEY_ID,
            authority_public_key_pem=self.attacker_public_key,
            authority_key_id=AUTHORITY_KEY_ID,
        )

        with _running_service(self._service(), expected_connections=1):
            with self.assertRaisesRegex(RepoPatchAuthorityError, "response signature rejected"):
                client.preflight(decision, evaluation, _idempotency_key(decision))

    def test_duplicate_key_oversized_and_truncated_frames_are_rejected(self) -> None:
        service = self._service()
        malformed_frames = (
            struct.pack(">I", 21) + b'{"body":{},"body":{}}',
            struct.pack(">I", MAX_FRAME_BYTES + 1),
            struct.pack(">I", 12) + b'{"body":{}}',
        )

        with _running_service(service, expected_connections=len(malformed_frames)):
            responses = [
                _raw_frame_round_trip(
                    self.socket_path,
                    frame,
                    shutdown_write=index == 2,
                )
                for index, frame in enumerate(malformed_frames)
            ]

        self.assertTrue(all(response["body"]["status"] == "rejected" for response in responses))
        self.assertTrue(all(response["body"]["rejection"]["code"] == "invalid_request_frame" for response in responses))

    def test_1024_authenticated_protocol_negative_cases_cannot_mutate(self) -> None:
        repo = _write_repo(self.root / "repo")
        target = repo / "app/search.py"
        decision, evaluation, gate = _admitted_action(repo)
        idempotency_key = _idempotency_key(decision)
        service = self._service()
        rejected = 0

        for case_index in range(256):
            forged = self._signed_request(
                decision,
                evaluation,
                gate,
                idempotency_key,
                private_key=self.attacker_private_key,
            )
            forged["body"]["request_id"] += f":forged:{case_index}"
            rejected += service.handle_request(
                forged,
                peer_uid=os.geteuid(),
                peer_gid=os.getegid(),
            )["body"]["status"] == "rejected"

            now = datetime.now(timezone.utc)
            stale = self._signed_request(
                decision,
                evaluation,
                gate,
                idempotency_key,
                issued_at=now - timedelta(minutes=2, seconds=case_index),
                expires_at=now - timedelta(minutes=1, seconds=case_index),
            )
            rejected += service.handle_request(
                stale,
                peer_uid=os.geteuid(),
                peer_gid=os.getegid(),
            )["body"]["status"] == "rejected"

            wrong_peer = self._signed_request(decision, evaluation, gate, idempotency_key)
            rejected += service.handle_request(
                wrong_peer,
                peer_uid=os.geteuid() + case_index + 1,
                peer_gid=os.getegid(),
            )["body"]["status"] == "rejected"

            drifted_gate = deepcopy(gate)
            drifted_gate["request_digest"] = "sha256:" + f"{case_index:064x}"
            drifted = self._signed_request(decision, evaluation, drifted_gate, idempotency_key)
            rejected += service.handle_request(
                drifted,
                peer_uid=os.geteuid(),
                peer_gid=os.getegid(),
            )["body"]["status"] == "rejected"

        self.assertEqual(rejected, 1024)
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'old'\n")
        self.assertFalse((self.state_directory / "repo_patch_authority_ledger.json").exists())

    def test_stale_signed_request_is_rejected_without_mutation(self) -> None:
        repo = _write_repo(self.root / "repo")
        target = repo / "app/search.py"
        decision, evaluation, gate = _admitted_action(repo)
        now = datetime.now(timezone.utc)
        request = self._signed_request(
            decision,
            evaluation,
            gate,
            _idempotency_key(decision),
            issued_at=now - timedelta(minutes=2),
            expires_at=now - timedelta(minutes=1),
        )

        with _running_service(self._service(), expected_connections=1):
            response = _round_trip(self.socket_path, request)

        self.assertEqual(response["body"]["rejection"]["code"], "request_time_rejected")
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_pre_attached_permit_is_rejected_without_mutation(self) -> None:
        repo = _write_repo(self.root / "repo")
        target = repo / "app/search.py"
        decision, evaluation, gate = _admitted_action(repo)
        payload = decision.to_dict()
        payload["execution_plan"]["parameters"][HSAI_EXECUTION_CONTEXT_KEY] = {
            "execution_permit": {"forged": True}
        }
        request = self._signed_request(
            Decision.from_dict(payload),
            evaluation,
            gate,
            _idempotency_key(decision),
        )

        with _running_service(self._service(), expected_connections=1):
            response = _round_trip(self.socket_path, request)

        self.assertEqual(response["body"]["rejection"]["code"], "pre_attached_permit_rejected")
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_hsai_ineligible_gate_is_rejected_without_mutation(self) -> None:
        repo = _write_repo(self.root / "repo")
        target = repo / "app/search.py"
        decision, evaluation, gate = _admitted_action(repo)
        gate["authority_eligible"] = False
        request = self._signed_request(decision, evaluation, gate, _idempotency_key(decision))

        with _running_service(self._service(), expected_connections=1):
            response = _round_trip(self.socket_path, request)

        self.assertEqual(response["body"]["rejection"]["code"], "admission_rejected")
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_terminal_replay_returns_same_result_without_second_mutation(self) -> None:
        repo = _write_repo(self.root / "repo")
        decision, evaluation, gate = _admitted_action(repo)
        client = self._client()
        service = self._service()
        idempotency_key = _idempotency_key(decision)

        with _running_service(service, expected_connections=3):
            preflight_receipt = client.preflight(decision, evaluation, idempotency_key)
            gate = _gate_for_preflight(decision, evaluation, preflight_receipt)
            first = client.execute(decision, evaluation, gate, idempotency_key, preflight_receipt)
            first_target_stat = (repo / "app/search.py").stat()
            second = client.execute(decision, evaluation, gate, idempotency_key, preflight_receipt)

        self.assertEqual(first["execution_result"], second["execution_result"])
        self.assertEqual((repo / "app/search.py").stat().st_ino, first_target_stat.st_ino)
        self.assertEqual((repo / "app/search.py").stat().st_mtime_ns, first_target_stat.st_mtime_ns)
        self.assertEqual(len(list((self.state_directory / "repo_patch_backups").glob("*.bak"))), 1)

    def test_sixteen_concurrent_signed_consumers_produce_one_mutation_and_terminal_replays(self) -> None:
        repo = _write_repo(self.root / "repo")
        decision, evaluation, gate = _admitted_action(repo)
        service = self._service()
        barrier = threading.Barrier(16)
        idempotency_key = _idempotency_key(decision)

        def consume(_: int) -> dict:
            barrier.wait(timeout=10)
            return self._client().execute(decision, evaluation, gate, idempotency_key, preflight_receipt)

        with _running_service(service, expected_connections=17):
            preflight_receipt = self._client().preflight(decision, evaluation, idempotency_key)
            gate = _gate_for_preflight(decision, evaluation, preflight_receipt)
            with ThreadPoolExecutor(max_workers=16) as pool:
                responses = list(pool.map(consume, range(16)))

        results = [response["execution_result"] for response in responses]
        self.assertTrue(all(response["status"] == "completed" for response in responses))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(results[0]["status"], "succeeded")
        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'new'\n")
        self.assertEqual(len(list((self.state_directory / "repo_patch_backups").glob("*.bak"))), 1)

    def test_socket_has_exact_mode_and_current_process_ownership(self) -> None:
        service = self._service()
        service.start()
        self.addCleanup(service.close)

        socket_stat = self.socket_path.lstat()
        self.assertTrue(stat.S_ISSOCK(socket_stat.st_mode))
        self.assertEqual(stat.S_IMODE(socket_stat.st_mode), 0o660)
        self.assertEqual(socket_stat.st_uid, os.geteuid())
        self.assertEqual(socket_stat.st_gid, os.getegid())
        self.assertEqual(stat.S_IMODE(self.socket_path.parent.stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE(self.state_directory.stat().st_mode), 0o700)

    def test_missing_socket_fails_closed_without_mutation(self) -> None:
        repo = _write_repo(self.root / "repo")
        decision, evaluation, gate = _admitted_action(repo)

        with self.assertRaisesRegex(RepoPatchAuthorityError, "transport failed"):
            self._client().preflight(decision, evaluation, _idempotency_key(decision))

        self.assertEqual((repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")
        self.assertFalse(self.state_directory.exists())

    def test_exact_allowlisted_command_succeeds_and_unlisted_command_fails_before_mutation(self) -> None:
        allowlisted_repo = _write_repo(self.root / "allowlisted-repo")
        blocked_repo = _write_repo(self.root / "blocked-repo")
        allowed_command = ("python3", "-c", "pass")
        service = self._service(allowed_test_commands=(allowed_command,))
        allowed = _admitted_action(
            allowlisted_repo,
            action_id="allowed",
            test_commands=["python3 -c pass"],
        )
        blocked = _admitted_action(
            blocked_repo,
            action_id="blocked",
            test_commands=["python3 -c 'raise SystemExit(0)'"],
        )

        with _running_service(service, expected_connections=3):
            allowed_response = _execute_with_preflight(self._client(), *allowed)
            with self.assertRaisesRegex(RepoPatchAuthorityError, "preflight rejected"):
                self._client().preflight(blocked[0], blocked[1], _idempotency_key(blocked[0]))

        self.assertEqual(allowed_response["execution_result"]["status"], "succeeded")
        self.assertEqual((allowlisted_repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'new'\n")
        self.assertEqual((blocked_repo / "app/search.py").read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_startup_invokes_incomplete_action_recovery_before_listening(self) -> None:
        service = self._service()

        with patch.object(service.actuator, "recover_incomplete_actions", return_value=[]) as recover:
            service.start()
            self.addCleanup(service.close)

        recover.assert_called_once_with()

    def test_corrupt_authority_ledger_blocks_startup_without_socket(self) -> None:
        self.state_directory.mkdir(mode=0o700)
        (self.state_directory / "repo_patch_authority_ledger.json").write_text(
            "{not-json",
            encoding="utf-8",
        )
        service = self._service()

        with self.assertRaisesRegex(ValueError, "corrupt JSON state file"):
            service.start()

        self.assertFalse(self.socket_path.exists())

    def test_production_has_single_actuator_owner_and_model_subprocesses_strip_authority_secrets(self) -> None:
        authority_service = REPO_ROOT / "services/actuators/repo_patch_authority_service.py"
        production_roots = [REPO_ROOT / name for name in ("services", "shared", "scripts", "mesh_brain", "simulation")]
        forbidden_imports: list[str] = []
        forbidden_constructors: list[str] = []
        for production_root in production_roots:
            for source_path in production_root.rglob("*.py"):
                if source_path == authority_service:
                    continue
                tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module == "services.actuators.repo_patch":
                        if any(alias.name == "RepoPatchAdapter" for alias in node.names):
                            forbidden_imports.append(str(source_path.relative_to(REPO_ROOT)))
                    if isinstance(node, ast.Call) and (
                        isinstance(node.func, ast.Name)
                        and node.func.id == "RepoPatchAdapter"
                        or isinstance(node.func, ast.Attribute)
                        and node.func.attr == "RepoPatchAdapter"
                    ):
                        forbidden_constructors.append(str(source_path.relative_to(REPO_ROOT)))

        base_environment = {key: f"secret-for-{key}" for key in REPO_PATCH_AUTHORITY_SECRET_ENV_KEYS}
        base_environment["SAFE_VALUE"] = "preserved"
        sanitized = model_subprocess_env(base_environment)
        self.assertEqual(forbidden_imports, [])
        self.assertEqual(forbidden_constructors, [])
        self.assertEqual(sanitized["SAFE_VALUE"], "preserved")
        self.assertTrue(all(key not in sanitized for key in REPO_PATCH_AUTHORITY_SECRET_ENV_KEYS))
        self._assert_model_subprocess_calls_use_sanitized_env()

    def _assert_model_subprocess_calls_use_sanitized_env(self) -> None:
        boundary_files = (
            REPO_ROOT / "services/orchestrator/goose_adapter.py",
            REPO_ROOT / "services/orchestrator/goose_bridge.py",
            REPO_ROOT / "services/orchestrator/hermes_adapter.py",
            REPO_ROOT / "services/orchestrator/hermes_bridge.py",
        )
        unsanitized: list[str] = []
        subprocess_calls = 0
        for source_path in boundary_files:
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if not isinstance(node.func.value, ast.Name) or node.func.value.id != "subprocess":
                    continue
                if node.func.attr not in {"run", "Popen"}:
                    continue
                subprocess_calls += 1
                environment = next((keyword.value for keyword in node.keywords if keyword.arg == "env"), None)
                if not isinstance(environment, ast.Call):
                    unsanitized.append(f"{source_path.relative_to(REPO_ROOT)}:{node.lineno}")
                    continue
                function_name = ast.unparse(environment.func)
                if function_name not in {
                    "model_subprocess_env",
                    "goose_subprocess_env",
                    "_command_env",
                    "_goose_env",
                    "_verifier_command_environment",
                }:
                    unsanitized.append(f"{source_path.relative_to(REPO_ROOT)}:{node.lineno}")
        self.assertGreater(subprocess_calls, 0)
        self.assertEqual(unsanitized, [])

    def _service(
        self,
        *,
        allowed_test_commands: tuple[tuple[str, ...], ...] = (DEFAULT_TEST_COMMAND,),
    ) -> RepoPatchAuthorityService:
        return RepoPatchAuthorityService(
            self.socket_path,
            self.state_directory,
            authority_private_key_pem=self.authority_private_key,
            authority_key_id=AUTHORITY_KEY_ID,
            client_public_keys={CLIENT_KEY_ID: self.client_public_key},
            allowed_uids={os.geteuid()},
            permit_signing_key=PERMIT_KEY,
            allowed_test_commands=allowed_test_commands,
            hsai_admission_adapter=_EligibleHsaiAdapter(),
            verifier_client=_SuccessfulVerifier(),  # type: ignore[arg-type]
        )

    def _client(self) -> RepoPatchAuthorityClient:
        return RepoPatchAuthorityClient(
            self.socket_path,
            client_private_key_pem=self.client_private_key,
            client_key_id=CLIENT_KEY_ID,
            authority_public_key_pem=self.authority_public_key,
            authority_key_id=AUTHORITY_KEY_ID,
        )

    def _signed_request(
        self,
        decision: Decision,
        evaluation: EvaluationResult,
        gate: dict | None,
        idempotency_key: str,
        *,
        operation: str = "execute",
        preflight_receipt: dict | None = None,
        private_key: str | None = None,
        issued_at: datetime | None = None,
        expires_at: datetime | None = None,
    ) -> dict:
        issued = issued_at or datetime.now(timezone.utc)
        expires = expires_at or issued + timedelta(seconds=30)
        body = {
            "schema_version": AUTHORITY_REQUEST_VERSION,
            "operation": operation,
            "request_id": f"request:{idempotency_key}",
            "idempotency_key": idempotency_key,
            "issued_at": _format_time(issued),
            "expires_at": _format_time(expires),
            "client_key_id": CLIENT_KEY_ID,
            "decision": decision.to_dict(),
            "evaluation": asdict(evaluation),
            "hsai_gate": gate,
            "preflight_receipt": (
                _synthetic_preflight_receipt(decision)
                if operation == "execute" and preflight_receipt is None
                else preflight_receipt
            ),
        }
        return {
            "body": body,
            "authorization_proof": build_ed25519_signature_proof(
                body,
                key_id=CLIENT_KEY_ID,
                private_key_pem=private_key or self.client_private_key,
                signing_profile=CLIENT_REQUEST_SIGNING_PROFILE,
            ),
        }


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
            raise AssertionError("authority service did not process the expected connection count")
        if failures:
            raise AssertionError(f"authority service thread failed: {failures!r}")
    finally:
        service.close()


def _round_trip(socket_path: Path, request: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(str(socket_path))
        send_json_frame(connection, request)
        return receive_json_frame(connection)


def _raw_frame_round_trip(socket_path: Path, frame: bytes, *, shutdown_write: bool = False) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect(str(socket_path))
        connection.sendall(frame)
        if shutdown_write:
            connection.shutdown(socket.SHUT_WR)
        return receive_json_frame(connection)


def _admitted_action(
    repo: Path,
    *,
    action_id: str | None = None,
    test_commands: list[str] | None = None,
) -> tuple[Decision, EvaluationResult, dict]:
    decision = _decision(repo, action_id=action_id, test_commands=test_commands)
    evaluation = _evaluation(decision.decision_id)
    gate = _gate_for_preflight(decision, evaluation, _synthetic_preflight_receipt(decision))
    return decision, evaluation, gate


def _decision(
    repo: Path,
    *,
    action_id: str | None = None,
    test_commands: list[str] | None = None,
) -> Decision:
    decision_id = "decision-authority-service" + (f"-{action_id}" if action_id else "")
    return Decision(
        decision_id=decision_id,
        trigger_id="trigger-authority-service",
        summary="Patch a disposable search service",
        decision_type="investigate_and_patch",
        autonomy_tier="approval_required",
        reasoning={
            "primary_hypothesis": "fixture value needs replacement",
            "evidence": ["local disposable fixture"],
            "alternatives_considered": ["leave unchanged"],
        },
        expected_outcome={
            "target_metrics": {
                "p95_latency_ms": "unchanged",
                "error_rate": "unchanged",
            },
            "time_to_effect": "local",
        },
        risk={
            "level": "medium",
            "blast_radius": "disposable repo",
            "customer_impact_if_wrong": "none",
        },
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
                "test_commands": ["python3 -c pass"] if test_commands is None else test_commands,
                "mesh_run_id": "run-authority-service" + (f"-{action_id}" if action_id else ""),
                "mesh_policy_id": "mesh_policy://repo-patch/authority-service-test",
                "actor_ref": {"actor_id": "operator.test", "team_id": "team.test"},
            },
            "rollback_plan": "restore the immutable backup",
        },
    )


def _evaluation(decision_id: str = "decision-authority-service") -> EvaluationResult:
    return EvaluationResult(
        evaluation_id=f"evaluation-{decision_id}",
        decision_id=decision_id,
        passed=True,
        final_recommendation="execute",
        stage_results={
            "policy_validation": {
                "passed": True,
                "policy_id": "mesh_policy://repo-patch/authority-service-test",
            }
        },
        blocking_reasons=[],
        review_route=None,
    )


def _write_repo(repo: Path) -> Path:
    target = repo / "app/search.py"
    target.parent.mkdir(parents=True)
    target.write_text("VALUE = 'old'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Mesh Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "mesh@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "app/search.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    return repo.resolve()


def _execute_with_preflight(
    client: RepoPatchAuthorityClient,
    decision: Decision,
    evaluation: EvaluationResult,
    gate: dict,
) -> dict:
    idempotency_key = _idempotency_key(decision)
    receipt = client.preflight(decision, evaluation, idempotency_key)
    gate = _gate_for_preflight(decision, evaluation, receipt)
    return client.execute(decision, evaluation, gate, idempotency_key, receipt)


def _gate_for_preflight(
    decision: Decision,
    evaluation: EvaluationResult,
    preflight_receipt: dict,
) -> dict:
    request = build_hsai_admission_request_v2(decision, evaluation, preflight_receipt)
    return evaluate_hsai_gate(request, _EligibleHsaiAdapter())


def _synthetic_preflight_receipt(decision: Decision) -> dict:
    target_path = decision.execution_plan["parameters"]["patch_template"]["target_file"]
    test_results = []
    for command in decision.execution_plan["parameters"]["test_commands"]:
        argv = shlex.split(command)
        test_results.append(
            {
                "argv": ["/usr/bin/python3", *argv[1:]],
                "returncode": 0,
                "stdout_digest": "sha256:" + ("4" * 64),
                "stderr_digest": "sha256:" + ("5" * 64),
            }
        )
    return {
        "state_slice": "mesh.repo_patch_disposable_worktree.v1",
        "base_commit": "a" * 40,
        "base_tree": "b" * 40,
        "target_path": target_path,
        "target_preimage_digest": "sha256:" + ("1" * 64),
        "target_postimage_digest": "sha256:" + ("2" * 64),
        "authorized_diff_digest": "sha256:" + ("3" * 64),
        "changed_paths": [target_path],
        "test_results": test_results,
    }


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


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    unittest.main()
