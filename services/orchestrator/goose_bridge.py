from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from services.actuators.repo_patch import RepoPatchAdapter
from services.actuators.service import AuditLogAdapter, FeatureFlagAdapter, IncidentAdapter, KubernetesAdapter
from shared.mesh_runtime import Decision, log_runtime_event


MESH_ROOT = Path(__file__).resolve().parents[2]
GOOSE_SYSTEM_PROMPT = (
    "Reply with only compact JSON matching this shape: "
    '{"approved": boolean, "summary": string, "risk_flags": string[], "next_action": string}. '
    "Do not include markdown."
)
GOOSE_CODE_PATCH_SYSTEM_PROMPT = (
    "Reply with only compact JSON matching this shape: "
    '{"approved": boolean, "summary": string, "risk_flags": string[], "next_action": string, '
    '"patch": {"target_file": string, "find": string, "replace": string}, "test_commands": string[]}. '
    "Do not include markdown."
)


def _goose_run_timeout_seconds() -> float:
    return float(os.getenv("MESH_GOOSE_RUN_TIMEOUT_SECONDS", "60"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesh Intelligence Goose bridge")
    parser.add_argument("--goose-bin", required=True, help="Path to the goose binary")
    parser.add_argument("--provider", help="Optional Goose provider override")
    parser.add_argument("--model", help="Optional Goose model override")
    parser.add_argument("--fallback-provider", help="Optional fallback Goose provider override")
    parser.add_argument("--fallback-model", help="Optional fallback Goose model override")
    parser.add_argument("--version", action="store_true", help="Print the upstream Goose version")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Run a minimal Goose prompt and exit 0 on success",
    )
    args = parser.parse_args()

    if args.version:
        raise SystemExit(_passthrough(args, ["--version"]))

    if args.healthcheck:
        review = _review(args, "Reply with a compact approval JSON object.")
        if review["approved"]:
            print(review["summary"])
            return
        raise SystemExit(review["summary"])

    payload = json.load(sys.stdin)
    mode = payload["mode"]
    decision = Decision.from_dict(payload["decision"])
    feature_flags = FeatureFlagAdapter()
    incidents = IncidentAdapter()
    kubernetes = KubernetesAdapter()
    audit_logs = AuditLogAdapter()
    repo_patch = RepoPatchAdapter()

    if mode == "incident":
        review = _review(
            args,
            (
                "Review this bounded incident request and return a compact approval JSON object.\n\n"
                f"Decision: {json.dumps(decision.to_dict(), sort_keys=True)}\n"
                f"Failure reason: {payload['failure_reason']}"
            ),
        )
        if not review["approved"]:
            log_runtime_event("goose_bridge_incident_rejected", review=review)
            json.dump(
                {
                    "external_refs": {"goose_review": review},
                    "failure": {"reason": "goose_rejected_incident_request", "goose_review": review},
                },
                sys.stdout,
                indent=2,
            )
            sys.stdout.write("\n")
            return
        result = incidents.open_incident(
            {
                "decision_id": decision.decision_id,
                "flag_key": decision.execution_plan["parameters"].get("flag_key"),
                "severity": "high",
                "reason": payload["failure_reason"],
            }
        )
        json.dump(
            {
                "external_refs": {
                    **result.get("external_refs", {}),
                    "goose_review": review,
                }
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        log_runtime_event("goose_bridge_incident_completed", review=review)
        return

    review = _review_execution(args, payload["idempotency_key"], decision)
    if not review["approved"]:
        log_runtime_event("goose_bridge_execution_rejected", review=review)
        json.dump(
            {
                "status": "failed",
                "external_refs": {"goose_review": review},
                "failure": {"reason": "goose_rejected_execution_request", "goose_review": review},
                "retryable": False,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return

    idempotency_key = payload["idempotency_key"]
    audit_result = audit_logs.write_record(decision, idempotency_key)
    if audit_result["status"] != "succeeded":
        json.dump(
            {
                "status": "failed",
                "external_refs": {},
                "failure": {"reason": "audit_logging_failed"},
                "retryable": False,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return

    execution_plan = decision.execution_plan
    external_refs = {
        "audit_log_id": audit_result["audit_log_id"],
        "goose_review": review,
    }
    if execution_plan["system"] == "feature_flag_service":
        result = feature_flags.set_rollout(execution_plan["parameters"])
    elif execution_plan["system"] == "incident_service":
        result = incidents.open_incident(execution_plan["parameters"])
    elif execution_plan["system"] == "kubernetes_service":
        if execution_plan["action"] == "rollback_deployment":
            result = kubernetes.rollback_deployment(execution_plan["parameters"])
        else:
            result = kubernetes.restart_deployment(execution_plan["parameters"])
    elif execution_plan["system"] == "repo_patch_service":
        patch_parameters = _resolved_patch_parameters(decision, review)
        result = repo_patch.execute_patch(patch_parameters, idempotency_key)
    else:
        result = {"status": "succeeded", "external_refs": {}}

    external_refs.update(result.get("external_refs", {}))
    json.dump(
        {
            "status": result["status"],
            "external_refs": external_refs,
            "failure": result.get("failure"),
            "retryable": result.get("retryable", False),
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")
    log_runtime_event("goose_bridge_execution_completed", status=result["status"], review=review)


def _passthrough(args: argparse.Namespace, extra_args: list[str]) -> int:
    completed = subprocess.run(
        [args.goose_bin] + extra_args,
        cwd=MESH_ROOT,
        check=False,
        text=True,
    )
    return completed.returncode


def _review(args: argparse.Namespace, prompt: str) -> dict[str, object]:
    return _run_goose_review_cli(args, prompt, system_prompt=GOOSE_SYSTEM_PROMPT)


def _run_goose_review_cli(
    args: argparse.Namespace, prompt: str, *, system_prompt: str
) -> dict[str, object]:
    """Run Goose once and parse approval JSON (shared by incident review and execution review)."""
    payload, error = _run_goose_prompt(args, prompt, system_prompt)
    if payload is None:
        return error or {
            "approved": False,
            "summary": "goose run failed",
            "risk_flags": ["cli_error"],
            "next_action": "human_review",
        }
    text = _assistant_text(payload)
    if not text:
        return {
            "approved": False,
            "summary": "goose did not return assistant text",
            "risk_flags": ["empty_response"],
            "next_action": "human_review",
        }
    return _parse_review_text(text)


def _review_execution(args: argparse.Namespace, idempotency_key: str, decision: Decision) -> dict[str, object]:
    decision_json = json.dumps(decision.to_dict(), sort_keys=True, separators=(",", ":"))
    prompt = (
        "Review this bounded execution request and return a compact approval JSON object.\n\n"
        f"Idempotency key: {idempotency_key}\n"
        f"Decision: {decision_json}"
    )
    system = (
        GOOSE_CODE_PATCH_SYSTEM_PROMPT
        if decision.execution_plan["system"] == "repo_patch_service"
        else GOOSE_SYSTEM_PROMPT
    )
    payload, error = _run_goose_prompt(args, prompt, system)
    if payload is None:
        return error or {
            "approved": False,
            "summary": "goose run failed",
            "risk_flags": ["cli_error"],
            "next_action": "human_review",
        }
    text = _assistant_text(payload)
    if not text:
        return {
            "approved": False,
            "summary": "goose did not return assistant text",
            "risk_flags": ["empty_response"],
            "next_action": "human_review",
        }
    return _parse_review_text(text)


def _review_code_patch(args: argparse.Namespace, prompt: str) -> dict[str, object]:
    payload, error = _run_goose_prompt(args, prompt, GOOSE_CODE_PATCH_SYSTEM_PROMPT)
    if payload is None:
        return error or {
            "approved": False,
            "summary": "goose run failed",
            "risk_flags": ["cli_error"],
            "next_action": "human_review",
        }
    text = _assistant_text(payload)
    if not text:
        return {
            "approved": False,
            "summary": "goose did not return assistant text",
            "risk_flags": ["empty_response"],
            "next_action": "human_review",
        }
    return _parse_review_text(text)


def _run_goose_prompt(
    args: argparse.Namespace,
    prompt: str,
    system_prompt: str,
) -> tuple[dict | None, dict[str, object] | None]:
    last_error: dict[str, object] | None = None
    for provider, model, is_fallback in _profiles_for_prompt(args):
        command = [
            args.goose_bin,
            "run",
            "--text",
            prompt,
            "--system",
            system_prompt,
            "--no-session",
            "--quiet",
            "--output-format",
            "json",
        ]
        if provider or model:
            command.append("--no-profile")
        if provider:
            command.extend(["--provider", provider])
        if model:
            command.extend(["--model", model])
        try:
            completed = subprocess.run(
                command,
                cwd=MESH_ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=_profile_timeout_seconds(provider, is_fallback),
                env=_command_env(provider),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_error = {
                "approved": False,
                "summary": f"goose subprocess failed: {exc}",
                "risk_flags": ["subprocess_error", "fallback_used" if is_fallback else "primary_failed"],
                "next_action": "human_review",
            }
            continue
        if completed.returncode != 0:
            last_error = {
                "approved": False,
                "summary": completed.stderr.strip() or completed.stdout.strip() or "goose run failed",
                "risk_flags": ["cli_error", "fallback_used" if is_fallback else "primary_failed"],
                "next_action": "human_review",
            }
            continue
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            last_error = {
                "approved": False,
                "summary": f"goose subprocess returned invalid JSON: {exc}",
                "risk_flags": ["invalid_json", "fallback_used" if is_fallback else "primary_failed"],
                "next_action": "human_review",
            }
            continue
        return payload, None
    return None, last_error


def _profiles_for_prompt(args: argparse.Namespace) -> list[tuple[str | None, str | None, bool]]:
    primary = (args.provider, args.model, False)
    fallback = (args.fallback_provider, args.fallback_model, True)
    profiles: list[tuple[str | None, str | None, bool]] = []
    if primary[0] or primary[1]:
        profiles.append(primary)
    else:
        profiles.append((None, None, False))
    if fallback[:2] != primary[:2] and (fallback[0] or fallback[1]):
        profiles.append(fallback)
    return profiles


def _profile_timeout_seconds(provider: str | None, is_fallback: bool) -> int:
    explicit = (os.getenv("MESH_GOOSE_RUN_TIMEOUT_SECONDS") or "").strip()
    if explicit:
        return int(float(explicit))
    if is_fallback:
        return int(os.getenv("GOOSE_FALLBACK_TIMEOUT_SECONDS", "90"))
    if provider == "ollama":
        return int(os.getenv("GOOSE_OLLAMA_TIMEOUT_SECONDS", "45"))
    return int(os.getenv("GOOSE_PRIMARY_TIMEOUT_SECONDS", "60"))


def _command_env(provider: str | None) -> dict[str, str]:
    return os.environ.copy()


def _parse_review_text(text: str) -> dict[str, object]:
    cleaned = text.strip()
    try:
        parsed = _parse_json_like_review(cleaned)
    except json.JSONDecodeError:
        lowered = cleaned.lower()
        if lowered.startswith("ack"):
            return {
                "approved": True,
                "summary": cleaned,
                "risk_flags": [],
                "next_action": "proceed",
            }
        return {
            "approved": False,
            "summary": f"goose rejected the request: {cleaned}",
            "risk_flags": ["model_rejection"],
            "next_action": "human_review",
        }

    approved = bool(parsed.get("approved", False))
    summary = str(parsed.get("summary", "goose review completed")).strip()
    risk_flags = parsed.get("risk_flags") or []
    if not isinstance(risk_flags, list):
        risk_flags = [str(risk_flags)]
    next_action = str(parsed.get("next_action", "proceed" if approved else "human_review"))
    return {
        "approved": approved,
        "summary": summary,
        "risk_flags": [str(item) for item in risk_flags],
        "next_action": next_action,
        "raw_text": cleaned,
        "patch": parsed.get("patch"),
        "test_commands": parsed.get("test_commands"),
    }


def _parse_json_like_review(text: str) -> dict[str, object]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced_match:
            return json.loads(fenced_match.group(1))
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _resolved_patch_parameters(decision: Decision, review: dict[str, object]) -> dict[str, object]:
    parameters = dict(decision.execution_plan["parameters"])
    if isinstance(review.get("patch"), dict):
        parameters["patch_template"] = {
            "target_file": review["patch"].get("target_file"),
            "find": review["patch"].get("find"),
            "replace": review["patch"].get("replace"),
        }
    if isinstance(review.get("test_commands"), list) and review["test_commands"]:
        parameters["test_commands"] = [str(command) for command in review["test_commands"]]
    return parameters


def _assistant_text(payload: dict) -> str:
    messages = payload.get("messages", [])
    for message in reversed(messages):
        if message.get("role") != "assistant":
            continue
        parts = message.get("content", [])
        text = "".join(part.get("text", "") for part in parts if part.get("type") == "text").strip()
        if text:
            return text
    return ""


if __name__ == "__main__":
    main()
