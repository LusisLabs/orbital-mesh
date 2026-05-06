"""K8sGPT-style analyzer tools for CloudOpsBench-shaped snapshots.

The eight raw cloudops tools (``GetResources``, ``DescribeResource``,
``GetAppYAML``, ``GetErrorLogs``, ``CheckServiceConnectivity``,
``CheckNodeServiceStatus``, ``GetAlerts``, ``GetClusterConfiguration``,
``GetRecentLogs``) are correct primitives but expose unstructured
``kubectl``-style text. The LLM has to re-parse multi-page describe
outputs every iteration, and frequently doesn't think to fetch the
right resource type at all — for example, *0 of 50* admission-fault
scenarios in the run on master picked up ``GetResources::events``,
even though the canonical ``serviceaccount "X" not found`` message
sits inside it.

This module ports the K8sGPT analyzer pattern: pre-canned investigation
recipes that fan out a handful of snapshot calls and emit a single
structured ``RawToolOutput`` whose ``output_summary`` contains the
keyword phrases the cloudops ontology already knows how to match. The
LLM picks the recipe, not the underlying calls, and the rule-based
ontology fires on the resulting summary.

Design contract:

* Each analyzer wraps a ``snapshot_tools.invoke(...)`` series — never
  a live cluster call. Same data shape as raw tools so the critic and
  scoring code don't change.
* ``valid=True`` whenever the analyzer ran end-to-end, regardless of
  whether it found the failure pattern. ``valid=False`` is reserved
  for hard failures (missing snapshot keys, malformed inputs).
* ``output_summary`` is the contract surface for downstream pattern
  matching — it MUST contain the exact phrase that the matching
  ontology rule searches for (e.g. ``serviceaccount "..." not found``,
  ``Active: inactive``, etc.). Adding a new failure class means
  extending both the analyzer's text emission AND
  ``cloudops_ontology.py`` rules — they're paired by string.
* Read-only by construction (the snapshot tool cache is read-only;
  these analyzers have no other I/O).
"""

from __future__ import annotations

import re
from typing import Any

from .harness.registry import RawToolOutput, ToolDefinition, ToolRegistry

CLOUDOPS_DOMAIN = "cloudops"

# ----------------------------------------------------------------------
# Tool definitions
# ----------------------------------------------------------------------

ANALYZER_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = (
    ToolDefinition(
        name="analyze_admission_events",
        domain=CLOUDOPS_DOMAIN,
        description=(
            "Find admission/scheduling failures: missing ServiceAccounts, ResourceQuota "
            "violations, webhook denials, FailedCreate/FailedScheduling events, image-pull "
            "errors. Use this whenever pods can't be created or are repeatedly evicted."
        ),
        args_schema={
            "namespace": {"type": "str", "required": True, "nullable": False},
        },
        mutation_class="read_only",
        timeout_seconds=2.0,
        budget_cost=1.0,
        citations_kind="cloudopsbench_snapshot",
    ),
    ToolDefinition(
        name="analyze_node_dataplane",
        domain=CLOUDOPS_DOMAIN,
        description=(
            "Check kubelet, containerd, kube-proxy, and kube-scheduler systemd state on "
            "every node. Surfaces inactive/failed daemons that explain widespread service "
            "unavailability or scheduling stalls. Use when the failure looks node-level."
        ),
        args_schema={},
        mutation_class="read_only",
        timeout_seconds=2.0,
        budget_cost=1.0,
        citations_kind="cloudopsbench_snapshot",
    ),
    ToolDefinition(
        name="analyze_service_routing",
        domain=CLOUDOPS_DOMAIN,
        description=(
            "Validate Service ↔ Endpoints ↔ Pod port consistency and Deployment env-var "
            "service references in a namespace. Surfaces port-mapping mismatches, empty "
            "endpoints, and env vars pointing at the wrong service:port. Use for "
            "service-to-service routing or connection-refused symptoms."
        ),
        args_schema={
            "namespace": {"type": "str", "required": True, "nullable": False},
            "service_name": {"type": "str", "required": False, "nullable": True},
        },
        mutation_class="read_only",
        timeout_seconds=2.0,
        budget_cost=1.0,
        citations_kind="cloudopsbench_snapshot",
    ),
)

