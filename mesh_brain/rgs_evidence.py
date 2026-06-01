from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

STATE_SLICE = "meshmodel-rgs-evidence-binding"
SCHEMA_VERSION = "mesh.meshmodel_rgs_evidence_binding.v1"
SOURCE_REPOSITORY = "LusisLabs/recoverable-ghost-states"
AUDIT_PACKET = Path("docs/breakthrough-threshold-audit-evidence.json")
CROSS_EVIDENCE_PACKET = Path("docs/cross-evidence-claim-synthesis.json")
PUBLIC_METRICS_PACKET = Path("docs/public-breakthrough-metrics.json")


def build_meshmodel_rgs_evidence_binding(
    payload: dict[str, Any] | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    payload = payload or {}
    inline = payload.get("rgs_evidence")
    source = _resolve_source(payload)
    if isinstance(inline, dict):
        binding = _binding_from_packets(
            audit_packet=dict(inline.get("audit_packet") or inline),
            cross_packet=_dict_or_none(inline.get("cross_evidence_packet")),
            public_metrics_packet=_dict_or_none(inline.get("public_metrics_packet")),
            source_ref=str(inline.get("source_ref") or "inline:rgs_evidence"),
            source_commit=_string_or_none(inline.get("source_commit")),
            expected_source_commit=_string_or_none(payload.get("expected_rgs_source_commit")),
            run_id=run_id,
        )
    elif source is not None:
        binding = _binding_from_source(
            source=source,
            run_id=run_id,
            expected_source_commit=_string_or_none(payload.get("expected_rgs_source_commit")),
        )
    else:
        binding = _missing_binding(run_id=run_id, reason="rgs_evidence_source_not_configured")

    binding["binding_hash"] = f"sha256:{_canonical_sha256(binding)}"
    return binding


def _resolve_source(payload: dict[str, Any]) -> Path | None:
    for key in ("rgs_evidence_path", "rgs_repo_root"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return Path(value).expanduser()
    for env_key in ("MESHMODEL_RGS_EVIDENCE_PATH", "MESHMODEL_RGS_REPO_ROOT", "RGS_REPO_ROOT"):
        value = os.environ.get(env_key, "").strip()
        if value:
            return Path(value).expanduser()
    return None


def _binding_from_source(
    *,
    source: Path,
    run_id: str,
    expected_source_commit: str | None,
) -> dict[str, Any]:
    source = source.resolve()
    if source.is_file():
        audit_packet = _load_json(source)
        repo_root = _discover_repo_root(source.parent)
        cross_packet = None
        public_metrics_packet = None
        source_ref = str(source)
    else:
        repo_root = source
        audit_path = source / AUDIT_PACKET
        cross_path = source / CROSS_EVIDENCE_PACKET
        public_metrics_path = source / PUBLIC_METRICS_PACKET
        if not audit_path.exists():
            return _missing_binding(
                run_id=run_id,
                reason="rgs_breakthrough_threshold_audit_packet_missing",
                source_ref=str(source),
                missing_paths=[str(audit_path)],
            )
        audit_packet = _load_json(audit_path)
        cross_packet = _load_json(cross_path) if cross_path.exists() else None
        public_metrics_packet = _load_json(public_metrics_path) if public_metrics_path.exists() else None
        source_ref = str(source)

    source_commit = _string_or_none(audit_packet.get("local_repo_commit"))
    if source_commit is None and repo_root is not None:
        source_commit = _git_head(repo_root)

    return _binding_from_packets(
        audit_packet=audit_packet,
        cross_packet=cross_packet,
        public_metrics_packet=public_metrics_packet,
        source_ref=source_ref,
        source_commit=source_commit,
        expected_source_commit=expected_source_commit,
        run_id=run_id,
    )


def _binding_from_packets(
    *,
    audit_packet: dict[str, Any],
    cross_packet: dict[str, Any] | None,
    public_metrics_packet: dict[str, Any] | None,
    source_ref: str,
    source_commit: str | None,
    expected_source_commit: str | None,
    run_id: str,
) -> dict[str, Any]:
    claim_boundary = _claim_boundary(audit_packet, cross_packet)
    blocked_items = _blocked_items(audit_packet, cross_packet)
    bounded_admitted = bool(
        audit_packet.get("bounded_breakthrough_evidence_admitted")
        or (cross_packet or {}).get("bounded_breakthrough_evidence_admitted")
    )
    threshold_admitted = bool(audit_packet.get("threshold_admitted") or (cross_packet or {}).get("threshold_admitted"))
    full_live_threshold = bool(
        audit_packet.get("full_live_external_runtime_threshold_admitted")
        or (cross_packet or {}).get("full_live_external_runtime_threshold_admitted")
    )
    cl12_admitted = bool(claim_boundary.get("cl12_live_external_runtime_replication") or full_live_threshold)
    packet_status = str(audit_packet.get("status") or "")
    commit_matches = expected_source_commit in {None, "", source_commit}
    input_ready = packet_status == "pass" and bounded_admitted and commit_matches
    blockers: list[str] = []
    if packet_status != "pass":
        blockers.append("rgs_breakthrough_threshold_audit_not_passing")
    if not bounded_admitted:
        blockers.append("rgs_bounded_breakthrough_evidence_not_admitted")
    if expected_source_commit and not commit_matches:
        blockers.append("rgs_source_commit_mismatch")
    if not cl12_admitted:
        blockers.append("rgs_cl12_live_external_runtime_not_admitted")
    if threshold_admitted and not cl12_admitted:
        blockers.append("rgs_threshold_admitted_without_live_cl12_packet")

    binding = {
        "version": SCHEMA_VERSION,
        "state_slice": STATE_SLICE,
        "run_id": run_id,
        "source_repository": SOURCE_REPOSITORY,
        "source_ref": source_ref,
        "source_commit": source_commit,
        "expected_source_commit": expected_source_commit,
        "status": "advisory_ready" if input_ready else "blocked",
        "advisory_ready": input_ready,
        "bounded_breakthrough_evidence_admitted": bounded_admitted,
        "bounded_breakthrough_evidence_status": str(audit_packet.get("bounded_breakthrough_evidence_status") or ""),
        "threshold_admitted": threshold_admitted,
        "threshold_admission_status": str(audit_packet.get("threshold_admission_status") or ""),
        "full_live_external_runtime_threshold_admitted": full_live_threshold,
        "cl12_live_external_runtime_replication_admitted": cl12_admitted,
        "blocked_items": blocked_items,
        "blockers": sorted(set(blockers)),
        "claim_boundary": claim_boundary,
        "public_metrics": _public_metrics_summary(public_metrics_packet),
        "release_effect": "advisory_evidence_only",
        "production_authority": False,
        "serving_authority": False,
        "promotion_authority": False,
        "production_readiness": False,
        "serving_readiness": False,
        "policy": {
            "meshmodel_release_input": True,
            "advisory_evidence_only": True,
            "requires_live_cl12_for_threshold": True,
            "allows_production_authority": False,
            "allows_serving_authority": False,
            "allows_promotion_authority": False,
        },
        "packet_hashes": {
            "breakthrough_threshold_audit": f"sha256:{_canonical_sha256(audit_packet)}",
            "cross_evidence_claim_synthesis": f"sha256:{_canonical_sha256(cross_packet)}" if cross_packet else None,
            "public_breakthrough_metrics": f"sha256:{_canonical_sha256(public_metrics_packet)}"
            if public_metrics_packet
            else None,
        },
    }
    return binding


def _missing_binding(
    *,
    run_id: str,
    reason: str,
    source_ref: str | None = None,
    missing_paths: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "state_slice": STATE_SLICE,
        "run_id": run_id,
        "source_repository": SOURCE_REPOSITORY,
        "source_ref": source_ref,
        "source_commit": None,
        "expected_source_commit": None,
        "status": "blocked",
        "advisory_ready": False,
        "bounded_breakthrough_evidence_admitted": False,
        "threshold_admitted": False,
        "full_live_external_runtime_threshold_admitted": False,
        "cl12_live_external_runtime_replication_admitted": False,
        "blocked_items": [{"item": reason, "state_slice": STATE_SLICE}],
        "blockers": [reason],
        "missing_paths": missing_paths or [],
        "claim_boundary": {
            "production_authority": False,
            "production_readiness": False,
            "serving_authority": False,
            "serving_readiness": False,
            "cl12_live_external_runtime_replication": False,
        },
        "public_metrics": None,
        "release_effect": "advisory_evidence_only",
        "production_authority": False,
        "serving_authority": False,
        "promotion_authority": False,
        "production_readiness": False,
        "serving_readiness": False,
        "policy": {
            "meshmodel_release_input": True,
            "advisory_evidence_only": True,
            "requires_live_cl12_for_threshold": True,
            "allows_production_authority": False,
            "allows_serving_authority": False,
            "allows_promotion_authority": False,
        },
        "packet_hashes": {
            "breakthrough_threshold_audit": None,
            "cross_evidence_claim_synthesis": None,
            "public_breakthrough_metrics": None,
        },
    }


def _claim_boundary(audit_packet: dict[str, Any], cross_packet: dict[str, Any] | None) -> dict[str, Any]:
    boundary: dict[str, Any] = {}
    for packet in (cross_packet, audit_packet):
        if isinstance(packet, dict) and isinstance(packet.get("claim_boundary"), dict):
            boundary.update(packet["claim_boundary"])
    boundary["production_authority"] = False
    boundary["production_readiness"] = False
    boundary["serving_authority"] = False
    boundary["serving_readiness"] = False
    return boundary


def _blocked_items(audit_packet: dict[str, Any], cross_packet: dict[str, Any] | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for packet in (audit_packet, cross_packet):
        raw = packet.get("blocked_items") if isinstance(packet, dict) else None
        if isinstance(raw, list):
            items.extend([dict(item) for item in raw if isinstance(item, dict)])
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = json.dumps(item, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _public_metrics_summary(packet: dict[str, Any] | None) -> dict[str, Any] | None:
    if packet is None:
        return None
    boundary = packet.get("public_claim_boundary") if isinstance(packet.get("public_claim_boundary"), dict) else {}
    return {
        "state_slice": packet.get("state_slice"),
        "status": packet.get("status"),
        "use_case_count": len(packet.get("use_case_metrics") or []),
        "sidecar_ledger_hash_bound": bool((packet.get("checks") or {}).get("sidecar_ledger_hash_bound")),
        "sidecar_ledger_hash_binding": packet.get("sidecar_ledger_hash_binding"),
        "strongest_supported_claim_scope": boundary.get("strongest_supported_claim_scope"),
        "production_authority": False,
        "serving_authority": False,
    }


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _discover_repo_root(start: Path) -> Path | None:
    for path in (start, *start.parents):
        if (path / ".git").exists():
            return path
    return None


def _git_head(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_sha256(payload: dict[str, Any] | None) -> str:
    raw = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
