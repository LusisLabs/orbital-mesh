from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from services.actuators.repo_patch_verifier_service import RepoPatchVerifierService
from shared.mesh_runtime.repo_patch_test_policy import AuthorizedTestCommand, RepoPatchTestCommandPolicy
from shared.mesh_runtime.repo_patch_verifier import (
    VERIFIER_PROTOCOL_STATE_SLICE,
    VERIFIER_REQUEST_VERSION,
    canonical_digest,
    workspace_manifest_digest,
)


IMAGE_DIGEST = "sha256:" + ("a" * 64)
SANDBOX_DIGEST = "sha256:" + ("b" * 64)


class RepoPatchIsolatedVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name).resolve()
        self.input_root = self.root / "input"
        self.input_root.mkdir()
        self.service = RepoPatchVerifierService(
            self.root / "socket" / "verifier.sock",
            self.input_root,
            self.root / "scratch",
            self.root / "ledger",
            allowed_authority_uids={os.geteuid()},
            runner_uid=os.geteuid(),
            runner_gid=os.getegid(),
            verifier_image_digest=IMAGE_DIGEST,
            sandbox_profile_digest=SANDBOX_DIGEST,
            require_identity_separation=False,
        )
        (self.root / "scratch").mkdir()
        (self.root / "ledger").mkdir()

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

    def test_wrong_peer_and_request_tamper_fail_closed(self) -> None:
        request = self._request(("python3", "-c", "pass"))
        wrong_peer = self.service.handle_request(request, peer_uid=os.geteuid() + 1)
        self.assertEqual(wrong_peer["code"], "authority_peer_rejected")

        request["timeout_seconds"] = 29
        tampered = self.service.handle_request(request, peer_uid=os.geteuid())
        self.assertEqual(tampered["code"], "request_contract_rejected")

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

        self.service._recover_interrupted_jobs()
        recovered = self.service.handle_request(request, peer_uid=os.geteuid())

        self.assertEqual(recovered["status"], "rejected")
        self.assertEqual(recovered["code"], "aborted_by_worker_restart")

    def test_worker_restart_preserves_existing_terminal_receipt(self) -> None:
        request = self._request(("python3", "-c", "pass"), marker="terminal-restart")
        terminal = self.service.handle_request(request, peer_uid=os.geteuid())
        self.service._create_running_record(self.service._running_path(request["job_id"]), request)

        self.service._recover_interrupted_jobs()
        recovered = self.service.handle_request(request, peer_uid=os.geteuid())

        self.assertEqual(recovered, terminal)
        self.assertEqual(recovered["status"], "succeeded")

    def _request(
        self,
        command: tuple[str, ...],
        *,
        marker: str = "valid",
        timeout_seconds: int = 30,
        output_limit_bytes: int = 64 * 1024,
    ) -> dict[str, object]:
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
        unsigned: dict[str, object] = {
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


if __name__ == "__main__":
    unittest.main()