ANALYZER_TOOL_NAMES: tuple[str, ...] = tuple(d.name for d in ANALYZER_TOOL_DEFINITIONS)


# ----------------------------------------------------------------------
# analyze_admission_events
# ----------------------------------------------------------------------

# Substrings that flag an event as admission/scheduling-relevant. Everything
# else is suppressed so the summary stays short enough to fit in the LLM's
# context window. Patterns are matched against the FULL event line
# (kubectl events output), case-insensitive.
_ADMISSION_EVENT_PATTERNS: tuple[str, ...] = (
    "Warning",  # any warning
    "FailedCreate",
    "FailedScheduling",
    "FailedAdmissionWebhook",
    "FailedToRetrieveImagePullSecret",
    "BackOff",
    "ErrImagePull",
    "ImagePullBackOff",
    "Forbidden",
    "denied the request",
    "exceeded quota",
    "not found",
)


def _analyze_admission_events_invoker(snapshot_tools: Any):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        namespace = (args or {}).get("namespace")
        if not namespace:
            return _failure("analyze_admission_events", "missing required arg: namespace")
        events_text = _safe_invoke(
            snapshot_tools, "GetResources", {"resource_type": "events", "namespace": namespace}
        )
        if events_text is None or _is_error_payload(events_text):
            return _failure(
                "analyze_admission_events",
                f"GetResources(events) unavailable in snapshot for namespace={namespace}",
            )
        text = events_text if isinstance(events_text, str) else str(events_text)

        # Filter: keep lines matching at least one warning/failure pattern.
        kept: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lower = stripped.lower()
            if any(p.lower() in lower for p in _ADMISSION_EVENT_PATTERNS):
                kept.append(stripped)

        if not kept:
            summary = (
                f"analyze_admission_events(namespace={namespace}): no admission/scheduling "
                f"warning events found in {len(text.splitlines())} event lines."
            )
            return RawToolOutput(
                output={"namespace": namespace, "warning_event_count": 0, "events": []},
                output_summary=summary,
                citations=[
                    {
                        "source_type": "cloudopsbench:analyze_admission_events",
                        "source_ref": namespace,
                    }
                ],
                valid=True,
                redaction_status="clean",
                status="completed",
            )

        # Surface the first ~12 hits — enough to capture root cause without
        # blowing the LLM's context. The LLM never sees the suppressed lines.
        head = kept[:12]
        body = "\n".join(head)
        more_msg = "" if len(kept) <= 12 else f" (+{len(kept) - 12} more suppressed)"
        summary = (
            f"analyze_admission_events(namespace={namespace}): {len(kept)} warning event(s)"
            f"{more_msg}.\n{body}"
        )
        return RawToolOutput(
            output={
                "namespace": namespace,
                "warning_event_count": len(kept),
                "events": kept,
            },
            output_summary=summary,
            citations=[
                {
                    "source_type": "cloudopsbench:analyze_admission_events",
                    "source_ref": namespace,
                }
            ],
            valid=True,
            redaction_status="clean",
            status="completed",
        )

    return invoke


# ----------------------------------------------------------------------
# analyze_node_dataplane
# ----------------------------------------------------------------------

# The four daemons CloudOpsBench tracks via CheckNodeServiceStatus.
_NODE_DAEMONS: tuple[str, ...] = ("kubelet", "containerd", "kube-proxy", "kube-scheduler")

# Default node names if the snapshot doesn't expose a node list. Boutique
# and trainticket scenarios both use this shape.
_DEFAULT_NODES: tuple[str, ...] = ("master", "worker-01", "worker-02", "worker-03")

# Match the systemd ``Active: <state>`` line. ``inactive``, ``failed``,
# ``activating``, and ``deactivating`` are all problematic.
_ACTIVE_LINE_RE = re.compile(r"^\s*Active:\s*(\S+)", re.MULTILINE)
_HEALTHY_ACTIVE_STATES = frozenset({"active"})


