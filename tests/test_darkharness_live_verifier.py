from __future__ import annotations

import errno
import tempfile
import unittest
from pathlib import Path

from scripts.verify_darkharness_live_packet import verify_darkharness_live_packet


class DarkharnessLiveVerifierTests(unittest.TestCase):
    def test_live_verifier_proves_real_run_endpoints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                result = verify_darkharness_live_packet(state_directory=Path(tmp))
            except PermissionError as exc:
                if exc.errno == errno.EPERM:
                    self.skipTest("localhost socket binding is blocked in this sandbox")
                raise

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["go_no_go"]["status"], "go")
        self.assertEqual(result["go_no_go"]["missing_evidence"], [])
        self.assertIn("/api/darkharness/pilot-packet", result["endpoint_proofs"])
        self.assertEqual(result["endpoint_proofs"]["/api/darkharness/pilot-packet"]["run_export_count"], 5)
        self.assertTrue(result["run_ids"]["allowed"].startswith("run_"))
        self.assertTrue(result["run_ids"]["denied"].startswith("run_"))
        self.assertEqual(result["boundaries"]["raw_reservoir_egress"], "deny")
        self.assertTrue(result["boundaries"]["production_actions_approval_required"])
        implemented = set(result["claim_boundary"]["implemented"])
        self.assertIn("multi_run_checkpoint_export", implemented)
        self.assertIn("allowed_action_proof", implemented)
        self.assertIn("denied_action_proof", implemented)
        self.assertIn("rollback_drill_proof", implemented)


if __name__ == "__main__":
    unittest.main()
