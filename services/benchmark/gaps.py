from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CAPABILITIES = (
    "environment setup",
    "trigger normalization",
    "evidence collection",
    "tool-use syntax",
    "root-cause localization",
    "decision mapping",
    "mitigation safety",
    "recovery verification",
    "learning",
)


@dataclass(frozen=True)
class GapReport:
    provider: str
    run_id: str
    output_dir: Path
    gaps: dict[str, list[dict[str, Any]]]

    @property
    def gap_count(self) -> int:
        return sum(len(items) for items in self.gaps.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "run_id": self.run_id,
            "gap_count": self.gap_count,
            "gaps": self.gaps,
        }


def generate_gap_report(*, provider: str, run_dir: Path, output_dir: Path | None = None) -> GapReport:
    benchmark = json.loads((run_dir / "benchmark.json").read_text(encoding="utf-8"))
    results = [item for item in benchmark.get("results", []) if isinstance(item, dict)]
    gaps: dict[str, list[dict[str, Any]]] = {capability: [] for capability in CAPABILITIES}
    for result in results:
        _add_result_gaps(gaps, provider, result)
    gaps = {key: value for key, value in gaps.items() if value}
    report = GapReport(
        provider=provider,
        run_id=str(benchmark.get("run_id") or run_dir.name),
        output_dir=output_dir or run_dir,
        gaps=gaps,
    )
    report.output_dir.mkdir(parents=True, exist_ok=True)
    (report.output_dir / "gap_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (report.output_dir / "gap_report.md").write_text(_render_gap_markdown(report), encoding="utf-8")
    return report


def _add_result_gaps(gaps: dict[str, list[dict[str, Any]]], provider: str, result: dict[str, Any]) -> None:
    scenario_id = str(result.get("scenario_id"))
    process = result.get("process_metrics") if isinstance(result.get("process_metrics"), dict) else {}
    if result.get("error"):
        _add(gaps, "environment setup", scenario_id, str(result["error"]), "blocked by benchmark infra")
    if not result.get("triggered"):
        _add(gaps, "trigger normalization", scenario_id, "scenario did not produce a trigger", "needs root-cause vocabulary")
    if not result.get("investigation_present") or int(result.get("investigation_probe_count") or 0) == 0:
        _add(gaps, "evidence collection", scenario_id, "no usable investigation probes were recorded", "needs new probe")
    if float(process.get("invalid_action_count") or 0.0) > 0:
        _add(gaps, "tool-use syntax", scenario_id, "invalid tool/action calls were recorded", "needs schema-constrained tool wrapper")
    if bool(process.get("zero_tool_diagnosis")):
        _add(gaps, "evidence collection", scenario_id, "diagnosis was produced without tools or probes", "needs new probe")
    if float(process.get("root_cause_accuracy") or 0.0) < 1.0:
        _add(gaps, "root-cause localization", scenario_id, "root cause did not match expected benchmark cause", "needs root-cause vocabulary")
    if not result.get("matched_decision"):
        _add(gaps, "decision mapping", scenario_id, "decision did not match expected benchmark action", "needs remediation mapping")
    if result.get("unsafe_action"):
        _add(gaps, "mitigation safety", scenario_id, "unsafe benchmark action was selected", "needs remediation mapping")
    if result.get("feedback_outcome") not in {"successful", "success", "recovered", "external_report_only"}:
        _add(gaps, "recovery verification", scenario_id, "no successful recovery observation was recorded", "needs topology model")
    if float(result.get("dimension_scores", {}).get("learning", 0.0)) < 0.75:
        _add(gaps, "learning", scenario_id, "feedback/learning artifact was missing or weak", "needs root-cause vocabulary")
    if provider == "cloudopsbench" and float(process.get("tool_coverage") or 0.0) < 1.0:
        _add(gaps, "evidence collection", scenario_id, "Cloud-OpsBench tool coverage is incomplete", "needs new probe")
    if provider == "sregym" and float(process.get("trajectory_in_order_match") or 0.0) < 1.0:
        _add(gaps, "tool-use syntax", scenario_id, "SREGym tool trajectory did not match expected phase order", "needs schema-constrained tool wrapper")


def _add(
    gaps: dict[str, list[dict[str, Any]]],
    capability: str,
    scenario_id: str,
    detail: str,
    recommendation: str,
) -> None:
    gaps.setdefault(capability, []).append(
        {
            "scenario_id": scenario_id,
            "detail": detail,
            "recommendation": recommendation,
        }
    )


def _render_gap_markdown(report: GapReport) -> str:
    lines = [
        f"# Mesh Benchmark Gap Report: {report.provider}",
        "",
        f"- Run ID: `{report.run_id}`",
        f"- Gap count: {report.gap_count}",
        "",
    ]
    if not report.gaps:
        lines.append("No benchmark gaps detected.")
        return "\n".join(lines) + "\n"
    for capability, items in report.gaps.items():
        lines.extend([f"## {capability.title()}", ""])
        for item in items:
            lines.append(
                f"- `{item['scenario_id']}`: {item['detail']} -> {item['recommendation']}"
            )
        lines.append("")
    return "\n".join(lines)
