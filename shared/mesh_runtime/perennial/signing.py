from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def build_hmac_signature_proof(
    payload: dict[str, Any],
    *,
    key_id: str,
    secret: str,
    signing_profile: str = "darkharness-hmac-sha256-v1",
) -> dict[str, Any]:
    canonical = _canonical_bytes(payload)
    payload_sha256 = hashlib.sha256(canonical).hexdigest()
    signature = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    return {
        "signing_profile": signing_profile,
        "algorithm": "hmac-sha256",
        "key_id": key_id,
        "signature": signature,
        "payload_sha256": payload_sha256,
        "status": "verified",
        "verifier": "orbital_mesh_hmac_sha256_v1",
    }


def verify_hmac_signature_proof(payload: dict[str, Any], proof: dict[str, Any], *, secret: str) -> bool:
    if proof.get("algorithm") != "hmac-sha256":
        return False
    expected = build_hmac_signature_proof(
        payload,
        key_id=str(proof.get("key_id") or ""),
        secret=secret,
        signing_profile=str(proof.get("signing_profile") or "darkharness-hmac-sha256-v1"),
    )
    return (
        hmac.compare_digest(str(proof.get("payload_sha256") or ""), expected["payload_sha256"])
        and hmac.compare_digest(str(proof.get("signature") or ""), expected["signature"])
    )


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
