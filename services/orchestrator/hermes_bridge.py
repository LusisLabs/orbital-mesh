from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from services.actuators.service import AuditLogAdapter, FeatureFlagAdapter, IncidentAdapter, KubernetesAdapter
from shared.mesh_runtime import Decision, log_runtime_event
from shared.mesh_runtime.goose_credentials import model_subprocess_env


MESH_ROOT = Path(__file__).resolve().parents[2]
HSAI_EXECUTION_CONTEXT_KEY = "_mesh_hsai_admission_context"
REPO_PATCH_REVIEW_ONLY_STATE_SLICE = "mesh.repo_patch_review_only_boundary.v1"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
HERMES_SYSTEM_PROMPT = (
    "Reply with only compact JSON matching this shape: "
    '{"approved": boolean, "summary": string, "risk_flags": string[], "next_action": string}. '
    "Do not include markdown."
)
HERMES_CODE_PATCH_SYSTEM_PROMPT = (
    "Reply with only compact JSON matching this shape: "
    '{"approved": boolean, "summary": string, "risk_flags": string[], "next_action": string, '
    '"patch": {"target_file": string, "find": string, "replace": string}, "test_commands": string[]}. '
    "Do not include markdown."
)
HERMES_EXPLAIN_SYSTEM_PROMPT = (
    "Reply with only compact JSON matching this shape: "
    '{"approved": false, "summary": string, "risk_flags": string[], "next_action": string, '
    '"recommendation": string, "operator_actions": string[], '
    '"assistant_reply": string, "proposed_command": string | null, "proposed_payload": object | null}. '
    "When you have a concrete operator move, set proposed_command to override_decision or "
    "override_execution_parameters and make proposed_payload match that steering command exactly. "
    "Explain why execution is blocked in plain operational terms. Do not include markdown."
)