def _parse_systemd_active_state(status_text: str) -> str | None:
    if not isinstance(status_text, str):
        return None
    match = _ACTIVE_LINE_RE.search(status_text)
    if match is None:
        return None
    return match.group(1).strip().lower()


def _analyze_node_dataplane_invoker(snapshot_tools: Any):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        nodes = _DEFAULT_NODES
        # If the caller passes ``node_name``, restrict the probe — useful
        # for narrowing once a suspect is known. Schema doesn't declare
        # this so the critic accepts ``{}``; we still honor it if present.
        single = (args or {}).get("node_name")
        if isinstance(single, str) and single.strip():
            nodes = (single.strip(),)

        unhealthy: list[dict[str, Any]] = []
        checked = 0
        for node in nodes:
            for daemon in _NODE_DAEMONS:
                # kube-scheduler is a master-only daemon in the
                # CloudOpsBench cluster shape; skip workers to avoid
                # spurious "missing" reports.
                if daemon == "kube-scheduler" and node != "master":
                    continue
                response = _safe_invoke(
                    snapshot_tools,
                    "CheckNodeServiceStatus",
                    {"node_name": node, "service_name": daemon},
                )
                if response is None or _is_error_payload(response):
                    # Snapshot lacks this exact key — common when the
                    # ground-truth solver didn't probe a healthy daemon.
                    # We don't count these as failures.
                    continue
                checked += 1
                state = _parse_systemd_active_state(
                    response if isinstance(response, str) else str(response)
                )
                if state is None:
                    continue
                if state not in _HEALTHY_ACTIVE_STATES:
                    unhealthy.append(
                        {"node": node, "daemon": daemon, "active_state": state}
                    )

        if not unhealthy:
            summary = (
                f"analyze_node_dataplane: probed {checked} (node, daemon) pairs across "
                f"{len(nodes)} node(s); all reported Active: active (running)."
            )
            return RawToolOutput(
                output={
                    "nodes": list(nodes),
                    "checked_pairs": checked,
                    "unhealthy": [],
                },
                output_summary=summary,
                citations=[
                    {
                        "source_type": "cloudopsbench:analyze_node_dataplane",
                        "source_ref": ",".join(nodes),
                    }
                ],
                valid=True,
                redaction_status="clean",
                status="completed",
            )

        # Build a summary that contains the per-daemon trigger phrase the
        # ontology matches — each unhealthy daemon contributes a literal
        # ``<daemon>.service is inactive`` clause so rules fire on the
        # canonical CloudOpsBench label (``containerd_unavailable``, etc.).
        clauses = [
            f"{u['daemon']}.service on {u['node']} is {u['active_state']} "
            f"(Active: {u['active_state']})"
            for u in unhealthy
        ]
        summary = (
            f"analyze_node_dataplane: {len(unhealthy)} unhealthy node-daemon pair(s).\n"
            + "\n".join(clauses)
        )
        return RawToolOutput(
            output={
                "nodes": list(nodes),
                "checked_pairs": checked,
                "unhealthy": unhealthy,
            },
            output_summary=summary,
            citations=[
                {
                    "source_type": "cloudopsbench:analyze_node_dataplane",
                    "source_ref": ",".join(nodes),
                }
            ],
            valid=True,
            redaction_status="clean",
            status="completed",
        )

    return invoke


# ----------------------------------------------------------------------
# analyze_service_routing
# ----------------------------------------------------------------------

# Lines from kubectl describe that we care about for port consistency.
_SERVICE_PORT_RE = re.compile(r"^\s*Port:\s+(\S+)\s+(\d+)/(TCP|UDP|SCTP)", re.MULTILINE)
_SERVICE_TARGET_PORT_RE = re.compile(r"^\s*TargetPort:\s+(\S+)/(TCP|UDP|SCTP)", re.MULTILINE)
_SERVICE_ENDPOINTS_RE = re.compile(r"^\s*Endpoints:\s+(.+)$", re.MULTILINE)
_SERVICE_NAME_RE = re.compile(r"^Name:\s+(\S+)", re.MULTILINE)

