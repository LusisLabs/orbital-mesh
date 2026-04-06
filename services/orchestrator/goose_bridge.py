from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from services.actuators.service import AuditLogAdapter, FeatureFlagAdapter, IncidentAdapter
from shared.mesh_runtime import Decision


MESH_ROOT = Path(__file__).resolve().parents[2]
GOOSE_SYSTEM_PROMPT = "Reply with only ACK or REJECT. Do not add punctuation, markdown, or explanation."


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
        ok, detail = _acknowledged(args, "Reply with ACK.")
        if ok:
            print(detail)
            return
        raise SystemExit(detail)

    payload = json.load(sys.stdin)
    mode = payload["mode"]
    decision = Decision.from_dict(payload["decision"])
    feature_flags = FeatureFlagAdapter()
    incidents = IncidentAdapter()
    audit_logs = AuditLogAdapter()

    if mode == "incident":
        ok, detail = _acknowledged(
            args,
            (
                "Review this bounded incident request and reply with ACK if it is coherent.\n\n"
                f"Decision: {json.dumps(decision.to_dict(), sort_keys=True)}\n"
                f"Failure reason: {payload['failure_reason']}"
            ),
        )
        if not ok:
            raise SystemExit(detail)
        result = incidents.open_incident(
            {
                "decision_id": decision.decision_id,
                "flag_key": decision.execution_plan["parameters"].get("flag_key"),
                "severity": "high",
                "reason": payload["failure_reason"],
            }
        )
        json.dump({"external_refs": result.get("external_refs", {})}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return

    ok, detail = _acknowledged(
        args,
        (
            "Review this bounded execution request and reply with ACK if it should proceed.\n\n"
            f"Idempotency key: {payload['idempotency_key']}\n"
            f"Decision: {json.dumps(decision.to_dict(), sort_keys=True)}"
        ),
    )
    if not ok:
        raise SystemExit(detail)

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
        "goose_review": detail,
    }
    if execution_plan["system"] == "feature_flag_service":
        result = feature_flags.set_rollout(execution_plan["parameters"])
    elif execution_plan["system"] == "incident_service":
        result = incidents.open_incident(execution_plan["parameters"])
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


def _passthrough(args: argparse.Namespace, extra_args: list[str]) -> int:
    completed = subprocess.run(
        [args.goose_bin] + extra_args,
        cwd=MESH_ROOT,
        check=False,
        text=True,
    )
    return completed.returncode


def _acknowledged(args: argparse.Namespace, prompt: str) -> tuple[bool, str]:
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
        return False, f"goose subprocess failed: {exc}"
    if completed.returncode != 0:
        return False, completed.stderr.strip() or completed.stdout.strip() or "goose run failed"
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return False, f"goose subprocess returned invalid JSON: {exc}"
    text = _assistant_text(payload)
    if not text:
        return False, "goose did not return assistant text"
    if text.lower().strip().startswith("ack"):
        return True, text.strip()
    return False, f"goose rejected the request: {text.strip()}"


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
