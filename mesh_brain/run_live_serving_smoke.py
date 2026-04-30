from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .model_client import OpenAICompatibleMeshBrainModelClient
from .serving import MeshBrainServingFabric, OpenAIChatRequest, ServingPool, TenantQuota


DEFAULT_BASE_URL = "http://127.0.0.1:1234"
DEFAULT_MODEL = "nvidia/nemotron-3-nano-4b"
DEFAULT_OUTPUT_DIRECTORY = Path(".mesh-runtime-state") / "mesh-brain" / "live-serving-smoke"


def run_live_serving_smoke(
    *,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    tenant_id: str = "tenant_a",
    hardware_tier: str = "apple_silicon",
    task_type: str = "crops",
    prompt: str = "Return one concise Mesh Brain live smoke response.",
    output_directory: str | Path = DEFAULT_OUTPUT_DIRECTORY,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    fabric = MeshBrainServingFabric(
        pools=[
            ServingPool(
                pool_id=f"live-{hardware_tier}",
                hardware_tier=hardware_tier,
                backend_name="mlx",
                metrics={"live_smoke": 1.0},
            )
        ],
        artifacts=[],
        quotas={tenant_id: TenantQuota(tenant_id=tenant_id, max_requests_per_minute=5, max_tokens_per_minute=8000)},
    )
    request = OpenAIChatRequest(
        tenant_id=tenant_id,
        model=model,
        messages=[{"role": "user", "content": prompt}],
        task_type=task_type,
        hardware_tier=hardware_tier,
        risk_level="low",
        stream=False,
        metadata={"sla": "interactive", "openai_model": model, "live_smoke": True},
    )
    client = OpenAICompatibleMeshBrainModelClient(base_url=base_url, timeout_seconds=timeout_seconds)
    execution = fabric.execute_chat_completion(request, client=client)
    summary = {
        "status": "passed",
        "base_url": base_url,
        "model": execution.completion["model"],
        "requested_model": model,
        "tenant_id": tenant_id,
        "hardware_tier": hardware_tier,
        "backend_name": execution.plan.backend_name,
        "request_id": execution.plan.request_id,
        "completion_id": execution.completion["completion_id"],
        "finish_reason": execution.completion["finish_reason"],
        "usage": execution.completion["usage"],
        "content_preview": str(execution.completion["content"])[:500],
    }
    written = write_live_serving_smoke(
        execution=execution.to_dict(),
        summary=summary,
        output_directory=output_directory,
    )
    return {**summary, "artifact_paths": written}


def write_live_serving_smoke(
    *,
    execution: dict[str, Any],
    summary: dict[str, Any],
    output_directory: str | Path,
) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    execution_path = output_path / "live_serving_execution.json"
    summary_path = output_path / "live_serving_summary.json"
    execution_path.write_text(_json(execution), encoding="utf-8")
    summary_path.write_text(_json(summary), encoding="utf-8")
    return {
        "live_serving_execution": str(execution_path),
        "live_serving_summary": str(summary_path),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a live Mesh Brain OpenAI-compatible serving smoke.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--tenant-id", default="tenant_a")
    parser.add_argument("--hardware-tier", default="apple_silicon")
    parser.add_argument("--task-type", default="crops")
    parser.add_argument("--prompt", default="Return one concise Mesh Brain live smoke response.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIRECTORY))
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_live_serving_smoke(
        base_url=args.base_url,
        model=args.model,
        tenant_id=args.tenant_id,
        hardware_tier=args.hardware_tier,
        task_type=args.task_type,
        prompt=args.prompt,
        output_directory=args.output,
        timeout_seconds=args.timeout_seconds,
    )
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"status={summary['status']}")
        print(f"model={summary['model']}")
        print(f"request_id={summary['request_id']}")
        print(f"completion_id={summary['completion_id']}")
        print(f"finish_reason={summary['finish_reason']}")
        print(f"content_preview={summary['content_preview']}")
    return 0


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
