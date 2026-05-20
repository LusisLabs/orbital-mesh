"""Read-only GitHub delivery event read model.

State slice: github-delivery-read-model.
"""

from __future__ import annotations

from copy import deepcopy
from importlib import import_module
from typing import Any


SUPPORTED_EVENT_TYPES = (
    "pull_request",
    "commit",
    "check_suite",
    "workflow_run",
    "deployment_status",
)

GITHUB_DELIVERY_CAPABILITIES: tuple[dict[str, Any], ...] = tuple(
    {
        "name": f"github_delivery_{event_type}",
        "event_type": event_type,
        "provider": "github",
        "read_only": True,
        "operations": ("normalize_event", "build_graph_fragment"),
    }
    for event_type in SUPPORTED_EVENT_TYPES
)


class UnsupportedGitHubDeliveryEvent(ValueError):
    """Raised when a GitHub delivery event type is outside this read model."""


class GitHubDeliveryReadModel:
    """Normalize GitHub delivery webhooks into graph node/edge fragments."""

    provider = "github"
    read_only = True

    def supported_event_types(self) -> tuple[str, ...]:
        return SUPPORTED_EVENT_TYPES

    def supported_capabilities(self) -> tuple[dict[str, Any], ...]:
        return supported_capabilities()

    def graph_fragment(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        return graph_fragment_from_github_event(event_type, payload)


def supported_capabilities() -> tuple[dict[str, Any], ...]:
    """Return defensive copies of the read-only capability metadata."""
    return tuple(deepcopy(capability) for capability in GITHUB_DELIVERY_CAPABILITIES)


def graph_fragment_from_github_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized graph fragment for one GitHub delivery payload."""
    normalized_event_type = _normalize_event_type(event_type)
    if normalized_event_type == "pull_request":
        fragment = _pull_request_fragment(payload)
    elif normalized_event_type == "commit":
        fragment = _commit_fragment(payload)
    elif normalized_event_type == "check_suite":
        fragment = _check_suite_fragment(payload)
    elif normalized_event_type == "workflow_run":
        fragment = _workflow_run_fragment(payload)
    elif normalized_event_type == "deployment_status":
        fragment = _deployment_status_fragment(payload)
    else:
        raise UnsupportedGitHubDeliveryEvent(f"unsupported GitHub delivery event: {event_type}")
    return _maybe_worker_a_fragment(fragment)


def _normalize_event_type(event_type: str) -> str:
    value = str(event_type or "").strip().lower().replace("-", "_")
    aliases = {
        "pullrequest": "pull_request",
        "pr": "pull_request",
        "push": "commit",
        "check_suite_event": "check_suite",
        "workflow_run_event": "workflow_run",
        "deployment": "deployment_status",
        "deployment_status_event": "deployment_status",
    }
    return aliases.get(value, value)


def _pull_request_fragment(payload: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_full_name(payload)
    pull_request = _required_mapping(payload, "pull_request")
    number = _required_value(pull_request, "number")
    pr_id = f"github_pull_request:{repo}#{number}"
    repo_id = _repo_id(repo)
    head = pull_request.get("head") if isinstance(pull_request.get("head"), dict) else {}
    base = pull_request.get("base") if isinstance(pull_request.get("base"), dict) else {}
    head_sha = _string_or_none(head.get("sha"))

    nodes = [
        _repo_node(repo, payload),
        _node(
            pr_id,
            "GitHubPullRequest",
            "pull_request",
            {
                "repository": repo,
                "number": number,
                "action": payload.get("action"),
                "state": pull_request.get("state"),
                "title": pull_request.get("title"),
                "merged": pull_request.get("merged"),
                "head_ref": head.get("ref"),
                "head_sha": head_sha,
                "base_ref": base.get("ref"),
                "url": pull_request.get("html_url") or pull_request.get("url"),
            },
        ),
    ]
    edges = [_edge(repo_id, pr_id, "repository_has_delivery_event", "pull_request")]
    if head_sha:
        commit_id = _commit_id(repo, head_sha)
        nodes.append(_commit_node(repo, {"sha": head_sha}, "pull_request"))
        edges.append(_edge(pr_id, commit_id, "references_commit", "pull_request"))
    return _fragment("pull_request", nodes, edges)


def _commit_fragment(payload: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_full_name(payload)
    repo_id = _repo_id(repo)
    commits = _commit_payloads(payload)
    if not commits:
        raise ValueError("commit event requires a commit, head_commit, or commits payload")

    nodes = [_repo_node(repo, payload)]
    edges = []
    for commit in commits:
        sha = _commit_sha(commit)
        node = _commit_node(repo, commit, "commit")
        nodes.append(node)
        edges.append(_edge(repo_id, _commit_id(repo, sha), "repository_has_delivery_event", "commit"))
    return _fragment("commit", _dedupe_nodes(nodes), edges)


def _check_suite_fragment(payload: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_full_name(payload)
    suite = _required_mapping(payload, "check_suite")
    suite_id = _required_value(suite, "id")
    suite_node_id = f"github_check_suite:{repo}:{suite_id}"
    repo_id = _repo_id(repo)
    head_sha = _string_or_none(suite.get("head_sha"))

    nodes = [
        _repo_node(repo, payload),
        _node(
            suite_node_id,
            "GitHubCheckSuite",
            "check_suite",
            {
                "repository": repo,
                "suite_id": suite_id,
                "action": payload.get("action"),
                "status": suite.get("status"),
                "conclusion": suite.get("conclusion"),
                "head_branch": suite.get("head_branch"),
                "head_sha": head_sha,
                "url": suite.get("html_url") or suite.get("url"),
            },
        ),
    ]
    edges = [_edge(repo_id, suite_node_id, "repository_has_delivery_event", "check_suite")]
    if head_sha:
        commit_id = _commit_id(repo, head_sha)
        nodes.append(_commit_node(repo, {"sha": head_sha}, "check_suite"))
        edges.append(_edge(suite_node_id, commit_id, "validates_commit", "check_suite"))
    return _fragment("check_suite", nodes, edges)


def _workflow_run_fragment(payload: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_full_name(payload)
    run = _required_mapping(payload, "workflow_run")
    run_id = _required_value(run, "id")
    run_node_id = f"github_workflow_run:{repo}:{run_id}"
    repo_id = _repo_id(repo)
    head_sha = _string_or_none(run.get("head_sha"))

    nodes = [
        _repo_node(repo, payload),
        _node(
            run_node_id,
            "GitHubWorkflowRun",
            "workflow_run",
            {
                "repository": repo,
                "run_id": run_id,
                "workflow_id": run.get("workflow_id"),
                "name": run.get("name"),
                "action": payload.get("action"),
                "event": run.get("event"),
                "status": run.get("status"),
                "conclusion": run.get("conclusion"),
                "head_branch": run.get("head_branch"),
                "head_sha": head_sha,
                "url": run.get("html_url") or run.get("url"),
            },
        ),
    ]
    edges = [_edge(repo_id, run_node_id, "repository_has_delivery_event", "workflow_run")]
    if head_sha:
        commit_id = _commit_id(repo, head_sha)
        nodes.append(_commit_node(repo, {"sha": head_sha}, "workflow_run"))
        edges.append(_edge(run_node_id, commit_id, "validates_commit", "workflow_run"))
    return _fragment("workflow_run", nodes, edges)


def _deployment_status_fragment(payload: dict[str, Any]) -> dict[str, Any]:
    repo = _repo_full_name(payload)
    status = _required_mapping(payload, "deployment_status")
    deployment = _required_mapping(payload, "deployment")
    deployment_id = _required_value(deployment, "id")
    status_id = status.get("id") or status.get("node_id") or status.get("state") or "latest"
    event_id = f"github_deployment_status:{repo}:{deployment_id}:{status_id}"
    repo_id = _repo_id(repo)
    sha = _string_or_none(deployment.get("sha"))

    nodes = [
        _repo_node(repo, payload),
        _node(
            event_id,
            "DeploymentEvent",
            "deployment_status",
            {
                "repository": repo,
                "deployment_id": deployment_id,
                "status_id": status_id,
                "action": payload.get("action"),
                "environment": deployment.get("environment") or status.get("environment"),
                "state": status.get("state"),
                "description": status.get("description"),
                "target_url": status.get("target_url"),
                "log_url": status.get("log_url"),
                "ref": deployment.get("ref"),
                "sha": sha,
            },
        ),
    ]
    edges = [_edge(repo_id, event_id, "repository_has_delivery_event", "deployment_status")]
    if sha:
        commit_id = _commit_id(repo, sha)
        nodes.append(_commit_node(repo, {"sha": sha}, "deployment_status"))
        edges.append(_edge(event_id, commit_id, "deploys_commit", "deployment_status"))
    return _fragment("deployment_status", nodes, edges)


def _fragment(event_type: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "provider": "github",
        "source_event": event_type,
        "read_only": True,
        "nodes": _dedupe_nodes(nodes),
        "edges": _dedupe_edges(edges),
    }


def _node(node_id: str, kind: str, event_type: str, attributes: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "provider": "github",
        "source_event": event_type,
        "read_only": True,
        "attributes": _compact(attributes),
    }


def _edge(source: str, target: str, kind: str, event_type: str, attributes: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "source": source,
        "target": target,
        "kind": kind,
        "provider": "github",
        "source_event": event_type,
        "read_only": True,
        "attributes": _compact(attributes or {}),
    }


def _repo_node(repo: str, payload: dict[str, Any]) -> dict[str, Any]:
    repository = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    return _node(
        _repo_id(repo),
        "GitHubRepository",
        "repository",
        {
            "full_name": repo,
            "default_branch": repository.get("default_branch"),
            "private": repository.get("private"),
            "url": repository.get("html_url") or repository.get("url"),
        },
    )


def _commit_node(repo: str, commit: dict[str, Any], event_type: str) -> dict[str, Any]:
    sha = _commit_sha(commit)
    return _node(
        _commit_id(repo, sha),
        "GitHubCommit",
        event_type,
        {
            "repository": repo,
            "sha": sha,
            "message": commit.get("message"),
            "timestamp": commit.get("timestamp"),
            "url": commit.get("html_url") or commit.get("url"),
            "author": _commit_author(commit),
        },
    )


def _repo_id(repo: str) -> str:
    return f"github_repository:{repo}"


def _commit_id(repo: str, sha: str) -> str:
    return f"github_commit:{repo}@{sha}"


def _repo_full_name(payload: dict[str, Any]) -> str:
    repository = payload.get("repository") if isinstance(payload.get("repository"), dict) else {}
    full_name = repository.get("full_name")
    if full_name:
        return str(full_name)
    owner = repository.get("owner") if isinstance(repository.get("owner"), dict) else {}
    owner_name = owner.get("login") or owner.get("name")
    repo_name = repository.get("name")
    if owner_name and repo_name:
        return f"{owner_name}/{repo_name}"
    raise ValueError("GitHub delivery payload requires repository.full_name")


def _commit_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload.get("commits"), list):
        return [commit for commit in payload["commits"] if isinstance(commit, dict)]
    for key in ("head_commit", "commit"):
        if isinstance(payload.get(key), dict):
            return [payload[key]]
    if _string_or_none(payload.get("sha")) or _string_or_none(payload.get("id")):
        return [payload]
    return []


def _commit_sha(commit: dict[str, Any]) -> str:
    sha = _string_or_none(commit.get("sha")) or _string_or_none(commit.get("id"))
    if not sha:
        raise ValueError("commit payload requires sha or id")
    return sha


def _commit_author(commit: dict[str, Any]) -> str | None:
    author = commit.get("author")
    if isinstance(author, dict):
        return _string_or_none(author.get("login")) or _string_or_none(author.get("name")) or _string_or_none(author.get("email"))
    return _string_or_none(author)


def _required_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"GitHub {key} event requires {key} object")
    return value


def _required_value(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is None or value == "":
        raise ValueError(f"GitHub delivery payload requires {key}")
    return value


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _compact(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for node in nodes:
        node_id = str(node.get("id") or "")
        if node_id in seen:
            continue
        seen.add(node_id)
        deduped.append(node)
    return deduped


def _dedupe_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for edge in edges:
        signature = (str(edge.get("source")), str(edge.get("target")), str(edge.get("kind")))
        if signature in seen:
            continue
        seen.add(signature)
        deduped.append(edge)
    return deduped


def _maybe_worker_a_fragment(fragment: dict[str, Any]) -> dict[str, Any]:
    """Use Worker A's graph boundary if it is present and exposes a plain adapter."""
    try:
        module = import_module("services.delivery.context_graph")
    except ModuleNotFoundError as exc:
        if exc.name == "services.delivery.context_graph":
            return fragment
        raise

    for name in ("normalize_fragment", "build_fragment", "from_fragment"):
        adapter = getattr(module, name, None)
        if callable(adapter):
            candidate = adapter(fragment)
            if hasattr(candidate, "to_dict"):
                return candidate.to_dict()
            if isinstance(candidate, dict):
                return candidate
            return fragment
    return fragment
