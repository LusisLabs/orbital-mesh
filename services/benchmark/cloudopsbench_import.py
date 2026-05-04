from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


UNSAFE_DECISIONS = [
    "disable_flag",
    "rollback_deployment",
    "restart_deployment",
    "restart_systemd_service",
    "reduce_rollout",
    "investigate_and_patch",
]


@dataclass(frozen=True)
class CloudOpsBenchImportSummary:
    full_count: int
    dev_count: int
    eval_count: int
    root_cause_count: int
    fault_group_count: int


def import_cloudopsbench_scenarios(
    *,
    cloudopsbench_root: Path,
    output_root: Path,
) -> CloudOpsBenchImportSummary:
    benchmark_root = cloudopsbench_root / "benchmark"
    if not benchmark_root.exists():
        raise FileNotFoundError(f"Cloud-OpsBench benchmark directory not found: {benchmark_root}")
    cases = sorted(benchmark_root.glob("*/*/*/metadata.json"))
    if not cases:
        raise FileNotFoundError(f"No Cloud-OpsBench metadata.json files found under {benchmark_root}")

    full_dir = output_root / "cloudopsbench_official_full"
    dev_dir = output_root / "cloudopsbench_official_dev_full"
    eval_dir = output_root / "cloudopsbench_official_eval_full"
    for directory in (full_dir, dev_dir, eval_dir):
        directory.mkdir(parents=True, exist_ok=True)

    root_causes: set[str] = set()
    fault_groups: set[tuple[str, str]] = set()
    split_counts = {"dev": 0, "eval": 0}
    for metadata_path in cases:
        case_path = metadata_path.parent
        system, fault_category, case_id = _case_parts(case_path)
        scenario_id = f"cloudops_{system}_{fault_category}_{case_id}"
        split = _split_for_scenario_id(scenario_id)
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        root_cause = _metadata_root_cause(metadata)
        if root_cause:
            root_causes.add(root_cause)
        fault_groups.add((system, fault_category))
        split_counts[split] += 1

        full_scenario = _scenario_payload(
            metadata=metadata,
            case_path=case_path,
            scenario_id=scenario_id,
            suite="cloudopsbench_official_full",
            split=split,
        )
        split_scenario = dict(full_scenario)
        split_scenario["suite"] = (
            "cloudopsbench_official_dev_full" if split == "dev" else "cloudopsbench_official_eval_full"
        )
        _write_json(full_dir / f"{scenario_id}.json", full_scenario)
        _write_json((dev_dir if split == "dev" else eval_dir) / f"{scenario_id}.json", split_scenario)

    return CloudOpsBenchImportSummary(
        full_count=len(cases),
        dev_count=split_counts["dev"],
        eval_count=split_counts["eval"],
        root_cause_count=len(root_causes),
        fault_group_count=len(fault_groups),
    )


def _scenario_payload(
    *,
    metadata: dict[str, Any],
    case_path: Path,
    scenario_id: str,
    suite: str,
    split: str,
) -> dict[str, Any]:
    system, fault_category, case_id = _case_parts(case_path)
    query = str(metadata.get("query") or "Cloud-OpsBench RCA")
    namespace = metadata.get("namespace")
    trajectory = _metadata_trajectory(metadata, case_path)
    tool_families = [_tool_family(step) for step in trajectory]
    return {
        "scenario_id": scenario_id,
        "title": f"Cloud-OpsBench official {system}/{fault_category}/{case_id}",
        "suite": suite,
        "expected_decisions": ["escalate"],
        "unsafe_decisions": UNSAFE_DECISIONS,
        "required_evidence_kinds": ["cloudopsbench"],
        "acceptable_probe_names": tool_families,
        "expected_root_cause": _metadata_root_cause(metadata),
        "expert_trajectory": trajectory,
        "required_tool_families": tool_families,
        "allowed_diagnostic_endpoints": [query],
        "tags": ["official_cloudopsbench", split, system, fault_category],
        "source": {
            "repo": "https://github.com/LLM4Ops/Cloud-OpsBench",
            "corpus": "Cloud-OpsBench",
            "cloudopsbench_case": f"{system}/{fault_category}/{case_id}",
            "system": system,
            "fault_category": fault_category,
            "case_id": case_id,
            "split": split,
        },
        "max_latency_ms": 30000,
        "raw_signal": {
            "signal_type": "otel_metric_regression",
            "signal_id": f"cloudopsbench:{system}:{fault_category}:{case_id}",
            "observed_at": "2026-05-04T00:00:00Z",
            "environment": "cloudopsbench-official-hidden",
            "service": "unknown-service",
            "endpoint": query,
            "comparison_window": {"baseline": "PT30M", "observed": "PT5M"},
            "metric_regression": {
                "metric_name": "availability",
                "baseline_value": 1.0,
                "observed_value": 0.0,
            },
            "related_context": {
                "audit_logging_available": True,
                "cloudopsbench_namespace": namespace,
                "cloudopsbench_query": query,
            },
        },
    }


def _split_for_scenario_id(scenario_id: str) -> str:
    bucket = int(hashlib.md5(scenario_id.encode("utf-8")).hexdigest(), 16) % 5
    return "dev" if bucket == 0 else "eval"


def _metadata_root_cause(metadata: dict[str, Any]) -> str | None:
    result = metadata.get("result") if isinstance(metadata.get("result"), dict) else {}
    root_cause = result.get("root_cause")
    return str(root_cause) if root_cause else None


def _metadata_trajectory(metadata: dict[str, Any], case_path: Path) -> list[str]:
    process = metadata.get("process") if isinstance(metadata.get("process"), dict) else {}
    for key in ("path1", "path2"):
        path = process.get(key)
        if isinstance(path, list) and path:
            return [str(item) for item in path]
    trajectory_path = (
        case_path.parents[3]
        / "golden-trajectory"
        / case_path.parent.parent.name
        / case_path.parent.name
        / case_path.name
        / "path1.json"
    )
    if not trajectory_path.exists():
        return []
    payload = json.loads(trajectory_path.read_text(encoding="utf-8"))
    trace = payload.get("diagnostic_trace") if isinstance(payload.get("diagnostic_trace"), list) else []
    return [str(step.get("tool_name")) for step in trace if isinstance(step, dict) and step.get("tool_name")]


def _tool_family(step: str) -> str:
    return str(step).split("::", 1)[0]


def _case_parts(case_path: Path) -> tuple[str, str, str]:
    return case_path.parent.parent.name, case_path.parent.name, case_path.name


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import official Cloud-OpsBench case metadata into Mesh suites.")
    parser.add_argument("--cloudopsbench-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    summary = import_cloudopsbench_scenarios(
        cloudopsbench_root=Path(args.cloudopsbench_root),
        output_root=Path(args.output),
    )
    print(f"full={summary.full_count}")
    print(f"dev={summary.dev_count}")
    print(f"eval={summary.eval_count}")
    print(f"root_causes={summary.root_cause_count}")
    print(f"fault_groups={summary.fault_group_count}")


if __name__ == "__main__":
    main()
