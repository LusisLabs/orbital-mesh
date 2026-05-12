"""Tests for the K8sGPT-style cloudops analyzer tools.

Each analyzer composes multiple snapshot calls into a structured
``RawToolOutput`` whose ``output_summary`` is the contract surface for
the cloudops ontology. Tests verify both the parsing logic in isolation
and the end-to-end summary text against synthetic snapshots, then
re-run the cloudops ontology over the produced summaries to confirm
the rules fire on the canonical CloudOpsBench labels.
"""

from __future__ import annotations

import unittest
from typing import Any

from services.investigation.cloudops_analyzers import (
    ANALYZER_TOOL_DEFINITIONS,
    ANALYZER_TOOL_NAMES,
    _NODE_DAEMONS,
    _analyze_admission_events_invoker,
    _analyze_node_dataplane_invoker,
    _analyze_service_routing_invoker,
    _parse_env_service_refs,
    _parse_service_describe,
    _parse_systemd_active_state,
    register_cloudops_analyzers,
)
from services.investigation.cloudops_ontology import rank_root_causes
from services.investigation.harness.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeSnapshotTools:
    """Records calls and returns canned responses by (tool_name, args).

    Args dicts are matched on a stable string form so callers don't
    have to worry about key ordering. Missing keys return ``None``,
    matching the analyzer's expected ``snapshot_tools.invoke`` contract
    on a cache miss (we use ``None`` rather than the ``{"error": ...}``
    shape since both are exercised in production).
    """

    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def invoke(self, tool_name: str, args: dict[str, Any]) -> Any:
        self.calls.append((tool_name, dict(args or {})))
        key = (tool_name, _stable_args(args or {}))
        return self._responses.get(key)


def _stable_args(args: dict[str, Any]) -> str:
    return ",".join(f"{k}={args[k]}" for k in sorted(args))


# ---------------------------------------------------------------------------
# Pure-parser tests
# ---------------------------------------------------------------------------


class ParseSystemdActiveStateTests(unittest.TestCase):
    def test_active_running(self) -> None:
        text = (
            "Status: ● containerd.service - containerd container runtime\n"
            "     Loaded: loaded (/etc/systemd/system/containerd.service; enabled; vendor preset: enabled)\n"
            "     Active: active (running) since Fri 2025-11-28 15:33:20 CST; 0h 14min ago\n"
        )
        self.assertEqual(_parse_systemd_active_state(text), "active")

    def test_inactive_dead(self) -> None:
        text = (
            "Status: ● containerd.service - containerd container runtime\n"
            "     Loaded: loaded\n"
            "     Active: inactive (dead) since Thu 2025-12-11 10:53:00 CST; 1min ago\n"
        )
        self.assertEqual(_parse_systemd_active_state(text), "inactive")

    def test_failed(self) -> None:
        text = "     Active: failed (Result: exit-code) since ..."
        self.assertEqual(_parse_systemd_active_state(text), "failed")

    def test_no_active_line(self) -> None:
        self.assertIsNone(_parse_systemd_active_state("Service: kubelet\nNode: master\n"))

    def test_non_string_input(self) -> None:
        # Defensive: parser is called on whatever the snapshot returns.
        self.assertIsNone(_parse_systemd_active_state({"oops": True}))  # type: ignore[arg-type]
        self.assertIsNone(_parse_systemd_active_state(None))  # type: ignore[arg-type]


class ParseServiceDescribeTests(unittest.TestCase):
    def test_extracts_ports_and_endpoints(self) -> None:
        # Verbatim shape from the boutique snapshot we sampled in the
        # 521-scenario eval — name, single port row, single targetport
        # row, plus an Endpoints line. Whitespace varies between fields
        # in real kubectl output; the regex is anchored to the field
        # name so layout drift doesn't break extraction.
        text = (
            "Name:                     emailservice\n"
            "Namespace:                boutique\n"
            "Selector:                 app=emailservice\n"
            "Type:                     ClusterIP\n"
            "Port:                     grpc  5000/TCP\n"
            "TargetPort:               5050/TCP\n"
            "Endpoints:                172.20.1.222:5050\n"
        )
        parsed = _parse_service_describe(text)
        self.assertEqual(parsed["name"], "emailservice")
        self.assertEqual(parsed["ports"], [("grpc", 5000, "TCP")])
        self.assertEqual(parsed["target_ports"], [("5050", "TCP")])
        self.assertEqual(parsed["endpoints"], "172.20.1.222:5050")

    def test_empty_endpoints_marker(self) -> None:
        text = (
            "Name:                     orphan-svc\n"
            "Port:                     http  80/TCP\n"
            "TargetPort:               http/TCP\n"
            "Endpoints:                <none>\n"
        )
        parsed = _parse_service_describe(text)
        self.assertEqual(parsed["endpoints"], "<none>")
        # Named target port preserved verbatim — analyzer only flags
        # numeric mismatches, named refs are LLM territory.
        self.assertEqual(parsed["target_ports"], [("http", "TCP")])

    def test_non_string_returns_empty(self) -> None:
        self.assertEqual(_parse_service_describe(42), {})  # type: ignore[arg-type]