def _hermes_chat_timeout_seconds() -> float:
    raw = (
        os.getenv("MESH_HERMES_RUN_TIMEOUT_SECONDS")
        or os.getenv("MESH_HERMES_COMMAND_TIMEOUT_SECONDS")
        or "180"
    )
    return float(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mesh Intelligence Hermes bridge")
    parser.add_argument("--hermes-command", required=True, help="Command used to invoke Hermes")
    parser.add_argument("--version", action="store_true", help="Print the upstream Hermes version")
    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Run a minimal Hermes prompt and exit 0 on success",
    )
    args = parser.parse_args()

    if args.version:
        raise SystemExit(_passthrough(args, ["version"]))

    if args.healthcheck:
        review = _review(args, "Reply with a compact approval JSON object.")
        if review["approved"]:
            print(review["summary"])
            return
        raise SystemExit(review["summary"])

    payload = json.load(sys.stdin)
    mode = payload["mode"]
    decision = Decision.from_dict(_review_only_decision_payload(payload["decision"]))
    feature_flags = FeatureFlagAdapter()
    incidents = IncidentAdapter()
    kubernetes = KubernetesAdapter()
    audit_logs = AuditLogAdapter()

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
            log_runtime_event("hermes_bridge_incident_rejected", review=review)
            json.dump(
                {
                    "external_refs": {"hermes_review": review},
                    "failure": {"reason": "hermes_rejected_incident_request", "hermes_review": review},
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
                    "hermes_review": review,
                }
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        log_runtime_event("hermes_bridge_incident_completed", review=review)
        return

    if mode == "explain":
        explanation = _explain_blockers(args, decision, payload.get("evaluation", {}), payload.get("blocking_reasons", []))
        json.dump(explanation, sys.stdout, indent=2)
        sys.stdout.write("\n")
        log_runtime_event("hermes_bridge_explanation_completed", explanation=explanation)
        return

    if mode == "chat_blockers":
        chat = _chat_blockers(
            args,
            decision,
            payload.get("evaluation", {}),
            payload.get("blocking_reasons", []),
            payload.get("history", []),
            str(payload.get("user_message", "")).strip(),
        )
        json.dump(chat, sys.stdout, indent=2)
        sys.stdout.write("\n")
        log_runtime_event("hermes_bridge_blocker_chat_completed", chat=chat)
        return

    repo_patch_review_only = decision.execution_plan["system"] == "repo_patch_service"
    review = _review_execution(args, payload["idempotency_key"], decision)
    if repo_patch_review_only:
        review = _repo_patch_review_metadata(review)
    if not review["approved"]:
        log_runtime_event("hermes_bridge_execution_rejected", review=review)
        review_refs = (
            _repo_patch_review_refs(review)
            if repo_patch_review_only
            else {"hermes_review": review}
        )
        json.dump(
            {
                "status": "failed",
                "external_refs": review_refs,
                "failure": {"reason": "hermes_rejected_execution_request", "hermes_review": review},
                "retryable": False,
            },
            sys.stdout,
            indent=2,
        )
        sys.stdout.write("\n")
        return

    if repo_patch_review_only:
        result = {
            "status": "succeeded",
            "external_refs": _repo_patch_review_refs(review),
            "retryable": False,
        }
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        log_runtime_event(
            "hermes_bridge_repo_patch_review_completed",
            status="succeeded",
            review=review,
        )
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
        "hermes_review": review,
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
    log_runtime_event("hermes_bridge_execution_completed", status=result["status"], review=review)


def _passthrough(args: argparse.Namespace, extra_args: list[str]) -> int:
    completed = subprocess.run(
        _resolve_command(args) + extra_args,
        cwd=MESH_ROOT,
        check=False,
        text=True,
        env=model_subprocess_env(),
    )
    return completed.returncode


def _review(args: argparse.Namespace, prompt: str) -> dict[str, object]:
    command = _resolve_command(args) + [
        "chat",
        "-q",
        f"{HERMES_SYSTEM_PROMPT}\n\n{prompt}",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=MESH_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=_hermes_chat_timeout_seconds(),
            env=model_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "approved": False,
            "summary": f"hermes subprocess failed: {exc}",
            "risk_flags": ["subprocess_error"],
            "next_action": "human_review",
        }
    if completed.returncode != 0:
        return {
            "approved": False,
            "summary": completed.stderr.strip() or completed.stdout.strip() or "hermes chat failed",
            "risk_flags": ["cli_error"],
            "next_action": "human_review",
        }
    text = _assistant_text(completed.stdout)
    if not text:
        return {
            "approved": False,
            "summary": "hermes did not return assistant text",
            "risk_flags": ["empty_response"],
            "next_action": "human_review",
        }
    return _parse_review_text(text)


def _review_execution(args: argparse.Namespace, idempotency_key: str, decision: Decision) -> dict[str, object]:
    prompt = (
        "Review this bounded execution request and return a compact approval JSON object.\n\n"
        f"Idempotency key: {idempotency_key}\n"
        f"Decision: {json.dumps(decision.to_dict(), sort_keys=True, separators=(',', ':'))}"
    )
    if decision.execution_plan["system"] != "repo_patch_service":
        return _review(args, prompt)
    return _review_code_patch(args, prompt)


def _review_code_patch(args: argparse.Namespace, prompt: str) -> dict[str, object]:
    command = _resolve_command(args) + [
        "chat",
        "-q",
        f"{HERMES_CODE_PATCH_SYSTEM_PROMPT}\n\n{prompt}",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=MESH_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=_hermes_chat_timeout_seconds(),
            env=model_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "approved": False,
            "summary": f"hermes subprocess failed: {exc}",
            "risk_flags": ["subprocess_error"],
            "next_action": "human_review",
        }
    if completed.returncode != 0:
        return {
            "approved": False,
            "summary": completed.stderr.strip() or completed.stdout.strip() or "hermes chat failed",
            "risk_flags": ["cli_error"],
            "next_action": "human_review",
        }
    text = _assistant_text(completed.stdout)
    if not text:
        return {
            "approved": False,
            "summary": "hermes did not return assistant text",
            "risk_flags": ["empty_response"],
            "next_action": "human_review",
        }
    return _parse_review_text(text)


def _explain_blockers(
    args: argparse.Namespace,
    decision: Decision,
    evaluation: object,
    blocking_reasons: object,
) -> dict[str, object]:
    prompt = (
        "Explain this blocked control-plane evaluation for an operator.\n\n"
        f"Decision: {json.dumps(decision.to_dict(), sort_keys=True, separators=(',', ':'))}\n"
        f"Evaluation: {json.dumps(evaluation, sort_keys=True, default=str, separators=(',', ':'))}\n"
        f"Blocking reasons: {json.dumps(blocking_reasons, sort_keys=True, default=str, separators=(',', ':'))}"
    )
    command = _resolve_command(args) + [
        "chat",
        "-q",
        f"{HERMES_EXPLAIN_SYSTEM_PROMPT}\n\n{prompt}",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=MESH_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=_hermes_chat_timeout_seconds(),
            env=model_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "approved": False,
            "summary": f"hermes subprocess failed: {exc}",
            "risk_flags": ["subprocess_error"],
            "next_action": "human_review",
            "recommendation": _evaluation_recommendation(evaluation),
            "operator_actions": ["fix_blockers_or_override"],
        }
    if completed.returncode != 0:
        return {
            "approved": False,
            "summary": completed.stderr.strip() or completed.stdout.strip() or "hermes chat failed",
            "risk_flags": ["cli_error"],
            "next_action": "human_review",
            "recommendation": _evaluation_recommendation(evaluation),
            "operator_actions": ["fix_blockers_or_override"],
        }
    text = _assistant_text(completed.stdout)
    if not text:
        return {
            "approved": False,
            "summary": "hermes did not return assistant text",
            "risk_flags": ["empty_response"],
            "next_action": "human_review",
            "recommendation": _evaluation_recommendation(evaluation),
            "operator_actions": ["fix_blockers_or_override"],
        }
    try:
        parsed = _parse_json_like_review(text)
    except json.JSONDecodeError:
        return {
            "approved": False,
            "summary": _clean_assistant_text(text) or "hermes explanation did not return valid JSON",
            "risk_flags": ["invalid_json"],
            "next_action": "human_review",
            "recommendation": _evaluation_recommendation(evaluation),
            "operator_actions": ["fix_blockers_or_override"],
        }
    operator_actions = parsed.get("operator_actions") or []
    if not isinstance(operator_actions, list):
        operator_actions = [str(operator_actions)]
    risk_flags = parsed.get("risk_flags") or []
    if not isinstance(risk_flags, list):
        risk_flags = [str(risk_flags)]
    return {
        "approved": False,
        "summary": str(parsed.get("summary", "evaluation is blocked")).strip(),
        "assistant_reply": str(parsed.get("assistant_reply", parsed.get("summary", "evaluation is blocked"))).strip(),
        "risk_flags": [str(item) for item in risk_flags],
        "next_action": str(parsed.get("next_action", "human_review")).strip() or "human_review",
        "recommendation": str(parsed.get("recommendation", _evaluation_recommendation(evaluation))).strip()
        or _evaluation_recommendation(evaluation),
        "operator_actions": [str(item) for item in operator_actions] or ["fix_blockers_or_override"],
        "proposed_command": _optional_string(parsed.get("proposed_command")),
        "proposed_payload": parsed.get("proposed_payload") if isinstance(parsed.get("proposed_payload"), dict) else None,
        "raw_text": _clean_assistant_text(text),
    }


def _chat_blockers(
    args: argparse.Namespace,
    decision: Decision,
    evaluation: object,
    blocking_reasons: object,
    history: object,
    user_message: str,
) -> dict[str, object]:
    if not user_message:
        return {
            "approved": False,
            "summary": "chat message is required",
            "assistant_reply": "chat message is required",
            "risk_flags": ["invalid_request"],
            "next_action": "human_review",
            "recommendation": _evaluation_recommendation(evaluation),
            "operator_actions": ["fix_blockers_or_override"],
            "proposed_command": None,
            "proposed_payload": None,
        }
    prompt = (
        "Continue this blocked-evaluation operator conversation. "
        "Answer the user's latest question, keep the response operational, and propose a concrete override only if warranted.\n\n"
        f"Decision: {json.dumps(decision.to_dict(), sort_keys=True, separators=(',', ':'))}\n"
        f"Evaluation: {json.dumps(evaluation, sort_keys=True, default=str, separators=(',', ':'))}\n"
        f"Blocking reasons: {json.dumps(blocking_reasons, sort_keys=True, default=str, separators=(',', ':'))}\n"
        f"Conversation history: {json.dumps(history, sort_keys=True, default=str, separators=(',', ':'))}\n"
        f"Latest user message: {json.dumps(user_message)}"
    )
    command = _resolve_command(args) + [
        "chat",
        "-q",
        f"{HERMES_EXPLAIN_SYSTEM_PROMPT}\n\n{prompt}",
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=MESH_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=_hermes_chat_timeout_seconds(),
            env=model_subprocess_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "approved": False,
            "summary": f"hermes subprocess failed: {exc}",
            "assistant_reply": f"hermes subprocess failed: {exc}",
            "risk_flags": ["subprocess_error"],
            "next_action": "human_review",
            "recommendation": _evaluation_recommendation(evaluation),
            "operator_actions": ["fix_blockers_or_override"],
            "proposed_command": None,
            "proposed_payload": None,
        }
    if completed.returncode != 0:
        reply = completed.stderr.strip() or completed.stdout.strip() or "hermes chat failed"
        return {
            "approved": False,
            "summary": reply,
            "assistant_reply": reply,
            "risk_flags": ["cli_error"],
            "next_action": "human_review",
            "recommendation": _evaluation_recommendation(evaluation),
            "operator_actions": ["fix_blockers_or_override"],
            "proposed_command": None,
            "proposed_payload": None,
        }
    text = _assistant_text(completed.stdout)
    if not text:
        return {
            "approved": False,
            "summary": "hermes did not return assistant text",
            "assistant_reply": "hermes did not return assistant text",
            "risk_flags": ["empty_response"],
            "next_action": "human_review",
            "recommendation": _evaluation_recommendation(evaluation),
            "operator_actions": ["fix_blockers_or_override"],
            "proposed_command": None,
            "proposed_payload": None,
        }
    try:
        parsed = _parse_json_like_review(text)
    except json.JSONDecodeError:
        cleaned = _clean_assistant_text(text)
        return {
            "approved": False,
            "summary": cleaned or "hermes explanation did not return valid JSON",
            "assistant_reply": cleaned or "hermes explanation did not return valid JSON",
            "risk_flags": ["invalid_json"],
            "next_action": "human_review",
            "recommendation": _evaluation_recommendation(evaluation),
            "operator_actions": ["fix_blockers_or_override"],
            "proposed_command": None,
            "proposed_payload": None,
        }
    operator_actions = parsed.get("operator_actions") or []
    if not isinstance(operator_actions, list):
        operator_actions = [str(operator_actions)]
    risk_flags = parsed.get("risk_flags") or []
    if not isinstance(risk_flags, list):
        risk_flags = [str(risk_flags)]
    summary = str(parsed.get("summary", parsed.get("assistant_reply", "hermes reply recorded"))).strip()
    assistant_reply = str(parsed.get("assistant_reply", summary)).strip() or summary
    return {
        "approved": False,
        "summary": summary,
        "assistant_reply": assistant_reply,
        "risk_flags": [str(item) for item in risk_flags],
        "next_action": str(parsed.get("next_action", "human_review")).strip() or "human_review",
        "recommendation": str(parsed.get("recommendation", _evaluation_recommendation(evaluation))).strip()
        or _evaluation_recommendation(evaluation),
        "operator_actions": [str(item) for item in operator_actions] or ["fix_blockers_or_override"],
        "proposed_command": _optional_string(parsed.get("proposed_command")),
        "proposed_payload": parsed.get("proposed_payload") if isinstance(parsed.get("proposed_payload"), dict) else None,
        "raw_text": _clean_assistant_text(text),
    }


def _parse_review_text(text: str) -> dict[str, object]:
    cleaned = ANSI_ESCAPE_RE.sub("", text).strip()
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
            "summary": f"hermes rejected the request: {cleaned}",
            "risk_flags": ["model_rejection"],
            "next_action": "human_review",
        }

    approved = bool(parsed.get("approved", False))
    summary = str(parsed.get("summary", "hermes review completed")).strip()
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
        return cast(dict[str, object], json.loads(text))
    except json.JSONDecodeError:
        fenced_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if fenced_match:
            return cast(dict[str, object], json.loads(fenced_match.group(1)))
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cast(dict[str, object], json.loads(text[start : end + 1]))
        raise


