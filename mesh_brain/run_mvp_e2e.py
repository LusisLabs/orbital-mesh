from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .mvp import MeshBrainMVPResult, run_private_crops_mvp_e2e


DEFAULT_OUTPUT_DIRECTORY = Path(".mesh-runtime-state") / "mesh-brain" / "mvp-e2e"


def run_persisted_mvp_e2e(
    *,
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    tenant_id: str = "tenant_a",
) -> MeshBrainMVPResult:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    result = run_private_crops_mvp_e2e(output_directory=output_path, tenant_id=tenant_id)
    write_run_summary(result=result, output_directory=output_path)
    return result


def write_run_summary(*, result: MeshBrainMVPResult, output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    summary = {
        "workflow_id": result.workflow_id,
        "tenant_id": result.serving_plan.route.tenant_id,
        "task_type": result.serving_plan.route.task_type,
        "release_decision": result.eval_job.release_decision,
        "canary_state": result.canary_alias.state,
        "rollback_state": result.rollback_alias.state,
        "golden_eval_case_count": result.acceptance_report["golden_eval_case_count"],
        "serving_backend": result.serving_plan.backend_name,
        "policy_route": result.observability.policy_route,
        "artifact_paths": persisted_artifact_paths(output_path),
    }
    path = output_path / "run_summary.json"
    path.write_text(_json(summary), encoding="utf-8")
    return {"run_summary.json": str(path)}


def persisted_artifact_paths(output_directory: str | Path) -> dict[str, str]:
    output_path = Path(output_directory)
    paths = {
        "mvp_workflow": output_path / "mvp_workflow.json",
        "acceptance_report": output_path / "mvp_acceptance_report.json",
        "trace_dataset_row": output_path / "trace_dataset_row.json",
        "dataset_manifest": output_path / "data" / "dataset_manifest.json",
        "sft_rows": output_path / "data" / "sft.jsonl",
        "eval_cases": output_path / "data" / "eval_cases.jsonl",
        "training_job": output_path / "training" / "training_job.json",
        "deployment_manifest": output_path / "training" / "deployment_manifest.json",
        "eval_job": output_path / "eval" / "eval_job.json",
        "serving_plan": output_path / "serving" / "serving_plan.json",
        "observability_metrics": output_path / "observability" / "mesh_brain_metrics.prom",
        "catalog_snapshot": output_path / "catalog" / "model_catalog_snapshot.json",
    }
    return {name: str(path) for name, path in paths.items()}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the persisted Mesh Brain private CROPS MVP e2e artifact generator.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_DIRECTORY),
        help="Directory for persisted e2e artifacts. Defaults to .mesh-runtime-state/mesh-brain/mvp-e2e.",
    )
    parser.add_argument("--tenant-id", default="tenant_a", help="Tenant id used for the deterministic MVP run.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable run summary JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_persisted_mvp_e2e(output_directory=args.output, tenant_id=args.tenant_id)
    summary = {
        "workflow_id": result.workflow_id,
        "output_directory": str(Path(args.output)),
        "release_decision": result.eval_job.release_decision,
        "golden_eval_case_count": result.acceptance_report["golden_eval_case_count"],
        "rollback_restored_prior_adapter": result.acceptance_report["rollback_restored_prior_adapter"],
    }
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"Mesh Brain MVP e2e artifacts written to {Path(args.output)}")
        print(f"workflow_id={summary['workflow_id']}")
        print(f"release_decision={summary['release_decision']}")
        print(f"golden_eval_case_count={summary['golden_eval_case_count']}")
        print(f"rollback_restored_prior_adapter={summary['rollback_restored_prior_adapter']}")
    return 0


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