class ParseEnvServiceRefsTests(unittest.TestCase):
    def test_extracts_addr_pattern(self) -> None:
        yaml_text = (
            "      containers:\n"
            "      - name: server\n"
            "        env:\n"
            '        - name: PORT\n          value: "8080"\n'
            '        - name: PRODUCT_CATALOG_SERVICE_ADDR\n          value: "productcatalogservice:3550"\n'
            '        - name: CART_SERVICE_ADDR\n          value: "cartservice:7070"\n'
        )
        refs = _parse_env_service_refs(yaml_text)
        # Only ADDR-suffixed names; PORT is excluded.
        names = [name for (name, _v) in refs]
        self.assertIn("PRODUCT_CATALOG_SERVICE_ADDR", names)
        self.assertIn("CART_SERVICE_ADDR", names)
        self.assertNotIn("PORT", names)

    def test_url_and_endpoint_hints(self) -> None:
        yaml_text = (
            '        - name: REDIS_URL\n          value: "redis://redis-cart:6379"\n'
            '        - name: API_ENDPOINT\n          value: "http://frontend:80/api"\n'
        )
        refs = _parse_env_service_refs(yaml_text)
        self.assertEqual(len(refs), 2)


# ---------------------------------------------------------------------------
# analyze_admission_events
# ---------------------------------------------------------------------------


# Verbatim slice from the failing 521-run scenario admission/1 — the
# canonical "missing service account" failure ships here as a `Warning
# FailedCreate ... serviceaccount "X" not found` line buried in
# kubectl get events output.
ADMISSION_EVENTS_FIXTURE = """\
119s        Normal    Created             pod/cartservice-79b49f5555-h95zb              Created container server
119s        Normal    Started             pod/cartservice-79b49f5555-h95zb              Started container server
119s        Normal    Pulled              pod/cartservice-79b49f5555-h95zb              Container image already present on machine
36s         Warning   FailedCreate        replicaset/adservice-6f86c56644               Error creating: pods "adservice-6f86c56644-" is forbidden: error looking up service account boutique/services: serviceaccount "services" not found
"""


