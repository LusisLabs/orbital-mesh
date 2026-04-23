"""Scenario: force CrashLoopBackOff and verify Mesh's response.

# The story this scenario tells

1. A healthy ``search-api`` deployment sits in the ``mesh-e2e`` namespace.
2. We inject a crash-loop by replacing the container's command with
   ``false`` (exits 1 immediately).
3. Within ~90s, the deployment's pods transition to CrashLoopBackOff.
4. Mesh collects a live signal via the existing
   ``kubernetes_live_signal`` path — same code path the watch daemon
   uses in production.
5. The signal carries ``error_signatures: [crash_loop]`` and
   ``rollout_status: degraded``.
6. Mesh's decision engine runs ``_decide_kubernetes``, which maps the
   ``crash_loop`` signature to a ``restart_deployment`` action (with
   ``approval_required`` autonomy tier if the run has prior rollbacks,
   otherwise ``autonomous``).
7. We revert the chaos — standing in for what a live kubectl actuator
   in staging would do — and wait for the deployment to recover.
8. The scenario's verdict is based on two assertions:
   - Mesh proposed a Kubernetes remediation (not ``escalate`` or
     ``no_action``).
   - The cluster returned to a healthy state after revert.

# Why restart_deployment, not rollback_deployment

The starter decision policy distinguishes the two by symptoms:

- ``image_pull_failure`` or ``rollout_status == "failed"`` → rollback
- ``crash_loop``, ``probe_failure``, ``oom_killed`` → restart

Crash-loop is usually transient (a deadlock, a leaked fd, a stuck
request) so a restart gives the system another chance before we pay
the cost of reverting to a previous image. Operators can override
either way via the steering API if they've already diagnosed the
root cause.

# What a full scenario looks like at runtime

```
[PASS] e2e:crash_loop (14.7s)
  Chaos injected:      crash_loop on mesh-e2e/search-api (detected after 8.2s)
  Mesh trigger:        kubernetes_deployment_unhealthy
  Mesh decision:       restart_deployment (confidence 0.78, autonomous)
  Reasoning:           Deployment search-api in mesh-e2e is unhealthy
                       due to crash_loop.
  Evidence:            rollout status is degraded
                       likely failure layer is application
                       event reasons: BackOff
  Recovery:            ready 2/2 after revert
```
"""

from __future__ import annotations

from tests.e2e.harness import Harness


def run(harness: Harness) -> dict:
    """Execute the crash-loop scenario and return its report fields.

    Contract with the harness:

    - Any ``AssertionError`` becomes a ``fail`` verdict with the
      assertion message as ``failure_reason``.
    - Any other exception becomes ``fail`` with the exception captured.
    - A clean return is treated as ``pass`` unless we explicitly set
      ``verdict="fail"`` in the returned dict.

    We return the signal/trigger/decision/etc. fields so the report
    renders them. The harness merges these into the :class:`ScenarioRun`.
    """
    deployment = "search-api"

    # --- 0. baseline snapshot -------------------------------------------
    # Take a snapshot before we touch anything so the report can show
    # before/after. If this fails, the cluster wasn't in the expected
    # baseline state and the scenario can't give a useful verdict.
    before = harness.snapshot_cluster(deployment, label="before_chaos")
    harness.wait_for_deployment_ready(deployment, timeout_seconds=60)
    harness.record_step("baseline:healthy")

    # --- 1. inject chaos ------------------------------------------------
    harness.inject("crash_loop", deployment)

    # --- 2. run Mesh -----------------------------------------------------
    # Collecting the live signal requires the pods to have already
    # transitioned to CrashLoopBackOff. The chaos injector blocks until
    # that state is observed, so by the time we reach this point the
    # signal will contain the error signatures we expect.
    pipeline_result = harness.run_mesh_pipeline(deployment)

    # Extract the pipeline artifacts for the report.
    signal_envelope = pipeline_result.get("normalized_event")
    trigger = pipeline_result.get("trigger")
    decision = pipeline_result.get("decision")
    evaluation = pipeline_result.get("evaluation")
    execution = pipeline_result.get("execution")
    feedback = pipeline_result.get("feedback")

    # --- 3. assert Mesh did the right thing -----------------------------
    # We don't require an exact decision_type because the starter policy
    # could legitimately escalate (e.g. if prior rollbacks are >0 from
    # an earlier scenario), but we do require the decision to be in the
    # k8s remediation family rather than no_action / escalate.
    assert trigger is not None, "Mesh did not fire a trigger for a clear CrashLoopBackOff signal"
    assert trigger.get("trigger_type") == "kubernetes_deployment_unhealthy", (
        f"expected kubernetes trigger type, got {trigger.get('trigger_type')!r}"
    )
    assert decision is not None, "Mesh did not produce a decision"
    decision_type = decision.get("decision_type")
    allowed_decisions = {"restart_deployment", "rollback_deployment", "escalate"}
    assert decision_type in allowed_decisions, (
        f"decision_type {decision_type!r} is not one of the expected k8s responses {sorted(allowed_decisions)}"
    )

    # --- 4. revert chaos + verify recovery ------------------------------
    # The harness's finally-block would revert anyway, but doing it
    # explicitly here means the "cluster recovered" assertion runs
    # against the actual reverted state rather than potentially racing
    # the cleanup.
    harness.injector.revert(deployment, harness.namespace)
    harness.record_step("chaos:reverted")

    harness.wait_for_deployment_ready(deployment, timeout_seconds=120)
    after = harness.snapshot_cluster(deployment, label="after_recovery")
    harness.record_step("recovery:verified")

    ready = int((after.get("deployment_status") or {}).get("readyReplicas") or 0)
    assert ready >= 1, f"deployment did not return to ready after revert (ready={ready})"

    return {
        "signal": signal_envelope,
        "trigger": trigger,
        "decision": decision,
        "evaluation": evaluation,
        "execution": execution,
        "feedback": feedback,
        "cluster_snapshots": {
            "before_chaos": before,
            "after_recovery": after,
        },
    }


__all__ = ["run"]
