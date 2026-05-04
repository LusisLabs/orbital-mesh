from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.investigation.cloudops_tools import CloudOpsLoopPlanner, register_cloudops_tools
from services.investigation.harness import ToolRegistry
from services.runtime import MeshRuntimeEngine
from shared.mesh_runtime.config import RuntimeConfig

from .models import BenchmarkScenario


@dataclass(frozen=True)
class SnapshotToolCall:
    tool_name: str
    args: dict[str, Any]
    output: Any
    status: str = "completed"
    valid: bool = True
    relevance: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "args": self.args,
            "output_summary": _summarize(self.output),
            "status": self.status,
            "valid": self.valid,
            "relevance": self.relevance,
            "citation_ids": [f"cloudopsbench:{self.tool_name}"],
        }


class CloudOpsSnapshotTools:
    """Deterministic read-only tool facade for Cloud-OpsBench-style snapshots."""

    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.snapshot = snapshot
        self.calls: list[SnapshotToolCall] = []

    def invoke(self, tool_name: str, args: dict[str, Any] | None = None) -> Any:
        args = dict(args or {})
        tools = _snapshot_tools(self.snapshot)
        normalized_name = _cloudops_tool_name(tool_name)
        output = tools.get(tool_name) or tools.get(normalized_name)
        if output is None:
            output = _lookup_cloudops_cache(tools, normalized_name, args)
        valid = output is not None
        if output is None:
            output = {"error": f"tool {tool_name!r} not available in snapshot"}
        call = SnapshotToolCall(
            tool_name=normalized_name,
            args=args,
            output=output,
            status="completed" if valid else "invalid",
            valid=valid,
            relevance=1.0 if valid else 0.0,
        )
        self.calls.append(call)
        return output

    def replay_expert_trajectory(self, trajectory: list[str]) -> list[dict[str, Any]]:
        for step in trajectory:
            tool_name, args = _trajectory_step_to_tool_call(step)
            self.invoke(tool_name, args)
        return [call.to_dict() for call in self.calls]


@dataclass(frozen=True)
class CloudOpsSnapshotRunner:
    runtime_config: RuntimeConfig
    cloudopsbench_root: Path | None = None
    ground_truth_mode: str = "hidden"

    def run_scenario(self, scenario: BenchmarkScenario, raw_signal: dict[str, Any], *, iteration: int) -> dict[str, Any]:
        if self.ground_truth_mode not in {"hidden", "oracle"}:
            raise ValueError("cloudopsbench ground_truth_mode must be 'hidden' or 'oracle'")
        expose_ground_truth = self.ground_truth_mode == "oracle"
        snapshot = self._load_snapshot(scenario, raw_signal)
        tools = CloudOpsSnapshotTools(snapshot)
        trajectory = list(scenario.expert_trajectory or snapshot.get("expert_trajectory") or [])
        registry: ToolRegistry | None = None
        planner: CloudOpsLoopPlanner | None = None
        if expose_ground_truth:
            tool_trajectory = tools.replay_expert_trajectory(trajectory)
        else:
            # Hidden mode: hand the snapshot tools to the harness as a
            # cloudops domain pack. The harness loop selects calls; the
            # recorded snapshot calls become the scored tool_trajectory.
            registry = ToolRegistry()
            register_cloudops_tools(registry, tools)
            tool_trajectory = []
        signal = _snapshot_signal(snapshot, raw_signal, expose_ground_truth=expose_ground_truth)
        if registry is not None:
            from services.ingest.service import IngestService
            from services.trigger.service import TriggerService

            normalized = IngestService().normalize_signal(signal)
            trigger = TriggerService().detect(normalized)
            if trigger is not None:
                planner = CloudOpsLoopPlanner(trigger)
        outcome = MeshRuntimeEngine(config=self.runtime_config).run_sync(
            signal,
            scenario_name=f"cloudopsbench_{scenario.scenario_id}_{iteration}",
            registry=registry,
            planner=planner,
        )
        report = outcome.get("investigation_report") if isinstance(outcome.get("investigation_report"), dict) else {}
        report.setdefault("findings", [])
        report.setdefault("citations", [])
        root_cause = snapshot.get("root_cause") or scenario.expected_root_cause
        if expose_ground_truth and root_cause:
            report["findings"] = list(report["findings"]) + [
                {"kind": "cloudopsbench_root_cause", "summary": str(root_cause), "confidence": 1.0}
            ]
            report["citations"] = list(report["citations"]) + [{"source_type": "cloudopsbench_snapshot", "source_ref": scenario.scenario_id}]
            report["root_cause_candidates"] = [
                {
                    "rank": 1,
                    "root_cause": str(root_cause),
                    "confidence": 1.0,
                    "matched_patterns": ["oracle"],
                    "supporting_tools": [],
                    "citation_ids": [f"cloudopsbench:{scenario.scenario_id}"],
                }
            ]
        if registry is not None:
            tool_trajectory = [call.to_dict() for call in tools.calls]
        outcome["backend"] = "cloudopsbench"
        outcome["investigation_report"] = report
        outcome["tool_trajectory"] = tool_trajectory
        outcome["mttri_ms"] = 0.0
        outcome["cloudopsbench_ground_truth_mode"] = self.ground_truth_mode
        return outcome

    def _load_snapshot(self, scenario: BenchmarkScenario, raw_signal: dict[str, Any]) -> dict[str, Any]:
        inline = raw_signal.get("cloudopsbench_snapshot")
        if isinstance(inline, dict):
            return inline
        source_snapshot = scenario.source.get("snapshot_file") or scenario.source.get("cloudopsbench_case")
        if not source_snapshot:
            raise FileNotFoundError(
                "Cloud-OpsBench scenario requires raw_signal.cloudopsbench_snapshot or source.snapshot_file"
            )
        if self.cloudopsbench_root is None:
            raise FileNotFoundError("Cloud-OpsBench root is required for source.snapshot_file scenarios")
        path = self._resolve_snapshot_path(scenario, str(source_snapshot))
        if path.is_dir():
            return _load_official_case(path, scenario, expose_ground_truth=self.ground_truth_mode == "oracle")
        return json.loads(path.read_text(encoding="utf-8"))

    def _resolve_snapshot_path(self, scenario: BenchmarkScenario, source_snapshot: str) -> Path:
        assert self.cloudopsbench_root is not None
        root = self.cloudopsbench_root
        candidates = [
            root / source_snapshot,
            root / "benchmark" / source_snapshot,
        ]
        system = scenario.source.get("system")
        fault_category = scenario.source.get("fault_category")
        case_id = scenario.source.get("case_id") or source_snapshot
        if system and fault_category and case_id:
            candidates.append(root / "benchmark" / str(system) / str(fault_category) / str(case_id))
        for candidate in candidates:
            if candidate.exists():
                return candidate
        matches = [
            path
            for path in (root / "benchmark").rglob(str(source_snapshot))
            if path.is_dir() or path.suffix in {".json", ".jsonl"}
        ] if (root / "benchmark").exists() else []
        if len(matches) == 1:
            return matches[0]
        raise FileNotFoundError(
            "Cloud-OpsBench snapshot not found. Expected a path like "
            "`benchmark/<system>/<fault_category>/<case_id>` or a JSON snapshot file under "
            f"{root}."
        )


