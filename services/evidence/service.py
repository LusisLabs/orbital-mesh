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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
import inspect
from typing import TYPE_CHECKING, Any, Callable

from services.evidence.reth_probe_registry import (
    RETH_PROBE_DEFINITIONS,
    citation_for_probe,
    snapshot_for_probe,
)
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
    # Detected by the log-pattern matcher below — we add it so any
    # downstream consumer that lists "what's in the fast-path set" sees
    # it explicitly, not just as a runtime side-effect.
    "filesystem_unsuitable",
})


# Log patterns that indicate database-engine corruption per client.
# Each entry is ``(regex, signature)`` where ``signature`` is the
# error_signatures token we stamp on the trigger so the deterministic
# policy and the LLM observer both see "DB on fire" rather than guess.
#
# Sources for the patterns (April 2026):
#   * libmdbx README + ``mdbx_chk`` man page (Reth, Erigon hot DB)
#   * Pebble error strings in ``cockroachdb/pebble`` (Geth ≥1.13)
#   * RocksDB Status messages (Nethermind, Teku, legacy Geth)
#   * BoltDB error constants (Prysm)
#   * SQLite ``integrity_check`` outputs (Lighthouse slashing-protection,
#     Nimbus chain DB)
#
# We deliberately cast a wide net: false-positives here cost us a single
# escalation, false-negatives can cost a node. Each pattern is
# case-insensitive and anchored at a token boundary so we don't match
# the literal string in a comment or chat log.
_DB_CORRUPTION_PATTERNS: tuple[tuple[str, str], ...] = (
    # MDBX (Reth, Erigon)
    (r"\bMDBX_CORRUPTED\b", "db_corruption_suspected"),
    (r"\bMDBX_INVALID\b", "db_corruption_suspected"),
    (r"\bMDBX_WANNA_RECOVERY\b", "db_corruption_suspected"),
    (r"\bMDBX_PAGE_NOTFOUND\b", "db_corruption_suspected"),
    (r"\bMDBX_INCOMPATIBLE\b", "db_corruption_suspected"),
    # Pebble (Geth)
    (r"pebble:\s*manifest\s+version\s+not\s+found", "db_corruption_suspected"),
    (r"pebble:\s*corruption\s+at\s+offset", "db_corruption_suspected"),
    (r"cannot\s+find\s+file.*\.sst.*referenced\s+in\s+manifest", "db_corruption_suspected"),
    # RocksDB (Nethermind, Teku)
    (r"Corruption:\s*SST\s+file\s+is\s+ahead\s+of\s+WAL", "db_corruption_suspected"),
    (r"Corruption:\s*MANIFEST\s+missing", "db_corruption_suspected"),
    (r"Corruption:\s*bad\s+block\s+contents", "db_corruption_suspected"),
    # BoltDB (Prysm validator.db, beaconchaindata)
    (r"\bbolt:\s*invalid\s+database\b", "db_corruption_suspected"),
    (r"\bmeta\s+page\s+checksum\s+failed\b", "db_corruption_suspected"),
    # SQLite (Lighthouse slashing-protection, Nimbus)
    (r"database\s+disk\s+image\s+is\s+malformed", "db_corruption_suspected"),
    (r"file\s+is\s+not\s+a\s+database", "db_corruption_suspected"),
    (r"PRAGMA\s+integrity_check[\s\S]{0,200}?(?!ok\b)\b\w+", "db_corruption_suspected"),
    # Generic state-trie divergence (bit-rot, pruner bugs)
    (r"\bmissing\s+trie\s+node\b", "db_corruption_suspected"),
    (r"\bstate\s+root\s+mismatch\b", "db_corruption_suspected"),
)


# Filesystems that are unsafe for chain databases. The MDBX README is
# explicit that NFS and FUSE break atomicity guarantees; tmpfs is a
# disk-loss-on-reboot trap; CIFS/SMB is even worse than NFS.
#
# We accept the filesystem name as it appears in ``/proc/mounts`` (and
# in ``signal.resource_attributes["mesh.node.fstype"]`` if the operator
# stamps it). The fast-path fires when the datadir's reported fstype
# matches; we do **not** call ``findmnt`` from inside the service because
# that would couple Mesh to the host where the *signal* originated, not
# where Mesh runs.
_UNSAFE_FILESYSTEMS: frozenset[str] = frozenset({
    "nfs", "nfs3", "nfs4",
    "cifs", "smbfs", "smb3",
    "fuse", "fuse.s3fs", "fuse.rclone", "fuse.sshfs",
    "tmpfs",
})


