from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.orchestrator.hsai_bridge_adapter import (
    HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2,
    RustEvidenceV2HsaiAdmissionAdapter,
    SubprocessHsaiAdmissionAdapter,
    build_hsai_admission_adapter,
)
from shared.mesh_runtime import RuntimeConfig


class HsaiAuthorityAdapterTests(unittest.TestCase):
    def test_ordinary_subprocess_adapter_cannot_be_authority_enabled(self) -> None:
        adapter = SubprocessHsaiAdmissionAdapter("python3 evidence_adapter.py")

        self.assertFalse(adapter.authority_eligible)
        self.assertEqual(adapter.adapter_identity, "mesh.hsai.subprocess_adapter.unpinned.v1")
        with self.assertRaises(TypeError):
            SubprocessHsaiAdmissionAdapter(
                "python3 evidence_adapter.py",
                authority_eligible=True,  # type: ignore[call-arg]
            )

    def test_pinned_absolute_executable_is_authority_eligible_with_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = _write_executable(Path(tmp) / "hsai-evidence-v2")
            second = _write_executable(Path(tmp) / "same-hsai-evidence-v2")
            pin = _sha256_pin(first)

            first_adapter = RustEvidenceV2HsaiAdmissionAdapter(
                f"{first} --current-policy-id mesh_policy://repo-patch/test",
                executable_sha256=pin,
            )
            second_adapter = RustEvidenceV2HsaiAdmissionAdapter(
                f"{second} --current-policy-id mesh_policy://repo-patch/test",
                executable_sha256=pin,
            )

            self.assertTrue(first_adapter.authority_eligible)
            self.assertEqual(first_adapter.authority_mode, HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2)
            self.assertEqual(first_adapter.adapter_identity, second_adapter.adapter_identity)
            self.assertIn(pin, first_adapter.adapter_identity)
            self.assertEqual(first_adapter.admit({"request": "bounded"}), {"decision": "allow"})

    def test_relative_executable_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "absolute path"):
            RustEvidenceV2HsaiAdmissionAdapter(
                "hsai-evidence-v2 --current-policy-id mesh_policy://repo-patch/test",
                executable_sha256="sha256:" + ("0" * 64),
            )

    def test_authority_command_requires_exact_current_policy_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = _write_executable(Path(tmp) / "hsai-evidence-v2")
            pin = _sha256_pin(executable)
            invalid_commands = (
                str(executable),
                f"{executable} evidence-v2",
                f"{executable} --current-policy-id",
                f"{executable} --current-policy-id ''",
                f"{executable} --current-policy-id policy extra",
            )
            for command in invalid_commands:
                with self.subTest(command=command):
                    with self.assertRaisesRegex(ValueError, "must be exactly"):
                        RustEvidenceV2HsaiAdmissionAdapter(
                            command,
                            executable_sha256=pin,
                        )

    def test_symlinked_executable_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = _write_executable(Path(tmp) / "hsai-evidence-v2")
            link = Path(tmp) / "hsai-link"
            link.symlink_to(executable)

            with self.assertRaisesRegex(RuntimeError, "must not be a symlink"):
                RustEvidenceV2HsaiAdmissionAdapter(
                    f"{link} --current-policy-id mesh_policy://repo-patch/test",
                    executable_sha256=_sha256_pin(executable),
                )

    def test_non_executable_regular_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = _write_executable(Path(tmp) / "hsai-evidence-v2")
            executable.chmod(0o600)

            with self.assertRaisesRegex(RuntimeError, "must be executable"):
                RustEvidenceV2HsaiAdmissionAdapter(
                    f"{executable} --current-policy-id mesh_policy://repo-patch/test",
                    executable_sha256=_sha256_pin(executable),
                )

    def test_pin_format_and_initial_mismatch_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = _write_executable(Path(tmp) / "hsai-evidence-v2")
            with self.assertRaisesRegex(ValueError, "sha256:<64 lowercase hex>"):
                RustEvidenceV2HsaiAdmissionAdapter(
                    f"{executable} --current-policy-id mesh_policy://repo-patch/test",
                    executable_sha256="A" * 64,
                )
            with self.assertRaisesRegex(RuntimeError, "pin mismatch"):
                RustEvidenceV2HsaiAdmissionAdapter(
                    f"{executable} --current-policy-id mesh_policy://repo-patch/test",
                    executable_sha256="sha256:" + ("0" * 64),
                )

    def test_executable_is_rehashed_before_every_admission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = _write_executable(Path(tmp) / "hsai-evidence-v2")
            adapter = RustEvidenceV2HsaiAdmissionAdapter(
                f"{executable} --current-policy-id mesh_policy://repo-patch/test",
                executable_sha256=_sha256_pin(executable),
            )
            executable.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
            executable.chmod(0o700)

            with patch("services.orchestrator.hsai_bridge_adapter.subprocess.run") as run:
                with self.assertRaisesRegex(RuntimeError, "pin mismatch"):
                    adapter.admit({"request": "must-not-run"})
                run.assert_not_called()

    def test_builder_requires_explicit_complete_authority_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executable = _write_executable(Path(tmp) / "hsai-evidence-v2")
            pin = _sha256_pin(executable)
            adapter = build_hsai_admission_adapter(
                RuntimeConfig(
                    hsai_admission_command=(
                        f"{executable} --current-policy-id mesh_policy://repo-patch/test"
                    ),
                    hsai_admission_authority_mode=HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2,
                    hsai_admission_executable_sha256=pin,
                )
            )
            self.assertIsInstance(adapter, RustEvidenceV2HsaiAdmissionAdapter)

            with self.assertRaisesRegex(ValueError, "requires an executable SHA-256 pin"):
                build_hsai_admission_adapter(
                    RuntimeConfig(
                        hsai_admission_command=str(executable),
                        hsai_admission_authority_mode=HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2,
                    )
                )
            with self.assertRaisesRegex(ValueError, "requires explicit Rust evidence-v2 authority mode"):
                build_hsai_admission_adapter(
                    RuntimeConfig(
                        hsai_admission_command=str(executable),
                        hsai_admission_executable_sha256=pin,
                    )
                )
            with self.assertRaisesRegex(ValueError, "unsupported HSAI admission authority mode"):
                build_hsai_admission_adapter(
                    RuntimeConfig(
                        hsai_admission_command=str(executable),
                        hsai_admission_authority_mode="unreviewed",
                        hsai_admission_executable_sha256=pin,
                    )
                )
            with self.assertRaisesRegex(ValueError, "require an admission command"):
                build_hsai_admission_adapter(
                    RuntimeConfig(
                        hsai_admission_authority_mode=HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2,
                        hsai_admission_executable_sha256=pin,
                    )
                )

    def test_runtime_config_loads_authority_mode_and_pin_from_environment(self) -> None:
        pin = "sha256:" + ("a" * 64)
        with patch.dict(
            "os.environ",
            {
                "MESH_HSAI_ADMISSION_COMMAND": (
                    "/opt/hsai/bin/hsai-evidence-v2 "
                    "--current-policy-id mesh_policy://repo-patch/test"
                ),
                "MESH_HSAI_ADMISSION_TIMEOUT_SECONDS": "17",
                "MESH_HSAI_ADMISSION_AUTHORITY_MODE": HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2,
                "MESH_HSAI_ADMISSION_EXECUTABLE_SHA256": pin,
            },
            clear=True,
        ):
            config = RuntimeConfig.from_env()

        self.assertEqual(
            config.hsai_admission_command,
            "/opt/hsai/bin/hsai-evidence-v2 --current-policy-id mesh_policy://repo-patch/test",
        )
        self.assertEqual(config.hsai_admission_timeout_seconds, 17)
        self.assertEqual(config.hsai_admission_authority_mode, HSAI_AUTHORITY_MODE_RUST_EVIDENCE_V2)
        self.assertEqual(config.hsai_admission_executable_sha256, pin)


def _write_executable(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "json.load(sys.stdin)\n"
        "json.dump({'decision': 'allow'}, sys.stdout)\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _sha256_pin(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
