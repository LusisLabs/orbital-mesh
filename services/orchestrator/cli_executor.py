from __future__ import annotations

import json
import sys

from services.actuators.repo_patch import RepoPatchAdapter
from services.actuators.service import AuditLogAdapter, FeatureFlagAdapter, IncidentAdapter, KubernetesAdapter
from shared.mesh_runtime import Decision


def main() -> None:
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
        action = execution_plan["action"]
        if action == "rollback_deployment":
            result = kubernetes.rollback_deployment(execution_plan["parameters"])
        elif action == "restart_pod":
            result = kubernetes.restart_pod(execution_plan["parameters"])
        elif action == "scale_deployment":
            result = kubernetes.scale_deployment(execution_plan["parameters"])
        elif action == "cordon_node":
            result = kubernetes.cordon_node(execution_plan["parameters"])
        elif action == "drain_node":
            result = kubernetes.drain_node(execution_plan["parameters"])
        else:
            result = kubernetes.restart_deployment(execution_plan["parameters"])
    elif execution_plan["system"] == "argocd_service":
        from services.actuators.argocd import ArgoCDAdapter
        from shared.mesh_runtime import RuntimeConfig as _RC
        _cfg = _RC.from_env()
        argocd = ArgoCDAdapter(
            url=_cfg.argocd_url,
            token=_cfg.argocd_token,
            ca_bundle=_cfg.argocd_ca_bundle,
            timeout_seconds=_cfg.argocd_timeout_seconds,
        )
        action = execution_plan["action"]
        if action == "sync_application":
            result = argocd.sync_application(execution_plan["parameters"])
        elif action == "rollback_application":
            result = argocd.rollback_application(execution_plan["parameters"])
        else:
            result = {"status": "failed", "failure": {"reason": "unknown_argocd_action", "detail": action},
                      "external_refs": {}}
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
