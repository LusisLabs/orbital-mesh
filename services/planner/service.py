"""Translate a diagnosis into a bounded remediation plan for the first slice."""

from __future__ import annotations

from shared.mesh_runtime import Diagnosis, RemediationPlan, Trigger


class PlannerService:
    def plan(self, trigger: Trigger, diagnosis: Diagnosis) -> RemediationPlan:
        flag_changes = (trigger.related_changes or {}).get("flag_changes", [])
        first_flag = flag_changes[0].split(":")[0] if flag_changes else "unknown_flag"

        plan = RemediationPlan(
            plan_id=f"plan_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            diagnosis_id=diagnosis.diagnosis_id,
            plan_type="multi_step_remediation",
            autonomy_tier="autonomous",
            goal="Restore service health while keeping the blast radius bounded.",
            primary_hypothesis_id="hyp_1",
            confidence=0.84,
            risk={
                "level": "medium",
                "blast_radius": "single_service_single_segment",
                "customer_impact_if_wrong": "temporary feature degradation",
            },
            steps=[
                {
                    "step_id": "step_1",
                    "category": "feature_flag_change",
                    "description": "Reduce the feature rollout for the affected segment.",
                    "system": "feature_flag_service",
                    "action": "set_rollout",
                    "parameters": {
                        "flag_key": first_flag,
                        "environment": trigger.scope["environment"],
                        "segment": trigger.scope["segment"],
                        "rollout_pct": 10,
                    },
                    "success_checkpoint": {
                        "type": "metric_window",
                        "window": "10m",
                        "target": "p95_latency_ms <= 500",
                    },
                    "rollback": {
                        "type": "restore_previous_value",
                        "value": 50,
                    },
                },
                {
                    "step_id": "step_2",
                    "category": "incident_open",
                    "description": "Open or update an incident if the checkpoint fails.",
                    "depends_on": ["step_1"],
                    "run_if": "checkpoint_failed",
                    "system": "incident_service",
                    "action": "open_incident",
                    "parameters": {
                        "service": trigger.scope["service"],
                        "endpoint": trigger.scope["endpoint"],
                        "severity": "high",
                    },
                    "success_checkpoint": {
                        "type": "manual_ack",
                        "window": "0m",
                        "target": "incident_created",
                    },
                    "rollback": None,
                },
            ],
            stop_conditions=[
                "risk level escalates to high",
                "customer impact broadens beyond declared scope",
                "two consecutive checkpoints fail without improvement",
            ],
            human_handoff_conditions=[
                "protected scope is impacted",
                "plan requires a disallowed actuator",
                "checkpoint failure persists after the first mitigation",
            ],
        )
        plan.validate()
        return plan