# Container env vars in YAML referencing another service. We only flag
# vars whose name strongly hints they hold a service reference — the
# LLM is welcome to dig deeper with raw tools if needed.
_ENV_NAME_HINTS = (
    "_ADDR",
    "_HOST",
    "_URL",
    "_SERVER",
    "_ENDPOINT",
    "_SERVICE",
    "_TARGET",
)
_ENV_VALUE_RE = re.compile(r"^\s*-\s*name:\s*(\S+)\s*\n\s+value:\s*\"?([^\"\n]+)\"?", re.MULTILINE)


def _parse_service_describe(text: str) -> dict[str, Any]:
    """Extract the routing-relevant fields from a kubectl describe svc output."""
    if not isinstance(text, str):
        return {}
    name_match = _SERVICE_NAME_RE.search(text)
    port_matches = _SERVICE_PORT_RE.findall(text)
    target_matches = _SERVICE_TARGET_PORT_RE.findall(text)
    endpoints_match = _SERVICE_ENDPOINTS_RE.search(text)
    return {
        "name": name_match.group(1) if name_match else None,
        # ``Port:`` lines: list of (port_name, port_number, proto).
        "ports": [(n, int(p), proto) for (n, p, proto) in port_matches],
        # ``TargetPort:`` lines: list of (port_value, proto). port_value
        # may be a number ("9555") or a name ("grpc") — we keep both
        # shapes since CloudOpsBench varies.
        "target_ports": [(v, proto) for (v, proto) in target_matches],
        "endpoints": endpoints_match.group(1).strip() if endpoints_match else None,
    }


def _parse_env_service_refs(yaml_text: str) -> list[tuple[str, str]]:
    """Return [(env_var_name, value)] for env vars hinting at service refs.

    Only env vars whose name contains one of ``_ENV_NAME_HINTS`` are
    returned, since the LLM doesn't need to see ``PORT=8080`` at this
    layer. The values are emitted verbatim — downstream comparison is
    string-based.
    """
    if not isinstance(yaml_text, str):
        return []
    out: list[tuple[str, str]] = []
    for match in _ENV_VALUE_RE.finditer(yaml_text):
        name = match.group(1).strip()
        value = match.group(2).strip()
        if any(hint in name.upper() for hint in _ENV_NAME_HINTS):
            out.append((name, value))
    return out


