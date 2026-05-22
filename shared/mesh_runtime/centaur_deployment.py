from __future__ import annotations

from pathlib import Path
from typing import Any


CENTAUR_DEPLOYMENT_PROFILE_VERSION = "mesh.centaur_deployment_profile.v1"


def verify_centaur_kubernetes_profile(path: str | Path) -> dict[str, Any]:
    profile_path = Path(path)
    text = profile_path.read_text(encoding="utf-8")
    documents = _load_yaml_documents(text)
    if not documents:
        return _verify_text_profile(profile_path, text)
    kinds = {str(doc.get("kind")) for doc in documents}
    deployment = _first_kind(documents, "Deployment")
    network_policy = _first_kind(documents, "NetworkPolicy")
    service_account = _first_kind(documents, "ServiceAccount")
    containers = _deployment_containers(deployment)
    checks = {
        "profile_present": profile_path.exists(),
        "namespace_present": "Namespace" in kinds,
        "service_account_present": service_account is not None,
        "default_deny_network_policy_present": _is_default_deny_network_policy(network_policy),
        "deployment_disabled_by_default": bool(deployment and deployment.get("spec", {}).get("replicas") == 0),
        "state_slice_labels_present": all(_has_state_slice_label(doc) for doc in documents),
        "service_account_token_not_automounted": bool(
            service_account
            and service_account.get("automountServiceAccountToken") is False
            and deployment
            and deployment.get("spec", {}).get("template", {}).get("spec", {}).get("automountServiceAccountToken") is False
        ),
        "health_probe_present": bool(
            containers
            and containers[0].get("readinessProbe", {}).get("httpGet", {}).get("path")
        ),
        "live_execution_blocked_annotation_present": bool(
            deployment
            and deployment.get("spec", {})
            .get("template", {})
            .get("metadata", {})
            .get("annotations", {})
            .get("mesh.lusis.io/live-execution")
            == "blocked-until-credential-egress-proof"
        ),
        "credential_proxy_sidecar_present": _container_named(containers, "credential-egress-proxy") is not None,
        "credential_proxy_placeholder_mode": _credential_proxy_placeholder_mode(containers),
        "credential_proxy_health_probe_present": bool(
            (_container_named(containers, "credential-egress-proxy") or {})
            .get("readinessProbe", {})
            .get("httpGet", {})
            .get("path")
        ),
        "real_adapter_image_configured": _adapter_image_is_real(containers),
        "per_sandbox_labels_present": _per_sandbox_labels_present(deployment),
        "cleanup_policy_present": _cleanup_policy_present(deployment),
    }
    return {
        "schema_version": CENTAUR_DEPLOYMENT_PROFILE_VERSION,
        "status": "pass" if all(checks.values()) else "fail",
        "profile_path": str(profile_path),
        "document_count": len(documents),
        "kinds": sorted(kinds),
        "checks": checks,
    }


def _load_yaml_documents(text: str) -> list[dict[str, Any]]:
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return []
    return [doc for doc in yaml.safe_load_all(text) if isinstance(doc, dict)]


