"""Evidence strategies for signal-profile dispatch.

The Reth path already has a rich audited evidence stage. The agnostic
profiles need the same contract shape even when they do not yet have
domain-specific live probes. These strategies turn "pass-through" into
a policy-bearing evidence artifact: known signal types get structural
field-presence checks, while the generic fallback records that no
profile exists and marks evidence insufficient for auto-action.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.evidence.service import EvidencePack, ProbeResult
from shared.mesh_runtime import Trigger


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_dotted(payload: dict[str, Any], path: str) -> Any:
    cursor: Any = payload
    for key in path.split("."):
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(key)
    return cursor


class RethEvidenceStrategy:
    """Adapter to the existing Reth evidence implementation."""

    def __init__(self) -> None:
        self._service: Any = None

    def bind(self, service: Any) -> None:
        self._service = service

    def assemble(
        self,
        *,
        trigger: Trigger,
        signal_payload: dict[str, Any],
        investigation_plan: dict[str, Any] | None = None,
    ) -> EvidencePack:
        if self._service is None:
            raise RuntimeError("RethEvidenceStrategy must be bound to EvidenceService")
        return self._service._assemble_reth(
            trigger=trigger,
            signal_payload=signal_payload,
            investigation_plan=investigation_plan,
        )


class StructuredSignalEvidenceStrategy:
    """Structural evidence check for non-Reth known signal profiles."""

    def __init__(self, *, signal_source: str, required_paths: tuple[str, ...]) -> None:
        self._signal_source = signal_source
        self._required_paths = required_paths

    def assemble(
        self,
        *,
        trigger: Trigger,
        signal_payload: dict[str, Any],
        investigation_plan: dict[str, Any] | None = None,
    ) -> EvidencePack:
        missing = [path for path in self._required_paths if _read_dotted(signal_payload, path) is None]
        sufficient = not missing
        return EvidencePack(
            pack=signal_payload,
            assembled_at=_now_iso(),
            source=f"{self._signal_source}_structured_signal",
            probe_results=[
                ProbeResult(
                    name="structured_signal_fields",
                    source="inline",
                    success=sufficient,
                    latency_ms=0.0,
                    error=None if sufficient else "missing_required_fields",
                    payload={
                        "required_fields": list(self._required_paths),
                        "missing_fields": missing,
                        "trigger_type": trigger.trigger_type,
                    },
                    citations=[
                        {
                            "source_type": "normalized_signal",
                            "source_ref": signal_payload.get("signal_id")
                            or signal_payload.get("id")
                            or trigger.trigger_id,
                        }
                    ],
                )
            ],
            sufficient=sufficient,
            missing_fields=missing,
        )


class GenericSignalEvidenceStrategy:
    """Evidence strategy for unknown signal types.

    Unknown types must produce an audited artifact, but they must not be
    treated like a known, actionable signal. The generic profile is
    sufficient only when the envelope has enough identity for an
    operator to inspect; even then the generic decision strategy still
    escalates unconditionally.
    """

    _REQUIRED_PATHS: tuple[str, ...] = (
        "signal_type",
        "environment",
        "service",
        "endpoint",
        "related_context.severity",
    )

    def assemble(
        self,
        *,
        trigger: Trigger,
        signal_payload: dict[str, Any],
        investigation_plan: dict[str, Any] | None = None,
    ) -> EvidencePack:
        missing = [path for path in self._REQUIRED_PATHS if _read_dotted(signal_payload, path) in (None, "")]
        signal_type = signal_payload.get("signal_type") if isinstance(signal_payload, dict) else None
        return EvidencePack(
            pack=signal_payload,
            assembled_at=_now_iso(),
            source="generic_signal_type",
            probe_results=[
                ProbeResult(
                    name="generic_profile_resolution",
                    source="inline",
                    success=not missing,
                    latency_ms=0.0,
                    error=None if not missing else "missing_generic_identity",
                    payload={
                        "unknown_signal_type": signal_type,
                        "required_fields": list(self._REQUIRED_PATHS),
                        "missing_fields": missing,
                    },
                    citations=[
                        {
                            "source_type": "signal_profile_registry",
                            "source_ref": f"resolved_to_generic:{signal_type or 'null'}",
                        }
                    ],
                )
            ],
            sufficient=False,
            missing_fields=missing or ["no_profile_registered"],
        )


__all__ = [
    "GenericSignalEvidenceStrategy",
    "RethEvidenceStrategy",
    "StructuredSignalEvidenceStrategy",
]
