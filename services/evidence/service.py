"""Evidence assembly stage — promote a signal from "lead" to "case".

# Why this stage exists

The pipeline used to fold ingestion and evidence-gathering into a single
step: ``bare_metal_node.RethNodeIngester.build_signal`` polled the node
and emitted a fully-populated ``reth_node`` signal which the trigger and
decision stages then read as ground truth. That works when the signal
arrives from our own poller, but it conflates *the alert that tripped*
with *the snapshot we trust*.

Two concrete problems with that conflation:

1. A webhook-driven alert (e.g. Prometheus rule firing on ``net_peerCount``)
   only carries the metric that fired, not a full pack. If the decision
   service reads it as authoritative, it acts on rumor.
2. Even when the signal is a full pack, there's no audited "we looked
   again before acting" event. Operators reading the run log can't tell
   whether the decision was made on stale or fresh data.

This stage produces an explicit ``EvidencePack`` artifact stamped on the
run with its own assembly timestamp and per-probe results. Everything
downstream of this stage reads the pack, not the inbound signal.

# Sufficiency vs. completeness

We don't require every field to be populated — Reth nodes vary by role
(archive vs RPC vs MEV). The evidence-sufficiency policy in
``policies/reth-node.policy.json`` lists ``min_populated_fields``, the
minimum we need to act. If those are missing, the decision is forced to
``escalate`` regardless of the hypothesis ranking. The point is to fail
loudly when we don't know enough, not to demand perfect data.

# Live vs. fixture mode

The default ``probe_runner`` is a no-op pass-through: if the inbound
signal is already a fully-shaped ``reth_node`` signal (the cron-poller
case), the pack is the signal. If callers want to enrich a sparse
webhook signal, they inject a runner that calls
``RethNodeIngester.build_signal`` against a configured target.

Tests inject a deterministic dict-backed runner. We deliberately keep
the runner pluggable rather than wiring the network ingester in at
this layer — keeps the service unit-testable without network mocks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable

from shared.mesh_runtime import load_policy

if TYPE_CHECKING:
    from shared.mesh_runtime import Trigger


_LOG = logging.getLogger("mesh.evidence")


# Signatures that mean "credential or exposure incident — do not auto-act".
# Mesh's reth-node policy already routes these to ``escalate`` at decision
# time, but we surface them at the evidence stage too so the run log
# carries an explicit fast-path event. The fast-path skips probe assembly
# (we already know we're going to escalate) so we don't add latency.
_FAST_PATH_ESCALATION_SIGNATURES: frozenset[str] = frozenset({
    "authrpc_exposed",
    "rpc_exposed",
    "jwt_missing",
    "jwt_secret_insecure_permissions",
    "db_corruption_suspected",
})


# Default sufficiency check: these are the fields the hypothesis engine's
# Reth predicates need to resolve. If the inbound signal omits them, the
# engine cannot falsify alternatives and the decision is forced to
# escalate. ``policies/reth-node.policy.json`` may override these via its
# ``evidence_sufficiency`` block — see ``_load_policy_overrides``.
_DEFAULT_REQUIRED_FIELDS: tuple[str, ...] = (
    "execution.peer_count",
    "execution.syncing",
    "execution.block_lag",
    "rpc.http_reachable",
)


# Maximum number of required fields that may be null before we declare
# the pack insufficient. Two is enough slack for a probe timeout on one
# RPC method without forcing escalate.
_DEFAULT_MAX_NULL_FIELDS: int = 2


def _load_policy_overrides() -> tuple[tuple[str, ...] | None, int | None]:
    """Read the ``evidence_sufficiency`` block from the Reth policy.

    Returns ``(required_fields, max_null_fields)`` from the policy, or
    ``(None, None)`` for any value the policy doesn't set or if the
    policy can't be loaded. Either piece can be partially overridden —
    operators commonly tighten ``min_populated_fields`` without changing
    the null-tolerance threshold, so we treat the two values
    independently.
    """
    try:
        policy = load_policy("reth-node.policy.json")
    except (FileNotFoundError, OSError, ValueError) as exc:
        _LOG.warning("evidence: could not load reth-node policy: %s", exc)
        return None, None
    block = policy.get("evidence_sufficiency")
    if not isinstance(block, dict):
        return None, None
    required: tuple[str, ...] | None = None
    raw_fields = block.get("min_populated_fields")
    if isinstance(raw_fields, list) and all(isinstance(f, str) for f in raw_fields):
        required = tuple(raw_fields)
    max_null: int | None = None
    raw_max = block.get("max_null_required_fields")
    if isinstance(raw_max, int) and raw_max >= 0:
        max_null = raw_max
    return required, max_null


@dataclass
class ProbeResult:
    """Audit record for a single probe run during evidence assembly."""

    name: str
    source: str               # "json_rpc" | "filesystem" | "systemd" | "posture" | "inline"
    success: bool
    latency_ms: float | None = None
    error: str | None = None


@dataclass
class EvidencePack:
    """The audited snapshot a decision is allowed to act on.

    For Reth this is the existing ``reth_node`` signal shape, plus
    assembly metadata. We deliberately reuse the schema rather than
    creating a parallel one — schema drift between signal and evidence
    would be a maintenance burden that buys nothing.
    """

    pack: dict[str, Any]
    assembled_at: str
    source: str               # "inline_signal" | "live_probe" | "fast_path_skip"
    probe_results: list[ProbeResult] = field(default_factory=list)
    sufficient: bool = True
    missing_fields: list[str] = field(default_factory=list)
    fast_path_signatures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack": self.pack,
            "assembled_at": self.assembled_at,
            "source": self.source,
            "probe_results": [
                {
                    "name": r.name,
                    "source": r.source,
                    "success": r.success,
                    "latency_ms": r.latency_ms,
                    "error": r.error,
                }
                for r in self.probe_results
            ],
            "sufficient": self.sufficient,
            "missing_fields": list(self.missing_fields),
            "fast_path_signatures": list(self.fast_path_signatures),
        }


# A probe runner takes a signal payload and returns (enriched_pack, probe_results).
# The default runner is the identity transform — it just returns the inbound
# signal as the pack. Live mode wires a runner that calls the bare-metal
# ingester; tests inject a deterministic dict-backed runner.
ProbeRunner = Callable[[dict[str, Any]], tuple[dict[str, Any], list[ProbeResult]]]


def _identity_runner(signal: dict[str, Any]) -> tuple[dict[str, Any], list[ProbeResult]]:
    """Default pass-through: trust the inbound signal as the pack."""
    return signal, [
        ProbeResult(
            name="inline_signal",
            source="inline",
            success=True,
            latency_ms=0.0,
        )
    ]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_dotted(payload: dict[str, Any], path: str) -> Any:
    """Read ``a.b.c`` from a nested dict, returning ``None`` if any
    intermediate key is missing or not a dict."""
    cursor: Any = payload
    for key in path.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor


class EvidenceService:
    """Assemble an audited evidence pack for a node-shaped signal.

    The service is intentionally narrow: it does not own probe code, does
    not know about specific clients (Reth/geth/Solana), and does not
    decide. It accepts an inbound signal payload, optionally runs a
    pluggable probe runner to enrich it, runs the sufficiency check, and
    returns an ``EvidencePack`` plus a list of run-event payloads the
    coordinator should append.

    The coordinator is the only thing allowed to touch run state, so this
    service stays pure (no I/O outside the probe runner). That makes it
    trivially testable.
    """

    def __init__(
        self,
        *,
        probe_runner: ProbeRunner | None = None,
        required_fields: tuple[str, ...] | None = None,
        max_null_fields: int | None = None,
    ) -> None:
        self._probe_runner = probe_runner or _identity_runner
        # Resolution order for sufficiency thresholds:
        #   1. Explicit constructor argument (used by tests).
        #   2. ``evidence_sufficiency`` block in reth-node.policy.json.
        #   3. Hardcoded defaults at the top of this module.
        # Operators changing the policy file should not have to also
        # change source — that was the original drift the policy block
        # was meant to prevent.
        policy_required, policy_max_null = _load_policy_overrides()
        self._required_fields = (
            required_fields
            if required_fields is not None
            else (policy_required if policy_required is not None else _DEFAULT_REQUIRED_FIELDS)
        )
        self._max_null_fields = (
            max_null_fields
            if max_null_fields is not None
            else (policy_max_null if policy_max_null is not None else _DEFAULT_MAX_NULL_FIELDS)
        )

    def assemble(
        self,
        *,
        trigger: "Trigger",
        signal_payload: dict[str, Any],
    ) -> EvidencePack:
        """Build a pack from the inbound signal and optional probes.

        Currently scoped to ``reth_node`` signals; other signal types
        return a no-op pack with ``source="inline_signal"`` and the input
        payload as the pack. This keeps the service safe to wire on the
        default path even before non-Reth handlers are added.
        """
        signal_type = signal_payload.get("signal_type")

        # Non-Reth signals: no-op pack so the rest of the pipeline still
        # reads ``evidence_pack`` uniformly. The probe runner is not invoked.
        if signal_type != "reth_node":
            return EvidencePack(
                pack=signal_payload,
                assembled_at=_now_iso(),
                source="inline_signal",
                probe_results=[],
                sufficient=True,
            )

        # Fast path: if the trigger already names an exposure/credential
        # signature, skip probe assembly. The decision will escalate
        # regardless and there's no point waiting on RPC.
        error_signatures = list(trigger.related_context.get("error_signatures", []))
        fast_path_hits = sorted(
            sig for sig in error_signatures if sig in _FAST_PATH_ESCALATION_SIGNATURES
        )
        if fast_path_hits:
            _LOG.info(
                "evidence: fast-path escalate trigger=%s signatures=%s",
                trigger.trigger_id,
                fast_path_hits,
            )
            return EvidencePack(
                pack=signal_payload,
                assembled_at=_now_iso(),
                source="fast_path_skip",
                probe_results=[
                    ProbeResult(
                        name="fast_path_check",
                        source="inline",
                        success=True,
                        latency_ms=0.0,
                    )
                ],
                sufficient=True,
                fast_path_signatures=fast_path_hits,
            )

        # Normal path: run the probe runner, run sufficiency.
        try:
            enriched, probes = self._probe_runner(signal_payload)
        except Exception as exc:
            # A probe runner that throws is itself an evidence problem.
            # We surface it as an insufficient pack rather than crashing
            # the run — the decision will escalate.
            _LOG.warning(
                "evidence: probe runner failed for trigger=%s: %s",
                trigger.trigger_id,
                exc,
            )
            return EvidencePack(
                pack=signal_payload,
                assembled_at=_now_iso(),
                source="live_probe",
                probe_results=[
                    ProbeResult(
                        name="probe_runner",
                        source="inline",
                        success=False,
                        error=str(exc),
                    )
                ],
                sufficient=False,
                missing_fields=list(self._required_fields),
            )

        # Pack source: ``live_probe`` if the runner enriched the input,
        # ``inline_signal`` if it returned an unchanged identity result.
        source = "live_probe" if enriched is not signal_payload else "inline_signal"

        sufficient, missing = self._check_sufficiency(enriched)

        return EvidencePack(
            pack=enriched,
            assembled_at=_now_iso(),
            source=source,
            probe_results=list(probes),
            sufficient=sufficient,
            missing_fields=missing,
        )

    def _check_sufficiency(self, pack: dict[str, Any]) -> tuple[bool, list[str]]:
        missing: list[str] = []
        for path in self._required_fields:
            if _read_dotted(pack, path) is None:
                missing.append(path)
        return (len(missing) <= self._max_null_fields), missing