def _snapshot_signal(snapshot: dict[str, Any], fallback: dict[str, Any], *, expose_ground_truth: bool) -> dict[str, Any]:
    signal = snapshot.get("raw_signal")
    if isinstance(signal, dict):
        return _redact_ground_truth_from_signal(dict(signal)) if not expose_ground_truth else dict(signal)
    signal = dict(fallback)
    related = signal.setdefault("related_context", {})
    if expose_ground_truth and isinstance(related, dict) and snapshot.get("root_cause"):
        related.setdefault("suspected_cause", snapshot["root_cause"])
    return _redact_ground_truth_from_signal(signal) if not expose_ground_truth else signal


def _redact_ground_truth_from_signal(signal: dict[str, Any]) -> dict[str, Any]:
    related = signal.get("related_context")
    if isinstance(related, dict):
        redacted = dict(related)
        for key in ("suspected_cause", "cloudopsbench_metadata", "cloudopsbench_result", "expected_root_cause"):
            redacted.pop(key, None)
        signal["related_context"] = redacted
    return signal


def _summarize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value[:500]
    return json.dumps(value, sort_keys=True)[:500]


def _load_official_case(case_path: Path, scenario: BenchmarkScenario, *, expose_ground_truth: bool) -> dict[str, Any]:
    metadata_path = case_path / "metadata.json"
    tool_cache_path = case_path / "tool_cache.json"
    if not metadata_path.exists() or not tool_cache_path.exists():
        raise FileNotFoundError(
            f"Cloud-OpsBench case {case_path} must contain metadata.json and tool_cache.json"
        )
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    tool_cache = json.loads(tool_cache_path.read_text(encoding="utf-8"))
    alert_path = case_path / "raw_data" / "alert.json"
    alert = json.loads(alert_path.read_text(encoding="utf-8")) if alert_path.exists() else {}
    root_cause = _metadata_root_cause(metadata) or scenario.expected_root_cause
    trajectory = _metadata_trajectory(metadata, case_path)
    system, fault_category, case_id = _case_parts(case_path)
    fallback_service = scenario.raw_signal.get("service") if scenario.raw_signal else None
    service = (_metadata_service(metadata) if expose_ground_truth else None) or fallback_service
    service = service or "unknown-service"
    related_context: dict[str, Any] = {
        "cloudopsbench_namespace": metadata.get("namespace"),
        "cloudopsbench_query": metadata.get("query"),
        "cloudopsbench_alert": alert,
        "audit_logging_available": True,
    }
    if expose_ground_truth:
        related_context["suspected_cause"] = root_cause
        related_context["cloudopsbench_metadata"] = metadata
    return {
        "raw_signal": {
            "signal_type": "otel_metric_regression",
            "signal_id": f"cloudopsbench:{system}:{fault_category}:{case_id}",
            "observed_at": "1970-01-01T00:00:00Z",
            "environment": "cloudopsbench",
            "service": service,
            "endpoint": str(metadata.get("query") or "rca"),
            "comparison_window": {"baseline": "PT30M", "observed": "PT5M"},
            "metric_regression": {
                "metric_name": "availability",
                "baseline_value": 1.0,
                "observed_value": 0.0,
            },
            "related_context": related_context,
        },
        "root_cause": root_cause,
        "expert_trajectory": trajectory,
        "tool_cache": tool_cache,
        "metadata": metadata,
    }