class AnalyzeAdmissionEventsTests(unittest.TestCase):
    def test_surfaces_missing_serviceaccount_event(self) -> None:
        snap = FakeSnapshotTools(
            {
                ("GetResources", _stable_args({"resource_type": "events", "namespace": "boutique"})): ADMISSION_EVENTS_FIXTURE,
            }
        )
        out = _analyze_admission_events_invoker(snap)({"namespace": "boutique"})
        self.assertTrue(out.valid)
        self.assertEqual(out.status, "completed")
        # The summary must contain the trigger phrase the existing
        # ``missing_service_account`` ontology rule searches for —
        # otherwise the LLM's choice to call this tool yields nothing.
        self.assertIn('serviceaccount "services" not found', out.output_summary)
        # And the structured payload should expose the count for the
        # downstream caller / decision engine.
        self.assertEqual(out.output["warning_event_count"], 1)

    def test_drives_ontology_to_correct_label(self) -> None:
        snap = FakeSnapshotTools(
            {
                ("GetResources", _stable_args({"resource_type": "events", "namespace": "boutique"})): ADMISSION_EVENTS_FIXTURE,
            }
        )
        out = _analyze_admission_events_invoker(snap)({"namespace": "boutique"})
        ranked = rank_root_causes([out.output_summary])
        labels = [r.root_cause for r in ranked]
        # Real proof of work: the ontology produces the canonical
        # CloudOpsBench label from the analyzer's text.
        self.assertIn("missing_service_account", labels)

    def test_no_events_returns_clean_valid(self) -> None:
        # Snapshot with only Normal events; no warnings.
        normal_only = (
            "10s   Normal   Created   pod/foo   Created container server\n"
            "10s   Normal   Started   pod/foo   Started container server\n"
        )
        snap = FakeSnapshotTools(
            {("GetResources", _stable_args({"resource_type": "events", "namespace": "boutique"})): normal_only}
        )
        out = _analyze_admission_events_invoker(snap)({"namespace": "boutique"})
        self.assertTrue(out.valid)
        self.assertEqual(out.output["warning_event_count"], 0)

    def test_missing_namespace_arg_fails_explicitly(self) -> None:
        snap = FakeSnapshotTools({})
        out = _analyze_admission_events_invoker(snap)({})
        self.assertFalse(out.valid)
        self.assertEqual(out.status, "failed")
        self.assertIn("namespace", (out.error or ""))

    def test_snapshot_miss_fails_cleanly(self) -> None:
        snap = FakeSnapshotTools({})  # nothing matches
        out = _analyze_admission_events_invoker(snap)({"namespace": "missing-ns"})
        self.assertFalse(out.valid)
        self.assertEqual(out.status, "failed")

    def test_long_warning_list_is_truncated(self) -> None:
        # 30 distinct warnings — analyzer should keep only the first 12
        # in the summary so context stays bounded, but expose the total
        # in the structured payload.
        lines = [
            f"5s   Warning   FailedScheduling   pod/svc-{i}   0/4 nodes are available"
            for i in range(30)
        ]
        snap = FakeSnapshotTools(
            {("GetResources", _stable_args({"resource_type": "events", "namespace": "boutique"})): "\n".join(lines)}
        )
        out = _analyze_admission_events_invoker(snap)({"namespace": "boutique"})
        self.assertTrue(out.valid)
        self.assertEqual(out.output["warning_event_count"], 30)
        # Structured payload keeps every event; summary truncates.
        self.assertEqual(len(out.output["events"]), 30)
        self.assertIn("more suppressed", out.output_summary)


# ---------------------------------------------------------------------------
# analyze_node_dataplane
# ---------------------------------------------------------------------------


SYSTEMD_ACTIVE = (
    "Service: containerd\n"
    "Node: {node}\n"
    "Status: ● {svc}.service - {svc}\n"
    "     Loaded: loaded\n"
    "     Active: active (running) since now\n"
)
SYSTEMD_INACTIVE = (
    "Service: {svc}\n"
    "Node: {node}\n"
    "Status: ● {svc}.service - {svc}\n"
    "     Loaded: loaded\n"
    "     Active: inactive (dead) since now\n"
)


def _all_active_responses() -> dict[tuple[str, str], Any]:
    """Build a complete systemd-active response set for every (node, daemon).

    The analyzer skips ``kube-scheduler`` on workers (it's master-only
    in the CloudOpsBench cluster shape) so we mirror that here.
    """
    out: dict[tuple[str, str], Any] = {}
    for node in ("master", "worker-01", "worker-02", "worker-03"):
        for daemon in _NODE_DAEMONS:
            if daemon == "kube-scheduler" and node != "master":
                continue
            key = ("CheckNodeServiceStatus", _stable_args({"node_name": node, "service_name": daemon}))
            out[key] = SYSTEMD_ACTIVE.format(svc=daemon, node=node)
    return out


