from __future__ import annotations

import argparse
import json
import sys

from services.actuators.repo_patch import RepoPatchAdapter
from services.actuators.service import AuditLogAdapter, FeatureFlagAdapter, IncidentAdapter, KubernetesAdapter
from shared.mesh_runtime import Decision


def main() -> None:
    if len(sys.argv) > 1:
        _run_hermes_cli(sys.argv[1:])
        return
    _run_goose_executor()


def _run_hermes_cli(argv: list[str]) -> None:
    if argv in (["version"], ["--version"]):
        print("Hermes Agent vvtest")
        print("Project: /opt/hermes-agent")
        print(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        print("OpenAI SDK: test")
        return
    if argv == ["--healthcheck"]:
        print("ready")
        return

    parser = argparse.ArgumentParser(description="Hermes CLI test shim")
    subparsers = parser.add_subparsers(dest="command", required=True)
    chat_parser = subparsers.add_parser("chat")
    chat_parser.add_argument("-q", "--query", required=True)
    args = parser.parse_args(argv)

    if args.command != "chat":
        raise SystemExit(2)

    print(json.dumps(_hermes_review_response(args.query), separators=(",", ":")))


def _hermes_review_response(prompt: str) -> dict[str, object]:
    decision = _extract_decision(prompt)
    if decision and decision.execution_plan["system"] == "repo_patch_service":
        parameters = decision.execution_plan.get("parameters", {})
        return {
            "approved": True,
            "summary": "bounded code patch approved by cli executor",
            "risk_flags": [],
            "next_action": "proceed",
            "patch": parameters.get("patch_template"),
            "test_commands": parameters.get("test_commands", []),
        }
    if "incident request" in prompt.lower():
        return {
            "approved": True,
            "summary": "bounded incident approved by cli executor",
            "risk_flags": [],
            "next_action": "proceed",
        }
    return {
        "approved": True,
        "summary": "bounded execution approved by cli executor",
        "risk_flags": [],
        "next_action": "proceed",
    }


def _extract_decision(prompt: str) -> Decision | None:
    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if not line.startswith("Decision:"):
            continue
        payload = line.partition("Decision:")[2].strip()
        if not payload:
            return None
        try:
            return Decision.from_dict(json.loads(payload))
        except json.JSONDecodeError:
            return None
    return None


def _run_goose_executor() -> None:
    payload = json.load(sys.stdin)
    mode = payload["mode"]
    decision = Decision.from_dict(payload["decision"])
    feature_flags = FeatureFlagAdapter()
    incidents = IncidentAdapter()
    kubernetes = KubernetesAdapter()
    audit_logs = AuditLogAdapter()
    repo_patch = RepoPatchAdapter()

    if mode == "incident":
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
                    "goose_review": {
                        "mode": "cli_executor",
                        "approved": True,
                        "summary": "cli executor approved incident creation",
                        "risk_flags": [],
                        "next_action": "proceed",
                    },
                }
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
        "goose_review": {
            "mode": "cli_executor",
            "approved": True,
            "summary": "cli executor approved bounded execution",
            "risk_flags": [],
            "next_action": "proceed",
        },
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
        result = repo_patch.execute_patch(execution_plan["parameters"], idempotency_key)
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


if __name__ == "__main__":
    main()
