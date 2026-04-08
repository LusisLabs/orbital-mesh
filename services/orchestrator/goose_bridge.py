from __future__ import annotations

import argparse
import json
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesh Intelligence Goose bridge")
    parser.add_argument("--goose-bin", required=True, help="Path to the goose binary")
    parser.add_argument("--provider", help="Optional Goose provider override")
    parser.add_argument("--model", help="Optional Goose model override")
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
    command = [
        args.goose_bin,
        "run",
        "--text",
        prompt,
        "--system",
        GOOSE_SYSTEM_PROMPT,
        "--no-session",
        "--quiet",
        "--output-format",
        "json",
    ]
    if args.provider or args.model:
        command.append("--no-profile")
    if args.provider:
        command.extend(["--provider", args.provider])
    if args.model:
        command.extend(["--model", args.model])
    try:
        completed = subprocess.run(
            command,
            cwd=MESH_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "approved": False,
            "summary": f"goose subprocess failed: {exc}",
            "risk_flags": ["subprocess_error"],
            "next_action": "human_review",
        }
    if completed.returncode != 0:
        return {
            "approved": False,
            "summary": completed.stderr.strip() or completed.stdout.strip() or "goose run failed",
            "risk_flags": ["cli_error"],
            "next_action": "human_review",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "approved": False,
            "summary": f"goose subprocess returned invalid JSON: {exc}",
            "risk_flags": ["invalid_json"],
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
    prompt = (
        "Review this bounded execution request and return a compact approval JSON object.\n\n"
        f"Idempotency key: {idempotency_key}\n"
        f"Decision: {json.dumps(decision.to_dict(), sort_keys=True)}"
    )
    if decision.execution_plan["system"] != "repo_patch_service":
        return _review(args, prompt)
    return _review_code_patch(args, prompt)


def _review_code_patch(args: argparse.Namespace, prompt: str) -> dict[str, object]:
    command = [
        args.goose_bin,
        "run",
        "--text",
        prompt,
        "--system",
        GOOSE_CODE_PATCH_SYSTEM_PROMPT,
        "--no-session",
        "--quiet",
        "--output-format",
        "json",
    ]
    if args.provider or args.model:
        command.append("--no-profile")
    if args.provider:
        command.extend(["--provider", args.provider])
    if args.model:
        command.extend(["--model", args.model])
    try:
        completed = subprocess.run(
            command,
            cwd=MESH_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "approved": False,
            "summary": f"goose subprocess failed: {exc}",
            "risk_flags": ["subprocess_error"],
            "next_action": "human_review",
        }
    if completed.returncode != 0:
        return {
            "approved": False,
            "summary": completed.stderr.strip() or completed.stdout.strip() or "goose run failed",
            "risk_flags": ["cli_error"],
            "next_action": "human_review",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return {
            "approved": False,
            "summary": f"goose subprocess returned invalid JSON: {exc}",
            "risk_flags": ["invalid_json"],
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


def _parse_review_text(text: str) -> dict[str, object]:
    cleaned = text.strip()
    try:
        parsed = json.loads(cleaned)
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
