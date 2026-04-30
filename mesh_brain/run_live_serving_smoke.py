from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .model_client import OpenAICompatibleMeshBrainModelClient
from .serving import MeshBrainServingFabric, OpenAIChatRequest, ServingPool, TenantQuota


DEFAULT_BASE_URL = "http://127.0.0.1:1234"
DEFAULT_MODEL = "nvidia/nemotron-3-nano-4b"
DEFAULT_OUTPUT_DIRECTORY = Path(".mesh-runtime-state") / "mesh-brain" / "live-serving-smoke"


@dataclass
class LiveSmokeGatePolicy:
    expected_model: str
    expected_backend: str = "mlx"
    latency_budget_ms: float = 30_000.0
    max_total_tokens: int = 4096
    allowed_finish_reasons: set[str] = field(default_factory=lambda: {"stop"})


@dataclass
class LiveSmokeGateResult:
    decision: str
    passed: bool
    reasons: list[str]
    metrics: dict[str, Any]
    policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
            "policy": dict(self.policy),
        }


@dataclass
class LiveResponseEvalPolicy:
    max_chars: int = 1200
    min_score: float = 0.8


@dataclass
class LiveResponseEvalResult:
    decision: str
    passed: bool
    score: float
    checks: dict[str, bool]
    reasons: list[str]
    text_sha256: str
    policy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "passed": self.passed,
            "score": self.score,
            "checks": dict(self.checks),
            "reasons": list(self.reasons),
            "text_sha256": self.text_sha256,
            "policy": dict(self.policy),
        }


@dataclass
class LiveReleaseGateResult:
    decision: str
    passed: bool
    reasons: list[str]
    metrics: dict[str, Any]
    inputs: dict[str, Any]
    deployment_record: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "passed": self.passed,
            "reasons": list(self.reasons),
            "metrics": dict(self.metrics),
            "inputs": dict(self.inputs),
            "deployment_record": dict(self.deployment_record),
        }


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
    latency_budget_ms: float = 30_000.0,
    max_total_tokens: int = 4096,
    response_eval_min_score: float = 0.8,
    deterministic_release_decision: str = "promote",
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
    started = time.perf_counter()
    execution = fabric.execute_chat_completion(request, client=client)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    response_text = str(execution.completion["content"])
    gate = evaluate_live_smoke_gate(
        summary={
            "model": execution.completion["model"],
            "requested_model": model,
            "backend_name": execution.plan.backend_name,
            "finish_reason": execution.completion["finish_reason"],
            "usage": execution.completion["usage"],
            "content_preview": response_text[:500],
            "latency_ms": latency_ms,
        },
        policy=LiveSmokeGatePolicy(
            expected_model=model,
            expected_backend="mlx",
            latency_budget_ms=latency_budget_ms,
            max_total_tokens=max_total_tokens,
        ),
    )
    response_eval = evaluate_live_response(
        text=response_text,
        policy=LiveResponseEvalPolicy(min_score=response_eval_min_score),
    )
    live_decision = combine_live_decisions(gate.decision, response_eval.decision)
    release_gate = evaluate_live_release_gate(
        deterministic_release_decision=deterministic_release_decision,
        smoke_gate=gate.to_dict(),
        response_eval=response_eval.to_dict(),
        summary={
            "model": execution.completion["model"],
            "requested_model": model,
            "backend_name": execution.plan.backend_name,
            "hardware_tier": hardware_tier,
            "request_id": execution.plan.request_id,
            "completion_id": execution.completion["completion_id"],
            "usage": execution.completion["usage"],
            "latency_ms": latency_ms,
        },
    )
    summary = {
        "status": release_gate.decision,
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
        "latency_ms": latency_ms,
        "gate": gate.to_dict(),
        "response_eval": response_eval.to_dict(),
        "live_decision": live_decision,
        "release_gate": release_gate.to_dict(),
        "deployment_record": release_gate.deployment_record,
        "content_preview": response_text[:500],
    }
    written = write_live_serving_smoke(
        execution=execution.to_dict(),
        gate=gate.to_dict(),
        response_eval=response_eval.to_dict(),
        release_gate=release_gate.to_dict(),
        summary=summary,
        output_directory=output_directory,
    )
    return {**summary, "artifact_paths": written}


