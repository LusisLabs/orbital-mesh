from __future__ import annotations

import time
from typing import Any

from .agent_workers import build_agent_task


OPERATOR_AGENT_INGRESS_VERSION = "mesh.operator_agent_ingress.v1"
OPERATOR_AGENT_INGRESS_TASK_KIND = "operator_ingress_investigation"


def build_operator_agent_ingress(
    *,
    source: str,
    request_id: str,
    operator_identity: dict[str, Any],
    requested_action: str,
    text: str,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    roles = {str(role) for role in operator_identity.get("roles", []) if str(role)}
    can_approve = "approver" in roles or "admin" in roles
    approval_requested = requested_action in {"approve_actuation", "execute_remediation"}
    return {
        "schema_version": OPERATOR_AGENT_INGRESS_VERSION,
        "request_id": request_id,
        "source": source,
        "received_at": _timestamp(),
        "operator_identity": dict(operator_identity),
        "requested_action": requested_action,
        "text": text,
        "evidence": dict(evidence or {}),
        "allowed_effect": "approval_review" if approval_requested and can_approve else "investigation_request",
        "direct_actuation_allowed": False,
        "approval_requires_mesh_role_policy": approval_requested,
        "authority": {
            "mesh_operator_identity_authoritative": True,
            "external_ingress_authoritative": False,
            "mesh_policy_required_before_actuation": True,
        },
    }


def build_operator_ingress_agent_task(
    *,
    run_id: str,
    ingress: dict[str, Any],
    agents: list[str] | None = None,
) -> dict[str, Any]:
    if ingress.get("schema_version") != OPERATOR_AGENT_INGRESS_VERSION:
        raise ValueError("operator ingress record must use mesh.operator_agent_ingress.v1")
    if ingress.get("direct_actuation_allowed") is not False:
        raise ValueError("operator ingress cannot create a task with direct actuation authority")

    task = build_agent_task(
        run_id=run_id,
        kind=OPERATOR_AGENT_INGRESS_TASK_KIND,
        open_questions=[str(ingress.get("text", ""))],
        agents=list(agents or ["hermes", "codex"]),
        memory_write_policy={
            "direct_write_allowed": False,
            "source": "operator_ingress",
            "authority": "mesh_review_required",
        },
        lane_routing={
            "operator_ingress": {
                "request_id": ingress["request_id"],
                "source": ingress["source"],
                "allowed_effect": ingress["allowed_effect"],
                "requested_action": ingress["requested_action"],
            }
        },
    ).to_dict()
    task["operator_ingress"] = {
        "request_id": ingress["request_id"],
        "source": ingress["source"],
        "operator_identity": dict(ingress.get("operator_identity", {})),
        "requested_action": ingress["requested_action"],
        "allowed_effect": ingress["allowed_effect"],
        "evidence": dict(ingress.get("evidence", {})),
        "authority": dict(ingress.get("authority", {})),
    }
    task["authority"] = {
        "mesh_control_plane_authoritative": True,
        "operator_ingress_authoritative": False,
        "direct_actuation_allowed": False,
        "approval_requires_mesh_role_policy": bool(ingress.get("approval_requires_mesh_role_policy")),
    }
    return task


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
