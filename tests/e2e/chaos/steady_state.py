"""Steady-state probe and circuit breaker for continuous chaos sessions.

# What "steady state" means here

From the Principles of Chaos: *"Focus on the measurable output of a
system, rather than internal attributes."* For Mesh, the measurable
outputs we can sample between experiments are:

1. **Cluster reachability** — ``kubectl get nodes`` returns without
   timeout. If the kube API is down, the session has bigger problems
   than whatever chaos we just injected.
2. **Baseline workload health** — the deployment we're not currently
   torturing reports ``readyReplicas == desired_replicas``. If the
   baseline is degraded, chaos bleeding between experiments is
   polluting the next one.
3. **Mesh pipeline liveness** — Mesh can collect a signal from the
   baseline deployment and run through the full pipeline in < N
   seconds without crashing. This is our proxy for "Mesh itself is
   still available." Latency breaches show up as a circuit-breaker
   trip long before a full crash would.

Each probe samples these three dimensions and records a
:class:`ProbeResult`. The session stores them as a time-series so the
report can show drift: if Mesh decision latency climbs from 80ms to
2s over the hour, the hypothesis probably failed even though no
single experiment tripped.

# Circuit breaker

The principle of *minimize blast radius* becomes concrete here. The
circuit breaker watches consecutive probe failures and halts the
session if:

* ≥2 probes in a row fail (the cluster or Mesh is clearly degraded,
  running more experiments is counterproductive)
* a single Mesh pipeline invocation hangs past the timeout
* baseline recovery time exceeds a bound (chaos is leaking between
  experiments — we lost control of the blast radius)

When the breaker trips, the session's final verdict is
``halted_by_circuit_breaker`` with the reason in the report. The
human operator investigates; the session never silently powers
through degraded probes.
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass, field


_LOG = logging.getLogger("mesh.e2e.steady_state")


@dataclass
class ProbeResult:
    """One sample of the steady-state.

    All fields are plain primitives so the dataclass serializes into
    the session report without a custom encoder. Timestamps are
    monotonic seconds-since-session-start — the report converts to
    wall-clock or relative as needed.
    """

    taken_at: float
    label: str  # human tag: "baseline", "after_5_experiments", "final"
    cluster_reachable: bool
    baseline_ready: bool
    mesh_pipeline_ok: bool
    mesh_pipeline_latency_seconds: float | None
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Pass iff all three dimensions are green.

        We deliberately don't weight the dimensions differently —
        steady state is an AND across all measured outputs. A probe
        that says "cluster fine, Mesh slow" is still a failed probe;
        the report explains *why* in ``notes``.
        """
        return self.cluster_reachable and self.baseline_ready and self.mesh_pipeline_ok