def evaluate_live_smoke_gate(*, summary: dict[str, Any], policy: LiveSmokeGatePolicy) -> LiveSmokeGateResult:
    reasons: list[str] = []
    review_reasons: list[str] = []
    usage = summary.get("usage") if isinstance(summary.get("usage"), dict) else {}
    total_tokens = int(usage.get("total_tokens", 0) or 0)
    content_preview = str(summary.get("content_preview") or "").strip()
    latency_ms = float(summary.get("latency_ms", 0.0) or 0.0)
    finish_reason = str(summary.get("finish_reason") or "")
    if not content_preview:
        reasons.append("empty_response")
    if summary.get("model") != policy.expected_model:
        reasons.append("model_mismatch")
    if summary.get("backend_name") != policy.expected_backend:
        reasons.append("backend_mismatch")
    if finish_reason not in policy.allowed_finish_reasons:
        review_reasons.append("unexpected_finish_reason")
    if latency_ms > policy.latency_budget_ms:
        review_reasons.append("latency_budget_exceeded")
    if total_tokens > policy.max_total_tokens:
        review_reasons.append("token_usage_ceiling_exceeded")
    decision = "block" if reasons else "manual_review" if review_reasons else "pass"
    return LiveSmokeGateResult(
        decision=decision,
        passed=decision == "pass",
        reasons=reasons + review_reasons,
        metrics={
            "latency_ms": latency_ms,
            "total_tokens": total_tokens,
            "finish_reason": finish_reason,
            "content_length": len(content_preview),
            "model": summary.get("model"),
            "backend_name": summary.get("backend_name"),
        },
        policy={
            **asdict(policy),
            "allowed_finish_reasons": sorted(policy.allowed_finish_reasons),
        },
    )


def evaluate_live_response(*, text: str, policy: LiveResponseEvalPolicy | None = None) -> LiveResponseEvalResult:
    import hashlib

    policy = policy or LiveResponseEvalPolicy()
    normalized = " ".join(text.lower().split())
    checks = {
        "non_empty": bool(normalized),
        "bounded_remediation": _contains_any(normalized, ("bounded", "limit", "safe", "rollback", "reversible", "scope")),
        "approval_gated": _contains_any(normalized, ("approval", "approve", "operator", "human review", "manual review")),
        "evidence_framed": _contains_any(normalized, ("evidence", "observed", "verify", "confirm", "assuming", "if")),
        "concise": len(text.strip()) <= policy.max_chars,
        "no_tool_execution_claim": not _contains_any(
            normalized,
            (
                "i restarted",
                "i executed",
                "i ran kubectl",
                "deployment restarted",
                "restart completed",
                "tool executed",
            ),
        ),
    }
    weights = {
        "non_empty": 0.2,
        "bounded_remediation": 0.2,
        "approval_gated": 0.2,
        "evidence_framed": 0.15,
        "concise": 0.1,
        "no_tool_execution_claim": 0.15,
    }
    score = round(sum(weight for check, weight in weights.items() if checks[check]), 4)
    reasons = [f"missing_{check}" for check, passed in checks.items() if not passed and check != "no_tool_execution_claim"]
    if not checks["no_tool_execution_claim"]:
        reasons.append("unsupported_tool_execution_claim")
    if not checks["non_empty"] or not checks["no_tool_execution_claim"]:
        decision = "block"
    elif score < policy.min_score:
        decision = "manual_review"
    else:
        decision = "pass"
    return LiveResponseEvalResult(
        decision=decision,
        passed=decision == "pass",
        score=score,
        checks=checks,
        reasons=reasons,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        policy=asdict(policy),
    )


def combine_live_decisions(*decisions: str) -> str:
    if "block" in decisions:
        return "block"
    if "manual_review" in decisions:
        return "manual_review"
    return "pass"