def _review_only_decision_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    execution_plan = sanitized.get("execution_plan")
    if not isinstance(execution_plan, dict) or execution_plan.get("system") != "repo_patch_service":
        return sanitized
    sanitized_plan = dict(execution_plan)
    parameters = sanitized_plan.get("parameters")
    if isinstance(parameters, dict):
        sanitized_parameters = dict(parameters)
        sanitized_parameters.pop(HSAI_EXECUTION_CONTEXT_KEY, None)
        sanitized_plan["parameters"] = sanitized_parameters
    sanitized["execution_plan"] = sanitized_plan
    return sanitized


def _repo_patch_review_metadata(review: dict[str, object]) -> dict[str, object]:
    return {
        **review,
        "repo_patch_review_only": True,
        "final_parameters_unchanged": True,
        "model_parameter_changes_ignored": True,
        "authority_invoked": False,
        "authority_credentials_forwarded": False,
    }


def _repo_patch_review_refs(review: dict[str, object]) -> dict[str, object]:
    return {
        "hermes_review": review,
        "repo_patch_review_only": True,
        "repo_patch_final_parameters_unchanged": True,
        "repo_patch_model_parameter_changes_ignored": True,
        "repo_patch_authority_invoked": False,
        "repo_patch_authority_credentials_forwarded": False,
        "repo_patch_review_state_slice": REPO_PATCH_REVIEW_ONLY_STATE_SLICE,
    }


def _assistant_text(output: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", output).strip()
    if not cleaned:
        return ""
    for line in reversed([line.strip() for line in cleaned.splitlines() if line.strip()]):
        if line.startswith("{") and line.endswith("}"):
            return line
    return cleaned


def _clean_assistant_text(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text).strip()


def _evaluation_recommendation(evaluation: object) -> str:
    if isinstance(evaluation, dict):
        return str(evaluation.get("final_recommendation", "human_review"))
    return "human_review"


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_command(args: argparse.Namespace) -> list[str]:
    return shlex.split(args.hermes_command)


if __name__ == "__main__":
    main()
