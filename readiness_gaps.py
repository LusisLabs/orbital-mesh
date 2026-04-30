from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .runtime import stable_digest, utc_now


@dataclass(frozen=True)
class ReadinessGap:
    capability: str
    current_state: str
    target_state: str
    risk: str
    next_proof: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReadinessGapReport:
    report_id: str
    generated_at: str
    ready_for_live_smoke: bool
    ready_for_real_posttraining: bool
    ready_for_moe: bool
    gaps: list[ReadinessGap]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "ready_for_live_smoke": self.ready_for_live_smoke,
            "ready_for_real_posttraining": self.ready_for_real_posttraining,
            "ready_for_moe": self.ready_for_moe,
            "gaps": [gap.to_dict() for gap in self.gaps],
        }


def build_readiness_gap_report() -> ReadinessGapReport:
    gaps = [
        ReadinessGap(
            capability="posttraining_execution",
            current_state="deterministic manifests for SFT, LoRA/QLoRA, DPO/IPO/KTO, RL, quantization, and QAT",
            target_state="real GPU job adapter with artifacts, logs, metrics, and failure capture",
            risk="training plans can be audited but do not yet prove optimizer/runtime correctness",
            next_proof="run a small real SFT or LoRA job against a toy dataset and register the resulting adapter",
        ),
        ReadinessGap(
            capability="llm_as_judge",
            current_state="deterministic rubric plus optional OpenAI-compatible judge client boundary",
            target_state="calibrated judge set with transcript retention, disagreement routing, and regression thresholds",
            risk="judge pass/fail behavior is not yet statistically calibrated across model families",
            next_proof="run judge calibration over fixed pass/manual/block fixtures and store confusion metrics",
        ),
        ReadinessGap(
            capability="moe_training_and_serving",
            current_state="research registry tracks MegaBlocks and MoE influence only",
            target_state="expert routing, sparse training config, serving compatibility, and eval gates",
            risk="MoE is not a deployable Mesh Brain lane yet",
            next_proof="add a deterministic MoE training/serving contract before attempting real sparse expert jobs",
        ),
        ReadinessGap(
            capability="serving_load",
            current_state="single-request OpenAI-compatible live smoke and backend matrix",
            target_state="sustained concurrency, latency, cost, and rollback smoke per backend",
            risk="single-call correctness does not prove production throughput or tail latency",
            next_proof="run bounded multi-request load smoke with p50/p95/p99 and failure-rate gates",
        ),
    ]
    report_id = f"mesh_brain_readiness_{stable_digest([gap.to_dict() for gap in gaps])[:12]}"
    return ReadinessGapReport(
        report_id=report_id,
        generated_at=utc_now(),
        ready_for_live_smoke=True,
        ready_for_real_posttraining=False,
        ready_for_moe=False,
        gaps=gaps,
    )


def write_readiness_gap_report(*, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    report = build_readiness_gap_report()
    path = output_path / "readiness_gap_report.json"
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"readiness_gap_report": str(path)}