# Pre-compile the corruption patterns once. Module-import cost is one-shot.
_DB_CORRUPTION_REGEX: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.IGNORECASE), signature)
    for pattern, signature in _DB_CORRUPTION_PATTERNS
)


def _scan_logs_for_corruption(log_lines: list[str]) -> list[str]:
    """Return the corruption signatures detected in the log lines.

    The matcher is allow-list-by-pattern: only patterns explicitly
    listed in ``_DB_CORRUPTION_PATTERNS`` produce a stamp, and the
    stamp is the signature token from that table. Multiple patterns
    can hit the same signature (e.g. several MDBX errors → one
    ``db_corruption_suspected``); we de-dupe.
    """
    if not log_lines:
        return []
    hits: set[str] = set()
    for line in log_lines:
        if not isinstance(line, str):
            continue
        for regex, signature in _DB_CORRUPTION_REGEX:
            if regex.search(line):
                hits.add(signature)
                break  # one signature per line is enough
    return sorted(hits)


def _detect_unsafe_filesystem(signal_payload: dict[str, Any]) -> str | None:
    """Return the filesystem name if it's in ``_UNSAFE_FILESYSTEMS``,
    else ``None``.

    The signal carries fs type via either:
      * ``resource_attributes["mesh.node.fstype"]`` — string,
        canonical lowercase name as it appears in /proc/mounts
      * ``storage["filesystem"]`` — same string in a more discoverable
        location for new emitters

    We accept both because operator-stamped attributes are easier to
    add to existing Prometheus rules than a schema change.
    """
    storage = signal_payload.get("storage") if isinstance(signal_payload.get("storage"), dict) else {}
    rsc = signal_payload.get("resource_attributes") if isinstance(signal_payload.get("resource_attributes"), dict) else {}
    candidates: list[str] = []
    fs_storage = storage.get("filesystem") if isinstance(storage, dict) else None
    if isinstance(fs_storage, str) and fs_storage:
        candidates.append(fs_storage.strip().lower())
    fs_attr = rsc.get("mesh.node.fstype") if isinstance(rsc, dict) else None
    if isinstance(fs_attr, str) and fs_attr:
        candidates.append(fs_attr.strip().lower())
    for fs in candidates:
        if fs in _UNSAFE_FILESYSTEMS:
            return fs
    return None


def _stamp_signature_on_trigger(trigger: "Trigger", signature: str) -> None:
    """Add a signature to the trigger's ``related_context.error_signatures``
    in place, if not already present.

    The decision service reads this list to choose an action; the
    hypothesis engine reads it to pick templates. By stamping at
    evidence-time we ensure both downstream stages see the same set.
    """
    rc = trigger.related_context
    if not isinstance(rc, dict):
        return
    sigs = rc.get("error_signatures")
    if not isinstance(sigs, list):
        sigs = []
    if signature not in sigs:
        sigs.append(signature)
    rc["error_signatures"] = sigs


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
    payload: dict[str, Any] | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)


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
                    "payload": r.payload or {},
                    "citations": list(r.citations),
                }
                for r in self.probe_results
            ],
            "sufficient": self.sufficient,
            "missing_fields": list(self.missing_fields),
            "fast_path_signatures": list(self.fast_path_signatures),
        }


# A probe runner takes a signal payload and an optional investigation plan,
# then returns (enriched_pack, probe_results).
# The default runner is the identity transform — it just returns the inbound
# signal as the pack. Live mode wires a runner that calls the bare-metal
# ingester; tests inject a deterministic dict-backed runner.
ProbeRunner = Callable[..., tuple[dict[str, Any], list[ProbeResult]]]


