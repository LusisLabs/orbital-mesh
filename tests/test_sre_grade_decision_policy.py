"""SRE-grade Kubernetes decision policy regression tests.

These tests pin down the new ``_decide_kubernetes`` semantics, which
was rewritten to follow standard SRE escalation practice:

* ``image_pull_failure`` → ``rollback_deployment``
  (supply-chain problem, rollback is the cleanest fix)

* ``oom_killed`` → ``patch_resources`` (raise memory ceiling)
  Restart is a band-aid: the new container fills the same limit and
  OOMs again. Bumping the limit is the SRE-correct first response.

* ``crash_loop`` + recent deploy (≤30 min) → ``rollback_deployment``
  Deploy is the prior-cause hypothesis.

* ``crash_loop`` + no recent deploy → ``escalate``
  The bug existed before the rollout. Restart can't fix it; needs
  log investigation by a human.

* ``probe_failure`` only (no crash, no OOM) → ``escalate``
  Probe failures usually mean a downstream dependency is sick;
  restarting our container won't fix the dependency.

* ``rollout_status == "failed"`` → ``rollback_deployment``
  ProgressDeadlineExceeded; controller has given up.

* unknown signature → ``escalate``
  Mesh refuses to guess. The previous policy defaulted to
  ``restart_deployment`` here, which an SRE would call "buying time
  without fixing anything."

Each test exercises one branch in isolation.
"""

from __future__ import annotations

import unittest

from services.decision.service import DecisionService
from shared.mesh_runtime import Trigger


def _make_trigger(
    *,
    error_signatures: list[str] | None = None,
    rollout_status: str = "degraded",
    seconds_since_deploy: int | None = None,
    rollbacks_last_24h: int = 0,
) -> Trigger:
    related_context = {
        "error_signatures": error_signatures or [],
        "deployment_name": "search-api",
        "namespace": "search",
        "rollout_status": rollout_status,
        "event_reasons": [],
        "likely_layer": "application",
        "cluster": "test",
        "deployment_image": "registry/search:1.0",
        "rollbacks_last_24h": rollbacks_last_24h,
    }
    if seconds_since_deploy is not None:
        related_context["seconds_since_deploy"] = seconds_since_deploy
    return Trigger(
        trigger_id="trig_test",
        trigger_type="kubernetes_deployment_unhealthy",
        triggered_at="2026-04-25T00:00:00Z",
        service="search",
        endpoint="deployment/search",
        environment="prod",
        flag_key="",
        current_rollout_pct=0,
        comparison_window={"start": "2026-04-25T00:00:00Z", "end": "2026-04-25T00:05:00Z"},
        segment={"customer_tier": "standard"},
        metrics={
            "baseline_p95_latency_ms": 100,
            "observed_p95_latency_ms": 100,
            "baseline_error_rate": 0.01,
            "observed_error_rate": 0.01,
        },
        related_context=related_context,
    )


class ImagePullPolicyTests(unittest.TestCase):
    """Image pull failure routes to rollback regardless of deploy timing —
    a missing image is a definitive supply-chain problem and the prior
    revision had a working image."""

    def test_image_pull_failure_routes_to_rollback(self) -> None:
        svc = DecisionService()
        trigger = _make_trigger(error_signatures=["image_pull_failure"])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "rollback_deployment")

    def test_image_pull_failure_with_repeated_rollback_escalates(self) -> None:
        """Repeated rollback in last 24h flips to approval_required to
        avoid a flapping rollback loop."""
        svc = DecisionService()
        trigger = _make_trigger(
            error_signatures=["image_pull_failure"],
            rollbacks_last_24h=2,
        )
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "rollback_deployment")
        self.assertEqual(decision.autonomy_tier, "approval_required")


