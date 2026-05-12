#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

from shared.mesh_runtime import RuntimeConfig
from shared.mesh_runtime.helix_memory import HelixMemoryProjectionError, build_helix_memory_projection


def verify_helix_memory_projection(config: RuntimeConfig, *, replay_pending: bool = False) -> dict[str, Any]:
    if config.memory_graph_backend != "helix":
        return {
            "status": "skipped",
            "reason": "MESH_MEMORY_GRAPH_BACKEND is not helix",
            "memory_graph_backend": config.memory_graph_backend,
        }

    projection = build_helix_memory_projection(config, raise_on_failure=True)
    replay_result = projection.replay_pending() if replay_pending else None
    if replay_result is not None and int(replay_result.get("failed") or 0) > 0:
        raise HelixMemoryProjectionError(
            f"HelixDB memory projection replay failed for {replay_result['failed']} outbox event(s)"
        )
    now = datetime.now(timezone.utc).isoformat()
    observation = {
        "observation_id": f"obs_helix_projection_probe_{_stamp(now)}",
        "scope": {"service": "helix-probe"},
        "kind": "projection_probe",
        "content": "HelixDB memory projection probe observation.",
        "service": "helix-probe",
        "run_id": None,
        "source_type": "verification",
        "source_refs": [],
        "created_at": now,
        "author": "mesh",
        "tags": ["helix", "projection"],
        "metadata": {},
    }
    claim = {
        "claim_id": f"claim_helix_projection_probe_{_stamp(now)}",
        "statement": "HelixDB memory projection accepted a probe claim.",
        "entity_refs": ["helix-probe"],
        "supporting_observation_ids": [observation["observation_id"]],
        "contradicting_claim_ids": [],
        "superseded_by": None,
        "confidence": 0.99,
        "confidence_factors": {
            "support_score": 1.0,
            "recency_score": 1.0,
            "authority_score": 0.9,
            "consistency_score": 1.0,
            "verification_score": 1.0,
        },
        "freshness": 1.0,
        "tier": "semantic",
        "state": "active",
        "created_at": now,
        "updated_at": now,
    }
    replacement_claim = {
        **claim,
        "claim_id": f"claim_helix_projection_probe_replacement_{_stamp(now)}",
        "statement": "HelixDB memory projection accepted a replacement probe claim.",
    }
    relationship = {
        "relationship_id": f"rel_helix_projection_probe_{_stamp(now)}",
        "from_id": claim["claim_id"],
        "to_id": observation["observation_id"],
        "type": "supported_by",
        "scope": {"service": "helix-probe"},
        "metadata": {},
        "created_at": now,
    }
    supersession = {
        "supersession_id": f"sup_helix_projection_probe_{_stamp(now)}",
        "old_claim_id": claim["claim_id"],
        "new_claim_id": replacement_claim["claim_id"],
        "reason": "Projection verifier supersession probe.",
        "created_at": now,
        "created_by": "mesh",
    }
    retrieval = {
        "retrieval_id": f"ret_helix_projection_probe_{_stamp(now)}",
        "query": "helix projection probe",
        "scope": {"service": "helix-probe"},
        "channels": ["graph"],
        "candidate_ids": [observation["observation_id"], claim["claim_id"]],
        "verified_ids": [claim["claim_id"]],
        "discarded_ids": [],
        "created_at": now,
    }
    packet = {
        "packet_id": f"packet_helix_projection_probe_{_stamp(now)}",
        "scope": {"service": "helix-probe"},
        "observations": [observation],
        "claims": [claim, replacement_claim],
        "procedures": [],
        "contradictions": [],
        "citations": [],
        "generated_at": now,
    }

    projection.upsert_observation(observation)
    projection.upsert_claim(claim)
    projection.upsert_claim(replacement_claim)
    projection.upsert_relationship(relationship)
    projection.upsert_supersession(supersession)
    projection.record_retrieval(retrieval)
    projection.upsert_memory_packet(packet)

    result = {
        "status": "passed",
        "memory_graph_backend": config.memory_graph_backend,
        "helix_endpoint": config.helix_api_endpoint or f"local:{config.helix_port}",
        "helix_query_namespace": config.helix_query_namespace,
        "outbox": projection.projection_status(),
        "projected": {
            "observation_id": observation["observation_id"],
            "claim_id": claim["claim_id"],
            "replacement_claim_id": replacement_claim["claim_id"],
            "relationship_id": relationship["relationship_id"],
            "supersession_id": supersession["supersession_id"],
            "retrieval_id": retrieval["retrieval_id"],
            "packet_id": packet["packet_id"],
        },
    }
    if replay_result is not None:
        result["replay"] = replay_result
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the optional HelixDB memory projection.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--require-enabled",
        action="store_true",
        help="Fail instead of skipping when MESH_MEMORY_GRAPH_BACKEND is not helix.",
    )
    parser.add_argument(
        "--replay-pending",
        action="store_true",
        help="Replay pending HelixDB projection outbox events before writing the probe records.",
    )
    args = parser.parse_args(argv)

    try:
        result = verify_helix_memory_projection(RuntimeConfig.from_env(), replay_pending=args.replay_pending)
    except HelixMemoryProjectionError as exc:
        result = {"status": "failed", "reason": str(exc)}

    if args.require_enabled and result["status"] == "skipped":
        result = {"status": "failed", "reason": result["reason"]}

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"{result['status']}: {result.get('reason') or result.get('projected')}")
    return 0 if result["status"] in {"passed", "skipped"} else 1


def _stamp(value: str) -> str:
    return value.replace("-", "").replace(":", "").replace(".", "").replace("+", "").replace("T", "_")


if __name__ == "__main__":
    raise SystemExit(main())