class AnalyzeNodeDataplaneTests(unittest.TestCase):
    def test_all_healthy(self) -> None:
        snap = FakeSnapshotTools(_all_active_responses())
        out = _analyze_node_dataplane_invoker(snap)({})
        self.assertTrue(out.valid)
        self.assertEqual(out.output["unhealthy"], [])
        self.assertIn("all reported Active: active", out.output_summary)

    def test_one_inactive_containerd_drives_label(self) -> None:
        responses = _all_active_responses()
        # Flip worker-01's containerd to inactive — the canonical
        # ``containerd_unavailable`` failure shape.
        responses[("CheckNodeServiceStatus", _stable_args({"node_name": "worker-01", "service_name": "containerd"}))] = (
            SYSTEMD_INACTIVE.format(svc="containerd", node="worker-01")
        )
        snap = FakeSnapshotTools(responses)
        out = _analyze_node_dataplane_invoker(snap)({})
        self.assertTrue(out.valid)
        self.assertEqual(len(out.output["unhealthy"]), 1)
        self.assertEqual(out.output["unhealthy"][0]["daemon"], "containerd")
        self.assertEqual(out.output["unhealthy"][0]["node"], "worker-01")
        # The summary's text drives the ontology to the canonical label.
        ranked = rank_root_causes([out.output_summary])
        labels = [r.root_cause for r in ranked]
        self.assertIn("containerd_unavailable", labels)

    def test_kube_proxy_and_kubelet_each_get_their_own_label(self) -> None:
        responses = _all_active_responses()
        # Flip kube-proxy on master, kubelet on worker-02.
        responses[("CheckNodeServiceStatus", _stable_args({"node_name": "master", "service_name": "kube-proxy"}))] = (
            SYSTEMD_INACTIVE.format(svc="kube-proxy", node="master")
        )
        responses[("CheckNodeServiceStatus", _stable_args({"node_name": "worker-02", "service_name": "kubelet"}))] = (
            SYSTEMD_INACTIVE.format(svc="kubelet", node="worker-02")
        )
        snap = FakeSnapshotTools(responses)
        out = _analyze_node_dataplane_invoker(snap)({})
        ranked = rank_root_causes([out.output_summary])
        labels = [r.root_cause for r in ranked]
        # Both labels should appear since the patterns are pinned to
        # the daemon name.
        self.assertIn("kube_proxy_unavailable", labels)
        self.assertIn("kubelet_unavailable", labels)

    def test_node_filter_narrows_probes(self) -> None:
        # Pass node_name to scope; analyzer should only probe that node.
        responses = _all_active_responses()
        snap = FakeSnapshotTools(responses)
        out = _analyze_node_dataplane_invoker(snap)({"node_name": "worker-01"})
        # All checked pairs should be on worker-01.
        for tool_name, args in snap.calls:
            self.assertEqual(tool_name, "CheckNodeServiceStatus")
            self.assertEqual(args.get("node_name"), "worker-01")
        self.assertTrue(out.valid)

    def test_snapshot_miss_returns_zero_unhealthy(self) -> None:
        # Empty snapshot — no daemons reported. Analyzer should not
        # claim anything is unhealthy (we don't know).
        snap = FakeSnapshotTools({})
        out = _analyze_node_dataplane_invoker(snap)({})
        self.assertTrue(out.valid)
        self.assertEqual(out.output["unhealthy"], [])


# ---------------------------------------------------------------------------
# analyze_service_routing
# ---------------------------------------------------------------------------


# Service list output from kubectl get services -n boutique. First column
# is the service name; analyzer drops the header and the ``kubernetes``
# system service.
SVC_LIST = """\
NAME                    TYPE        CLUSTER-IP        EXTERNAL-IP   PORT(S)    AGE
emailservice            ClusterIP   10.68.241.177     <none>        5000/TCP   2m
frontend                ClusterIP   10.68.241.178     <none>        80/TCP     2m
kubernetes              ClusterIP   10.68.0.1         <none>        443/TCP    1d
"""

# emailservice describe with a port mismatch (Service.port=5000 but
# TargetPort=5050 — the canonical ``service_port_mapping_mismatch``).
EMAILSERVICE_DESCRIBE_MISMATCH = """\
Name:                     emailservice
Namespace:                boutique
Labels:                   app=emailservice
Selector:                 app=emailservice
Type:                     ClusterIP
Port:                     grpc  5000/TCP
TargetPort:               5050/TCP
Endpoints:                172.20.1.222:5050
"""

EMAILSERVICE_DESCRIBE_OK = """\
Name:                     emailservice
Namespace:                boutique
Selector:                 app=emailservice
Type:                     ClusterIP
Port:                     grpc  5000/TCP
TargetPort:               5000/TCP
Endpoints:                172.20.1.222:5000
"""

FRONTEND_DESCRIBE_OK = """\
Name:                     frontend
Namespace:                boutique
Type:                     ClusterIP
Port:                     http  80/TCP
TargetPort:               80/TCP
Endpoints:                172.20.1.219:80
"""

# Frontend deployment YAML referencing emailservice on the wrong port —
# the ``service_env_var_address_mismatch`` shape.
FRONTEND_YAML_BAD_REF = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
spec:
  template:
    spec:
      containers:
      - name: server
        env:
        - name: PORT
          value: "8080"
        - name: EMAIL_SERVICE_ADDR
          value: "emailservice:5050"