def _metadata_root_cause(metadata: dict[str, Any]) -> str | None:
    result = metadata.get("result") if isinstance(metadata.get("result"), dict) else {}
    root_cause = result.get("root_cause")
    return str(root_cause) if root_cause else None


def _metadata_service(metadata: dict[str, Any]) -> str | None:
    result = metadata.get("result") if isinstance(metadata.get("result"), dict) else {}
    fault_object = str(result.get("fault_object") or "")
    if "/" in fault_object:
        return fault_object.rsplit("/", 1)[-1]
    return fault_object or None


def _metadata_trajectory(metadata: dict[str, Any], case_path: Path) -> list[str]:
    process = metadata.get("process") if isinstance(metadata.get("process"), dict) else {}
    for key in ("path1", "path2"):
        path = process.get(key)
        if isinstance(path, list) and path:
            return [str(item) for item in path]
    trajectory_root = case_path.parents[3] / "golden-trajectory" / case_path.parent.parent.name / case_path.parent.name / case_path.name
    path1 = trajectory_root / "path1.json"
    if not path1.exists():
        return []
    payload = json.loads(path1.read_text(encoding="utf-8"))
    trace = payload.get("diagnostic_trace") if isinstance(payload.get("diagnostic_trace"), list) else []
    return [str(step.get("tool_name")) for step in trace if isinstance(step, dict) and step.get("tool_name")]


def _case_parts(case_path: Path) -> tuple[str, str, str]:
    try:
        return case_path.parent.parent.name, case_path.parent.name, case_path.name
    except IndexError:
        return "unknown", "unknown", case_path.name


def _snapshot_tools(snapshot: dict[str, Any]) -> dict[str, Any]:
    tools = snapshot.get("tools")
    if isinstance(tools, dict):
        return tools
    tool_cache = snapshot.get("tool_cache")
    if isinstance(tool_cache, dict):
        return tool_cache
    return {}


def _cloudops_tool_name(tool_name: str) -> str:
    return str(tool_name).split("::", 1)[0]


def _trajectory_step_to_tool_call(step: str) -> tuple[str, dict[str, Any]]:
    parts = str(step).split("::")
    tool_name = parts[0]
    args: dict[str, Any] = {"source": "expert_trajectory", "expert_step": str(step)}
    if len(parts) > 1 and parts[1]:
        args["resource_type"] = parts[1]
    if len(parts) > 2 and parts[2]:
        args["name_hint"] = parts[2]
    return tool_name, args


def _lookup_cloudops_cache(tools: dict[str, Any], tool_name: str, args: dict[str, Any]) -> Any:
    prefix = f"{tool_name}:"
    candidates = [(key, value) for key, value in tools.items() if isinstance(key, str) and key.startswith(prefix)]
    if not candidates:
        return None
    resource_type = str(args.get("resource_type") or "").lower()
    # Tool caches in the official CloudOps format key on ``name`` (e.g.
    # ``"name":"productcatalogservice"``). Older expert-trajectory steps
    # used ``name_hint``. Accept either so probe-loop callers and
    # trajectory replay both find their entries.
    name_hint = str(args.get("name") or args.get("name_hint") or "").lower()
    namespace = str(args.get("namespace") or "").lower()
    for key, value in candidates:
        lowered = key.lower()
        if resource_type and resource_type not in lowered:
            continue
        if name_hint and name_hint not in lowered:
            continue
        if namespace and f'"namespace":"{namespace}"' not in lowered and namespace not in lowered:
            continue
        return value
    if resource_type:
        for key, value in candidates:
            if re.search(rf'"resource_type":"?{re.escape(resource_type)}', key.lower()):
                return value
    return candidates[0][1]
