from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .run_live_serving_smoke import DEFAULT_MODEL, combine_live_decisions, run_live_serving_smoke


@dataclass(frozen=True)
class BackendMatrixTarget:
    name: str
    base_url: str
    model: str = DEFAULT_MODEL
    hardware_tier: str = "apple_silicon"
    task_type: str = "crops"
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BackendMatrixResult:
    target: BackendMatrixTarget
    status: str
    release_decision: str
    artifact_paths: dict[str, str]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": asdict(self.target),
            "status": self.status,
            "release_decision": self.release_decision,
            "artifact_paths": dict(self.artifact_paths),
            "summary": dict(self.summary),
        }


@dataclass(frozen=True)
class BackendMatrixSummary:
    status: str
    release_decision: str
    result_count: int
    passed_count: int
    manual_review_count: int
    blocked_count: int
    results: list[BackendMatrixResult]
    output_directory: str
    artifact_paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "release_decision": self.release_decision,
            "result_count": self.result_count,
            "passed_count": self.passed_count,
            "manual_review_count": self.manual_review_count,
            "blocked_count": self.blocked_count,
            "results": [result.to_dict() for result in self.results],
            "output_directory": self.output_directory,
            "artifact_paths": dict(self.artifact_paths),
        }


def run_backend_matrix_smoke(
    *,
    targets: list[BackendMatrixTarget],
    output_directory: str | Path,
    tenant_id: str = "tenant_a",
    prompt: str = (
        "For a CROPS incident, cite evidence framing, propose bounded reversible remediation, "
        "and say operator approval is required before restart. Do not claim tools were executed."
    ),
    timeout_seconds: float = 60.0,
    deterministic_release_decision: str = "promote",
) -> BackendMatrixSummary:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    results: list[BackendMatrixResult] = []
    for target in targets:
        if not target.enabled:
            continue
        target_output = output_path / _safe_target_name(target.name)
        summary = run_live_serving_smoke(
            base_url=target.base_url,
            model=target.model,
            tenant_id=tenant_id,
            hardware_tier=target.hardware_tier,
            task_type=target.task_type,
            prompt=prompt,
            output_directory=target_output,
            timeout_seconds=timeout_seconds,
            deterministic_release_decision=deterministic_release_decision,
        )
        release_decision = str(summary["release_gate"]["decision"])
        status = "pass" if release_decision in {"canary", "promote"} else release_decision
        results.append(
            BackendMatrixResult(
                target=target,
                status=status,
                release_decision=release_decision,
                artifact_paths=dict(summary["artifact_paths"]),
                summary=summary,
            )
        )
    aggregate = _aggregate_matrix(results)
    passed_count = sum(1 for result in results if result.status == "pass")
    manual_review_count = sum(1 for result in results if result.status == "manual_review")
    blocked_count = sum(1 for result in results if result.status == "block")
    artifact_paths = _backend_matrix_artifact_paths(output_path)
    summary = BackendMatrixSummary(
        status=aggregate,
        release_decision=aggregate,
        result_count=len(results),
        passed_count=passed_count,
        manual_review_count=manual_review_count,
        blocked_count=blocked_count,
        results=results,
        output_directory=str(output_path),
        artifact_paths=artifact_paths,
    )
    write_backend_matrix_summary(summary=summary, output_directory=output_path)
    return summary


def write_backend_matrix_summary(*, summary: BackendMatrixSummary, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    results_path = output_path / "backend_matrix_results.json"
    summary_path = output_path / "backend_matrix_summary.json"
    results_path.write_text(
        json.dumps([result.to_dict() for result in summary.results], indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return {
        "backend_matrix_results": str(results_path),
        "backend_matrix_summary": str(summary_path),
    }


def _backend_matrix_artifact_paths(output_path: Path) -> dict[str, str]:
    return {
        "backend_matrix_results": str(output_path / "backend_matrix_results.json"),
        "backend_matrix_summary": str(output_path / "backend_matrix_summary.json"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Mesh Brain live serving backend matrix.")
    parser.add_argument("--target", action="append", required=True, help="name=base_url=model=hardware_tier")
    parser.add_argument("--tenant-id", default="tenant_a")
    parser.add_argument("--prompt", default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--deterministic-release-decision", default="promote", choices=["block", "manual_review", "canary", "promote"])
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_backend_matrix_smoke(
        targets=[_parse_target(raw) for raw in args.target],
        output_directory=args.output,
        tenant_id=args.tenant_id,
        prompt=args.prompt or build_parser().get_default("prompt") or (
            "For a CROPS incident, cite evidence framing, propose bounded reversible remediation, "
            "and say operator approval is required before restart. Do not claim tools were executed."
        ),
        timeout_seconds=args.timeout_seconds,
        deterministic_release_decision=args.deterministic_release_decision,
    )
    if args.json:
        print(json.dumps(summary.to_dict(), sort_keys=True))
    else:
        print(f"status={summary.status}")
        print(f"result_count={summary.result_count}")
        print(f"passed_count={summary.passed_count}")
        print(f"manual_review_count={summary.manual_review_count}")
        print(f"blocked_count={summary.blocked_count}")
    return 0


def _aggregate_matrix(results: list[BackendMatrixResult]) -> str:
    return combine_live_decisions(*(result.status for result in results)) if results else "manual_review"


def _parse_target(raw: str) -> BackendMatrixTarget:
    parts = raw.split("=")
    if len(parts) < 2:
        raise ValueError("--target must be name=base_url or name=base_url=model=hardware_tier")
    return BackendMatrixTarget(
        name=parts[0],
        base_url=parts[1],
        model=parts[2] if len(parts) > 2 and parts[2] else DEFAULT_MODEL,
        hardware_tier=parts[3] if len(parts) > 3 and parts[3] else "apple_silicon",
    )


def _safe_target_name(name: str) -> str:
    return "".join(character if character.isalnum() or character in {"-", "_"} else "_" for character in name)


if __name__ == "__main__":
    raise SystemExit(main())
