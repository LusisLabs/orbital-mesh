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
from services.ingest.kubernetes_live_signal import (
    collect_kubernetes_signal,
    _configuration_drift_signals,
    _parse_memory_quantity,
    _resource_pressure_signals,
)
from services.ingest.service import IngestService
from services.pipeline import FirstSlicePipeline
from services.trigger.service import TriggerService
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

    def test_collect_kubernetes_signal_rejects_missing_kubectl(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "kubectl command not found"):
            collect_kubernetes_signal(
                deployment_name="semantic-search",
                namespace="search",
                kubectl_command="definitely-missing-kubectl-for-mesh",
            )

    def test_configuration_drift_labels_are_exposed_as_weak_signals(self) -> None:
        deployment = {
            "spec": {
                "template": {
                    "metadata": {
                        "labels": {
                            "app": "semantic-search",
                            "mesh.chaos.config_drift": "true",
                        }
                    }
                }
            }
        }

        signals = _configuration_drift_signals(deployment)

        self.assertEqual(
            signals,
            [{"field": "labels", "key": "mesh.chaos.config_drift", "value": "true"}],
        )

    def test_low_memory_limit_is_exposed_as_resource_pressure(self) -> None:
        deployment = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "semantic-search",
                                "resources": {"limits": {"memory": "8Mi"}},
                            }
                        ]
                    }
                }
            }
        }

        signals = _resource_pressure_signals(deployment)

        self.assertEqual(signals[0]["container"], "semantic-search")
        self.assertEqual(signals[0]["reason"], "memory_limit_too_low")
        self.assertEqual(signals[0]["limit_bytes"], 8 * 1024 * 1024)

    def test_memory_quantity_parser_handles_binary_and_decimal_units(self) -> None:
        self.assertEqual(_parse_memory_quantity("8Mi"), 8 * 1024 * 1024)
        self.assertEqual(_parse_memory_quantity("16M"), 16 * 1000 * 1000)
        self.assertIsNone(_parse_memory_quantity("not-a-quantity"))

    def test_scale_to_zero_signal_normalizes_without_trigger(self) -> None:
        signal = _raw_kubernetes_signal()
        signal["signal_id"] = "sig_k8s_scale_zero"
        signal["deployment"] = {
            **signal["deployment"],
            "rollout_status": "healthy",
            "desired_replicas": 0,
            "updated_replicas": 0,
            "available_replicas": 0,
        }
        signal["pods"] = []
        signal["events"] = [
            {
                "reason": "ScalingReplicaSet",
                "message": "Scaled down replica set semantic-search to 0 from 3",
                "count": 1,
                "type": "Normal",
            }
        ]
        signal["logs"] = []

        envelope = IngestService().normalize_signal(signal)
        self.assertEqual(envelope.payload["pods"], [])
        self.assertEqual(envelope.payload["deployment"]["desired_replicas"], 0)
        self.assertIsNone(TriggerService().detect(envelope))

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

            # SRE-grade policy: crash_loop with recent deploy → rollback
            # (deploy is the prior cause hypothesis). The previous
            # policy returned restart_deployment, which is what an
            # SRE would call "buying time without fixing anything."
            self.assertEqual(result["decision"]["decision_type"], "rollback_deployment")
            self.assertEqual(result["execution"]["status"], "succeeded")
            self.assertTrue(result["execution"]["external_refs"]["live_execution"])
            state = json.loads(Path(temp_dir, "fake-kubectl-state.json").read_text())
            # ``rollout undo`` is the kubectl op behind ``rollback_deployment``.
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
    # Stamp the fake event with a wall-clock-fresh timestamp. The live
    # signal collector's freshness filter drops events older than 5
    # minutes, so a hard-coded historical date would make the event
    # invisible and the decision engine would fall through to
    # ``escalate`` in this test. Real Kubernetes always populates
    # ``lastTimestamp`` on events; using ``now()`` here keeps the
    # fixture realistic regardless of when the test runs.
    #
    # Same reasoning for the deployment's ``Progressing`` condition
    # ``lastUpdateTime`` — the SRE-grade decision policy uses the age
    # of that timestamp to decide whether a crash is deploy-correlated
    # (within the 30-minute window). A historical date would make
    # every fake-kubectl test trigger ``escalate`` instead of
    # ``rollback_deployment``.
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    fresh_ts = now.isoformat().replace("+00:00", "Z")
    deploy_ts = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
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
                        "lastUpdateTime": deploy_ts,
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
                        "lastUpdateTime": deploy_ts,
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
                        "lastUpdateTime": deploy_ts,
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
                    "lastTimestamp": fresh_ts,
                }
            ]
        },
        "logs": {
            "semantic-search-abc": "ModuleNotFoundError: No module named search.semantic_query_parser"
        },
    }


def _raw_kubernetes_signal() -> dict:
    # Use a fresh deploy timestamp so the SRE-grade decision policy
    # treats this as deploy-correlated. Without it, the policy
    # correctly routes crash_loop signals to ``escalate`` (a sustained
    # crash loop with no recent deploy needs human investigation, not
    # a blind restart).
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    deploy_ts = (now - timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    return {
        "signal_type": "kubernetes_deployment_issue",
        "signal_id": "sig_k8s_live_001",
        "observed_at": now.isoformat().replace("+00:00", "Z"),
        "environment": "staging",
        "cluster": "k3d-mesh-e2e",
        "namespace": "search",
        "service": "semantic-search",
        "deployment": {
            "name": "semantic-search",
            "revision": "2",
            "image": "busybox:1.36",
            "rollout_started_at": deploy_ts,
            "rollout_status": "degraded",
            "desired_replicas": 3,
            "updated_replicas": 3,
            "available_replicas": 0,
            "last_deploy_timestamp": deploy_ts,
            "seconds_since_deploy": 120,
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
        "post_action_observations": {
            "30m": {
                "rollout_status": "healthy",
                "desired_replicas": 3,
                "ready_replicas": 3,
                "restart_delta": 0,
                "new_error_signatures": [],
                "measured_at": "2026-04-08T12:35:00Z",
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
