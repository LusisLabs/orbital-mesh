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
    # Secrets / config
    _Rule("missing_secret_binding", ("secret \"", "secret not found", "couldn't find key", "createcontainerconfigerror"), weight=1.1),
    _Rule("missing_configmap", ("configmap \"", "configmap not found", "couldn't find configmap")),
    _Rule("missing_service_account", ("serviceaccount not found", "service account not found", "no such service account")),
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
    _Rule("pod_network_delay", ("network is unreachable", "no route to host", "i/o timeout", "context deadline exceeded")),
    _Rule("dns_resolution_failure", ("dns lookup failed", "no such host", "name resolution", "no servers could be reached")),
    _Rule("connection_refused", ("connection refused", "dial tcp", "ECONNREFUSED")),
    # Disk / volume
    _Rule("disk_pressure", ("nodehasdiskpressure", "disk pressure", "no space left on device")),
    _Rule("volume_mount_failed", ("failed to mount volume", "mountvolume.setup failed", "unable to mount volumes")),
    _Rule("persistent_volume_claim_pending", ("pod has unbound immediate persistentvolumeclaims", "unbound persistentvolumeclaims", "persistentvolumeclaim is not bound")),
    # Cluster / node
    _Rule("node_not_ready", ("node not ready", "kubelet stopped posting", "kubelet is not ready")),
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
        score = rule.weight * (1.0 + 0.25 * (len(matched) - 1))
        cause_score, cause_patterns = hits.get(rule.root_cause, (0.0, set()))
        hits[rule.root_cause] = (cause_score + score, cause_patterns | matched)
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
