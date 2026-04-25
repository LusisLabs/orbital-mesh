"""End-to-end harness orchestrator.

# What this does

Given a live kind cluster and a scenario (inject crash-loop on the
``search-api`` deployment, say), this module:

1. Asserts the cluster is reachable and baseline-healthy.
2. Invokes the chaos injector to produce the failure.
3. Collects a live Kubernetes signal via Mesh's existing
   :mod:`services.ingest.kubernetes_live_signal` — the same code path
   that the watch daemon uses in production.
4. Runs the signal through the synchronous ``FirstSlicePipeline`` so
   Mesh's full ingest → trigger → decision → evaluation → execution →
   feedback loop fires against the real cluster.
5. For scenarios where Mesh's proposed action is a real mutation
   (``rollback_deployment``), kicks off the revert through the chaos
   injector so the cluster returns to baseline — this mirrors what a
   live Kubernetes actuator would do in staging, without requiring the
   e2e run to have cluster-admin privileges.
6. Produces a :class:`ScenarioRun` dataclass that the report generator
   renders into markdown + JSON.

# Why synchronous pipeline, not the HTTP server

The question this harness answers is "does Mesh's decision loop work
against a real cluster?" Using :class:`FirstSlicePipeline` directly is
the tightest path to an answer — no server lifecycle, no SSE consumer,
no race with the approval gate, no port conflicts. A follow-up
scenario can exercise the HTTP path once this baseline is proved.

The pipeline uses the same services, contracts, schemas, and
actuators as the HTTP path. The only thing missing is HTTP-layer
concerns: authentication, rate limiting, the streaming event feed.
Those have their own unit tests.

# How scenarios hook in

A scenario is a plain function: given a harness, an injector, a
kubectl context, and a namespace, run the failure + observe Mesh's
response + return a :class:`ScenarioRun`. The first concrete
scenario — :mod:`tests.e2e.scenarios.crash_loop` — is ~50 lines
because almost everything interesting lives here in the harness.

Adding new scenarios is:
1. Call the right chaos primitive.
2. Call :meth:`Harness.run_mesh_pipeline` with the expected signal
   ``deployment_name`` / ``namespace``.
3. Assert the decision type is what you expect.
4. Optionally verify recovery.
5. Return the :class:`ScenarioRun` for the report.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from shared.mesh_runtime import RuntimeConfig
from tests.e2e.chaos.injector import ChaosInjector, InjectionResult


_LOG = logging.getLogger("mesh.e2e.harness")


@dataclass
class ScenarioStep:
    """One step in the scenario timeline.

    Named steps map to the stages of Mesh's pipeline (``ingest``,
    ``trigger``, ``decision``, ``execution``) plus harness-level steps
    (``chaos_injected``, ``recovery_verified``). The report groups by
    step name so a reader can see at a glance where time went.
    """

    name: str
    started_at: float
    completed_at: float
    status: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScenarioRun:
    """Complete record of a single scenario execution.

    Everything the report needs is in here. The harness never reaches
    into private state of the services it invokes; instead it captures
    what it passed in and what came back, so the report is always a
    closed-form description of the run.
    """

    name: str
    started_at: float
    completed_at: float
    verdict: str  # "pass" | "fail" | "inconclusive"
    failure_reason: str | None = None
    steps: list[ScenarioStep] = field(default_factory=list)
    chaos: list[InjectionResult] = field(default_factory=list)
    signal: dict[str, Any] | None = None
    trigger: dict[str, Any] | None = None
    decision: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None
    execution: dict[str, Any] | None = None
    feedback: dict[str, Any] | None = None
    merkle_root: str | None = None
    cluster_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)


class Harness:
    """Orchestrates one scenario run against a live cluster.

    One instance per scenario. The harness holds cluster-level state
    (kubectl context, namespace) and scenario-level accumulators (the
    timeline of steps, the captured signal, the Mesh run result).
    Scenarios call into the harness's high-level methods instead of
    interacting with kubectl or Mesh directly; this keeps scenarios
    short and keeps the failure modes uniform.
    """

    def __init__(
        self,
        kube_context: str,
        namespace: str,
        kubectl: str = "kubectl",
        state_directory: str | None = None,
        log_file: str | None = None,
    ):
        self.kube_context = kube_context
        self.namespace = namespace
        self.kubectl = kubectl
        # The pipeline writes to state_directory; for hermetic e2e we
        # point it at a per-run tempdir so local state from previous
        # runs never leaks in.
        self.state_directory = state_directory or tempfile.mkdtemp(prefix="mesh-e2e-")
        self.injector = ChaosInjector(kubectl=kubectl, kube_context=kube_context)
        self._steps: list[ScenarioStep] = []
        self._chaos: list[InjectionResult] = []
        # Optional log file — when set, every ``mesh.*`` logger gets a
        # FileHandler installed here so the scenario's Python log output
        # lands alongside the markdown/JSON reports. The handler is kept
        # as an instance attribute so we can remove it on teardown; if we
        # didn't, a second harness run in the same process would double-
        # write every log line.
        self._log_handler: logging.Handler | None = None
        if log_file:
            self._install_log_capture(log_file)
        # Print the state directory + log path only when we're running
        # as a standalone scenario (``log_file`` set by the scenario
        # driver). The session runner creates a fresh harness per
        # experiment — printing this 40 times in a 60-minute session
        # drowns out the real signal. Operators debugging one scenario
        # still get the info; session operators get a clean log.
        if log_file:
            print(f"[harness] state directory: {self.state_directory}", file=sys.stderr)
            print(f"[harness] server log:      {log_file}", file=sys.stderr)
        else:
            _LOG.debug("harness state directory: %s", self.state_directory)

    # ---------------------------------------------------------------- logging

    def _install_log_capture(self, log_file: str) -> None:
        """Route every ``mesh.*`` logger at INFO+ to ``log_file``.

        Two design choices worth noting:

        1. We attach to the ``mesh`` parent logger rather than to each
           child logger individually. That way any new ``mesh.X.Y``
           logger added anywhere in the codebase is captured
           automatically — no coordination required between the
           harness and the services.

        2. We keep the handler on ``self`` so teardown can remove it.
           Without removal, a second harness invocation in the same
           Python process (common during iterative scenario writing)
           would log every line twice into the new file.
        """
        handler = logging.FileHandler(log_file, mode="w", encoding="utf-8")
        handler.setLevel(logging.INFO)
        handler.setFormatter(
            logging.Formatter("%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s",
                              datefmt="%H:%M:%S")
        )
        root_mesh = logging.getLogger("mesh")
        root_mesh.setLevel(logging.INFO)
        root_mesh.addHandler(handler)
        self._log_handler = handler

    def close_log_capture(self) -> None:
        """Remove the FileHandler we installed, if any.

        Called from :meth:`run_scenario`'s finally-block. Idempotent:
        calling it twice is safe, and calling it without a handler
        attached is a no-op.
        """
        if self._log_handler is None:
            return
        logging.getLogger("mesh").removeHandler(self._log_handler)
        try:
            self._log_handler.close()
        finally:
            self._log_handler = None

    # ---------------------------------------------------------------- top-level

    def run_scenario(self, scenario_name: str, scenario_fn) -> ScenarioRun:
        """Run ``scenario_fn(self)`` wrapped in timing + cleanup.

        ``scenario_fn`` is a plain callable that takes this harness and
        returns a dict of scenario-specific fields to merge into the
        resulting :class:`ScenarioRun`. Wrapping here means every
        scenario gets the same start/end accounting, the same
        automatic chaos revert, and the same failure-catch that keeps
        a crashed scenario from leaving the cluster dirty.
        """
        started_at = time.monotonic()
        run = ScenarioRun(
            name=scenario_name,
            started_at=started_at,
            completed_at=started_at,
            verdict="inconclusive",
        )
        try:
            scenario_result = scenario_fn(self) or {}
            # Merge any fields the scenario chose to populate.
            for key, value in scenario_result.items():
                if hasattr(run, key):
                    setattr(run, key, value)
            # If the scenario didn't set a verdict, default to pass —
            # scenarios indicate failure by raising an AssertionError
            # or by explicitly setting verdict="fail" in their return.
            if run.verdict == "inconclusive":
                run.verdict = "pass"
        except AssertionError as exc:
            run.verdict = "fail"
            run.failure_reason = f"assertion failed: {exc}"
            _LOG.error("scenario %s failed: %s", scenario_name, exc)
        except Exception as exc:  # noqa: BLE001 — scenario-level catch for cleanup
            run.verdict = "fail"
            run.failure_reason = f"{type(exc).__name__}: {exc}"
            _LOG.exception("scenario %s crashed", scenario_name)
        finally:
            run.completed_at = time.monotonic()
            run.steps = list(self._steps)
            run.chaos = list(self._chaos)
            # Always revert chaos so the cluster is reusable for the
            # next scenario even if this one failed.
            self.injector.revert_all()
            # Close the log handler *after* revert so the revert output
            # itself is captured in the log.
            self.close_log_capture()
        return run

    # ---------------------------------------------------------------- steps

    def record_step(self, name: str, status: str = "completed", **payload: Any) -> ScenarioStep:
        """Append a step to the scenario timeline.

        Scenarios call this to mark notable milestones beyond what the
        harness records automatically. The returned step is also a
        convenient handle for updating ``status`` if the scenario needs
        to amend it later (e.g. "running" → "completed").
        """
        now = time.monotonic()
        step = ScenarioStep(name=name, started_at=now, completed_at=now, status=status, payload=payload)
        self._steps.append(step)
        return step

    # ---------------------------------------------------------------- cluster ops

    def wait_for_deployment_ready(
        self, deployment: str, namespace: str | None = None, timeout_seconds: int = 120
    ) -> None:
        """Block until the deployment reports all replicas ready.

        Uses ``kubectl rollout status`` for this because its semantics
        are precisely what we need ("all replicas have moved to the new
        spec and are ready") and its exit code is clean. We don't hand-
        roll a pod-polling loop because ``rollout status`` already does
        it server-side with the right event filtering.

        ``rollout status`` alone is NOT enough to guarantee isolation
        between chaos experiments — it returns as soon as the new
        replicaset has the right pod count, but old replicasets can
        still be terminating and their events are still live in the
        event log. Use :meth:`wait_for_stable_state` after this if
        you need full cluster quiescence.
        """
        namespace = namespace or self.namespace
        command = [self.kubectl, "--context", self.kube_context, "rollout", "status",
                   f"deployment/{deployment}", "-n", namespace,
                   f"--timeout={timeout_seconds}s"]
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout_seconds + 10)
        if completed.returncode != 0:
            raise AssertionError(
                f"deployment {namespace}/{deployment} did not become ready within {timeout_seconds}s: "
                f"{completed.stderr.strip()}"
            )

    def wait_for_stable_state(
        self,
        deployment: str,
        namespace: str | None = None,
        *,
        settle_seconds: float = 20.0,
        timeout_seconds: float = 90.0,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        """Wait for a deployment to reach quiescence — safe for the NEXT experiment.

        The chaos harness runs experiments back-to-back. Between each
        one we revert the chaos and call ``wait_for_deployment_ready``,
        which returns as soon as ``kubectl rollout status`` succeeds.
        That check is too weak: a deployment can be "ready" per the
        rollout status while old replicasets are still being torn
        down, their pods are still Terminating, and their events are
        still present in the event log. Those old events then
        contaminate the next experiment's signal — the root cause of
        the cascading failure observed in chaos session #3.

        Quiescence here means five conditions, all concurrently true
        for at least ``settle_seconds``:

        1. ``status.readyReplicas == spec.replicas``
        2. ``status.availableReplicas == spec.replicas``
        3. ``status.updatedReplicas == spec.replicas``
        4. No pods with phase in {``Pending``, ``Succeeded``, ``Failed``}
           — we require every live pod to be ``Running``
        5. No containers in ``terminated`` or ``waiting`` states; all
           must be in ``running``

        Once all five are true, the settle timer starts. Any single
        poll that breaks a condition resets the timer. The method
        returns only after the timer completes. This is strict but
        correct — the whole point is to let the cluster fully cool
        down before the next chaos fires.

        Timeout is generous (90s default) because this runs AFTER
        revert and the operator has already accepted the experiment
        failed; we'd rather burn 90 seconds than contaminate the next
        experiment.
        """
        namespace = namespace or self.namespace
        deadline = time.monotonic() + timeout_seconds
        stable_since: float | None = None

        while time.monotonic() < deadline:
            try:
                dep = self._kubectl_json("get", "deployment", deployment, "-n", namespace, "-o", "json")
                pods = self._kubectl_json("get", "pods", "-n", namespace, "-l", f"app={deployment}", "-o", "json")
            except AssertionError:
                # kubectl hiccup — don't penalize stability accounting.
                # Reset the timer; next poll will re-evaluate.
                stable_since = None
                time.sleep(poll_interval_seconds)
                continue

            if self._is_stable(dep, pods):
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= settle_seconds:
                    return
            else:
                # Any instability resets the settle timer — we need
                # continuous quiescence, not cumulative.
                stable_since = None

            time.sleep(poll_interval_seconds)

        # Didn't stabilize in time. Don't raise — the session-level
        # circuit breaker owns "cluster is chronically broken" logic,
        # and raising here would mask that with a per-experiment
        # AssertionError. Log and return; the probe will catch it.
        _LOG.warning(
            "deployment %s/%s did not reach stable state within %ss",
            namespace, deployment, timeout_seconds,
        )

    @staticmethod
    def _is_stable(deployment: dict[str, Any], pods: dict[str, Any]) -> bool:
        """Check the five quiescence conditions documented on ``wait_for_stable_state``."""
        spec = deployment.get("spec") or {}
        status = deployment.get("status") or {}
        desired = int(spec.get("replicas") or 0)

        # Conditions 1-3: replica counters all match desired.
        ready = int(status.get("readyReplicas") or 0)
        available = int(status.get("availableReplicas") or 0)
        updated = int(status.get("updatedReplicas") or 0)
        if not (ready == desired and available == desired and updated == desired):
            return False

        # Condition 4 + 5: every live pod is Running with only
        # running containers. A pod in Pending or Terminating
        # (phase still Running with a deletionTimestamp set) blocks.
        for pod in pods.get("items", []):
            pod_status = pod.get("status") or {}
            phase = pod_status.get("phase")
            if phase != "Running":
                return False
            metadata = pod.get("metadata") or {}
            if metadata.get("deletionTimestamp"):
                return False
            for container_status in pod_status.get("containerStatuses") or []:
                state = container_status.get("state") or {}
                if "running" not in state:
                    return False
        return True

    def snapshot_cluster(self, deployment: str, namespace: str | None = None, label: str = "snapshot") -> dict[str, Any]:
        """Capture a deployment-level state snapshot for the report.

        We only capture what the report cares about: the deployment's
        current spec revision, its ready/desired/available counts, and
        the phase + restart count of each pod. A full ``kubectl get
        deployment -o yaml`` dump would be noisier and wouldn't add
        much diagnostic value for the common "did Mesh drive this back
        to healthy?" question.
        """
        namespace = namespace or self.namespace
        deploy_raw = self._kubectl_json("get", "deployment", deployment, "-n", namespace, "-o", "json")
        pods_raw = self._kubectl_json(
            "get", "pods", "-n", namespace, "-l", f"app={deployment}", "-o", "json"
        )
        snapshot = {
            "label": label,
            "taken_at": time.time(),
            "deployment_status": deploy_raw.get("status") or {},
            "deployment_revision": deploy_raw.get("metadata", {}).get("annotations", {}).get(
                "deployment.kubernetes.io/revision"
            ),
            "pods": [
                {
                    "name": p.get("metadata", {}).get("name"),
                    "phase": (p.get("status") or {}).get("phase"),
                    "restarts": sum(
                        int(cs.get("restartCount", 0))
                        for cs in (p.get("status") or {}).get("containerStatuses", [])
                    ),
                }
                for p in pods_raw.get("items", [])
            ],
        }
        return snapshot

    # ---------------------------------------------------------------- chaos

    def inject(self, primitive: str, deployment: str, namespace: str | None = None, **kwargs: Any) -> InjectionResult:
        """Call a chaos primitive and record the injection in the scenario.

        Routing through this method (instead of scenario code calling
        ``self.injector.inject_crash_loop(...)`` directly) means every
        injection is automatically added to the scenario timeline.
        That's what the report shows in the "Chaos" section; without
        this wrapper, a scenario that forgets to call ``record_step``
        would produce a report with the failure invisibly missing.
        """
        namespace = namespace or self.namespace
        method = getattr(self.injector, f"inject_{primitive}", None)
        if method is None:
            raise AssertionError(f"unknown chaos primitive: {primitive}")
        result = method(deployment, namespace, **kwargs)
        self._chaos.append(result)
        self.record_step(
            f"chaos:{primitive}",
            deployment=deployment,
            namespace=namespace,
            detected_after_seconds=round((result.observed_at or result.injected_at) - result.injected_at, 2),
        )
        return result

    # ---------------------------------------------------------------- mesh pipeline

    def run_mesh_pipeline(self, deployment: str, namespace: str | None = None) -> dict[str, Any]:
        """Collect a live signal and run the full Mesh pipeline on it.

        Isolated as its own method so scenarios can call it multiple
        times in a run — e.g. once to get Mesh's initial decision on
        the chaos, once again after remediation to confirm the follow-
        up signal is healthy. The pipeline is pure with respect to
        ``state_directory`` so repeated calls don't interfere.
        """
        from services.ingest.kubernetes_live_signal import collect_kubernetes_signal
        from services.pipeline import FirstSlicePipeline

        namespace = namespace or self.namespace
        self.record_step("mesh:collect_signal", deployment=deployment, namespace=namespace)
        signal = collect_kubernetes_signal(
            deployment_name=deployment,
            namespace=namespace,
            kube_context=self.kube_context,
            environment="e2e",
        )

        # The pipeline config overrides: we want live Kubernetes
        # execution *disabled* in the harness because the harness
        # drives remediation through the chaos injector's revert, not
        # through kubectl-rollback. Running the actuator live here
        # would double-action the cluster and confuse the report.
        config = RuntimeConfig(
            environment="e2e",
            evaluation_mode="native",
            orchestration_mode="native",
            state_directory=self.state_directory,
            default_steering_mode="interruptible_auto",
            default_operator_pause_point="",
            kubernetes_live_execution_enabled=False,
            server_host="127.0.0.1",
            server_port=0,  # never bound; pipeline doesn't start a server
        )
        self.record_step("mesh:pipeline_start")
        pipeline = FirstSlicePipeline(config=config)
        result = pipeline.run(signal, scenario_name=f"e2e:{deployment}")
        self.record_step("mesh:pipeline_complete", stages_emitted=len(result.get("run_events", [])))
        return result

    # ---------------------------------------------------------------- kubectl

    def _kubectl_json(self, *args: str) -> dict[str, Any]:
        command = [self.kubectl, "--context", self.kube_context] + list(args)
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
        if completed.returncode != 0:
            raise AssertionError(f"kubectl {' '.join(args)} failed: {completed.stderr.strip()}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(f"kubectl {' '.join(args)} returned invalid JSON: {exc}") from exc


# ---------------------------------------------------------------- cluster lifecycle


def ensure_cluster_reachable(kube_context: str, kubectl: str = "kubectl") -> None:
    """Fail-fast check that the operator remembered to bring up the cluster.

    A scenario that starts executing against a nonexistent cluster
    produces a confusing chain of kubectl errors. Checking up front
    with a clear message is much kinder to the operator.
    """
    completed = subprocess.run(
        [kubectl, "--context", kube_context, "get", "nodes"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"cluster with context {kube_context!r} is not reachable. "
            f"Run `kind create cluster --config tests/e2e/fixtures/kind-config.yaml` first.\n"
            f"kubectl stderr: {completed.stderr.strip()}"
        )


def apply_workload(manifest_path: str | os.PathLike[str], kube_context: str, kubectl: str = "kubectl") -> None:
    """Apply the baseline workload manifest.

    Idempotent — ``kubectl apply`` handles the "already exists" case.
    Run from the driver script, not from scenarios; scenarios assume
    the baseline is already there.
    """
    command = [kubectl, "--context", kube_context, "apply", "-f", str(manifest_path)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    if completed.returncode != 0:
        raise AssertionError(f"kubectl apply failed: {completed.stderr.strip()}")
    _LOG.info("applied %s", manifest_path)


__all__ = [
    "Harness",
    "ScenarioRun",
    "ScenarioStep",
    "apply_workload",
    "ensure_cluster_reachable",
]


# Re-export for convenience
if __name__ == "__main__":  # pragma: no cover - manual invocation
    raise SystemExit(
        "Don't run harness.py directly. Use scripts/run_e2e.sh or import from a scenario module."
    )


# Keep Path import used (mypy/ruff hint)
_ = Path
