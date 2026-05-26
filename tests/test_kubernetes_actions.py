"""Tests for the expanded KubernetesAdapter action catalog."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.actuators.service import KubernetesAdapter
from shared.mesh_runtime import RuntimeConfig


def _dry_config() -> RuntimeConfig:
    return RuntimeConfig(kubernetes_live_execution_enabled=False)


def _live_config(**overrides) -> RuntimeConfig:
    kwargs = dict(
        kubernetes_live_execution_enabled=True,
        kubernetes_allowed_contexts=("test-ctx",),
        kubernetes_allowed_namespaces=("prod", "staging"),
    )
    kwargs.update(overrides)
    return RuntimeConfig(**kwargs)


class RestartPodTests(unittest.TestCase):
    def test_dry_run_returns_synthetic_success(self):
        adapter = KubernetesAdapter(config=_dry_config())
        result = adapter.restart_pod({"pod_name": "web-abc", "namespace": "prod"})
        self.assertEqual(result["status"], "succeeded")
        self.assertIn("k8sdeletepod_prod_web-abc", result["external_refs"]["rollout_change_id"])

    def test_missing_pod_name_fails(self):
        adapter = KubernetesAdapter(config=_dry_config())
        result = adapter.restart_pod({"namespace": "prod"})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "missing_parameter")

    @patch("services.actuators.service.subprocess.run")
    def test_live_executes_kubectl_delete(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="pod deleted", stderr="")
        adapter = KubernetesAdapter(config=_live_config())
        result = adapter.restart_pod({
            "pod_name": "web-abc",
            "namespace": "prod",
            "kube_context": "test-ctx",
        })
        self.assertEqual(result["status"], "succeeded")
        called_cmd = mock_run.call_args[0][0]
        self.assertIn("delete", called_cmd)
        self.assertIn("pod", called_cmd)
        self.assertIn("web-abc", called_cmd)

    def test_live_rejects_unallowed_namespace(self):
        adapter = KubernetesAdapter(config=_live_config())
        result = adapter.restart_pod({
            "pod_name": "web-abc",
            "namespace": "restricted",
            "kube_context": "test-ctx",
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("allowed list", result["failure"]["detail"])

    def test_live_rejects_missing_explicit_context_allowlist(self):
        adapter = KubernetesAdapter(config=_live_config(kubernetes_allowed_contexts=()))
        result = adapter.restart_pod({
            "pod_name": "web-abc",
            "namespace": "prod",
            "kube_context": "test-ctx",
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("explicit context allowed list", result["failure"]["detail"])

    def test_live_rejects_missing_explicit_namespace_allowlist(self):
        adapter = KubernetesAdapter(config=_live_config(kubernetes_allowed_namespaces=()))
        result = adapter.restart_pod({
            "pod_name": "web-abc",
            "namespace": "prod",
            "kube_context": "test-ctx",
        })
        self.assertEqual(result["status"], "failed")
        self.assertIn("explicit namespace allowed list", result["failure"]["detail"])


class ScaleDeploymentTests(unittest.TestCase):
    def test_dry_run(self):
        adapter = KubernetesAdapter(config=_dry_config())
        result = adapter.scale_deployment({
            "deployment_name": "web-api",
            "namespace": "prod",
            "replicas": 5,
        })
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["external_refs"]["replicas"], 5)

    def test_missing_replicas_fails(self):
        adapter = KubernetesAdapter(config=_dry_config())
        result = adapter.scale_deployment({"deployment_name": "web-api"})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "missing_parameter")

    def test_negative_replicas_fails(self):
        adapter = KubernetesAdapter(config=_dry_config())
        result = adapter.scale_deployment({
            "deployment_name": "web-api",
            "replicas": -1,
        })
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "invalid_parameter")

    @patch("services.actuators.service.subprocess.run")
    def test_live_calls_kubectl_scale(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="scaled", stderr="")
        adapter = KubernetesAdapter(config=_live_config())
        result = adapter.scale_deployment({
            "deployment_name": "web-api",
            "namespace": "prod",
            "kube_context": "test-ctx",
            "replicas": 3,
        })
        self.assertEqual(result["status"], "succeeded")
        called_cmd = mock_run.call_args[0][0]
        self.assertIn("scale", called_cmd)
        self.assertIn("deployment/web-api", called_cmd)
        self.assertIn("--replicas=3", called_cmd)


class CordonNodeTests(unittest.TestCase):
    def test_dry_run(self):
        adapter = KubernetesAdapter(config=_dry_config())
        result = adapter.cordon_node({"node_name": "node-1"})
        self.assertEqual(result["status"], "succeeded")
        self.assertIn("k8scordon_node-1", result["external_refs"]["rollout_change_id"])

    def test_missing_node_name_fails(self):
        adapter = KubernetesAdapter(config=_dry_config())
        result = adapter.cordon_node({})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "missing_parameter")

    @patch("services.actuators.service.subprocess.run")
    def test_live_calls_kubectl_cordon(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="cordoned", stderr="")
        adapter = KubernetesAdapter(config=_live_config())
        result = adapter.cordon_node({"node_name": "node-1", "kube_context": "test-ctx"})
        self.assertEqual(result["status"], "succeeded")
        called_cmd = mock_run.call_args[0][0]
        self.assertIn("cordon", called_cmd)
        self.assertIn("node-1", called_cmd)

    def test_live_rejects_missing_explicit_context_allowlist(self):
        adapter = KubernetesAdapter(config=_live_config(kubernetes_allowed_contexts=()))
        result = adapter.cordon_node({"node_name": "node-1", "kube_context": "test-ctx"})
        self.assertEqual(result["status"], "failed")
        self.assertIn("explicit context allowed list", result["failure"]["detail"])


class DrainNodeTests(unittest.TestCase):
    def test_dry_run(self):
        adapter = KubernetesAdapter(config=_dry_config())
        result = adapter.drain_node({"node_name": "node-1"})
        self.assertEqual(result["status"], "succeeded")

    @patch("services.actuators.service.subprocess.run")
    def test_live_drain_includes_safety_flags(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="drained", stderr="")
        adapter = KubernetesAdapter(config=_live_config())
        result = adapter.drain_node({
            "node_name": "node-1",
            "kube_context": "test-ctx",
            "grace_period_seconds": 30,
        })
        self.assertEqual(result["status"], "succeeded")
        called_cmd = mock_run.call_args[0][0]
        self.assertIn("drain", called_cmd)
        self.assertIn("--ignore-daemonsets", called_cmd)
        self.assertIn("--delete-emptydir-data", called_cmd)
        self.assertIn("--grace-period=30", called_cmd)


if __name__ == "__main__":
    unittest.main()
