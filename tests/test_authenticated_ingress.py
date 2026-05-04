from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class AuthenticatedIngressRehearsalTests(unittest.TestCase):
    def test_rehearsal_script_proves_operator_role_gates(self) -> None:
        result = subprocess.run(
            [sys.executable, "scripts/verify_authenticated_ingress.py", "--json"],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "mesh.authenticated_ingress_rehearsal.v1")
        self.assertEqual(payload["status"], "passed")
        checks = {check["name"]: check["status"] for check in payload["checks"]}
        for name in [
            "anonymous_run_creation_denied",
            "viewer_run_creation_denied",
            "viewer_policy_simulation_accepted",
            "launcher_run_creation_accepted",
            "launcher_run_inspectable",
            "launcher_approval_denied",
            "approver_approval_accepted",
            "launcher_kill_switch_denied",
            "admin_kill_switch_accepted",
        ]:
            self.assertEqual(checks.get(name), "pass", name)

    def test_authenticated_ingress_doc_records_proxy_trust_boundary(self) -> None:
        doc = (REPO_ROOT / "docs/authenticated-ingress.md").read_text(encoding="utf-8")

        for marker in [
            "MESH_OPERATOR_IDENTITY_REQUIRED=1",
            "X-Mesh-Operator",
            "X-Mesh-Roles",
            "strip",
            "authenticated TLS reverse proxy",
            "scripts/verify_authenticated_ingress.py",
        ]:
            self.assertIn(marker, doc)


if __name__ == "__main__":
    unittest.main()
