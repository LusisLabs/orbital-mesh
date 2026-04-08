from __future__ import annotations

import hashlib
import json

from .control_plane_models import MerkleProof, MerkleProofStep, MerkleSnapshot, RunEvent


def canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def leaf_hash_for_payload(payload: dict) -> str:
    return hashlib.sha256(f"leaf:{canonical_json(payload)}".encode("utf-8")).hexdigest()


def branch_hash(left_hash: str, right_hash: str) -> str:
    return hashlib.sha256(f"node:{left_hash}:{right_hash}".encode("utf-8")).hexdigest()


def build_merkle_snapshot(run_id: str, events: list[RunEvent]) -> MerkleSnapshot:
    leaves = [event.merkle_leaf_hash or leaf_hash_for_payload(event.canonical_payload()) for event in events]
    root_hash = compute_merkle_root(leaves)
    return MerkleSnapshot(
        run_id=run_id,
        root_hash=root_hash,
        leaf_count=len(leaves),
        event_ids=[event.event_id for event in events],
    )


def build_merkle_proof(run_id: str, events: list[RunEvent], event_id: str) -> MerkleProof | None:
    index = None
    leaves: list[str] = []
    for candidate_index, event in enumerate(events):
        leaves.append(event.merkle_leaf_hash or leaf_hash_for_payload(event.canonical_payload()))
        if event.event_id == event_id:
            index = candidate_index

    if index is None:
        return None

    proof: list[MerkleProofStep] = []
    layer = list(leaves)
    working_index = index
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        sibling_index = working_index - 1 if working_index % 2 else working_index + 1
        position = "left" if sibling_index < working_index else "right"
        proof.append(MerkleProofStep(position=position, hash=layer[sibling_index]))
        next_layer: list[str] = []
        for offset in range(0, len(layer), 2):
            next_layer.append(branch_hash(layer[offset], layer[offset + 1]))
        working_index //= 2
        layer = next_layer

    root_hash = layer[0] if layer else hashlib.sha256(b"empty").hexdigest()
    leaf_hash = leaves[index]
    return MerkleProof(
        run_id=run_id,
        event_id=event_id,
        leaf_hash=leaf_hash,
        root_hash=root_hash,
        proof=proof,
        valid=verify_merkle_proof(leaf_hash, root_hash, proof),
    )


def compute_merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return hashlib.sha256(b"empty").hexdigest()
    layer = list(leaves)
    while len(layer) > 1:
        if len(layer) % 2 == 1:
            layer.append(layer[-1])
        layer = [branch_hash(layer[offset], layer[offset + 1]) for offset in range(0, len(layer), 2)]
    return layer[0]


def verify_merkle_proof(leaf_hash: str, root_hash: str, proof: list[MerkleProofStep]) -> bool:
    cursor = leaf_hash
    for step in proof:
        if step.position == "left":
            cursor = branch_hash(step.hash, cursor)
        else:
            cursor = branch_hash(cursor, step.hash)
    return cursor == root_hash

