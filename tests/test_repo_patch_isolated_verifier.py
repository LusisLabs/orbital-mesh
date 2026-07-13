from __future__ import annotations

import os
import socket
import tempfile
import threading
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.actuators.repo_patch_verifier_service import RepoPatchVerifierService, _read_private_key
from shared.mesh_runtime.repo_patch_authority import receive_json_frame, send_json_frame
from shared.mesh_runtime.repo_patch_test_policy import AuthorizedTestCommand, RepoPatchTestCommandPolicy
from shared.mesh_runtime.repo_patch_verifier import (
    VERIFIER_PROTOCOL_STATE_SLICE,
    VERIFIER_REQUEST_VERSION,
    RepoPatchVerifierClient,
    RepoPatchVerifierError,
    canonical_digest,
    validate_signed_verifier_response,
    workspace_manifest_digest,
)


IMAGE_DIGEST = "sha256:" + ("a" * 64)
SANDBOX_DIGEST = "sha256:" + ("b" * 64)
VERIFIER_KEY_ID = "test-repo-patch-verifier"


class RepoPatchIsolatedVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name).resolve()
        self.input_root = self.root / "input"
        self.input_root.mkdir()
        self.verifier_private_key, self.verifier_public_key = _ed25519_key_pair()
        self.service = self._new_service()
        (self.root / "scratch").mkdir()
        (self.root / "ledger").mkdir()

    def _new_service(self) -> RepoPatchVerifierService:
        return RepoPatchVerifierService(
            self.root / "socket" / "verifier.sock",
            self.input_root,
            self.root / "scratch",
            self.root / "ledger",
            allowed_authority_uids={os.geteuid()},
            runner_uid=os.geteuid(),
            runner_gid=os.getegid(),
            verifier_image_digest=IMAGE_DIGEST,
            sandbox_profile_digest=SANDBOX_DIGEST,
            verifier_private_key_pem=self.verifier_private_key,
            verifier_key_id=VERIFIER_KEY_ID,
            require_identity_separation=False,
        )

    def test_valid_command_is_manifest_bound_and_terminal_replay_is_stable(self) -> None:
        command = ("python3", "-c", "from pathlib import Path; assert Path('app.py').read_text() == 'bounded\\n'")
        request = self._request(command)

        first = self.service.handle_request(request, peer_uid=os.geteuid())
        second = self.service.handle_request(request, peer_uid=os.geteuid())

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(first["code"], "verified")
        self.assertEqual(first["workspace_manifest_before"], first["workspace_manifest_after"])
        self.assertEqual(first["runner_uid"], os.geteuid())
        self.assertEqual(first["test_results"][0]["returncode"], 0)
        self.assertEqual(first["authorization_proof"]["key_id"], VERIFIER_KEY_ID)
        validate_signed_verifier_response(
            first,
            expected_key_id=VERIFIER_KEY_ID,
            public_key_pem=self.verifier_public_key,
        )

    def test_wrong_peer_and_request_tamper_fail_closed(self) -> None:
        request = self._request(("python3", "-c", "pass"))
        wrong_peer = self.service.handle_request(request, peer_uid=os.geteuid() + 1)
        self.assertEqual(wrong_peer["code"], "authority_peer_rejected")
        validate_signed_verifier_response(
            wrong_peer,
            expected_key_id=VERIFIER_KEY_ID,
            public_key_pem=self.verifier_public_key,
        )

        request["timeout_seconds"] = 29
        tampered = self.service.handle_request(request, peer_uid=os.geteuid())
        self.assertEqual(tampered["code"], "request_contract_rejected")
        validate_signed_verifier_response(
            tampered,
            expected_key_id=VERIFIER_KEY_ID,
            public_key_pem=self.verifier_public_key,
        )

    def test_signed_receipt_rejects_tamper_wrong_key_malformed_proof_and_unsigned_v1_shape(self) -> None:
        receipt = self.service.handle_request(
            self._request(("python3", "-c", "pass"), marker="receipt-adversarial"),
            peer_uid=os.geteuid(),
        )

        tampered = _deep_copy(receipt)
        tampered["runner_uid"] = int(tampered["runner_uid"]) + 1
        with self.assertRaisesRegex(ValueError, "signature rejected"):
            validate_signed_verifier_response(
                tampered,
                expected_key_id=VERIFIER_KEY_ID,
                public_key_pem=self.verifier_public_key,
            )

        _, attacker_public_key = _ed25519_key_pair()
        with self.assertRaisesRegex(ValueError, "signer identity rejected"):
            validate_signed_verifier_response(
                receipt,
                expected_key_id=VERIFIER_KEY_ID,
                public_key_pem=attacker_public_key,
            )

        malformed = _deep_copy(receipt)
        malformed["authorization_proof"]["signature"] = "not-base64"
        with self.assertRaisesRegex(ValueError, "signature rejected"):
            validate_signed_verifier_response(
                malformed,
                expected_key_id=VERIFIER_KEY_ID,
                public_key_pem=self.verifier_public_key,
            )

        unsigned = _deep_copy(receipt)
        del unsigned["authorization_proof"]
        unsigned["schema_version"] = "mesh.repo_patch_verifier_response.v1"
        unsigned["state_slice"] = "mesh.repo_patch_verifier_receipt.v1"
        with self.assertRaises(ValueError):
            validate_signed_verifier_response(
                unsigned,
                expected_key_id=VERIFIER_KEY_ID,
                public_key_pem=self.verifier_public_key,
            )

    def test_private_signing_key_reader_rejects_group_or_world_access(self) -> None:
        key_path = self.root / "verifier-private.pem"
        key_path.write_text(self.verifier_private_key, encoding="utf-8")
        key_path.chmod(0o600)
        self.assertEqual(_read_private_key(key_path), self.verifier_private_key)

        for mode in (0o640, 0o604):
            with self.subTest(mode=oct(mode)):
                key_path.chmod(mode)
                with self.assertRaisesRegex(RuntimeError, "permissions are too broad"):
                    _read_private_key(key_path)

    def test_nonzero_exit_and_workspace_mutation_are_rejected(self) -> None:
        failed = self.service.handle_request(
            self._request(("python3", "-c", "raise SystemExit(7)"), marker="failure"),
            peer_uid=os.geteuid(),
        )
        self.assertEqual(failed["status"], "rejected")
        self.assertEqual(failed["code"], "command_failed")
        self.assertEqual(failed["test_results"][0]["returncode"], 7)

        mutated = self.service.handle_request(
            self._request(
                ("python3", "-c", "from pathlib import Path; Path('unexpected').write_text('x')"),
                marker="mutation",
            ),
            peer_uid=os.geteuid(),
        )
        self.assertEqual(mutated["status"], "rejected")
        self.assertEqual(mutated["code"], "workspace_mutation_rejected")

    def test_timeout_and_streaming_output_limit_are_bounded(self) -> None:
        timed_out = self.service.handle_request(
            self._request(
                ("python3", "-c", "import time; time.sleep(5)"),
                marker="timeout",
                timeout_seconds=1,
            ),
            peer_uid=os.geteuid(),
        )
        self.assertEqual(timed_out["code"], "command_timed_out")
        self.assertTrue(timed_out["test_results"][0]["timed_out"])

        output = self.service.handle_request(
            self._request(
                ("python3", "-c", "import os; os.write(1, b'x' * 70000)"),
                marker="output",
                output_limit_bytes=1024,
            ),
            peer_uid=os.geteuid(),
        )
        self.assertEqual(output["code"], "output_limit_exceeded")
        self.assertTrue(output["test_results"][0]["output_limit_exceeded"])
        self.assertLessEqual(output["test_results"][0]["stdout_bytes"], 8192)

    def test_executable_digest_drift_and_symlink_handoff_are_rejected(self) -> None:
        request = self._request(("python3", "-c", "pass"), marker="digest")
        request["commands"][0]["executable_digest"] = "sha256:" + ("f" * 64)
        request["commands"][0]["command_digest"] = canonical_digest(
            {
                "argv": request["commands"][0]["argv"],
                "executable_path": request["commands"][0]["executable_path"],
                "executable_digest": request["commands"][0]["executable_digest"],
            }
        )
        request["request_digest"] = canonical_digest(
            {key: value for key, value in request.items() if key != "request_digest"}
        )
        drifted = self.service.handle_request(request, peer_uid=os.geteuid())
        self.assertEqual(drifted["status"], "rejected")

        workspace = self.input_root / ("workspace_" + ("e" * 64))
        workspace.mkdir()
        (workspace / "escape").symlink_to(self.root / "outside")
        with self.assertRaisesRegex(ValueError, "symlinks"):
            workspace_manifest_digest(workspace)

    def test_worker_restart_terminalizes_running_job_without_rerun(self) -> None:
        request = self._request(("python3", "-c", "pass"), marker="restart")
        self.service._create_running_record(self.service._running_path(request["job_id"]), request)

        restarted = self._new_service()
        restarted._recover_interrupted_jobs()
        recovered = restarted.handle_request(request, peer_uid=os.geteuid())

        self.assertEqual(recovered["status"], "rejected")
        self.assertEqual(recovered["code"], "aborted_by_worker_restart")
        validate_signed_verifier_response(
            recovered,
            expected_key_id=VERIFIER_KEY_ID,
            public_key_pem=self.verifier_public_key,
        )

    def test_worker_restart_preserves_existing_terminal_receipt(self) -> None:
        request = self._request(("python3", "-c", "pass"), marker="terminal-restart")
        terminal = self.service.handle_request(request, peer_uid=os.geteuid())
        self.service._create_running_record(self.service._running_path(request["job_id"]), request)

        restarted = self._new_service()
        restarted._recover_interrupted_jobs()
        recovered = restarted.handle_request(request, peer_uid=os.geteuid())

        self.assertEqual(recovered, terminal)
        self.assertEqual(recovered["status"], "succeeded")

    def test_client_pins_signer_and_exposes_only_current_verified_terminal_receipt(self) -> None:
        request = self._request(("python3", "-c", "pass"), marker="client-success")
        client = self._client_for()

        results = self._run_client(client, request)

        self.assertEqual(results[0]["returncode"], 0)
        receipt = client.last_verified_receipt
        self.assertIsNotNone(receipt)
        assert receipt is not None
        self.assertEqual(receipt["authorization_proof"]["key_id"], VERIFIER_KEY_ID)
        receipt["status"] = "rejected"
        self.assertEqual(client.last_verified_receipt["status"], "succeeded")  # type: ignore[index]

        with self.assertRaisesRegex(RepoPatchVerifierError, "workspace id rejected"):
            client.verify(
                workspace_id="invalid",
                workspace_manifest=str(request["workspace_manifest_digest"]),
                candidate_binding=dict(request["candidate_binding"]),
                commands=(),
            )
        self.assertIsNone(client.last_verified_receipt)

    def test_client_rejects_tampered_unsigned_and_wrong_key_terminal_responses(self) -> None:
        modifiers: tuple[Callable[[dict[str, Any]], None], ...] = (
            lambda response: response.__setitem__("code", "tampered"),
            lambda response: response.pop("authorization_proof"),
            lambda response: response["authorization_proof"].__setitem__("signature", "malformed"),
        )
        for index, modifier in enumerate(modifiers):
            with self.subTest(index=index):
                request = self._request(
                    ("python3", "-c", "pass"),
                    marker=f"client-adversarial-{index}",
                )
                client = self._client_for()
                with self.assertRaisesRegex(RepoPatchVerifierError, "response contract rejected"):
                    self._run_client(client, request, modifier=modifier)
                self.assertIsNone(client.last_verified_receipt)

        request = self._request(("python3", "-c", "pass"), marker="client-wrong-key")
        _, attacker_public_key = _ed25519_key_pair()
        client = self._client_for(public_key_pem=attacker_public_key)
        with self.assertRaisesRegex(RepoPatchVerifierError, "response contract rejected"):
            self._run_client(client, request)
        self.assertIsNone(client.last_verified_receipt)

    def _client_for(
        self,
        *,
        public_key_pem: str | None = None,
    ) -> RepoPatchVerifierClient:
        return RepoPatchVerifierClient(
            self.root / "client.sock",
            expected_verifier_uid=os.geteuid(),
            verifier_image_digest=IMAGE_DIGEST,
            sandbox_profile_digest=SANDBOX_DIGEST,
            verifier_public_key_pem=public_key_pem or self.verifier_public_key,
            verifier_key_id=VERIFIER_KEY_ID,
        )

    def _run_client(
        self,
        client: RepoPatchVerifierClient,
        request: dict[str, Any],
        *,
        modifier: Callable[[dict[str, Any]], None] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(client.socket_path))
        server.listen(1)
        server_error: list[BaseException] = []

        def serve() -> None:
            try:
                connection, _ = server.accept()
                with connection:
                    incoming = receive_json_frame(connection, max_frame_bytes=client.max_frame_bytes)
                    response = self.service.handle_request(incoming, peer_uid=os.geteuid())
                    if modifier is not None:
                        modifier(response)
                    send_json_frame(connection, response, max_frame_bytes=client.max_frame_bytes)
            except BaseException as exc:  # pragma: no cover - surfaced in the test thread join.
                server_error.append(exc)
            finally:
                server.close()

        thread = threading.Thread(target=serve)
        thread.start()
        command_record = request["commands"][0]
        command = AuthorizedTestCommand(
            argv=tuple(command_record["argv"]),
            executable_path=command_record["executable_path"],
            executable_digest=command_record["executable_digest"],
            command_digest=command_record["command_digest"],
        )
        try:
            with patch("shared.mesh_runtime.repo_patch_verifier._peer_uid", return_value=os.geteuid()):
                return client.verify(
                    workspace_id=str(request["workspace_id"]),
                    workspace_manifest=str(request["workspace_manifest_digest"]),
                    candidate_binding=dict(request["candidate_binding"]),
                    commands=(command,),
                    timeout_seconds=int(request["timeout_seconds"]),
                    output_limit_bytes=int(request["output_limit_bytes"]),
                )
        finally:
            thread.join(timeout=5)
            client.socket_path.unlink(missing_ok=True)
            if server_error:
                raise server_error[0]

    def _request(
        self,
        command: tuple[str, ...],
        *,
        marker: str = "valid",
        timeout_seconds: int = 30,
        output_limit_bytes: int = 64 * 1024,
    ) -> dict[str, Any]:
        workspace_id = "workspace_" + canonical_digest(marker).removeprefix("sha256:")
        workspace = self.input_root / workspace_id
        workspace.mkdir()
        (workspace / "app.py").write_text("bounded\n", encoding="utf-8")
        executable_identity = RepoPatchTestCommandPolicy((("python3", "-c", "pass"),)).authorize(
            ("python3 -c pass",)
        )[0]
        executable = AuthorizedTestCommand(
            argv=command,
            executable_path=executable_identity.executable_path,
            executable_digest=executable_identity.executable_digest,
            command_digest=canonical_digest(
                {
                    "argv": command,
                    "executable_path": executable_identity.executable_path,
                    "executable_digest": executable_identity.executable_digest,
                }
            ),
        )
        candidate_binding = {
            "base_commit": "a" * 40,
            "base_tree": "b" * 40,
            "target_path": "app.py",
            "target_preimage_digest": "sha256:" + ("c" * 64),
            "target_postimage_digest": "sha256:" + ("d" * 64),
            "authorized_diff_digest": "sha256:" + ("e" * 64),
        }
        unsigned: dict[str, Any] = {
            "schema_version": VERIFIER_REQUEST_VERSION,
            "state_slice": VERIFIER_PROTOCOL_STATE_SLICE,
            "job_id": "verifier_job_" + canonical_digest(marker + "-job").removeprefix("sha256:"),
            "workspace_id": workspace_id,
            "workspace_manifest_digest": workspace_manifest_digest(workspace),
            "candidate_binding": candidate_binding,
            "commands": [executable.to_dict()],
            "verifier_image_digest": IMAGE_DIGEST,
            "sandbox_profile_digest": SANDBOX_DIGEST,
            "timeout_seconds": timeout_seconds,
            "output_limit_bytes": output_limit_bytes,
        }
        return {**unsigned, "request_digest": canonical_digest(unsigned)}


def _deep_copy(value: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(value)


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
