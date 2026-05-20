from __future__ import annotations

import unittest

from services.delivery.github_read_model import (
    GitHubDeliveryReadModel,
    UnsupportedGitHubDeliveryEvent,
    graph_fragment_from_github_event,
    supported_capabilities,
)


class GitHubDeliveryReadModelTests(unittest.TestCase):
    def test_pull_request_maps_to_repository_pr_and_commit_nodes(self) -> None:
        fragment = graph_fragment_from_github_event(
            "pull_request",
            {
                "action": "opened",
                "repository": _repository(),
                "pull_request": {
                    "number": 17,
                    "state": "open",
                    "title": "Patch checkout cache",
                    "head": {"ref": "fix-cache", "sha": "abc123"},
                    "base": {"ref": "main"},
                    "html_url": "https://github.com/LusisLabs/mesh/pull/17",
                },
            },
        )

        self.assertEqual(_node_kinds(fragment), {"GitHubRepository", "GitHubPullRequest", "GitHubCommit"})
        self.assertIn("references_commit", _edge_kinds(fragment))
        self.assertTrue(_all_read_only(fragment))

    def test_commit_maps_to_repository_and_commit_nodes(self) -> None:
        fragment = graph_fragment_from_github_event(
            "commit",
            {
                "repository": _repository(),
                "head_commit": {
                    "id": "def456",
                    "message": "Wire delivery context",
                    "author": {"name": "A. Dev"},
                    "timestamp": "2026-05-18T12:00:00Z",
                },
            },
        )

        self.assertEqual(_node_kinds(fragment), {"GitHubRepository", "GitHubCommit"})
        self.assertIn("repository_has_delivery_event", _edge_kinds(fragment))
        self.assertTrue(_all_read_only(fragment))

    def test_check_suite_maps_to_repository_suite_and_commit_nodes(self) -> None:
        fragment = graph_fragment_from_github_event(
            "check_suite",
            {
                "action": "completed",
                "repository": _repository(),
                "check_suite": {
                    "id": 91,
                    "status": "completed",
                    "conclusion": "success",
                    "head_branch": "main",
                    "head_sha": "feedface",
                    "html_url": "https://github.com/LusisLabs/mesh/actions/runs/91",
                },
            },
        )

        self.assertEqual(_node_kinds(fragment), {"GitHubRepository", "GitHubCheckSuite", "GitHubCommit"})
        self.assertIn("validates_commit", _edge_kinds(fragment))
        self.assertTrue(_all_read_only(fragment))

    def test_workflow_run_maps_to_repository_run_and_commit_nodes(self) -> None:
        fragment = graph_fragment_from_github_event(
            "workflow_run",
            {
                "action": "completed",
                "repository": _repository(),
                "workflow_run": {
                    "id": 301,
                    "workflow_id": 44,
                    "name": "CI",
                    "event": "pull_request",
                    "status": "completed",
                    "conclusion": "failure",
                    "head_branch": "fix-cache",
                    "head_sha": "badc0de",
                    "html_url": "https://github.com/LusisLabs/mesh/actions/runs/301",
                },
            },
        )

        self.assertEqual(_node_kinds(fragment), {"GitHubRepository", "GitHubWorkflowRun", "GitHubCommit"})
        self.assertIn("validates_commit", _edge_kinds(fragment))
        self.assertTrue(_all_read_only(fragment))

    def test_deployment_status_maps_to_repository_deployment_event_and_commit_nodes(self) -> None:
        fragment = graph_fragment_from_github_event(
            "deployment_status",
            {
                "action": "created",
                "repository": _repository(),
                "deployment": {
                    "id": 707,
                    "environment": "production",
                    "ref": "main",
                    "sha": "c001d00d",
                },
                "deployment_status": {
                    "id": 808,
                    "state": "success",
                    "description": "deployed",
                    "target_url": "https://deployments.example/707",
                },
            },
        )

        self.assertEqual(_node_kinds(fragment), {"GitHubRepository", "DeploymentEvent", "GitHubCommit"})
        self.assertIn("deploys_commit", _edge_kinds(fragment))
        self.assertTrue(_all_read_only(fragment))

    def test_capabilities_are_read_only_and_do_not_expose_mutation_operations(self) -> None:
        capabilities = supported_capabilities()
        self.assertEqual(
            {capability["event_type"] for capability in capabilities},
            set(GitHubDeliveryReadModel().supported_event_types()),
        )
        for capability in capabilities:
            self.assertIs(capability["read_only"], True)
            self.assertEqual(capability["provider"], "github")
            forbidden = {"create", "update", "delete", "merge", "rerun", "cancel", "approve", "deploy"}
            self.assertTrue(forbidden.isdisjoint(set(capability.get("operations", ()))))

    def test_unsupported_event_fails_closed(self) -> None:
        with self.assertRaises(UnsupportedGitHubDeliveryEvent):
            graph_fragment_from_github_event("pull_request_review", {"repository": _repository()})


def _repository() -> dict[str, object]:
    return {
        "full_name": "LusisLabs/mesh",
        "default_branch": "main",
        "private": True,
        "html_url": "https://github.com/LusisLabs/mesh",
    }


def _node_kinds(fragment: dict[str, object]) -> set[str]:
    return {str(node["kind"]) for node in fragment["nodes"]}  # type: ignore[index]


def _edge_kinds(fragment: dict[str, object]) -> set[str]:
    return {str(edge["kind"]) for edge in fragment["edges"]}  # type: ignore[index]


def _all_read_only(fragment: dict[str, object]) -> bool:
    nodes = fragment["nodes"]  # type: ignore[index]
    edges = fragment["edges"]  # type: ignore[index]
    return bool(fragment["read_only"]) and all(node["read_only"] for node in nodes) and all(edge["read_only"] for edge in edges)


if __name__ == "__main__":
    unittest.main()
