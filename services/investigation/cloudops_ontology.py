"""CloudOps RCA ontology — text patterns to canonical root-cause labels.

Cloud-OpsBench scores a fixed vocabulary of ~49 canonical root causes
(``pod_network_delay``, ``incorrect_image_reference``,
``missing_secret_binding``, ...). The investigation stage observes raw
snapshot text from tools like ``DescribeResource`` and ``GetErrorLogs``;
this module is the bridge between the two.

Every entry is a list of substring patterns. A snapshot-text hit on any
of an entry's patterns adds prior weight to that canonical cause. The
ontology is conservative on purpose — it should produce an empty ranking
when the snapshot does not contain a clear signal, rather than guess.
The hypothesis loop that consumes this ranking is responsible for
calling more probes when the ranking is thin.

Patterns are kept lowercase; matching is also lowercase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class _Rule:
    root_cause: str
    patterns: tuple[str, ...]
    weight: float = 1.0


_RULES: tuple[_Rule, ...] = (
    # Image / startup
    _Rule("incorrect_image_reference", ("imagepullbackoff", "errimagepull", "manifest unknown", "image not found", "no such image")),
    _Rule("image_pull_failure", ("rpc error: code = unknown desc = failed to pull and unpack image", "back-off pulling image")),
    _Rule("missing_image_pull_secret", ("failedtoretrieveimagepullsecret", "unable to retrieve some image pull secrets"), weight=1.6),
    _Rule("invalid_image_command", ("invalid container command", "command not found", "exec: \"")),
    # Scheduling
    _Rule("node_selector_mismatch", ("didn't match node selector", "didn't match pod's node affinity/selector"), weight=1.3),
    _Rule("node_affinity_mismatch", ("didn't match pod's node affinity", "node affinity rules", "required node affinity")),
    _Rule("taint_toleration_mismatch", ("had untolerated taint", "tolerations don't tolerate", "node had taint")),
    _Rule("pod_anti_affinity_conflict", ("didn't match pod anti-affinity rules", "pod anti-affinity"), weight=1.4),
    _Rule("cpu_capacity_mismatch", ("insufficient cpu",), weight=1.4),
    _Rule("memory_capacity_mismatch", ("insufficient memory",), weight=1.4),
    _Rule("insufficient_resources", ("no nodes are available", "didn't have free ports", "exceeded quota")),
    # Service routing
    _Rule("service_selector_mismatch", ("no endpoints available for service", "endpoints not found", "selector doesn't match", "0 endpoints", "endpoints: <none>")),
    _Rule("service_port_mismatch", ("no port matching", "service port", "targetport", "target port", "does not have a port named")),
    # Two newer canonical labels that CloudOpsBench scores under more
    # specific names — emitted by ``analyze_service_routing`` when the
    # numeric Service.spec.ports[i].targetPort disagrees with the
    # backing pod's containerPort, or when a deployment env var like
    # ``EMAIL_SERVICE_ADDR=emailservice:5050`` references a port the
    # service doesn't expose. Patterns intentionally include the verbose
    # phrasing the analyzer emits so we don't false-fire on raw
    # describe text that contains "port mapping" incidentally.
    _Rule(
        "service_port_mapping_mismatch",
        ("port mapping mismatch", "service port mapping mismatch"),
        weight=1.5,
    ),
    _Rule(
        "service_env_var_address_mismatch",
        # Only patterns specific enough to identify the
        # ``analyze_service_routing`` analyzer's emitted text. A bare
        # ``"env var"`` substring would false-fire on any tool
        # description, error log, or unrelated diagnostic that mentions
        # environment variables — the ontology fires on ANY pattern
        # match (not all), so even one weak pattern poisons the rule.
        ("references service address mismatch", "service address mismatch"),
        weight=1.5,
    ),
    # Secrets / config
    _Rule("missing_secret_binding", ("secret \"", "secret not found", "couldn't find key", "createcontainerconfigerror"), weight=1.1),
    _Rule("missing_configmap", ("configmap \"", "configmap not found", "couldn't find configmap")),
    _Rule(
        "missing_service_account",
        (
            "serviceaccount not found",
            "service account not found",
            "no such service account",
            # CloudOpsBench events emit the kube-apiserver canonical
            # form: ``error looking up service account NS/NAME:
            # serviceaccount "NAME" not found``. Both the verbose
            # phrase and the quoted form land here so substring
            # matching fires regardless of which slice surfaces.
            "looking up service account",
            'serviceaccount "',
        ),
    ),
    # Auth / DB
    _Rule("mysql_invalid_credentials", ("access denied for user", "authentication failed", "1045", "er_access_denied")),
    _Rule("postgres_invalid_credentials", ("password authentication failed", "fatal:  password", "28p01")),
    # Runtime crashes
    _Rule("oom_killed", ("oomkilled", "out of memory", "memory cgroup out of memory")),
    _Rule("crash_loop_backoff", ("crashloopbackoff", "back-off restarting failed container")),
    _Rule(
        "liveness_probe_incorrect_port",
        ("liveness probe failed: dial tcp", "liveness probe failed: grpc", "liveness probe failed: connect: connection refused"),
        weight=1.6,
    ),
    _Rule(
        "readiness_probe_incorrect_port",
        ("readiness probe failed: dial tcp", "readiness probe failed: grpc", "readiness probe failed: connect: connection refused"),
        weight=1.6,
    ),
    _Rule(
        "readiness_probe_incorrect_protocol",
        ("http probe failed", "server gave http response to https client", "client sent an http request to an https server"),
        weight=1.6,
    ),
    _Rule("liveness_probe_failed", ("liveness probe failed", "failed liveness probe"), weight=1.2),
    _Rule("readiness_probe_failed", ("readiness probe failed", "failed readiness probe"), weight=1.2),
    # Network / DNS
    _Rule(
        "pod_network_delay",
        (
            "network is unreachable",
            "no route to host",
            "i/o timeout",
            "context deadline exceeded",
            "traffic_anomaly [network drop]",
        ),
    ),
    _Rule("dns_resolution_failure", ("dns lookup failed", "no such host", "name resolution", "no servers could be reached")),
    _Rule("connection_refused", ("connection refused", "dial tcp", "ECONNREFUSED")),
    # Disk / volume
    _Rule("disk_pressure", ("nodehasdiskpressure", "disk pressure", "no space left on device")),
    _Rule("volume_mount_failed", ("failed to mount volume", "mountvolume.setup failed", "unable to mount volumes")),
    _Rule("persistent_volume_claim_pending", ("pod has unbound immediate persistentvolumeclaims", "unbound persistentvolumeclaims", "persistentvolumeclaim is not bound")),
    # Cluster / node
    _Rule("node_not_ready", ("node not ready", "kubelet stopped posting", "kubelet is not ready")),
    # Node-daemon failure family — fired by ``analyze_node_dataplane``
    # when systemd reports ``Active: inactive`` (or ``failed``) for a
    # specific daemon. Each rule pins the daemon name so different
    # daemons land on the right canonical label rather than colliding
    # on a shared "node down" bucket.
    _Rule(
        "containerd_unavailable",
        ("containerd.service on", "containerd.service is inactive", "containerd.service is failed"),
        weight=1.6,
    ),
    _Rule(
        "kube_proxy_unavailable",
        ("kube-proxy.service on", "kube-proxy.service is inactive", "kube-proxy.service is failed"),
        weight=1.6,
    ),
    _Rule(
        "kubelet_unavailable",
        ("kubelet.service on", "kubelet.service is inactive", "kubelet.service is failed"),
        weight=1.6,
    ),
    _Rule(
        "kube_scheduler_unavailable",
        ("kube-scheduler.service on", "kube-scheduler.service is inactive"),
        weight=1.4,
    ),
)


@dataclass(frozen=True)
class RankedCause:
    root_cause: str
    confidence: float
    matched_patterns: tuple[str, ...]


def rank_root_causes(text: Iterable[str], *, top_k: int = 5) -> list[RankedCause]:
    """Score canonical root causes against a stream of observed text.

    Returns at most ``top_k`` ranked causes. Confidence is normalized to
    [0, 1] across the matched rules and scaled by per-rule weight. When
    no rule fires, returns an empty list — callers should treat that as
    "diagnose harder," not "unknown is the root cause."
    """

    haystack = "\n".join(str(item or "").lower() for item in text)
    if not haystack.strip():
        return []
    hits: dict[str, tuple[float, set[str]]] = {}
    for rule in _RULES:
        matched: set[str] = set()
        for pattern in rule.patterns:
            if pattern.lower() in haystack:
                matched.add(pattern)
        if not matched:
            continue
        _add_hit(hits, rule.root_cause, rule.weight * (1.0 + 0.25 * (len(matched) - 1)), matched)
    for derived in _derived_probe_port_rules(haystack):
        _add_hit(hits, derived.root_cause, derived.weight, set(derived.patterns))
    for derived in _derived_probe_protocol_rules(haystack):
        _add_hit(hits, derived.root_cause, derived.weight, set(derived.patterns))
    for derived in _derived_deployment_rules(haystack):
        _add_hit(hits, derived.root_cause, derived.weight, set(derived.patterns))
    for derived in _derived_scheduler_rules(haystack):
        _add_hit(hits, derived.root_cause, derived.weight, set(derived.patterns))
    if not hits:
        return []
    total = sum(score for score, _ in hits.values()) or 1.0
    ranked = sorted(hits.items(), key=lambda item: item[1][0], reverse=True)[:top_k]
    return [
        RankedCause(
            root_cause=cause,
            confidence=round(score / total, 3),
            matched_patterns=tuple(sorted(patterns)),
        )
        for cause, (score, patterns) in ranked
    ]


def _add_hit(
    hits: dict[str, tuple[float, set[str]]],
    root_cause: str,
    score: float,
    matched: set[str],
) -> None:
    cause_score, cause_patterns = hits.get(root_cause, (0.0, set()))
    hits[root_cause] = (cause_score + score, cause_patterns | matched)


def _derived_probe_port_rules(haystack: str) -> tuple[_Rule, ...]:
    derived: list[_Rule] = []
    if _probe_port_mismatch(haystack, "readiness"):
        derived.append(
            _Rule(
                "readiness_probe_incorrect_port",
                ("readiness probe failed", "readiness:", "readinessprobe", "targetport"),
                weight=4.0,
            )
        )
    if _probe_port_mismatch(haystack, "liveness"):
        derived.append(
            _Rule(
                "liveness_probe_incorrect_port",
                ("liveness probe failed", "liveness:", "livenessprobe", "targetport"),
                weight=4.0,
            )
        )
    return tuple(derived)


def _derived_probe_protocol_rules(haystack: str) -> tuple[_Rule, ...]:
    derived: list[_Rule] = []
    if _probe_protocol_mismatch(haystack, "readiness"):
        derived.append(
            _Rule(
                "readiness_probe_incorrect_protocol",
                ("readiness probe failed", "malformed http response", "http-get"),
                weight=4.0,
            )
        )
    if _probe_protocol_mismatch(haystack, "liveness"):
        derived.append(
            _Rule(
                "liveness_probe_incorrect_protocol",
                ("liveness probe failed", "malformed http response", "http-get"),
                weight=4.0,
            )
        )
    return tuple(derived)


def _derived_deployment_rules(haystack: str) -> tuple[_Rule, ...]:
    if "ready" not in haystack or "up-to-date" not in haystack or "available" not in haystack:
        return ()
    if not re.search(r"(?m)^\s*[a-z0-9][a-z0-9-]*\s+0/0\s+0\s+0\b", haystack):
        return ()
    return (
        _Rule(
            "deployment_zero_replicas",
            ("ready", "up-to-date", "available", "0/0"),
            weight=4.0,
        ),
    )


def _derived_scheduler_rules(haystack: str) -> tuple[_Rule, ...]:
    if "untolerated taint" not in haystack and "had untolerated taint" not in haystack:
        return ()
    return (
        _Rule(
            "taint_toleration_mismatch",
            ("untolerated taint",),
            weight=3.0,
        ),
    )


def _probe_port_mismatch(haystack: str, probe: str) -> bool:
    if f"{probe} probe failed" not in haystack:
        return False
    probe_ports = _probe_ports(haystack, probe)
    if not probe_ports:
        return False
    serving_ports = _serving_ports(haystack)
    return bool(serving_ports and any(port not in serving_ports for port in probe_ports))


def _probe_protocol_mismatch(haystack: str, probe: str) -> bool:
    if f"{probe} probe failed" not in haystack:
        return False
    if "malformed http response" not in haystack and "http/1.x transport connection broken" not in haystack:
        return False
    return "http-get" in haystack or 'get "http://' in haystack or "get 'http://" in haystack


def _probe_ports(haystack: str, probe: str) -> set[str]:
    ports: set[str] = set()
    for pattern in (
        rf"{probe}:\s+\w+\s+<pod>:(\d+)",
        rf"{probe}probe:.*?port:\s*[\"']?(\d+)",
    ):
        ports.update(re.findall(pattern, haystack, flags=re.DOTALL))
    return ports


def _serving_ports(haystack: str) -> set[str]:
    ports: set[str] = set()
    for pattern in (
        r"containerport:\s*[\"']?(\d+)",
        r"targetport:\s*[\"']?(\d+)",
        r"\bport:\s+(\d+)/tcp",
    ):
        ports.update(re.findall(pattern, haystack))
    return ports
