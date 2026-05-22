from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class DarkharnessPolicyResult:
    checks: dict[str, bool]
    violations: list[str]

    @property
    def allowed(self) -> bool:
        return not self.violations


def evaluate_darkharness_packet_policy(
    *,
    pilot_scope: dict[str, Any],
    run_export: dict[str, Any],
    action_records: list[dict[str, Any]],
) -> DarkharnessPolicyResult:
    checks = {
        "approval_required": _approval_required(pilot_scope),
        "raw_reservoir_egress_denied": _raw_reservoir_egress_denied(pilot_scope),
        "external_model_calls_denied_by_default": _external_model_calls_denied_by_default(pilot_scope),
        "production_action_has_operator_approval": _production_action_has_operator_approval(
            run_export,
            action_records,
        ),
    }
    return DarkharnessPolicyResult(
        checks=checks,
        violations=[name for name, passed in checks.items() if not passed],
    )


def _approval_required(pilot_scope: dict[str, Any]) -> bool:
    authority = _record(pilot_scope.get("authority"))
    return authority.get("production_actions_approval_required") is True


def _raw_reservoir_egress_denied(pilot_scope: dict[str, Any]) -> bool:
    boundary = _record(pilot_scope.get("data_boundary"))
    return boundary.get("raw_reservoir_egress") == "deny"


def _external_model_calls_denied_by_default(pilot_scope: dict[str, Any]) -> bool:
    boundary = _record(pilot_scope.get("data_boundary"))
    return boundary.get("external_model_calls") == "deny_by_default"


def _production_action_has_operator_approval(
    run_export: dict[str, Any],
    action_records: list[dict[str, Any]],
) -> bool:
    evaluation = _record(run_export.get("evaluation_record"))
    is_allowed = evaluation.get("final_recommendation") == "execute" and not evaluation.get("blocking_reasons")
    if not is_allowed:
        return True
    production_impact = _max_production_impact(action_records)
    if production_impact not in {"possible", "direct"}:
        return True
    return bool(run_export.get("approval_records"))


def _max_production_impact(action_records: list[dict[str, Any]]) -> str:
    rank = {"none": 0, "possible": 1, "direct": 2}
    selected = "none"
    for record in action_records:
        action = _record(record.get("action"))
        impact = str(action.get("production_impact") or "none")
        if rank.get(impact, 0) > rank[selected]:
            selected = impact
    return selected


def _record(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}