class OOMKilledPolicyTests(unittest.TestCase):
    """OOMKilled → raise the memory limit. Restart is a band-aid:
    the new container fills the same limit and OOMs again within
    minutes."""

    def test_oom_killed_routes_to_patch_resources_not_restart(self) -> None:
        svc = DecisionService()
        trigger = _make_trigger(error_signatures=["oom_killed"])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "patch_resources")
        self.assertEqual(decision.execution_plan["action"], "patch_resources")

    def test_oom_killed_requires_approval_for_resource_changes(self) -> None:
        """Resource-limit bumps have cluster-wide cost implications.
        An SRE should sign off, even on high-confidence calls."""
        svc = DecisionService()
        trigger = _make_trigger(error_signatures=["oom_killed"])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.autonomy_tier, "approval_required")

    def test_oom_killed_execution_plan_includes_memory_target(self) -> None:
        svc = DecisionService()
        trigger = _make_trigger(error_signatures=["oom_killed"])
        decision = svc._decide_kubernetes(trigger)
        params = decision.execution_plan["parameters"]
        self.assertIn("limits", params)
        self.assertIn("memory", params["limits"])


class CrashLoopPolicyTests(unittest.TestCase):
    """Crash loop branches on deploy correlation. With recent deploy →
    rollback (deploy is the cause). Without → escalate (code bug
    that existed before this revision)."""

    def test_crash_loop_with_recent_deploy_rolls_back(self) -> None:
        svc = DecisionService()
        trigger = _make_trigger(
            error_signatures=["crash_loop"],
            seconds_since_deploy=120,  # 2 minutes
        )
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "rollback_deployment")

    def test_crash_loop_with_old_deploy_escalates(self) -> None:
        """A crash loop hours after a deploy means the bug existed
        before the rollout. Mesh should escalate for log
        investigation rather than blindly rollback or restart."""
        svc = DecisionService()
        trigger = _make_trigger(
            error_signatures=["crash_loop"],
            seconds_since_deploy=7200,  # 2 hours, well outside the 30-min window
        )
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "escalate")
        self.assertEqual(decision.autonomy_tier, "escalated")

    def test_crash_loop_with_no_deploy_data_escalates(self) -> None:
        """Missing deploy timestamp = can't confirm correlation = escalate.
        The SRE-grade rule: don't guess when you don't have the
        evidence to support a remediation."""
        svc = DecisionService()
        trigger = _make_trigger(error_signatures=["crash_loop"])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "escalate")


class ProbeFailurePolicyTests(unittest.TestCase):
    """Probe failure alone (no crash, no OOM, no image-pull) usually
    means a downstream dependency is sick. Restarting our container
    won't fix the dependency. Escalate."""

    def test_probe_failure_alone_escalates(self) -> None:
        svc = DecisionService()
        trigger = _make_trigger(error_signatures=["probe_failure"])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "escalate")

    def test_probe_failure_with_crash_loop_uses_crash_branch(self) -> None:
        """If the probe is failing AND we have a crash loop, the crash
        branch wins (probe is symptomatic of the crash, not a separate
        downstream issue). Crash + recent deploy → rollback."""
        svc = DecisionService()
        trigger = _make_trigger(
            error_signatures=["crash_loop", "probe_failure"],
            seconds_since_deploy=300,
        )
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "rollback_deployment")


class RolloutFailedPolicyTests(unittest.TestCase):
    """``rollout_status == "failed"`` is the controller's
    ProgressDeadlineExceeded verdict. Rollback is the standard
    response unless we already rolled back recently."""

    def test_rollout_failed_with_no_recent_rollback_rolls_back(self) -> None:
        svc = DecisionService()
        trigger = _make_trigger(rollout_status="failed", error_signatures=[])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "rollback_deployment")

    def test_rollout_failed_with_repeated_rollback_escalates(self) -> None:
        """Avoid the flapping-rollback antipattern: if we've already
        rolled back today and the rollout still fails, the bug
        exists in the rollback target too. Escalate."""
        svc = DecisionService()
        trigger = _make_trigger(
            rollout_status="failed",
            error_signatures=[],
            rollbacks_last_24h=1,
        )
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "escalate")


class UnknownSignaturePolicyTests(unittest.TestCase):
    """The catch-all branch. The previous policy defaulted to
    ``restart_deployment`` here — exactly the naive remediation SREs
    criticize. The new policy escalates instead."""

    def test_unknown_signature_escalates_not_restarts(self) -> None:
        svc = DecisionService()
        trigger = _make_trigger(error_signatures=["something_unrecognized"])
        decision = svc._decide_kubernetes(trigger)
        self.assertEqual(decision.decision_type, "escalate")
        self.assertNotEqual(decision.decision_type, "restart_deployment")


if __name__ == "__main__":
    unittest.main()
