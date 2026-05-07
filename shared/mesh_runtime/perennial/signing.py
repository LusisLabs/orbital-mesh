from __future__ import annotations

import hashlib
import hmac
import json
from base64 import b64decode, b64encode
from typing import Any

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
except Exception:  # pragma: no cover - dependency absence is reported at provider construction.
    InvalidSignature = None
    serialization = None
    Ed25519PrivateKey = None
    Ed25519PublicKey = None


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


def build_ed25519_signature_proof(
    payload: dict[str, Any],
    *,
    key_id: str,
    private_key_pem: str,
    signing_profile: str = "darkharness-ed25519-v1",
) -> dict[str, Any]:
    if serialization is None:
        raise RuntimeError("cryptography package is required for Ed25519 Darkharness signatures")
    canonical = _canonical_bytes(payload)
    payload_sha256 = hashlib.sha256(canonical).hexdigest()
    private_key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("Darkharness Ed25519 signing key must be an Ed25519 private key PEM")
    signature = private_key.sign(canonical)
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return {
        "signing_profile": signing_profile,
        "algorithm": "ed25519",
        "key_id": key_id,
        "signature": b64encode(signature).decode("ascii"),
        "payload_sha256": payload_sha256,
        "public_key_pem": public_key_pem,
        "status": "verified",
        "verifier": "orbital_mesh_ed25519_v1",
    }


def verify_ed25519_signature_proof(payload: dict[str, Any], proof: dict[str, Any], *, public_key_pem: str | None = None) -> bool:
    if serialization is None or InvalidSignature is None:
        return False
    if proof.get("algorithm") != "ed25519":
        return False
    key_pem = public_key_pem or str(proof.get("public_key_pem") or "")
    if not key_pem:
        return False
    canonical = _canonical_bytes(payload)
    payload_sha256 = hashlib.sha256(canonical).hexdigest()
    if not hmac.compare_digest(str(proof.get("payload_sha256") or ""), payload_sha256):
        return False
    try:
        public_key = serialization.load_pem_public_key(key_pem.encode("utf-8"))
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        public_key.verify(b64decode(str(proof.get("signature") or "")), canonical)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