def _identity_runner(
    signal: dict[str, Any],
    investigation_plan: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[ProbeResult]]:
    """Default pass-through: trust the inbound signal as the pack."""
    typed = _probe_results_from_plan(signal, investigation_plan, default_source="inline")
    if typed:
        return signal, typed
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
        investigation_plan: dict[str, Any] | None = None,
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

        # Pre-fast-path scans. Two passes that can stamp escalation
        # signatures the trigger didn't carry:
        #
        #   1. Log-pattern matcher for DB-engine corruption. The
        #      operator's Prometheus rule may have fired on a generic
        #      symptom (peer count low, sync stalled) while the actual
        #      root cause is MDBX/Pebble/RocksDB/BoltDB/SQLite saying
        #      "I'm broken." We scan the recent error lines the
        #      ingester captured and stamp ``db_corruption_suspected``
        #      so the decision escalates instead of restarting a
        #      stateful process from a corrupted DB.
        #   2. Filesystem unsuitability check. Operators sometimes
        #      mount data directories on NFS/FUSE/tmpfs to "save
        #      money" or "share state." Both are unsafe for chain DBs;
        #      MDBX in particular relies on atomic 4K-aligned writes
        #      that NFS does not provide. If the signal carries a
        #      filesystem hint that's in our deny-list, we stamp
        #      ``filesystem_unsuitable`` and let the fast-path
        #      escalation fire.
        recent_errors = (signal_payload.get("logs") or {}).get("recent_errors") or []
        if isinstance(recent_errors, list):
            for sig in _scan_logs_for_corruption(recent_errors):
                _stamp_signature_on_trigger(trigger, sig)
        unsafe_fs = _detect_unsafe_filesystem(signal_payload)
        if unsafe_fs is not None:
            _LOG.warning(
                "evidence: unsafe filesystem detected for trigger=%s fstype=%s",
                trigger.trigger_id,
                unsafe_fs,
            )
            _stamp_signature_on_trigger(trigger, "filesystem_unsuitable")

        # Fast path: if the trigger already names an exposure/credential
        # signature (originally, or stamped above), skip probe assembly.
        # The decision will escalate regardless and there's no point
        # waiting on RPC.
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
                        payload={"fast_path_signatures": fast_path_hits},
                        citations=[{"source_type": "trigger", "source_ref": trigger.trigger_id}],
                    )
                ],
                sufficient=True,
                fast_path_signatures=fast_path_hits,
            )

        # Normal path: run the probe runner, run sufficiency.
        try:
            enriched, probes = _invoke_probe_runner(self._probe_runner, signal_payload, investigation_plan)
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
                        citations=[{"source_type": "evidence_runner", "source_ref": "probe_runner"}],
                    )
                ],
                sufficient=False,
                missing_fields=list(self._required_fields),
            )

        # Pack source: ``live_probe`` if the runner attempted an external
        # lookup, ``inline_signal`` for the identity runner.
        source = (
            "live_probe"
            if enriched is not signal_payload or any(probe.source != "inline" for probe in probes)
            else "inline_signal"
        )

        sufficient, missing = self._check_sufficiency(enriched)
        failed_live_probes = [
            probe.name
            for probe in probes
            if not probe.success and probe.source in {"configured_targets", "json_rpc", "filesystem", "systemd", "posture"}
        ]
        if failed_live_probes:
            sufficient = False
            missing = sorted(set([*missing, *failed_live_probes]))

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


def _invoke_probe_runner(
    runner: ProbeRunner,
    signal_payload: dict[str, Any],
    investigation_plan: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[ProbeResult]]:
    try:
        params = inspect.signature(runner).parameters
    except (TypeError, ValueError):
        return runner(signal_payload, investigation_plan)

    accepts_varargs = any(param.kind == param.VAR_POSITIONAL for param in params.values())
    positional_params = [
        param
        for param in params.values()
        if param.kind in {param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD}
    ]
    if accepts_varargs or len(positional_params) >= 2:
        return runner(signal_payload, investigation_plan)
    return runner(signal_payload)


def _probe_results_from_plan(
    snapshot: dict[str, Any],
    investigation_plan: dict[str, Any] | None,
    *,
    default_source: str,
) -> list[ProbeResult]:
    if not isinstance(investigation_plan, dict):
        return []
    probes = investigation_plan.get("probes")
    if not isinstance(probes, list):
        return []
    results: list[ProbeResult] = []
    for probe in probes:
        if not isinstance(probe, dict):
            continue
        name = str(probe.get("name", ""))
        definition = RETH_PROBE_DEFINITIONS.get(name)
        if definition is None:
            continue
        payload = snapshot_for_probe(name, snapshot)
        results.append(
            ProbeResult(
                name=name,
                source=str(definition.get("source") or default_source),
                success=bool(payload),
                latency_ms=0.0,
                error=None if payload else "probe_payload_unavailable",
                payload=payload,
                citations=[citation_for_probe(name)],
            )
        )
    return results
