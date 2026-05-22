from __future__ import annotations

from pathlib import Path
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

    def test_kubernetes_overlays_keep_preview_and_prod_gated(self) -> None:
        local = Path("config/centaur-sandbox-runtime.local.k8s.yaml").read_text(encoding="utf-8")
        preview = Path("config/centaur-sandbox-runtime.preview.k8s.yaml").read_text(encoding="utf-8")
        prod = Path("config/centaur-sandbox-runtime.prod.k8s.yaml").read_text(encoding="utf-8")

        self.assertIn("mesh.lusis.io/environment: local", local)
        self.assertIn("replicas: 1", local)
        self.assertIn("local-only-after-credential-egress-proof", local)
        self.assertIn("replicas: 0", preview)
        self.assertIn("blocked-until-preview-credential-egress-proof", preview)
        self.assertIn("replicas: 0", prod)
        self.assertIn("blocked-until-prod-credential-egress-proof", prod)
        self.assertIn("release-thread-and-delete-sandbox", prod)


if __name__ == "__main__":
    unittest.main()
