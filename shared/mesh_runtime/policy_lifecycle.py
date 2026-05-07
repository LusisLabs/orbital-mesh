from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_DIR = REPO_ROOT / "policies"
DEFAULT_POLICY_LIFECYCLE_MANIFEST = REPO_ROOT / "config" / "policy-lifecycle.manifest.json"


def build_policy_lifecycle_packet(
    *,
    manifest_path: str | None = None,
    signing_key: str | None = None,
    signing_key_id: str = "policy-lifecycle-hmac",
) -> dict[str, Any]:
    resolved_manifest = _resolve_path(manifest_path or str(DEFAULT_POLICY_LIFECYCLE_MANIFEST))
    manifest = _load_manifest(resolved_manifest)
    policy_hashes = _policy_hashes(DEFAULT_POLICY_DIR)
    manifest_paths = {str(item.get("path")) for item in manifest.get("policies", []) if isinstance(item, dict)}
    actual_paths = {item["path"] for item in policy_hashes}
    coverage = {
        "manifest_policy_count": len(manifest_paths),
        "hashed_policy_count": len(actual_paths),
        "missing_from_manifest": sorted(actual_paths - manifest_paths),
        "missing_policy_files": sorted(manifest_paths - actual_paths),
    }
    combined = _combined_hash(policy_hashes)
    signed_payload = {
        "manifest_sha256": _sha256(resolved_manifest),
        "policy_hashes": policy_hashes,
        "combined_policy_sha256": combined,
    }
    signature = _sign_payload(signed_payload, signing_key=signing_key, signing_key_id=signing_key_id)
    missing = []
    if coverage["missing_from_manifest"]:
        missing.append("manifest_covers_all_policy_files")
    if coverage["missing_policy_files"]:
        missing.append("manifest_policy_files_exist")
    if not signature:
        missing.append("policy_hash_signature")
    packet: dict[str, Any] = {
        "schema_version": "mesh.policy_lifecycle.v1",
        "generated_at": _timestamp(),
        "status": "complete" if not missing else "incomplete",
        "manifest_path": _display_path(resolved_manifest),
        "manifest_sha256": signed_payload["manifest_sha256"],
        "policy_hashes": policy_hashes,
        "combined_policy_sha256": combined,
        "coverage": coverage,
        "signature": signature,
        "missing": missing,
    }
    validate_payload("policy-lifecycle-packet.schema.json", packet)
    return packet


def policy_lifecycle_ready(
    *,
    manifest_path: str | None,
    signing_key: str | None,
    signing_key_id: str = "policy-lifecycle-hmac",
) -> bool:
    try:
        packet = build_policy_lifecycle_packet(
            manifest_path=manifest_path,
            signing_key=signing_key,
            signing_key_id=signing_key_id,
        )
    except (OSError, json.JSONDecodeError, SchemaValidationError, ValueError):
        return False
    return packet.get("status") == "complete"


def _load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_payload("policy-lifecycle-manifest.schema.json", payload)
    return payload


def _policy_hashes(directory: Path) -> list[dict[str, str]]:
    return [
        {"path": str(path.relative_to(REPO_ROOT)), "sha256": _sha256(path)}
        for path in sorted(directory.glob("*.json"))
        if path.is_file()
    ]


def _sign_payload(payload: dict[str, Any], *, signing_key: str | None, signing_key_id: str) -> dict[str, str] | None:
    key = (signing_key or "").strip()
    if not key:
        return None
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return {
        "algorithm": "hmac-sha256",
        "key_id": signing_key_id,
        "signature": digest,
    }


def _combined_hash(records: list[dict[str, str]]) -> str | None:
    if not records:
        return None
    digest = hashlib.sha256()
    for record in records:
        digest.update(record["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
