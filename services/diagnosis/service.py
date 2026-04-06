"""Build a deterministic diagnosis from a validated trigger and prior evidence."""

from __future__ import annotations

from shared.mesh_runtime import Diagnosis, Trigger


class DiagnosisService:
    def diagnose(self, trigger: Trigger) -> Diagnosis:
        flag_changes = (trigger.related_changes or {}).get("flag_changes", [])
        release_id = (trigger.related_changes or {}).get("release_id")
        primary_statement = (
            "recent feature-flag rollout likely increased downstream request cost"
            if flag_changes
            else "recent release likely introduced a latency regression"
        )

        diagnosis = Diagnosis(
            diagnosis_id=f"diag_{trigger.trigger_id}",
            trigger_id=trigger.trigger_id,
            summary=(
                f"{trigger.scope['service']} latency regression is most likely linked to "
                f"{'feature rollout changes' if flag_changes else 'the latest release'}."
            ),
            affected_scope={
                "services": [trigger.scope["service"]],
                "customer_segments": [trigger.scope["segment"]],
                "blast_radius": "medium",
            },
            hypotheses=[
                {
                    "hypothesis_id": "hyp_1",
                    "statement": primary_statement,
                    "confidence": 0.84,
                    "supporting_evidence": [
                        "latency threshold exceeded by more than 25 percent",
                        "error rate also degraded in the same scope",
                        f"related changes observed: {flag_changes or [release_id]}",
                    ],
                    "conflicting_evidence": [],
                },
                {
                    "hypothesis_id": "hyp_2",
                    "statement": "an unrelated dependency degradation is contributing to the incident",
                    "confidence": 0.35,
                    "supporting_evidence": ["additional investigation may be needed if mitigation fails"],
                    "conflicting_evidence": ["the signal aligns closely with recent deployment or rollout activity"],
                },
            ],
            candidate_remediations=[
                "reduce feature rollout",
                "disable feature rollout",
                "open or update incident",
                "shift bounded traffic if policy allows",
            ],
        )
        diagnosis.validate()
        return diagnosis
