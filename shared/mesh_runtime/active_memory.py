from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .contracts import MemoryCompactionRecord
from .json_store import LockedJsonFile

_MAX_ACTIVE_FACTS_PER_SERVICE = 25


class ActiveMemoryStore:
    """Compressed decision context backed by immutable run evidence elsewhere."""

    def __init__(self, state_directory: str | Path):
        self._memory_dir = Path(state_directory) / "memory"
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._active_path = self._memory_dir / "active_context.json"

    def compact(
        self,
        *,
        run_id: str | None,
        service: str,
        candidate_facts: list[dict[str, Any]],
        source_event_ids: list[str],
        merkle_root: str | None = None,
    ) -> MemoryCompactionRecord:
        active: list[dict[str, Any]] = []
        suppressed: list[dict[str, Any]] = []
        for fact in candidate_facts:
            normalized = _normalize_fact(fact, service=service, run_id=run_id, source_event_ids=source_event_ids)
            if _is_active_fact(normalized):
                active.append(normalized)
            else:
                normalized.setdefault("suppression_reason", "low_relevance_or_confidence")
                suppressed.append(normalized)

        with LockedJsonFile(self._active_path) as payload:
            by_service = payload.setdefault("services", {})
            existing = list(by_service.get(service, []))
            merged = _dedupe_facts(existing + active)
            by_service[service] = merged[:_MAX_ACTIVE_FACTS_PER_SERVICE]
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()

        record = MemoryCompactionRecord(
            compaction_id=f"memcmp_{uuid4().hex[:12]}",
            run_id=run_id,
            service=service,
            created_at=datetime.now(timezone.utc).isoformat(),
            active_facts=active,
            suppressed_facts=suppressed,
            source_event_ids=list(source_event_ids),
            merkle_root=merkle_root,
        )
        record.validate()
        return record

    def refresh_from_claims(
        self,
        *,
        run_id: str | None,
        service: str,
        claims: list[dict[str, Any]],
        source_event_ids: list[str],
        merkle_root: str | None = None,
    ) -> MemoryCompactionRecord:
        candidate_facts: list[dict[str, Any]] = []
        for claim in claims:
            if str(claim.get("state")) != "active":
                continue
            candidate_facts.append(
                {
                    "service": service,
                    "kind": str(claim.get("tier") or "semantic"),
                    "content": str(claim.get("statement") or ""),
                    "confidence": float(claim.get("confidence", 0.0) or 0.0),
                    "source_run_id": run_id,
                    "source_event_ids": source_event_ids,
                    "created_at": claim.get("updated_at") or claim.get("created_at"),
                    "reinforcement_count": max(1, len(claim.get("supporting_observation_ids", []))),
                }
            )
        return self.compact(
            run_id=run_id,
            service=service,
            candidate_facts=candidate_facts,
            source_event_ids=source_event_ids,
            merkle_root=merkle_root,
        )

    def project_packet(
        self,
        *,
        run_id: str | None,
        service: str,
        packet: dict[str, Any],
        source_event_ids: list[str],
        merkle_root: str | None = None,
    ) -> MemoryCompactionRecord:
        claims = list(packet.get("claims", [])) + list(packet.get("procedures", []))
        return self.refresh_from_claims(
            run_id=run_id,
            service=service,
            claims=claims,
            source_event_ids=source_event_ids,
            merkle_root=merkle_root,
        )

    def active_facts(self, service: str | None = None) -> dict[str, Any]:
        if not self._active_path.exists():
            return {"services": {}, "updated_at": None}
        with LockedJsonFile(self._active_path) as payload:
            snapshot = deepcopy(payload)
        if service:
            return {
                "services": {service: list(snapshot.get("services", {}).get(service, []))},
                "updated_at": snapshot.get("updated_at"),
            }
        return snapshot


def _normalize_fact(
    fact: dict[str, Any],
    *,
    service: str,
    run_id: str | None,
    source_event_ids: list[str],
) -> dict[str, Any]:
    confidence = float(fact.get("confidence", 0.0) or 0.0)
    return {
        "fact_id": str(fact.get("fact_id") or f"fact_{uuid4().hex[:12]}"),
        "service": str(fact.get("service") or service),
        "kind": str(fact.get("kind") or "observation"),
        "content": str(fact.get("content") or fact.get("summary") or ""),
        "confidence": max(0.0, min(confidence, 1.0)),
        "source_run_id": fact.get("source_run_id") or run_id,
        "source_event_ids": list(fact.get("source_event_ids") or source_event_ids),
        "created_at": str(fact.get("created_at") or datetime.now(timezone.utc).isoformat()),
        "reinforcement_count": int(fact.get("reinforcement_count", 1) or 1),
    }


def _is_active_fact(fact: dict[str, Any]) -> bool:
    return bool(fact.get("content")) and float(fact.get("confidence", 0.0)) >= 0.55


def _dedupe_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for fact in facts:
        key = (str(fact.get("kind")), str(fact.get("content")))
        if key not in by_key:
            by_key[key] = fact
            continue
        current = by_key[key]
        current["confidence"] = max(float(current.get("confidence", 0.0)), float(fact.get("confidence", 0.0)))
        current["reinforcement_count"] = int(current.get("reinforcement_count", 1)) + int(
            fact.get("reinforcement_count", 1)
        )
        current["source_event_ids"] = sorted(set(current.get("source_event_ids", [])) | set(fact.get("source_event_ids", [])))
    return sorted(
        by_key.values(),
        key=lambda item: (float(item.get("confidence", 0.0)), int(item.get("reinforcement_count", 0))),
        reverse=True,
    )
