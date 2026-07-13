from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from shared.mesh_runtime.repo_patch_test_policy import (
    RepoPatchTestCommandPolicy,
    validate_authorized_test_commands,
)


class RepoPatchTestCommandPolicyTests(unittest.TestCase):
    def test_exact_policy_command_is_bound_to_executable_digest(self) -> None:
        policy = RepoPatchTestCommandPolicy([["python3", "-m", "unittest", "tests.test_contracts"]])

        authorized = policy.authorize(["python3 -m unittest tests.test_contracts"])

        self.assertEqual(len(authorized), 1)
        self.assertEqual(authorized[0].argv, ("python3", "-m", "unittest", "tests.test_contracts"))
        self.assertTrue(authorized[0].executable_path.startswith("/"))
        self.assertRegex(authorized[0].executable_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertRegex(authorized[0].command_digest, r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(validate_authorized_test_commands([authorized[0].to_dict()], policy), authorized)

    def test_argument_extension_is_rejected(self) -> None:
        policy = RepoPatchTestCommandPolicy([["python3", "-m", "unittest", "tests.test_contracts"]])

        with self.assertRaisesRegex(ValueError, "not policy-authorized"):
            policy.authorize(["python3 -m unittest tests.test_contracts tests.test_loop_behaviors"])

    def test_shell_syntax_is_rejected_before_matching(self) -> None:
        policy = RepoPatchTestCommandPolicy([["python3", "-m", "unittest"]])

        with self.assertRaisesRegex(ValueError, "shell syntax"):
            policy.authorize(["python3 -m unittest && touch escaped"])

    def test_missing_policy_fails_closed_for_mutable_authority(self) -> None:
        policy = RepoPatchTestCommandPolicy([])

        with self.assertRaisesRegex(ValueError, "at least one"):
            policy.authorize([])
        with self.assertRaisesRegex(ValueError, "not policy-authorized"):
            policy.authorize(["python3 -m unittest"])

    def test_environment_contract_requires_argv_arrays(self) -> None:
        with patch.dict(os.environ, {"MESH_REPO_PATCH_ALLOWED_TEST_COMMANDS_JSON": json.dumps(["python3 -m unittest"])}):
            with self.assertRaisesRegex(ValueError, "array of argv arrays"):
                RepoPatchTestCommandPolicy.from_environment()

    def test_record_drift_is_rejected(self) -> None:
        policy = RepoPatchTestCommandPolicy([["python3", "-m", "unittest", "tests.test_contracts"]])
        record = policy.authorize(["python3 -m unittest tests.test_contracts"])[0].to_dict()
        record["executable_digest"] = "sha256:" + ("0" * 64)

        with self.assertRaisesRegex(ValueError, "drifted"):
            validate_authorized_test_commands([record], policy)


if __name__ == "__main__":
    unittest.main()