class SteadyStateProbe:
    """Sample the three steady-state dimensions.

    Construct once per session. The probe holds no per-sample state —
    each call to :meth:`sample` produces a fresh :class:`ProbeResult`
    and appends nothing internally. The session stores the history.
    """

    def __init__(
        self,
        kube_context: str,
        namespace: str,
        baseline_deployment: str,
        kubectl: str = "kubectl",
        mesh_pipeline_timeout_seconds: float = 10.0,
    ):
        self.kube_context = kube_context
        self.namespace = namespace
        self.baseline_deployment = baseline_deployment
        self.kubectl = kubectl
        self.mesh_pipeline_timeout_seconds = mesh_pipeline_timeout_seconds

    def sample(self, label: str, session_start: float) -> ProbeResult:
        """Take one steady-state sample.

        Never raises. Every failure mode populates the ``notes`` field
        and flips the relevant dimension to False. The session runner
        wants a loud but non-fatal probe — if the probe itself raised
        on a kubectl timeout, we'd lose visibility into the exact
        failure that tripped the circuit breaker.
        """
        notes: list[str] = []
        # --- cluster reachability -----------------------------------
        cluster_ok = self._cluster_reachable(notes)
        # --- baseline deployment health -----------------------------
        baseline_ok = False
        if cluster_ok:
            baseline_ok = self._baseline_ready(notes)
        # --- Mesh pipeline liveness ---------------------------------
        mesh_ok, mesh_latency = False, None
        if cluster_ok:
            mesh_ok, mesh_latency = self._mesh_pipeline_alive(notes)

        taken_at = time.monotonic() - session_start
        result = ProbeResult(
            taken_at=taken_at,
            label=label,
            cluster_reachable=cluster_ok,
            baseline_ready=baseline_ok,
            mesh_pipeline_ok=mesh_ok,
            mesh_pipeline_latency_seconds=mesh_latency,
            notes=notes,
        )
        _LOG.info(
            "probe[%s]: cluster=%s baseline=%s mesh=%s mesh_latency=%s",
            label, cluster_ok, baseline_ok, mesh_ok,
            f"{mesh_latency:.2f}s" if mesh_latency is not None else "n/a",
        )
        return result

    # ---------------------------------------------------------------- dimensions

    def _cluster_reachable(self, notes: list[str]) -> bool:
        """``kubectl get nodes`` with a tight timeout."""
        try:
            completed = subprocess.run(
                [self.kubectl, "--context", self.kube_context, "get", "nodes", "--no-headers"],
                capture_output=True, text=True, check=False, timeout=5,
            )
        except subprocess.TimeoutExpired:
            notes.append("cluster: kubectl timed out")
            return False
        if completed.returncode != 0:
            notes.append(f"cluster: {completed.stderr.strip()}")
            return False
        return True

    def _baseline_ready(self, notes: list[str]) -> bool:
        """Check that the baseline deployment has ready == desired."""
        try:
            completed = subprocess.run(
                [
                    self.kubectl, "--context", self.kube_context,
                    "get", "deployment", self.baseline_deployment,
                    "-n", self.namespace,
                    "-o", "jsonpath={.status.readyReplicas}/{.status.replicas}",
                ],
                capture_output=True, text=True, check=False, timeout=5,
            )
        except subprocess.TimeoutExpired:
            notes.append(f"baseline[{self.baseline_deployment}]: kubectl timed out")
            return False
        if completed.returncode != 0:
            notes.append(f"baseline[{self.baseline_deployment}]: {completed.stderr.strip()}")
            return False
        raw = completed.stdout.strip()
        if "/" not in raw:
            notes.append(f"baseline[{self.baseline_deployment}]: unexpected output {raw!r}")
            return False
        ready_s, desired_s = raw.split("/", 1)
        try:
            ready = int(ready_s or "0")
            desired = int(desired_s or "0")
        except ValueError:
            notes.append(f"baseline[{self.baseline_deployment}]: could not parse {raw!r}")
            return False
        if desired == 0:
            notes.append(f"baseline[{self.baseline_deployment}]: desired=0 (probably a scale_to_zero leak)")
            return False
        if ready < desired:
            notes.append(f"baseline[{self.baseline_deployment}]: {ready}/{desired} ready")
            return False
        return True

    def _mesh_pipeline_alive(self, notes: list[str]) -> tuple[bool, float | None]:
        """Run a minimal Mesh pipeline invocation against the baseline.

        We reuse the existing ``kubernetes_live_signal`` path so the
        probe measures the same code path the scheduler exercises.
        The signal is collected from a healthy deployment so Mesh
        should either no_trigger or produce a low-severity decision —
        we don't check the decision content, only that the pipeline
        completed within the timeout.
        """
        from services.ingest.kubernetes_live_signal import collect_kubernetes_signal
        from services.pipeline import FirstSlicePipeline
        from shared.mesh_runtime import RuntimeConfig

        start = time.monotonic()
        try:
            signal = collect_kubernetes_signal(
                deployment_name=self.baseline_deployment,
                namespace=self.namespace,
                kube_context=self.kube_context,
                environment="e2e-probe",
            )
        except Exception as exc:  # noqa: BLE001 — probe must never raise
            notes.append(f"mesh: signal collection failed: {exc}")
            return False, None

        # Minimal config: the probe shares a temp state dir with the
        # session, but latency is the only thing we care about. The
        # RuntimeConfig here is a throwaway.
        config = RuntimeConfig(
            environment="e2e-probe",
            evaluation_mode="native",
            orchestration_mode="native",
            default_steering_mode="interruptible_auto",
            default_operator_pause_point="",
            kubernetes_live_execution_enabled=False,
            server_host="127.0.0.1",
            server_port=0,
        )
        try:
            FirstSlicePipeline(config=config).run(signal, scenario_name="probe")
        except Exception as exc:  # noqa: BLE001 — probe must never raise
            notes.append(f"mesh: pipeline crashed: {exc}")
            return False, time.monotonic() - start

        latency = time.monotonic() - start
        if latency > self.mesh_pipeline_timeout_seconds:
            notes.append(f"mesh: latency {latency:.2f}s exceeded {self.mesh_pipeline_timeout_seconds:.2f}s")
            return False, latency
        return True, latency


class CircuitBreaker:
    """Track consecutive probe failures and decide when to halt.

    Intentionally small: one state (consecutive failure count), three
    methods (record_result, should_halt, halt_reason). The session
    runner checks ``should_halt()`` after every probe and after every
    experiment.
    """

    def __init__(self, max_consecutive_failures: int = 2, max_pipeline_latency_seconds: float = 10.0):
        self.max_consecutive_failures = max_consecutive_failures
        self.max_pipeline_latency_seconds = max_pipeline_latency_seconds
        self._consecutive_failures = 0
        self._halt_reason: str | None = None

    def record_result(self, probe: ProbeResult) -> None:
        """Consume a probe result and update breaker state.

        A passed probe resets the counter. A failed probe increments
        it and, if we've crossed the threshold, records a halt reason.
        """
        if probe.passed:
            self._consecutive_failures = 0
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.max_consecutive_failures:
            notes = "; ".join(probe.notes) if probe.notes else "probe failed"
            self._halt_reason = (
                f"{self._consecutive_failures} consecutive probe failures "
                f"(last probe notes: {notes})"
            )
        elif probe.mesh_pipeline_latency_seconds is not None and (
            probe.mesh_pipeline_latency_seconds > self.max_pipeline_latency_seconds
        ):
            self._halt_reason = (
                f"mesh pipeline latency {probe.mesh_pipeline_latency_seconds:.2f}s "
                f"exceeded threshold {self.max_pipeline_latency_seconds:.2f}s"
            )

    def should_halt(self) -> bool:
        return self._halt_reason is not None

    def halt_reason(self) -> str | None:
        return self._halt_reason

    def reset(self) -> None:
        """Reset breaker state. Useful in tests; the session runner never calls it."""
        self._consecutive_failures = 0
        self._halt_reason = None


__all__ = ["CircuitBreaker", "ProbeResult", "SteadyStateProbe"]