"""

# Same env var pointing at the TargetPort of a port-mismatched service
# (emailservice has Port=5000, TargetPort=5050; the env var references
# 5050). Pre-fix this would silently pass validation because the
# service-port lookup conflated Port and TargetPort. The bug Cursor's
# review caught: clients can only DNS-reach Service Port=5000, never
# 5050. This fixture exercises the canonical port-mismatch failure
# (Service.Port vs Pod.containerPort) compounded by an env var pinned
# to the wrong side.
FRONTEND_YAML_REFS_TARGETPORT = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
spec:
  template:
    spec:
      containers:
      - name: server
        env:
        - name: PORT
          value: "8080"
        - name: EMAIL_SERVICE_ADDR
          value: "emailservice:5050"
"""

EMAILSERVICE_YAML_OK = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: emailservice
spec:
  template:
    spec:
      containers:
      - name: server
        env:
        - name: PORT
          value: "5000"
"""


class AnalyzeServiceRoutingTests(unittest.TestCase):
    def test_port_target_mismatch_drives_label(self) -> None:
        snap = FakeSnapshotTools(
            {
                ("GetResources", _stable_args({"resource_type": "services", "namespace": "boutique"})): SVC_LIST,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_DESCRIBE_MISMATCH,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "frontend", "namespace": "boutique"})): FRONTEND_DESCRIBE_OK,
                ("GetAppYAML", _stable_args({"app_name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_YAML_OK,
                ("GetAppYAML", _stable_args({"app_name": "frontend", "namespace": "boutique"})): "",
            }
        )
        out = _analyze_service_routing_invoker(snap)({"namespace": "boutique"})
        self.assertTrue(out.valid)
        self.assertEqual(len(out.output["port_target_mismatches"]), 1)
        ranked = rank_root_causes([out.output_summary])
        labels = [r.root_cause for r in ranked]
        self.assertIn("service_port_mapping_mismatch", labels)

    def test_env_var_address_mismatch_drives_label(self) -> None:
        # Same emailservice describe (correct), but frontend YAML
        # references emailservice:5050 while the service exposes 5000.
        snap = FakeSnapshotTools(
            {
                ("GetResources", _stable_args({"resource_type": "services", "namespace": "boutique"})): SVC_LIST,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_DESCRIBE_OK,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "frontend", "namespace": "boutique"})): FRONTEND_DESCRIBE_OK,
                ("GetAppYAML", _stable_args({"app_name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_YAML_OK,
                ("GetAppYAML", _stable_args({"app_name": "frontend", "namespace": "boutique"})): FRONTEND_YAML_BAD_REF,
            }
        )
        out = _analyze_service_routing_invoker(snap)({"namespace": "boutique"})
        self.assertTrue(out.valid)
        self.assertEqual(len(out.output["env_mismatches"]), 1)
        ranked = rank_root_causes([out.output_summary])
        labels = [r.root_cause for r in ranked]
        self.assertIn("service_env_var_address_mismatch", labels)

    def test_env_var_referencing_target_port_is_flagged(self) -> None:
        # Regression for the bug Cursor's review caught: when a service
        # has Port != TargetPort and a deployment env var points at the
        # TargetPort, pre-fix the env-var validation silently accepted
        # the value because it scanned both Port and TargetPort into
        # ``service_port_lookup``. Only ``Port:`` is DNS-reachable; the
        # bug masked exactly the failure this analyzer is meant to find.
        snap = FakeSnapshotTools(
            {
                ("GetResources", _stable_args({"resource_type": "services", "namespace": "boutique"})): SVC_LIST,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_DESCRIBE_MISMATCH,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "frontend", "namespace": "boutique"})): FRONTEND_DESCRIBE_OK,
                ("GetAppYAML", _stable_args({"app_name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_YAML_OK,
                ("GetAppYAML", _stable_args({"app_name": "frontend", "namespace": "boutique"})): FRONTEND_YAML_REFS_TARGETPORT,
            }
        )
        out = _analyze_service_routing_invoker(snap)({"namespace": "boutique"})
        self.assertTrue(out.valid)
        # Both failures land — the service-side mismatch AND the
        # client-side env-var mismatch.
        self.assertEqual(len(out.output["port_target_mismatches"]), 1)
        self.assertEqual(len(out.output["env_mismatches"]), 1)
        env_issue = out.output["env_mismatches"][0]
        self.assertEqual(env_issue["env_var"], "EMAIL_SERVICE_ADDR")
        self.assertEqual(env_issue["ref_port"], 5050)
        # Service port lookup must NOT include 5050 (the TargetPort).
        self.assertEqual(env_issue["exposed_ports"], [5000])
        ranked = rank_root_causes([out.output_summary])
        labels = [r.root_cause for r in ranked]
        self.assertIn("service_env_var_address_mismatch", labels)

    def test_clean_routing_returns_no_issues(self) -> None:
        snap = FakeSnapshotTools(
            {
                ("GetResources", _stable_args({"resource_type": "services", "namespace": "boutique"})): SVC_LIST,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_DESCRIBE_OK,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "frontend", "namespace": "boutique"})): FRONTEND_DESCRIBE_OK,
                ("GetAppYAML", _stable_args({"app_name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_YAML_OK,
                ("GetAppYAML", _stable_args({"app_name": "frontend", "namespace": "boutique"})): "",
            }
        )
        out = _analyze_service_routing_invoker(snap)({"namespace": "boutique"})
        self.assertTrue(out.valid)
        self.assertEqual(out.output["empty_endpoints"], [])
        self.assertEqual(out.output["port_target_mismatches"], [])
        self.assertEqual(out.output["env_mismatches"], [])

    def test_missing_namespace_arg_fails(self) -> None:
        snap = FakeSnapshotTools({})
        out = _analyze_service_routing_invoker(snap)({})
        self.assertFalse(out.valid)
        self.assertEqual(out.status, "failed")

    def test_missing_services_list_fails_cleanly(self) -> None:
        snap = FakeSnapshotTools({})  # no services key
        out = _analyze_service_routing_invoker(snap)({"namespace": "boutique"})
        self.assertFalse(out.valid)


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------


class RegistryWiringTests(unittest.TestCase):
    def test_register_adds_three_tools(self) -> None:
        registry = ToolRegistry()
        snap = FakeSnapshotTools({})
        register_cloudops_analyzers(registry, snap)
        names = {d.name for d in registry.list_definitions()}
        self.assertIn("analyze_admission_events", names)
        self.assertIn("analyze_node_dataplane", names)
        self.assertIn("analyze_service_routing", names)
        self.assertEqual(set(ANALYZER_TOOL_NAMES), set(names))

    def test_all_tools_are_read_only(self) -> None:
        # The critic enforces read-only at runtime, but a registration
        # bug could ship a mutating analyzer if we get lazy. Pin it.
        for definition in ANALYZER_TOOL_DEFINITIONS:
            self.assertEqual(definition.mutation_class, "read_only", definition.name)


# ---------------------------------------------------------------------------
# Graph-backed path: analyze_service_routing consults InfraGraph when
# populated. Phase C of the topology integration — when the populator
# has covered the trigger namespace, the analyzer skips kubectl-describe
# round-trips and uses graph edges for empty-endpoints detection. The
# regex path stays the fallback; tests above cover it exhaustively.
# ---------------------------------------------------------------------------


import tempfile  # noqa: E402 — keeps the graph imports adjacent to the new tests

from services.investigation.cloudops_analyzers import (  # noqa: E402
    _decompose_graph_ports,
    _service_records_from_graph,
)
from services.investigation.topology_builder import populate as _populate_topology  # noqa: E402
from shared.mesh_runtime.infra_graph import InfraGraph  # noqa: E402


def _routing_snapshot(*, frontend_yaml: str = "", emailservice_yaml: str = "") -> dict[str, Any]:
    """Build a CloudOps-shaped snapshot suitable for both the populator
    and the analyzer.

    The populator reads ``DescribeResource`` cache entries to materialize
    the graph; the analyzer reads ``GetAppYAML`` to harvest env-var refs
    (the graph doesn't model container env yet). Both keys must be
    present for the graph-backed path to be exercised end-to-end with
    the env-mismatch branch.
    """
    return {
        "tool_cache": {
            'GetResources:{"resource_type":"services","namespace":"boutique"}': SVC_LIST,
            'DescribeResource:{"resource_type":"services","name":"emailservice","namespace":"boutique"}': EMAILSERVICE_DESCRIBE_MISMATCH,
            'DescribeResource:{"resource_type":"services","name":"frontend","namespace":"boutique"}': FRONTEND_DESCRIBE_OK,
            'GetAppYAML:{"app_name":"emailservice","namespace":"boutique"}': emailservice_yaml or EMAILSERVICE_YAML_OK,
            'GetAppYAML:{"app_name":"frontend","namespace":"boutique"}': frontend_yaml,
        }
    }


class DecomposeGraphPortsTests(unittest.TestCase):
    """The populator stores Service.attributes["ports"] verbatim from
    kubectl describe text. The analyzer needs the same (name, num, proto)
    / (target, proto) tuple shape its regex path produces, so the
    decomposer is on the hot path of the graph-backed branch.
    """

    def test_named_and_numeric_port(self) -> None:
        ports, targets = _decompose_graph_ports(
            [{"port": "grpc  5000/TCP", "target_port": "5050/TCP"}]
        )
        self.assertEqual(ports, [("grpc", 5000, "TCP")])
        self.assertEqual(targets, [("5050", "TCP")])

    def test_anonymous_port(self) -> None:
        ports, _ = _decompose_graph_ports([{"port": "80/TCP", "target_port": "80/TCP"}])
        self.assertEqual(ports, [("", 80, "TCP")])

    def test_named_target_port_preserved_verbatim(self) -> None:
        # Mirrors the regex path: named target ports are kept as strings;
        # only numeric mismatches drive port_target_mismatches downstream.
        _, targets = _decompose_graph_ports([{"port": "http  80/TCP", "target_port": "http/TCP"}])
        self.assertEqual(targets, [("http", "TCP")])

    def test_malformed_entries_skipped(self) -> None:
        ports, targets = _decompose_graph_ports(["not a dict", {"port": "no-protocol"}, {}])
        self.assertEqual(ports, [])
        self.assertEqual(targets, [])


class ServiceRecordsFromGraphTests(unittest.TestCase):
    """Fallback signal: ``None`` means "fall through to regex path",
    ``[]`` means "graph populated but no matching services". The
    analyzer relies on that distinction to know whether to short-
    circuit or to call DescribeResource.
    """

    def test_returns_none_when_graph_is_none(self) -> None:
        self.assertIsNone(_service_records_from_graph(None, "boutique", None))

    def test_returns_none_when_graph_empty(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            graph = InfraGraph(state)
            self.assertIsNone(_service_records_from_graph(graph, "boutique", None))

    def test_returns_none_when_namespace_uncovered(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            graph = InfraGraph(state)
            _populate_topology(graph, snapshot=_routing_snapshot(), namespace_hint="boutique")
            # Asking for a namespace the populator never saw → fall through.
            self.assertIsNone(_service_records_from_graph(graph, "other-ns", None))

    def test_records_mirror_regex_shape(self) -> None:
        with tempfile.TemporaryDirectory() as state:
            graph = InfraGraph(state)
            _populate_topology(graph, snapshot=_routing_snapshot(), namespace_hint="boutique")
            recs = _service_records_from_graph(graph, "boutique", None)
            self.assertIsNotNone(recs)
            names = sorted(r["raw_name"] for r in recs)
            self.assertEqual(names, ["emailservice", "frontend"])
            email = next(r for r in recs if r["raw_name"] == "emailservice")
            self.assertEqual(email["ports"], [("grpc", 5000, "TCP")])
            self.assertEqual(email["target_ports"], [("5050", "TCP")])
            # Selector matches no pods in this snapshot — graph edge count
            # of zero translates to the canonical "<none>" marker so the
            # downstream summary clause matches the same ontology rule
            # the regex path triggers.
            self.assertEqual(email["endpoints"], "<none>")


class AnalyzeServiceRoutingGraphPathTests(unittest.TestCase):
    """End-to-end: register the analyzer with an InfraGraph, run it,
    verify the same ontology labels fire. Critical contract — the
    summary text is what downstream rule-matching keys on, so changing
    the source must not change the output phrasing.
    """

    def _populate(self, frontend_yaml: str = "") -> tuple[InfraGraph, FakeSnapshotTools]:
        # Use a long-lived directory so the InfraGraph state survives
        # the populate call; tests clean up via the unittest tearDown.
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        graph = InfraGraph(self.tmpdir.name)
        snap_dict = _routing_snapshot(frontend_yaml=frontend_yaml)
        _populate_topology(graph, snapshot=snap_dict, namespace_hint="boutique")
        # The analyzer still calls GetAppYAML through snapshot_tools for
        # env-var harvesting; build a FakeSnapshotTools that exposes the
        # same YAML keys.
        snap = FakeSnapshotTools(
            {
                ("GetResources", _stable_args({"resource_type": "services", "namespace": "boutique"})): SVC_LIST,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_DESCRIBE_MISMATCH,
                ("DescribeResource", _stable_args({"resource_type": "services", "name": "frontend", "namespace": "boutique"})): FRONTEND_DESCRIBE_OK,
                ("GetAppYAML", _stable_args({"app_name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_YAML_OK,
                ("GetAppYAML", _stable_args({"app_name": "frontend", "namespace": "boutique"})): frontend_yaml,
            }
        )
        return graph, snap

    def test_graph_path_detects_port_target_mismatch(self) -> None:
        graph, snap = self._populate()
        out = _analyze_service_routing_invoker(snap, graph)({"namespace": "boutique"})
        self.assertTrue(out.valid)
        self.assertEqual(len(out.output["port_target_mismatches"]), 1)
        ranked = rank_root_causes([out.output_summary])
        self.assertIn("service_port_mapping_mismatch", [r.root_cause for r in ranked])

    def test_graph_path_skips_describe_calls(self) -> None:
        # Behavioral contract: when the graph covers the namespace, the
        # analyzer should NOT call DescribeResource/GetResources. The
        # snapshot calls list is the cheapest place to assert this —
        # only GetAppYAML calls should be recorded (env-var harvest).
        graph, snap = self._populate()
        _analyze_service_routing_invoker(snap, graph)({"namespace": "boutique"})
        tool_names_called = {name for (name, _args) in snap.calls}
        self.assertNotIn("DescribeResource", tool_names_called)
        self.assertNotIn("GetResources", tool_names_called)
        self.assertIn("GetAppYAML", tool_names_called)

    def test_graph_path_detects_env_var_address_mismatch(self) -> None:
        graph, snap = self._populate(frontend_yaml=FRONTEND_YAML_BAD_REF)
        out = _analyze_service_routing_invoker(snap, graph)({"namespace": "boutique"})
        self.assertTrue(out.valid)
        env_mismatches = out.output["env_mismatches"]
        # In this snapshot, emailservice has selector ``app=emailservice``
        # but no pods carry that label → the graph-backed branch also
        # surfaces ``service_selector_mismatch`` via empty endpoints.
        # The env-var mismatch must still appear alongside it.
        self.assertEqual(len(env_mismatches), 1)
        self.assertEqual(env_mismatches[0]["ref_service"], "emailservice")
        self.assertEqual(env_mismatches[0]["ref_port"], 5050)
        ranked = rank_root_causes([out.output_summary])
        self.assertIn("service_env_var_address_mismatch", [r.root_cause for r in ranked])

    def test_empty_graph_falls_back_to_regex_path(self) -> None:
        # Contract: an empty graph must not break analysis — the
        # snapshot-text path takes over cleanly. Reuse the existing
        # mismatch fixture; assert the label still fires.
        with tempfile.TemporaryDirectory() as state:
            empty_graph = InfraGraph(state)
            snap = FakeSnapshotTools(
                {
                    ("GetResources", _stable_args({"resource_type": "services", "namespace": "boutique"})): SVC_LIST,
                    ("DescribeResource", _stable_args({"resource_type": "services", "name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_DESCRIBE_MISMATCH,
                    ("DescribeResource", _stable_args({"resource_type": "services", "name": "frontend", "namespace": "boutique"})): FRONTEND_DESCRIBE_OK,
                    ("GetAppYAML", _stable_args({"app_name": "emailservice", "namespace": "boutique"})): EMAILSERVICE_YAML_OK,
                    ("GetAppYAML", _stable_args({"app_name": "frontend", "namespace": "boutique"})): "",
                }
            )
            out = _analyze_service_routing_invoker(snap, empty_graph)({"namespace": "boutique"})
            self.assertTrue(out.valid)
            self.assertEqual(len(out.output["port_target_mismatches"]), 1)
            # Regex path was used → DescribeResource must have been called.
            self.assertIn("DescribeResource", {n for (n, _) in snap.calls})


class RegisterPassesInfraGraphTests(unittest.TestCase):
    def test_register_threads_infra_graph_to_service_routing(self) -> None:
        # Bug shield: ``register_cloudops_analyzers`` must pass
        # ``infra_graph`` only to the analyzers that consume it.
        # Other analyzers stay on the snapshot_tools-only signature so
        # an accidental positional drift in factories doesn't ship a
        # broken registration.
        with tempfile.TemporaryDirectory() as state:
            graph = InfraGraph(state)
            _populate_topology(
                graph, snapshot=_routing_snapshot(), namespace_hint="boutique"
            )
            registry = ToolRegistry()
            snap = FakeSnapshotTools({})
            register_cloudops_analyzers(registry, snap, infra_graph=graph)
            entry = registry.get("cloudops", "analyze_service_routing")
            self.assertIsNotNone(entry)


if __name__ == "__main__":
    unittest.main()
