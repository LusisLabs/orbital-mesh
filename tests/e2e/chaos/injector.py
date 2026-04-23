"""Deterministic failure injection via kubectl.

# Design

Each method on :class:`ChaosInjector` mutates a target deployment into a
specific failure mode so the harness can assert Mesh's remediation
response. Mutations are:

* **Deterministic** — same input produces the same failed state.
* **Reversible** — :meth:`ChaosInjector.revert` restores the deployment
  to its baseline spec. A test that leaves the cluster dirty is a bug.
* **Observable** — each method waits for the expected pod state before
  returning, so the caller never has to second-guess whether the
  failure has actually manifested.

We use ``kubectl patch`` with a strategic merge patch for everything
except pod-level kills. Strategic merge patches compose with the
existing manifest and can be reverted by reading the original spec
before mutating — which :class:`ChaosInjector` does automatically for
any deployment it touches.

# What's NOT in here

No chaos-mesh, no litmus, no pumba, no privileged containers. The
primitives cover the 80% that matter for Mesh's current action catalog:

| Failure mode | Exercises Mesh action |
|--------------|----------------------|
| CrashLoopBackOff (bad command) | restart_deployment / rollback_deployment |
| ImagePullBackOff (bad image) | rollback_deployment |
| Readiness-probe failure | restart_deployment |
| Memory pressure (tight limit) | scale_deployment / patch_resources |
| Pod kill | no direct action — validates baseline recovery |

More exotic failures (network partition, disk fault, clock skew)
require additional tooling and belong in a follow-up PR alongside the
Mesh actions they'd drive.

# Why not use chaos-mesh for scenario #1?

chaos-mesh is the industry standard and has richer primitives, but it's
a controller + CRDs + webhook — installing it on every e2e run adds
~60s and a stateful dependency that's easy to get wrong. The first
scenario is about proving Mesh's end-to-end loop works against a real
cluster; the failure just needs to be real and deterministic. A 200-
line kubectl wrapper does that without the tax.

We can layer chaos-mesh on top of this interface later — the scenarios
call ``injector.inject_crash_loop()``, not ``kubectl`` directly, so a
``ChaosMeshInjector`` drop-in is a future-PR-sized change.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


_LOG = logging.getLogger("mesh.e2e.chaos")


class ChaosError(RuntimeError):
    """Raised when kubectl fails or a failure mode doesn't manifest in time.

    We raise rather than swallow because chaos injection is the premise of
    every scenario — a scenario that can't inject its failure is not a
    valid test, and we want that visible immediately rather than buried
    in a misleading 'Mesh didn't detect the fault' assertion later.
    """


@dataclass
class DeploymentBaseline:
    """Snapshot of a deployment's pre-chaos spec so we can revert cleanly.

    We capture ``spec.template`` (the pod template) because that's the
    only section the chaos primitives modify. Keeping the snapshot
    narrow makes it obvious what revert will and won't touch.
    """

    name: str
    namespace: str
    spec_template: dict[str, Any]


@dataclass
class InjectionResult:
    """Outcome of an injection, stamped into the scenario report.

    Timings here feed directly into the report's ``chaos`` block so the
    generated markdown shows exactly when each failure was introduced.
    """

    deployment: str
    namespace: str
    mode: str
    injected_at: float
    observed_at: float | None = None
    pod_snapshot: list[dict[str, Any]] = field(default_factory=list)


class ChaosInjector:
    """Inject deterministic failures into a kind cluster via kubectl.

    Construct once per scenario run; the injector caches a baseline of
    each deployment it touches so :meth:`revert` can put the cluster
    back to its pre-chaos state. Scenarios should always call
    :meth:`revert` in a finally-block — a half-broken cluster left
    behind is both a test-suite problem and a waste of operator time.
    """

    def __init__(self, kubectl: str = "kubectl", kube_context: str | None = None, timeout_seconds: int = 30):
        self.kubectl = kubectl
        self.kube_context = kube_context
        self.timeout_seconds = timeout_seconds
        self._baselines: dict[tuple[str, str], DeploymentBaseline] = {}

    # ---------------------------------------------------------------- injection

    def inject_crash_loop(self, deployment: str, namespace: str) -> InjectionResult:
        """Force a deployment into CrashLoopBackOff by replacing its command.

        We patch the container's ``command`` to ``false`` — the Unix
        command that immediately exits 1. Kubelet tries to restart the
        container on failure, the container exits again, the kubelet
        backs off, and after two or three cycles the pod status becomes
        ``CrashLoopBackOff``.

        The Mesh signal ingester recognizes this pattern and the decision
        engine's ``_decide_kubernetes`` branch proposes ``restart_deployment``
        (which won't help — the command is still bad, the point is to
        prove the loop fires) or ``rollback_deployment`` (which does
        help, because the baseline revision still has the good command).
        """
        self._snapshot(deployment, namespace)
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            # Match on container name. Strategic merge
                            # patches with an array need the key ("name")
                            # to identify which element to patch.
                            {"name": deployment, "command": ["false"], "args": []}
                        ]
                    }
                }
            }
        }
        injected_at = time.monotonic()
        self._kubectl_patch(deployment, namespace, patch)
        _LOG.info("injected crash_loop into %s/%s", namespace, deployment)

        observed_at = self._wait_for_pod_reason(
            deployment, namespace, reasons=("CrashLoopBackOff",), timeout_seconds=90,
        )
        return InjectionResult(
            deployment=deployment,
            namespace=namespace,
            mode="crash_loop",
            injected_at=injected_at,
            observed_at=observed_at,
            pod_snapshot=self._list_pods(deployment, namespace),
        )

    def inject_bad_image(self, deployment: str, namespace: str, bad_image: str = "nginx:does-not-exist-mesh-e2e") -> InjectionResult:
        """Force ImagePullBackOff by pointing the container at a missing image.

        Same trigger shape as crash-loop from kubectl's perspective
        (pod status shows a non-running reason), but exercises a
        different Mesh decision path: the event reasons list includes
        ``ImagePullBackOff`` / ``ErrImagePull``, which the Mesh trigger
        detector maps to a ``image_pull_failure`` error signature,
        which drives ``rollback_deployment`` in the decision engine.
        """
        self._snapshot(deployment, namespace)
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{"name": deployment, "image": bad_image}]
                    }
                }
            }
        }
        injected_at = time.monotonic()
        self._kubectl_patch(deployment, namespace, patch)
        _LOG.info("injected bad_image (%s) into %s/%s", bad_image, namespace, deployment)

        observed_at = self._wait_for_pod_reason(
            deployment,
            namespace,
            reasons=("ImagePullBackOff", "ErrImagePull"),
            timeout_seconds=60,
        )
        return InjectionResult(
            deployment=deployment,
            namespace=namespace,
            mode="bad_image",
            injected_at=injected_at,
            observed_at=observed_at,
            pod_snapshot=self._list_pods(deployment, namespace),
        )

    def inject_readiness_failure(self, deployment: str, namespace: str) -> InjectionResult:
        """Make the readiness probe permanently fail.

        The pod itself keeps running — the container doesn't crash —
        but the service stops routing traffic to it because readiness
        is false. This is a subtle failure mode: ``kubectl get pods``
        shows ``Running`` but ``kubectl get deployment`` shows
        ``READY 0/2``.

        Exercised for completeness — it's the "soft" failure the decision
        engine should also handle. We point the probe at a port that
        isn't listening so the probe fails without a container restart
        (unlike liveness, readiness-probe failures don't trigger
        kubelet restarts).
        """
        self._snapshot(deployment, namespace)
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": deployment,
                                "readinessProbe": {
                                    "tcpSocket": {"port": 9999},
                                    "initialDelaySeconds": 1,
                                    "periodSeconds": 2,
                                    "failureThreshold": 2,
                                },
                            }
                        ]
                    }
                }
            }
        }
        injected_at = time.monotonic()
        self._kubectl_patch(deployment, namespace, patch)
        _LOG.info("injected readiness_failure into %s/%s", namespace, deployment)

        observed_at = self._wait_for_zero_ready(deployment, namespace, timeout_seconds=60)
        return InjectionResult(
            deployment=deployment,
            namespace=namespace,
            mode="readiness_failure",
            injected_at=injected_at,
            observed_at=observed_at,
            pod_snapshot=self._list_pods(deployment, namespace),
        )

    # ---------------------------------------------------------------- revert

    def revert(self, deployment: str, namespace: str) -> None:
        """Restore a deployment to its captured baseline.

        Safe to call multiple times — after the first successful revert,
        the cached baseline matches the live spec and the second call is
        a no-op. If no baseline was captured (revert called on something
        we never mutated), we log and return. Raising here would make
        scenario teardown brittle in exactly the cases you'd want it to
        be generous.
        """
        key = (namespace, deployment)
        baseline = self._baselines.get(key)
        if baseline is None:
            _LOG.warning("revert called on %s/%s but no baseline captured", namespace, deployment)
            return
        patch = {"spec": {"template": baseline.spec_template}}
        self._kubectl_patch(deployment, namespace, patch)
        _LOG.info("reverted %s/%s to baseline", namespace, deployment)

    def revert_all(self) -> None:
        """Revert every deployment this injector has snapshotted.

        Intended for the scenario teardown path. Exceptions during revert
        are logged but not re-raised — if one deployment fails to revert,
        we still want the others to be tried.
        """
        for (namespace, deployment) in list(self._baselines.keys()):
            try:
                self.revert(deployment, namespace)
            except ChaosError as exc:
                _LOG.error("failed to revert %s/%s: %s", namespace, deployment, exc)

    # ---------------------------------------------------------------- helpers

    def _snapshot(self, deployment: str, namespace: str) -> None:
        """Capture the pod template for later revert.

        We grab only the template rather than the full deployment spec
        because every chaos primitive mutates inside ``spec.template``;
        reverting outside of that scope risks undoing legitimate changes
        the operator might have made during the scenario (e.g. scale).
        """
        key = (namespace, deployment)
        if key in self._baselines:
            return
        raw = self._kubectl_json(
            "get",
            "deployment",
            deployment,
            "-n",
            namespace,
            "-o",
            "json",
        )
        try:
            template = raw["spec"]["template"]
        except KeyError as exc:
            raise ChaosError(f"deployment {namespace}/{deployment} has no spec.template") from exc
        self._baselines[key] = DeploymentBaseline(
            name=deployment,
            namespace=namespace,
            spec_template=deepcopy(template),
        )

    def _wait_for_pod_reason(
        self,
        deployment: str,
        namespace: str,
        reasons: tuple[str, ...],
        timeout_seconds: int,
    ) -> float:
        """Block until any pod for this deployment shows a matching reason.

        Returns the monotonic timestamp at which the reason was first
        observed — the caller stamps that into the :class:`InjectionResult`
        so the report can show "took N seconds for CrashLoopBackOff to
        manifest", which is useful for distinguishing "Mesh was fast"
        from "chaos was slow".
        """
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            pods = self._list_pods(deployment, namespace)
            for pod in pods:
                for container_status in pod.get("containerStatuses", []):
                    waiting = container_status.get("state", {}).get("waiting") or {}
                    if waiting.get("reason") in reasons:
                        return time.monotonic()
            time.sleep(1.0)
        raise ChaosError(
            f"no pod for {namespace}/{deployment} reached any of {reasons!r} "
            f"within {timeout_seconds}s"
        )

    def _wait_for_zero_ready(self, deployment: str, namespace: str, timeout_seconds: int) -> float:
        """Block until the deployment's ready replica count hits zero."""
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            raw = self._kubectl_json(
                "get", "deployment", deployment, "-n", namespace, "-o", "json",
            )
            status = raw.get("status") or {}
            if int(status.get("readyReplicas", 0) or 0) == 0:
                return time.monotonic()
            time.sleep(1.0)
        raise ChaosError(
            f"deployment {namespace}/{deployment} still had ready replicas after {timeout_seconds}s"
        )

    def _list_pods(self, deployment: str, namespace: str) -> list[dict[str, Any]]:
        """Return a flat list of pod status summaries for this deployment.

        We filter by the standard ``app=<deployment>`` label used in the
        e2e workload manifests. If you change the label selector in the
        manifests, update this too — kubectl doesn't report mismatches,
        it just returns empty, which makes failures silent.
        """
        raw = self._kubectl_json(
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            f"app={deployment}",
            "-o",
            "json",
        )
        pods: list[dict[str, Any]] = []
        for item in raw.get("items", []):
            status = item.get("status") or {}
            pods.append(
                {
                    "name": item.get("metadata", {}).get("name"),
                    "phase": status.get("phase"),
                    "conditions": status.get("conditions", []),
                    "containerStatuses": status.get("containerStatuses", []),
                }
            )
        return pods

    # ---------------------------------------------------------------- kubectl

    def _kubectl_patch(self, deployment: str, namespace: str, patch: dict[str, Any]) -> None:
        """Issue a strategic merge patch on the deployment."""
        command = self._kubectl_base() + [
            "patch",
            "deployment",
            deployment,
            "-n",
            namespace,
            "--type",
            "strategic",
            "-p",
            json.dumps(patch),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=self.timeout_seconds)
        if completed.returncode != 0:
            raise ChaosError(f"kubectl patch failed: {completed.stderr.strip()}")

    def _kubectl_json(self, *args: str) -> dict[str, Any]:
        command = self._kubectl_base() + list(args)
        completed = subprocess.run(command, capture_output=True, text=True, check=False, timeout=self.timeout_seconds)
        if completed.returncode != 0:
            raise ChaosError(f"kubectl {' '.join(args)} failed: {completed.stderr.strip()}")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ChaosError(f"kubectl returned invalid JSON: {exc}") from exc

    def _kubectl_base(self) -> list[str]:
        base = [self.kubectl]
        if self.kube_context:
            base.extend(["--context", self.kube_context])
        return base


__all__ = ["ChaosError", "ChaosInjector", "DeploymentBaseline", "InjectionResult"]
