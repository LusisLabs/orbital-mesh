from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from services.actuators.service import KubernetesAdapter
from services.pipeline import FirstSlicePipeline
from shared.mesh_runtime import RuntimeConfig


class KubernetesLiveExecutionTests(unittest.TestCase):
    def test_restart_deployment_uses_live_kubectl(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path, fake_command = _write_fake_kubectl(Path(temp_dir))
            config = RuntimeConfig(
                kubernetes_live_execution_enabled=True,
                kubectl_command=fake_command,
                kubernetes_allowed_contexts=("k3d-mesh-e2e",),
                kubernetes_allowed_namespaces=("search",),
                kubernetes_rollout_timeout_seconds=5,
            )
            result = KubernetesAdapter(config=config).restart_deployment(
                {
                    "cluster": "mesh-e2e",
                    "kube_context": "k3d-mesh-e2e",
                    "namespace": "search",
                    "deployment_name": "semantic-search",
                }
            )

            state = json.loads(state_path.read_text())
            self.assertEqual(result["status"], "succeeded")
            self.assertTrue(result["external_refs"]["live_execution"])
            self.assertEqual(result["external_refs"]["kube_context"], "k3d-mesh-e2e")
            self.assertEqual(result["external_refs"]["deployment_name"], "semantic-search")
            self.assertEqual(state["actions"][0]["action"], "restart")
            self.assertEqual(state["actions"][1]["action"], "status")

    def test_live_execution_rejects_unallowed_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, fake_command = _write_fake_kubectl(Path(temp_dir))
            config = RuntimeConfig(
                kubernetes_live_execution_enabled=True,
                kubectl_command=fake_command,
                kubernetes_allowed_contexts=("k3d-mesh-e2e",),
                kubernetes_allowed_namespaces=("allowed-only",),
            )
            result = KubernetesAdapter(config=config).restart_deployment(
                {
                    "kube_context": "k3d-mesh-e2e",
                    "namespace": "search",
                    "deployment_name": "semantic-search",
                }
            )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failure"]["reason"], "kubernetes_live_execution_failed")
            self.assertIn("allowed list", result["failure"]["detail"])

    def test_collect_kubernetes_signal_emits_mesh_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            _, fake_command = _write_fake_kubectl(temp_path)
            output_path = temp_path / "signal.json"

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/collect_kubernetes_signal.py",
                    "--deployment",
                    "semantic-search",
                    "--namespace",
                    "search",
                    "--environment",
                    "staging",
                    "--kubectl-command",
                    fake_command,
                    "--repo-path",
                    "/workspace/search_service",
                    "--suspected-file",
                    "app/search.py",
                    "--allowed-path",
                    "app/search.py",
                    "--test-command",
                    "python3 -m unittest discover -s tests",
                    "--patch-target-file",
                    "app/search.py",
                    "--patch-find",
                    "PARSE_TIMEOUT_MS = 100",
                    "--patch-replace",
                    "PARSE_TIMEOUT_MS = 80",
                    "--output",
                    str(output_path),
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            signal = json.loads(output_path.read_text())
            self.assertEqual(signal["signal_type"], "kubernetes_deployment_issue")
            self.assertEqual(signal["cluster"], "k3d-mesh-e2e")
            self.assertEqual(signal["namespace"], "search")
            self.assertEqual(signal["deployment"]["name"], "semantic-search")
            self.assertEqual(signal["deployment"]["rollout_status"], "degraded")
            self.assertTrue(signal["logs"])
            self.assertEqual(signal["related_context"]["kube_context"], "k3d-mesh-e2e")
            self.assertTrue(signal["related_context"]["code_remediation_candidate"])
            self.assertEqual(signal["related_context"]["patch_template"]["target_file"], "app/search.py")

    def test_pipeline_uses_live_snapshot_for_kubernetes_feedback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            _, fake_command = _write_fake_kubectl(Path(temp_dir))
            config = RuntimeConfig(
                evaluation_mode="native",
                orchestration_mode="native",
                state_directory=temp_dir,
                kubernetes_live_execution_enabled=True,
                kubectl_command=fake_command,
                kubernetes_allowed_contexts=("k3d-mesh-e2e",),
                kubernetes_allowed_namespaces=("search",),
                kubernetes_rollout_timeout_seconds=5,
            )

            result = FirstSlicePipeline(config=config).run(_raw_kubernetes_signal(), scenario_name="live-k8s")

            self.assertEqual(result["decision"]["decision_type"], "rollback_deployment")
            self.assertEqual(result["execution"]["status"], "succeeded")
            self.assertTrue(result["execution"]["external_refs"]["live_execution"])
            state = json.loads(Path(temp_dir, "fake-kubectl-state.json").read_text())
            self.assertEqual(state["actions"][0]["action"], "undo")
            self.assertEqual(state["actions"][1]["action"], "status")
            self.assertEqual(result["feedback"]["outcome"], "successful")
            self.assertEqual(result["feedback"]["recommended_follow_up"], "record_rollout_recovery")


def _write_fake_kubectl(temp_path: Path) -> tuple[Path, str]:
    state_path = temp_path / "fake-kubectl-state.json"
    script_path = temp_path / "fake_kubectl.py"
    state_path.write_text(json.dumps(_fake_state(), indent=2) + "\n")
    script_path.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env python3
            from __future__ import annotations

            import json
            import os
            import sys
            from pathlib import Path

            state_path = Path(os.environ["FAKE_KUBECTL_STATE"])
            state = json.loads(state_path.read_text())
            args = sys.argv[1:]
            if args[:2] == ["--context", state["context"]]:
                args = args[2:]

            def save() -> None:
                state_path.write_text(json.dumps(state, indent=2) + "\\n")

            if args == ["config", "current-context"]:
                print(state["context"])
                raise SystemExit(0)

            if args[:3] == ["get", "deployment", "semantic-search"]:
                print(json.dumps(state["deployment"]))
                raise SystemExit(0)

            if args[:2] == ["get", "pods"]:
                print(json.dumps(state["pods"]))
                raise SystemExit(0)

            if args[:2] == ["get", "events"]:
                print(json.dumps(state["events"]))
                raise SystemExit(0)

            if args[:2] == ["rollout", "restart"]:
                state["actions"].append({"action": "restart", "args": args})
                state["deployment"] = state["after_restart"]
                save()
                print("deployment.apps/semantic-search restarted")
                raise SystemExit(0)

            if args[:2] == ["rollout", "undo"]:
                state["actions"].append({"action": "undo", "args": args})
                state["deployment"] = state["after_undo"]
                save()
                print("deployment.apps/semantic-search rolled back")
                raise SystemExit(0)

            if args[:2] == ["rollout", "status"]:
                state["actions"].append({"action": "status", "args": args})
                save()
                print('deployment "semantic-search" successfully rolled out')
                raise SystemExit(0)

            if args and args[0] == "logs":
                pod_name = args[1]
                print(state["logs"].get(pod_name, ""))
                raise SystemExit(0)

            print(f"unsupported fake kubectl args: {args}", file=sys.stderr)
            raise SystemExit(1)
            """
        )
    )
    script_path.chmod(0o755)
    os.environ["FAKE_KUBECTL_STATE"] = str(state_path)
    return state_path, f"{sys.executable} {script_path}"


def _fake_state() -> dict:
    return {
        "context": "k3d-mesh-e2e",
        "actions": [],
        "deployment": {
            "metadata": {
                "name": "semantic-search",
                "namespace": "search",
                "generation": 2,
                "creationTimestamp": "2026-04-08T12:00:00Z",
                "annotations": {"deployment.kubernetes.io/revision": "2"},
            },
            "spec": {
                "replicas": 3,
                "selector": {"matchLabels": {"app": "semantic-search"}},
                "template": {"spec": {"containers": [{"name": "semantic-search", "image": "busybox:1.36"}]}},
            },
            "status": {
                "observedGeneration": 2,
                "updatedReplicas": 3,
                "availableReplicas": 0,
                "unavailableReplicas": 3,
                "conditions": [
                    {
                        "type": "Progressing",
                        "status": "True",
                        "reason": "ReplicaSetUpdated",
                        "lastUpdateTime": "2026-04-08T12:01:00Z",
                    }
                ],
            },
        },
        "after_restart": {
            "metadata": {
                "name": "semantic-search",
                "namespace": "search",
                "generation": 3,
                "creationTimestamp": "2026-04-08T12:00:00Z",
                "annotations": {"deployment.kubernetes.io/revision": "2"},
            },
            "spec": {
                "replicas": 3,
                "selector": {"matchLabels": {"app": "semantic-search"}},
                "template": {"spec": {"containers": [{"name": "semantic-search", "image": "busybox:1.36"}]}},
            },
            "status": {
                "observedGeneration": 3,
                "updatedReplicas": 3,
                "availableReplicas": 3,
                "unavailableReplicas": 0,
                "conditions": [
                    {
                        "type": "Progressing",
                        "status": "True",
                        "reason": "NewReplicaSetAvailable",
                        "lastUpdateTime": "2026-04-08T12:03:00Z",
                    }
                ],
            },
        },
        "after_undo": {
            "metadata": {
                "name": "semantic-search",
                "namespace": "search",
                "generation": 4,
                "creationTimestamp": "2026-04-08T12:00:00Z",
                "annotations": {"deployment.kubernetes.io/revision": "1"},
            },
            "spec": {
                "replicas": 3,
                "selector": {"matchLabels": {"app": "semantic-search"}},
                "template": {"spec": {"containers": [{"name": "semantic-search", "image": "busybox:1.35"}]}},
            },
            "status": {
                "observedGeneration": 4,
                "updatedReplicas": 3,
                "availableReplicas": 3,
                "unavailableReplicas": 0,
                "conditions": [
                    {
                        "type": "Progressing",
                        "status": "True",
                        "reason": "NewReplicaSetAvailable",
                        "lastUpdateTime": "2026-04-08T12:04:00Z",
                    }
                ],
            },
        },
        "pods": {
            "items": [
                {
                    "metadata": {"name": "semantic-search-abc"},
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [
                            {
                                "name": "semantic-search",
                                "ready": False,
                                "restartCount": 4,
                                "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                                "lastState": {"terminated": {"reason": "Error"}},
                            }
                        ],
                    },
                },
                {
                    "metadata": {"name": "semantic-search-def"},
                    "status": {
                        "phase": "Running",
                        "containerStatuses": [
                            {
                                "name": "semantic-search",
                                "ready": True,
                                "restartCount": 0,
                                "state": {"running": {}},
                                "lastState": {},
                            }
                        ],
                    },
                },
            ]
        },
        "events": {
            "items": [
                {
                    "involvedObject": {"kind": "Pod", "name": "semantic-search-abc"},
                    "reason": "BackOff",
                    "message": "Back-off restarting failed container",
                    "count": 7,
                    "type": "Warning",
                }
            ]
        },
        "logs": {
            "semantic-search-abc": "ModuleNotFoundError: No module named search.semantic_query_parser"
        },
    }


def _raw_kubernetes_signal() -> dict:
    return {
        "signal_type": "kubernetes_deployment_issue",
        "signal_id": "sig_k8s_live_001",
        "observed_at": "2026-04-08T12:00:00Z",
        "environment": "staging",
        "cluster": "k3d-mesh-e2e",
        "namespace": "search",
        "service": "semantic-search",
        "deployment": {
            "name": "semantic-search",
            "revision": "2",
            "image": "busybox:1.36",
            "rollout_started_at": "2026-04-08T11:54:00Z",
            "rollout_status": "degraded",
            "desired_replicas": 3,
            "updated_replicas": 3,
            "available_replicas": 0,
        },
        "pods": [
            {
                "name": "semantic-search-abc",
                "phase": "Running",
                "ready": False,
                "restarts": 4,
                "container_status": "CrashLoopBackOff",
                "last_state_reason": "Error",
            }
        ],
        "events": [
            {
                "reason": "BackOff",
                "message": "Back-off restarting failed container",
                "count": 7,
                "type": "Warning",
            }
        ],
        "logs": [
            {
                "pod": "semantic-search-abc",
                "container": "semantic-search",
                "stream": "stderr",
                "message": "ModuleNotFoundError: No module named search.semantic_query_parser",
            }
        ],
        "related_context": {
            "active_incidents": 0,
            "similar_prior_cases": 0,
            "rollbacks_last_24h": 0,
            "cluster_access_available": True,
            "audit_logging_available": True,
            "kube_context": "k3d-mesh-e2e",
        },
        "post_action_observations": {},
    }


if __name__ == "__main__":
    unittest.main()
