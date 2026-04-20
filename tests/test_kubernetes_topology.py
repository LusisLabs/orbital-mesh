"""Tests for the Kubernetes topology collector (kubectl → InfraGraph)."""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from services.ingest.kubernetes_topology import collect_topology, _matches_selector


def _kubectl_mock_responses():
    """Build a mock response table keyed by the kubectl subcommand."""
    return {
        # Cluster-wide nodes
        "nodes": {
            "items": [
                {
                    "metadata": {"name": "node-1", "labels": {"zone": "us-east-1a"}},
                    "spec": {"unschedulable": False},
                    "status": {
                        "conditions": [{"type": "Ready", "status": "True"}],
                        "capacity": {"cpu": "4", "memory": "16Gi"},
                    },
                }
            ]
        },
        # Namespace list (for default filter)
        "namespaces": {"items": [{"metadata": {"name": "prod"}}]},
        # Per-namespace resources
        ("pods", "prod"): {
            "items": [
                {
                    "metadata": {
                        "name": "web-api-abc",
                        "namespace": "prod",
                        "labels": {"app": "web"},
                        "ownerReferences": [{"kind": "ReplicaSet", "name": "web-api-rs"}],
                    },
                    "spec": {
                        "nodeName": "node-1",
                        "containers": [
                            {"name": "app", "envFrom": [{"configMapRef": {"name": "web-config"}}]}
                        ],
                        "volumes": [{"name": "secret-vol", "secret": {"secretName": "api-token"}}],
                    },
                    "status": {"phase": "Running", "podIP": "10.0.0.5"},
                }
            ]
        },
        ("deployments", "prod"): {
            "items": [
                {
                    "metadata": {"name": "web-api", "namespace": "prod", "labels": {"app": "web"}},
                    "spec": {
                        "replicas": 2,
                        "selector": {"matchLabels": {"app": "web"}},
                        "template": {"spec": {"containers": [{"image": "registry/web:1.0"}]}},
                    },
                    "status": {"readyReplicas": 2},
                }
            ]
        },
        ("statefulsets", "prod"): {"items": []},
        ("daemonsets", "prod"): {"items": []},
        ("services", "prod"): {
            "items": [
                {
                    "metadata": {"name": "web", "namespace": "prod"},
                    "spec": {
                        "selector": {"app": "web"},
                        "type": "ClusterIP",
                        "clusterIP": "10.10.10.1",
                        "ports": [{"port": 80}],
                    },
                }
            ]
        },
        ("ingresses", "prod"): {
            "items": [
                {
                    "metadata": {"name": "web-ingress", "namespace": "prod"},
                    "spec": {
                        "rules": [
                            {
                                "host": "app.example.com",
                                "http": {
                                    "paths": [{"backend": {"service": {"name": "web"}}}]
                                },
                            }
                        ]
                    },
                }
            ]
        },
        ("configmaps", "prod"): {
            "items": [
                {"metadata": {"name": "web-config", "namespace": "prod"}}
            ]
        },
        ("secrets", "prod"): {
            "items": [
                {"metadata": {"name": "api-token", "namespace": "prod"}, "type": "Opaque"}
            ]
        },
    }


def _build_mock_subprocess_run(responses: dict):
    def _fake_run(command, **kwargs):
        # Identify which resource we're asking for
        if "nodes" in command and "get" in command:
            payload = responses["nodes"]
        elif "namespaces" in command and "get" in command:
            payload = responses["namespaces"]
        else:
            # Resource + namespace pair
            try:
                idx = command.index("-n")
                resource = command[idx - 1]
                namespace = command[idx + 1]
                payload = responses.get((resource, namespace), {"items": []})
            except ValueError:
                payload = {"items": []}
        completed = MagicMock()
        completed.returncode = 0
        completed.stdout = json.dumps(payload)
        completed.stderr = ""
        return completed
    return _fake_run


class TopologyCollectorTests(unittest.TestCase):
    @patch("services.ingest.kubernetes_topology.shutil.which", return_value="/usr/bin/kubectl")
    @patch("services.ingest.kubernetes_topology.subprocess.run")
    def test_collects_full_topology(self, mock_run, _mock_which):
        responses = _kubectl_mock_responses()
        mock_run.side_effect = _build_mock_subprocess_run(responses)

        nodes, edges = collect_topology()

        # Node kinds we should see
        kinds = {n.kind for n in nodes}
        self.assertIn("namespace", kinds)
        self.assertIn("node", kinds)
        self.assertIn("pod", kinds)
        self.assertIn("deployment", kinds)
        self.assertIn("service", kinds)
        self.assertIn("ingress", kinds)
        self.assertIn("configmap", kinds)
        self.assertIn("secret", kinds)

        # Critical edges
        edge_kinds = {e.kind for e in edges}
        self.assertIn("routes_to", edge_kinds)  # ingress → service
        self.assertIn("selects", edge_kinds)    # service → pod
        self.assertIn("exposes", edge_kinds)    # service → deployment
        self.assertIn("owns", edge_kinds)       # deployment → pod
        self.assertIn("scheduled_on", edge_kinds)  # pod → node
        self.assertIn("mounts", edge_kinds)     # pod → configmap/secret

    @patch("services.ingest.kubernetes_topology.shutil.which", return_value="/usr/bin/kubectl")
    @patch("services.ingest.kubernetes_topology.subprocess.run")
    def test_deployment_owns_its_pods(self, mock_run, _mock_which):
        responses = _kubectl_mock_responses()
        mock_run.side_effect = _build_mock_subprocess_run(responses)

        nodes, edges = collect_topology()
        owns_edges = [e for e in edges if e.kind == "owns"]
        # deployment web-api → pod web-api-abc
        self.assertTrue(any(
            "deployment:prod:web-api" in e.source and "pod:prod:web-api-abc" in e.target
            for e in owns_edges
        ))

    @patch("services.ingest.kubernetes_topology.shutil.which", return_value="/usr/bin/kubectl")
    @patch("services.ingest.kubernetes_topology.subprocess.run")
    def test_service_exposes_deployment_via_label_match(self, mock_run, _mock_which):
        responses = _kubectl_mock_responses()
        mock_run.side_effect = _build_mock_subprocess_run(responses)

        nodes, edges = collect_topology()
        exposes = [e for e in edges if e.kind == "exposes"]
        self.assertTrue(any(
            "service:prod:web" in e.source and "deployment:prod:web-api" in e.target
            for e in exposes
        ))

    @patch("services.ingest.kubernetes_topology.shutil.which", return_value="/usr/bin/kubectl")
    @patch("services.ingest.kubernetes_topology.subprocess.run")
    def test_pod_mounts_configmap_and_secret(self, mock_run, _mock_which):
        responses = _kubectl_mock_responses()
        mock_run.side_effect = _build_mock_subprocess_run(responses)

        nodes, edges = collect_topology()
        mounts = [e for e in edges if e.kind == "mounts"]
        # Pod mounts both configmap (envFrom) and secret (volume)
        targets = {e.target for e in mounts}
        self.assertIn("configmap:prod:web-config", targets)
        self.assertIn("secret:prod:api-token", targets)


class SelectorMatchTests(unittest.TestCase):
    def test_exact_match(self):
        self.assertTrue(_matches_selector({"app": "web"}, {"app": "web", "tier": "frontend"}))

    def test_no_match(self):
        self.assertFalse(_matches_selector({"app": "web"}, {"app": "api"}))

    def test_empty_selector_does_not_match(self):
        self.assertFalse(_matches_selector({}, {"app": "web"}))


if __name__ == "__main__":
    unittest.main()