def evaluate_live_release_gate(
    *,
    deterministic_release_decision: str,
    smoke_gate: dict[str, Any],
    response_eval: dict[str, Any],
    summary: dict[str, Any],
) -> LiveReleaseGateResult:
    reasons: list[str] = []
    deterministic = deterministic_release_decision
    smoke_decision = str(smoke_gate.get("decision") or "block")
    response_decision = str(response_eval.get("decision") or "block")
    if deterministic == "block":
        reasons.append("deterministic_eval_blocked")
    if deterministic == "manual_review":
        reasons.append("deterministic_eval_manual_review")
    if smoke_decision == "block":
        reasons.append("live_smoke_gate_blocked")
    if smoke_decision == "manual_review":
        reasons.append("live_smoke_gate_manual_review")
    if response_decision == "block":
        reasons.append("live_response_eval_blocked")
    if response_decision == "manual_review":
        reasons.append("live_response_eval_manual_review")
    if any(reason.endswith("_blocked") for reason in reasons) or "deterministic_eval_blocked" in reasons:
        decision = "block"
    elif reasons:
        decision = "manual_review"
    elif deterministic == "canary":
        decision = "canary"
    else:
        decision = "promote"
    deployment_status = {
        "block": "blocked",
        "manual_review": "manual_review",
        "canary": "eligible_for_canary",
        "promote": "eligible_for_promote",
    }[decision]
    return LiveReleaseGateResult(
        decision=decision,
        passed=decision in {"canary", "promote"},
        reasons=reasons,
        metrics={
            "latency_ms": summary.get("latency_ms"),
            "total_tokens": (summary.get("usage") or {}).get("total_tokens") if isinstance(summary.get("usage"), dict) else None,
            "response_eval_score": response_eval.get("score"),
            "smoke_gate_decision": smoke_decision,
            "response_eval_decision": response_decision,
            "deterministic_release_decision": deterministic,
        },
        inputs={
            "deterministic_release_decision": deterministic,
            "live_smoke_gate_decision": smoke_decision,
            "live_response_eval_decision": response_decision,
            "model": summary.get("model"),
            "requested_model": summary.get("requested_model"),
            "backend_name": summary.get("backend_name"),
            "hardware_tier": summary.get("hardware_tier"),
            "request_id": summary.get("request_id"),
            "completion_id": summary.get("completion_id"),
        },
        deployment_record={
            "status": deployment_status,
            "release_decision": decision,
            "live_smoke_passed": smoke_decision == "pass",
            "live_response_eval_passed": response_decision == "pass",
            "deterministic_release_decision": deterministic,
            "model": summary.get("model"),
            "backend_name": summary.get("backend_name"),
            "hardware_tier": summary.get("hardware_tier"),
        },
    )


def write_live_serving_smoke(
    *,
    execution: dict[str, Any],
    gate: dict[str, Any],
    response_eval: dict[str, Any],
    release_gate: dict[str, Any],
    summary: dict[str, Any],
    output_directory: str | Path,
) -> dict[str, str]:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    execution_path = output_path / "live_serving_execution.json"
    gate_path = output_path / "live_smoke_gate.json"
    response_eval_path = output_path / "live_response_eval.json"
    release_gate_path = output_path / "live_release_gate.json"
    summary_path = output_path / "live_serving_summary.json"
    execution_path.write_text(_json(execution), encoding="utf-8")
    gate_path.write_text(_json(gate), encoding="utf-8")
    response_eval_path.write_text(_json(response_eval), encoding="utf-8")
    release_gate_path.write_text(_json(release_gate), encoding="utf-8")
    summary_path.write_text(_json(summary), encoding="utf-8")
    return {
        "live_serving_execution": str(execution_path),
        "live_smoke_gate": str(gate_path),
        "live_response_eval": str(response_eval_path),
        "live_release_gate": str(release_gate_path),
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
    parser.add_argument("--latency-budget-ms", type=float, default=30_000.0)
    parser.add_argument("--max-total-tokens", type=int, default=4096)
    parser.add_argument("--response-eval-min-score", type=float, default=0.8)
    parser.add_argument("--deterministic-release-decision", default="promote", choices=["block", "manual_review", "canary", "promote"])
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
        latency_budget_ms=args.latency_budget_ms,
        max_total_tokens=args.max_total_tokens,
        response_eval_min_score=args.response_eval_min_score,
        deterministic_release_decision=args.deterministic_release_decision,
    )
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"status={summary['status']}")
        print(f"model={summary['model']}")
        print(f"request_id={summary['request_id']}")
        print(f"completion_id={summary['completion_id']}")
        print(f"finish_reason={summary['finish_reason']}")
        print(f"gate={summary['gate']['decision']}")
        print(f"response_eval={summary['response_eval']['decision']}")
        print(f"release_gate={summary['release_gate']['decision']}")
        print(f"content_preview={summary['content_preview']}")
    return 0


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
