from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.watcher_ownership import build_watcher_ownership_packet


class WatcherOwnershipTests(unittest.TestCase):
    def test_watcher_ownership_resolves_targets_from_ownership_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path = Path(tmp) / "ownership.registry.json"
            registry_path.write_text(json.dumps(_registry()), encoding="utf-8")
            packet = build_watcher_ownership_packet(
                registry_path=str(registry_path),
                default_environment="production",
                watcher_status={
                    "watchers": [
                        {
                            "name": "legacy-k8s",
                            "signal_source": "kubernetes",
                            "interval_seconds": 60,
                            "running": False,
                            "detail": {
                                "targets": [
                                    {
                                        "deployment_name": "semantic-search",
                                        "namespace": "search",
                                        "kube_context": "mesh-compose",
                                    }
                                ]
                            },
                        }
                    ]
                },
            )

        self.assertEqual(packet["schema_version"], "mesh.watcher_ownership.v1")
        self.assertEqual(packet["status"], "complete")
        self.assertEqual(packet["unresolved_watchers"], [])
        watcher = packet["watchers"][0]
        self.assertEqual(watcher["owner"]["owner_id"], "platform.search")
        self.assertEqual(watcher["resolved_target_count"], 1)
        target = watcher["targets"][0]
        self.assertTrue(target["resolved"])
        self.assertEqual(target["record_id"], "own_semantic_search_pilot")
        self.assertEqual(target["tenant_id"], "tenant_a")
        self.assertEqual(target["customer_boundary"], "single_customer")
        self.assertIn("rollback_deployment", target["allowed_action_classes"])

    def test_watcher_without_targets_is_blocked(self) -> None:
        packet = build_watcher_ownership_packet(
            registry_path=None,
            default_environment="production",
            watcher_status={
                "watchers": [
                    {
                        "name": "unowned",
                        "signal_source": "kubernetes",
                        "interval_seconds": 60,
                        "running": False,
                        "detail": {},
                    }
                ]
            },
        )

        self.assertEqual(packet["status"], "blocked")
        self.assertEqual(packet["unresolved_watchers"], ["unowned"])
        self.assertEqual(packet["watchers"][0]["blockers"], ["watcher_targets_missing"])


def _registry() -> dict:
    return {
        "version": "ownership.registry.v1",
        "records": [
            {
                "record_id": "own_semantic_search_pilot",
                "service": "semantic-search",
                "environment": "production",
                "namespace": "search",
                "tenant_id": "tenant_a",
                "customer_id": "design_partner_a",
                "customer_boundary": "single_customer",
                "owner": {
                    "owner_id": "platform.search",
                    "display_name": "Search Platform",
                    "source_refs": ["registry://owners/platform.search"],
                },
                "approver_roles": ["approver", "admin"],
                "rollback_authority": {
                    "role": "approver",
                    "source_refs": ["policy://rollback/deployment"],
                },
                "escalation_route": "pager://platform/search",
                "allowed_action_classes": ["rollback_deployment"],
                "policy_refs": ["policies/rollback.policy.json"],
                "data_boundary": {
                    "classification": "operational",
                    "export_allowed": True,
                    "retention_days": 30,
                    "reservoir_refs": ["reservoir://tenant_a/search-runtime"],
                    "export_policy": {
                        "allowed": True,
                        "allowed_destinations": ["audit_archive"],
                        "redaction_required": True,
                    },
                    "legal_action_scope": {
                        "allowed": False,
                        "review_required": True,
                        "authority_ref": "policy://legal/no-production-action-without-counsel-review",
                    },
                },
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
