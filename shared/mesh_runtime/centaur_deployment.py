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
    deployment = _named_kind(documents, "Deployment", "mesh-centaur-sandbox-adapter")
    proxy_deployment = _named_kind(documents, "Deployment", "mesh-centaur-credential-egress-proxy")
    proxy_service = _named_kind(documents, "Service", "mesh-centaur-credential-egress-proxy")
    network_policy = _first_kind(documents, "NetworkPolicy")
    service_account = _first_kind(documents, "ServiceAccount")
    containers = _deployment_containers(deployment)
    proxy_containers = _deployment_containers(proxy_deployment)
    checks = {
        "profile_present": profile_path.exists(),
        "namespace_present": "Namespace" in kinds,
        "service_account_present": service_account is not None,
        "default_deny_network_policy_present": _is_default_deny_network_policy(network_policy),
        "deployment_disabled_by_default": bool(deployment and deployment.get("spec", {}).get("replicas") == 0),
        "proxy_deployment_disabled_by_default": bool(
            proxy_deployment and proxy_deployment.get("spec", {}).get("replicas") == 0
        ),
        "state_slice_labels_present": all(_has_state_slice_label(doc) for doc in documents),
        "service_account_token_not_automounted": bool(
            service_account
            and service_account.get("automountServiceAccountToken") is False
            and deployment
            and deployment.get("spec", {}).get("template", {}).get("spec", {}).get("automountServiceAccountToken") is False
            and proxy_deployment
            and proxy_deployment.get("spec", {}).get("template", {}).get("spec", {}).get("automountServiceAccountToken")
            is False
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
        "adapter_egress_proxy_url_present": _adapter_egress_proxy_url_present(containers),
        "credential_proxy_separate_deployment_present": proxy_deployment is not None,
        "credential_proxy_service_present": _service_targets_proxy(proxy_service),
        "adapter_proxy_only_network_policy_present": _adapter_proxy_only_network_policy_present(documents),
        "dns_egress_policy_present": _dns_egress_policy_present(documents),
        "credential_proxy_not_sidecar": _container_named(containers, "credential-egress-proxy") is None,
        "credential_proxy_placeholder_mode": _credential_proxy_placeholder_mode(proxy_containers),
        "credential_proxy_health_probe_present": bool(
            (_container_named(proxy_containers, "credential-egress-proxy") or {})
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
        "proxy_deployment_disabled_by_default": (
            "name: mesh-centaur-credential-egress-proxy" in text
            and "replicas: 0" in text
        ),
        "state_slice_labels_present": text.count(f"mesh.lusis.io/state-slice: {CENTAUR_DEPLOYMENT_PROFILE_VERSION}") >= 4,
        "service_account_token_not_automounted": text.count("automountServiceAccountToken: false") >= 2,
        "health_probe_present": "readinessProbe:" in text and "path: /health/ready" in text,
        "live_execution_blocked_annotation_present": "blocked-until-credential-egress-proof" in text,
        "adapter_egress_proxy_url_present": "MESH_CREDENTIAL_EGRESS_PROXY_URL" in text,
        "credential_proxy_separate_deployment_present": (
            "kind: Deployment" in text
            and "name: mesh-centaur-credential-egress-proxy" in text
        ),
        "credential_proxy_service_present": "kind: Service" in text and "name: mesh-centaur-credential-egress-proxy" in text,
        "adapter_proxy_only_network_policy_present": "allow-adapter-to-credential-proxy" in text and "port: 15001" in text,
        "dns_egress_policy_present": "allow-dns-egress" in text and "port: 53" in text,
        "credential_proxy_not_sidecar": "mesh.lusis.io/proxy-sidecar" not in text,
        "credential_proxy_placeholder_mode": "MESH_CREDENTIAL_PLACEHOLDER_MODE" in text and 'value: "true"' in text,
        "credential_proxy_health_probe_present": "path: /health/ready" in text and "containerPort: 15001" in text,
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


def _named_kind(documents: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any] | None:
    for document in documents:
        metadata = document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
        if document.get("kind") == kind and metadata.get("name") == name:
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


def _adapter_egress_proxy_url_present(containers: list[dict[str, Any]]) -> bool:
    adapter = _container_named(containers, "adapter")
    if not adapter:
        return False
    env = adapter.get("env")
    if not isinstance(env, list):
        return False
    values = {item.get("name"): item.get("value") for item in env if isinstance(item, dict)}
    return values.get("MESH_CREDENTIAL_EGRESS_PROXY_URL") == "http://mesh-centaur-credential-egress-proxy:15001"


def _service_targets_proxy(service: dict[str, Any] | None) -> bool:
    if not service:
        return False
    spec = service.get("spec") if isinstance(service.get("spec"), dict) else {}
    selector = spec.get("selector") if isinstance(spec.get("selector"), dict) else {}
    ports = spec.get("ports") if isinstance(spec.get("ports"), list) else []
    return (
        selector.get("app.kubernetes.io/name") == "mesh-centaur-credential-egress-proxy"
        and any(isinstance(port, dict) and port.get("port") == 15001 for port in ports)
    )


def _adapter_proxy_only_network_policy_present(documents: list[dict[str, Any]]) -> bool:
    policy = _named_kind(documents, "NetworkPolicy", "allow-adapter-to-credential-proxy")
    if not policy:
        return False
    spec = policy.get("spec") if isinstance(policy.get("spec"), dict) else {}
    selector = spec.get("podSelector") if isinstance(spec.get("podSelector"), dict) else {}
    match_labels = selector.get("matchLabels") if isinstance(selector.get("matchLabels"), dict) else {}
    egress = spec.get("egress") if isinstance(spec.get("egress"), list) else []
    if match_labels.get("app.kubernetes.io/name") != "mesh-centaur-sandbox-adapter":
        return False
    return _egress_targets_proxy_port(egress)


def _egress_targets_proxy_port(egress: list[Any]) -> bool:
    for rule in egress:
        if not isinstance(rule, dict):
            continue
        ports = rule.get("ports") if isinstance(rule.get("ports"), list) else []
        destinations = rule.get("to") if isinstance(rule.get("to"), list) else []
        has_port = any(isinstance(port, dict) and port.get("port") == 15001 for port in ports)
        has_proxy = any(
            isinstance(destination, dict)
            and (
                destination.get("podSelector", {})
                .get("matchLabels", {})
                .get("app.kubernetes.io/name")
                == "mesh-centaur-credential-egress-proxy"
            )
            for destination in destinations
        )
        if has_port and has_proxy:
            return True
    return False


def _dns_egress_policy_present(documents: list[dict[str, Any]]) -> bool:
    policy = _named_kind(documents, "NetworkPolicy", "allow-dns-egress")
    if not policy:
        return False
    spec = policy.get("spec") if isinstance(policy.get("spec"), dict) else {}
    egress = spec.get("egress") if isinstance(spec.get("egress"), list) else []
    for rule in egress:
        if not isinstance(rule, dict):
            continue
        ports = rule.get("ports") if isinstance(rule.get("ports"), list) else []
        port_protocols = {
            (port.get("port"), port.get("protocol"))
            for port in ports
            if isinstance(port, dict)
        }
        if (53, "UDP") in port_protocols and (53, "TCP") in port_protocols:
            return True
    return False


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