def _verify_text_profile(profile_path: Path, text: str) -> dict[str, Any]:
    kinds = sorted({line.split(":", 1)[1].strip() for line in text.splitlines() if line.strip().startswith("kind:")})
    checks = {
        "profile_present": profile_path.exists(),
        "namespace_present": "kind: Namespace" in text,
        "service_account_present": "kind: ServiceAccount" in text,
        "default_deny_network_policy_present": (
            "kind: NetworkPolicy" in text
            and "podSelector: {}" in text
            and "- Ingress" in text
            and "- Egress" in text
        ),
        "deployment_disabled_by_default": "kind: Deployment" in text and "replicas: 0" in text,
        "state_slice_labels_present": text.count(f"mesh.lusis.io/state-slice: {CENTAUR_DEPLOYMENT_PROFILE_VERSION}") >= 4,
        "service_account_token_not_automounted": text.count("automountServiceAccountToken: false") >= 2,
        "health_probe_present": "readinessProbe:" in text and "path: /health/ready" in text,
        "live_execution_blocked_annotation_present": "blocked-until-credential-egress-proof" in text,
        "credential_proxy_sidecar_present": "name: credential-egress-proxy" in text,
        "credential_proxy_placeholder_mode": "MESH_CREDENTIAL_PLACEHOLDER_MODE" in text and 'value: "true"' in text,
        "credential_proxy_health_probe_present": "path: /health" in text and "port: 15001" in text,
        "real_adapter_image_configured": "mesh-centaur-sandbox-adapter:latest" in text and ":disabled" not in text,
        "per_sandbox_labels_present": all(
            label in text
            for label in (
                "mesh.lusis.io/run-id",
                "mesh.lusis.io/task-id",
                "mesh.lusis.io/attempt-id",
                "mesh.lusis.io/agent",
            )
        ),
        "cleanup_policy_present": "mesh.lusis.io/cleanup-policy: release-thread-and-delete-sandbox" in text,
    }
    return {
        "schema_version": CENTAUR_DEPLOYMENT_PROFILE_VERSION,
        "status": "pass" if all(checks.values()) else "fail",
        "profile_path": str(profile_path),
        "document_count": text.count("\n---") + 1 if text.strip() else 0,
        "kinds": kinds,
        "checks": checks,
    }


def _first_kind(documents: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    for document in documents:
        if document.get("kind") == kind:
            return document
    return None


def _has_state_slice_label(document: dict[str, Any]) -> bool:
    metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    labels = metadata.get("labels") if isinstance(metadata.get("labels"), dict) else {}
    return labels.get("mesh.lusis.io/state-slice") == CENTAUR_DEPLOYMENT_PROFILE_VERSION


def _deployment_containers(deployment: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not deployment:
        return []
    containers = (
        deployment.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    return [container for container in containers if isinstance(container, dict)] if isinstance(containers, list) else []


def _container_named(containers: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for container in containers:
        if container.get("name") == name:
            return container
    return None


def _credential_proxy_placeholder_mode(containers: list[dict[str, Any]]) -> bool:
    proxy = _container_named(containers, "credential-egress-proxy")
    if not proxy:
        return False
    env = proxy.get("env")
    if not isinstance(env, list):
        return False
    values = {
        item.get("name"): item.get("value")
        for item in env
        if isinstance(item, dict)
    }
    return (
        values.get("MESH_CREDENTIAL_PLACEHOLDER_MODE") == "true"
        and values.get("MESH_CREDENTIAL_POLICY_REF") == "mesh.credential_egress_policy.v1"
    )


def _adapter_image_is_real(containers: list[dict[str, Any]]) -> bool:
    adapter = _container_named(containers, "adapter")
    if not adapter:
        return False
    image = str(adapter.get("image") or "")
    return bool(image) and not image.endswith(":disabled")


def _per_sandbox_labels_present(deployment: dict[str, Any] | None) -> bool:
    labels = (
        deployment.get("spec", {})
        .get("template", {})
        .get("metadata", {})
        .get("labels", {})
        if deployment
        else {}
    )
    return all(
        labels.get(key)
        for key in (
            "mesh.lusis.io/run-id",
            "mesh.lusis.io/task-id",
            "mesh.lusis.io/attempt-id",
            "mesh.lusis.io/agent",
        )
    )


def _cleanup_policy_present(deployment: dict[str, Any] | None) -> bool:
    annotations = (
        deployment.get("spec", {})
        .get("template", {})
        .get("metadata", {})
        .get("annotations", {})
        if deployment
        else {}
    )
    return annotations.get("mesh.lusis.io/cleanup-policy") == "release-thread-and-delete-sandbox"


def _is_default_deny_network_policy(document: dict[str, Any] | None) -> bool:
    if not document:
        return False
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    return spec.get("podSelector") == {} and set(spec.get("policyTypes", [])) == {"Ingress", "Egress"}