def _analyze_service_routing_invoker(snapshot_tools: Any):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        namespace = (args or {}).get("namespace")
        if not namespace:
            return _failure("analyze_service_routing", "missing required arg: namespace")
        target = (args or {}).get("service_name")

        # Step 1: enumerate services. If the caller named one, we still
        # list services so we can flag empty-endpoints across the namespace.
        svc_list_text = _safe_invoke(
            snapshot_tools,
            "GetResources",
            {"resource_type": "services", "namespace": namespace},
        )
        if svc_list_text is None or _is_error_payload(svc_list_text):
            return _failure(
                "analyze_service_routing",
                f"GetResources(services) unavailable for namespace={namespace}",
            )
        # Pull service names from the first column of kubectl get output,
        # skipping the header line.
        service_names: list[str] = []
        for line in str(svc_list_text).splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            first = line.split()[0]
            if first and first not in {"NAME", "kubernetes"}:
                service_names.append(first)

        if target:
            service_names = [s for s in service_names if s == target] or [target]

        # Step 2: describe each service, parse its port spec.
        service_records: list[dict[str, Any]] = []
        for svc in service_names:
            describe_text = _safe_invoke(
                snapshot_tools,
                "DescribeResource",
                {"resource_type": "services", "name": svc, "namespace": namespace},
            )
            if describe_text is None or _is_error_payload(describe_text):
                continue
            parsed = _parse_service_describe(
                describe_text if isinstance(describe_text, str) else str(describe_text)
            )
            if not parsed:
                continue
            parsed["raw_name"] = svc
            service_records.append(parsed)

        # Step 3: for each service, also pull the matching deployment
        # YAML and harvest service-ref env vars across deployments. We
        # intentionally pull every deployment YAML once — CloudOpsBench
        # snapshots cap at ~10 services and the cost is bounded.
        env_refs_by_deployment: dict[str, list[tuple[str, str]]] = {}
        for svc in service_names:
            yaml_text = _safe_invoke(
                snapshot_tools,
                "GetAppYAML",
                {"app_name": svc, "namespace": namespace},
            )
            if yaml_text is None or _is_error_payload(yaml_text):
                continue
            refs = _parse_env_service_refs(
                yaml_text if isinstance(yaml_text, str) else str(yaml_text)
            )
            if refs:
                env_refs_by_deployment[svc] = refs

        # Step 4: detect issues. Three classes:
        #
        #   (a) Service has no endpoints — selector mismatch, often the
        #       leading indicator of ``service_selector_mismatch``.
        #   (b) Service Port and TargetPort numerically disagree (e.g.
        #       Port: 5000 → TargetPort: 5050, the canonical
        #       ``service_port_mapping_mismatch`` shape).
        #   (c) An env var like ``EMAIL_SERVICE_ADDR=emailservice:5000``
        #       references a service:port pair that doesn't appear among
        #       any service's exposed ports — the canonical
        #       ``service_env_var_address_mismatch`` shape.
        empty_endpoints: list[str] = []
        port_target_mismatches: list[dict[str, Any]] = []
        for rec in service_records:
            name = rec.get("raw_name")
            endpoints_value = rec.get("endpoints")
            if endpoints_value and endpoints_value.strip().lower() in {"<none>", "none", ""}:
                empty_endpoints.append(name)
            ports = rec.get("ports") or []
            targets = rec.get("target_ports") or []
            for (i, (_pname, port_num, _proto)) in enumerate(ports):
                if i >= len(targets):
                    continue
                target_value, _proto2 = targets[i]
                # Numeric mismatch only flags integer comparisons —
                # named target ports (``http``, ``grpc``) are valid as
                # long as the backing pod declares the name. We don't
                # have container ports parsed yet; named targets are
                # left for the LLM to check via DescribeResource(pod).
                if str(target_value).isdigit() and int(target_value) != port_num:
                    port_target_mismatches.append(
                        {
                            "service": name,
                            "service_port": port_num,
                            "target_port": int(target_value),
                        }
                    )

        # Build a service-port lookup for env-var validation:
        # {"emailservice": {5000, 5050}, "frontend": {80}, ...}.
        service_port_lookup: dict[str, set[int]] = {}
        for rec in service_records:
            name = rec.get("raw_name")
            if not name:
                continue
            ports = {p for (_n, p, _proto) in (rec.get("ports") or [])}
            ports.update(
                int(t) for (t, _proto) in (rec.get("target_ports") or []) if str(t).isdigit()
            )
            if ports:
                service_port_lookup.setdefault(name, set()).update(ports)

        env_mismatches: list[dict[str, Any]] = []
        for deployment, refs in env_refs_by_deployment.items():
            for env_name, value in refs:
                # Most refs look like ``service:port`` or ``http://service:port``
                # or just ``service``. We only flag the ones we can parse.
                ref_match = re.search(r"([a-z][a-z0-9-]*):(\d+)", value)
                if ref_match is None:
                    continue
                ref_service = ref_match.group(1)
                ref_port = int(ref_match.group(2))
                exposed = service_port_lookup.get(ref_service)
                if exposed is None:
                    # Unknown service — could be cross-namespace; don't flag.
                    continue
                if ref_port not in exposed:
                    env_mismatches.append(
                        {
                            "deployment": deployment,
                            "env_var": env_name,
                            "value": value,
                            "ref_service": ref_service,
                            "ref_port": ref_port,
                            "exposed_ports": sorted(exposed),
                        }
                    )

        if not empty_endpoints and not port_target_mismatches and not env_mismatches:
            summary = (
                f"analyze_service_routing(namespace={namespace}): {len(service_records)} "
                f"service(s) checked, no port-mapping or env-var mismatches found."
            )
            return RawToolOutput(
                output={
                    "namespace": namespace,
                    "checked_services": [r.get("raw_name") for r in service_records],
                    # Mirror the dirty-path schema so callers can read
                    # the same keys regardless of outcome.
                    "empty_endpoints": [],
                    "port_target_mismatches": [],
                    "env_mismatches": [],
                },
                output_summary=summary,
                citations=[
                    {
                        "source_type": "cloudopsbench:analyze_service_routing",
                        "source_ref": namespace,
                    }
                ],
                valid=True,
                redaction_status="clean",
                status="completed",
            )

        clauses: list[str] = []
        for svc in empty_endpoints:
            # Triggers ``service_selector_mismatch`` ontology rule.
            clauses.append(f"Service {svc} has no endpoints available for service")
        for m in port_target_mismatches:
            # Triggers ``service_port_mapping_mismatch`` (new rule below).
            clauses.append(
                f"Service {m['service']} port mapping mismatch: "
                f"service port {m['service_port']} does not have a port named, "
                f"TargetPort is {m['target_port']}"
            )
        for m in env_mismatches:
            # Triggers ``service_env_var_address_mismatch`` (new rule below).
            clauses.append(
                f"Deployment {m['deployment']}: env var {m['env_var']}={m['value']} "
                f"references service address mismatch: {m['ref_service']}:{m['ref_port']} "
                f"but service {m['ref_service']} exposes {sorted(m['exposed_ports'])}"
            )
        summary = (
            f"analyze_service_routing(namespace={namespace}): "
            f"{len(empty_endpoints) + len(port_target_mismatches) + len(env_mismatches)} "
            f"routing issue(s) detected.\n" + "\n".join(clauses)
        )
        return RawToolOutput(
            output={
                "namespace": namespace,
                "empty_endpoints": empty_endpoints,
                "port_target_mismatches": port_target_mismatches,
                "env_mismatches": env_mismatches,
            },
            output_summary=summary,
            citations=[
                {
                    "source_type": "cloudopsbench:analyze_service_routing",
                    "source_ref": namespace,
                }
            ],
            valid=True,
            redaction_status="clean",
            status="completed",
        )

    return invoke


