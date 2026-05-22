from __future__ import annotations

import unittest

from shared.mesh_runtime.centaur_deployment import verify_centaur_kubernetes_profile


class CentaurDeploymentProfileTests(unittest.TestCase):
    def test_kubernetes_profile_renders_as_disabled_mesh_owned_sandbox_profile(self) -> None:
        result = verify_centaur_kubernetes_profile("config/centaur-sandbox-runtime.k8s.yaml")

        self.assertEqual(result["status"], "pass")
        self.assertIn("Namespace", result["kinds"])
        self.assertIn("NetworkPolicy", result["kinds"])
        self.assertEqual(result["checks"]["deployment_disabled_by_default"], True)
        self.assertEqual(result["checks"]["default_deny_network_policy_present"], True)
        self.assertEqual(result["checks"]["live_execution_blocked_annotation_present"], True)
        self.assertEqual(result["checks"]["credential_proxy_sidecar_present"], True)
        self.assertEqual(result["checks"]["credential_proxy_placeholder_mode"], True)
        self.assertEqual(result["checks"]["credential_proxy_health_probe_present"], True)
        self.assertEqual(result["checks"]["real_adapter_image_configured"], True)
        self.assertEqual(result["checks"]["per_sandbox_labels_present"], True)
        self.assertEqual(result["checks"]["cleanup_policy_present"], True)


if __name__ == "__main__":
    unittest.main()
