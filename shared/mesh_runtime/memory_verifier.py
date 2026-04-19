from __future__ import annotations

from typing import Any


def verify_memory_candidates(
    *,
    observations: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    ranked_ids: list[str],
    channel_map: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    verified: list[dict[str, Any]] = []
    contradictions: list[dict[str, Any]] = []
    discarded: list[str] = []
    contradictory_claims: set[str] = set()

    for claim_id, claim in claims.items():
        if str(claim.get("state")) != "active":
            continue
        contrad = [
            other_id
            for other_id in claim.get("contradicting_claim_ids", [])
            if other_id in claims and str(claims[other_id].get("state")) == "active"
        ]
        if contrad:
            contradictory_claims.add(claim_id)
            contradictory_claims.update(contrad)

    emitted_ids: set[str] = set()
    for item_id in ranked_ids:
        if item_id in emitted_ids:
            continue
        observation = observations.get(item_id)
        if observation is not None:
            if not observation.get("source_refs"):
                discarded.append(item_id)
                continue
            verified.append(
                {
                    "id": item_id,
                    "type": "observation",
                    "content": observation.get("content"),
                    "channels": channels_for(item_id, channel_map),
                    "citation_refs": observation.get("source_refs", []),
                    "verified_confidence": 1.0,
                    "state": "active",
                    "rank_score": 0.0,
                    "record": observation,
                }
            )
            emitted_ids.add(item_id)
            continue

        claim = claims.get(item_id)
        if claim is None:
            discarded.append(item_id)
            continue
        if not claim.get("supporting_observation_ids"):
            discarded.append(item_id)
            continue
        if claim.get("superseded_by"):
            discarded.append(item_id)
            continue
        support_records = [observations.get(obs_id) for obs_id in claim.get("supporting_observation_ids", [])]
        citation_refs = [
            ref
            for observation_record in support_records
            if observation_record is not None
            for ref in observation_record.get("source_refs", [])
        ]
        if not citation_refs:
            discarded.append(item_id)
            continue
        if item_id in contradictory_claims:
            contradictions.append(
                {
                    "claim_id": item_id,
                    "statement": claim.get("statement"),
                    "contradicting_claim_ids": list(claim.get("contradicting_claim_ids", [])),
                    "citation_refs": citation_refs,
                }
            )
            discarded.append(item_id)
            continue
        verified.append(
            {
                "id": item_id,
                "type": "claim",
                "content": claim.get("statement"),
                "channels": channels_for(item_id, channel_map),
                "citation_refs": citation_refs,
                "verified_confidence": float(claim.get("confidence", 0.0) or 0.0),
                "state": claim.get("state"),
                "tier": claim.get("tier"),
                "rank_score": 0.0,
                "record": claim,
            }
        )
        emitted_ids.add(item_id)

    return verified, contradictions, discarded


def channels_for(item_id: str, channel_map: dict[str, list[str]]) -> list[str]:
    channels: list[str] = []
    for channel, item_ids in channel_map.items():
        if item_id in item_ids:
            channels.append(channel)
    return channels