# ----------------------------------------------------------------------
# Registry wiring
# ----------------------------------------------------------------------

_INVOKER_FACTORIES: dict[str, Any] = {
    "analyze_admission_events": _analyze_admission_events_invoker,
    "analyze_node_dataplane": _analyze_node_dataplane_invoker,
    "analyze_service_routing": _analyze_service_routing_invoker,
}


def register_cloudops_analyzers(registry: ToolRegistry, snapshot_tools: Any) -> None:
    """Register the K8sGPT-style analyzer tools alongside the raw cloudops tools.

    Idempotent on the same registry — re-registering a tool overwrites
    the previous entry, which is fine since both registrations point at
    the same snapshot. The registry rejects mutating tools at register
    time, so the read-only contract is enforced regardless.
    """
    for definition in ANALYZER_TOOL_DEFINITIONS:
        factory = _INVOKER_FACTORIES.get(definition.name)
        if factory is None:  # pragma: no cover — defensive
            continue
        registry.register(definition, factory(snapshot_tools))


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _safe_invoke(snapshot_tools: Any, tool_name: str, args: dict[str, Any]) -> Any:
    """Wrap snapshot_tools.invoke to never raise — returns None on error.

    ``snapshot_tools.invoke`` may raise if the snapshot is malformed; we
    treat any exception as a missing key and let the analyzer continue
    with whatever it has. Catching ``Exception`` is intentional: tests
    inject fakes that may raise different types.
    """
    try:
        return snapshot_tools.invoke(tool_name, args)
    except Exception:
        return None


def _is_error_payload(payload: Any) -> bool:
    """Detect the ``{'error': ...}`` shape ``CloudOpsSnapshotTools`` emits on miss."""
    return isinstance(payload, dict) and "error" in payload and len(payload) <= 2


def _failure(tool_name: str, message: str) -> RawToolOutput:
    return RawToolOutput(
        output={"error": message},
        output_summary=f"{tool_name}: {message}",
        citations=[],
        valid=False,
        redaction_status="clean",
        status="failed",
        error=message,
    )
