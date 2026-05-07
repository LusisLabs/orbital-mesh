from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FAILURE_MODE_LIBRARY = REPO_ROOT / "config" / "failure-mode.library.json"
REQUIRED_FAILURE_MODES = frozenset(
    {
        "denied_namespace",
        "stale_kubeconfig",
        "llm_unavailable",
        "audit_sink_unavailable",
        "kubernetes_crashloop",
        "kubernetes_image_pull_backoff",
        "kubernetes_oom_killed",
        "kubernetes_readiness_probe_failure",
        "duplicate_signal",
        "delayed_feedback",
        "dependency_timeout",
        "queue_backpressure",
        "transient_network_failure",
    }
)


def load_failure_mode_library(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    library_path = _resolve_path(path)
    if not library_path.exists():
        return None
    payload = json.loads(library_path.read_text(encoding="utf-8"))
    validate_payload("failure-mode-library.schema.json", payload)
    return payload


def failure_mode_library_ready(path: str | None) -> bool:
    try:
        packet = build_failure_mode_library_packet(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError):
        return False
    return packet.get("status") == "complete"


def build_failure_mode_library_packet(path: str | None = None) -> dict[str, Any]:
    resolved_path = _resolve_path(path or str(DEFAULT_FAILURE_MODE_LIBRARY))
    blockers: list[str] = []
    try:
        library = load_failure_mode_library(str(resolved_path))
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        library = None
        blockers.append(f"failure_mode_library_invalid:{exc}")
    if library is None:
        blockers.append("failure_mode_library_missing")
        entries: list[dict[str, Any]] = []
    else:
        entries = [entry for entry in library.get("entries", []) if isinstance(entry, dict)]
    ids = [str(entry.get("id") or "") for entry in entries]
    unique_ids = sorted(set(ids))
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    missing_modes = sorted(REQUIRED_FAILURE_MODES - set(ids))
    entries_without_ui_replay = sorted(
        str(entry.get("id"))
        for entry in entries
        if not any(str(ref).startswith("ui://") for ref in entry.get("replay_refs", []))
    )
    entries_without_test_ref = sorted(
        str(entry.get("id"))
        for entry in entries
        if not any(str(ref).startswith("tests/") for ref in entry.get("test_refs", []))
    )
    checks = {
        "library_present": library is not None,
        "ids_unique": not duplicate_ids,
        "required_modes_present": not missing_modes,
        "ui_replay_refs_present": not entries_without_ui_replay,
        "test_refs_present": not entries_without_test_ref,
        "operator_actions_present": bool(entries)
        and all(bool(entry.get("operator_actions")) for entry in entries),
        "authority_boundaries_present": bool(entries)
        and all(bool(str(entry.get("authority_boundary") or "").strip()) for entry in entries),
    }
    blockers.extend(name for name, passed in checks.items() if not passed)
    packet = {
        "schema_version": "mesh.failure_mode_library.v1",
        "generated_at": _timestamp(),
        "status": "complete" if not blockers else "incomplete",
        "library_path": _display_path(resolved_path),
        "library_sha256": _sha256(resolved_path) if resolved_path.exists() else None,
        "entry_count": len(entries),
        "required_modes": sorted(REQUIRED_FAILURE_MODES),
        "covered_modes": unique_ids,
        "entries": entries,
        "missing_modes": missing_modes,
        "duplicate_ids": duplicate_ids,
        "entries_without_ui_replay": entries_without_ui_replay,
        "entries_without_test_ref": entries_without_test_ref,
        "checks": checks,
        "blockers": sorted(set(blockers)),
    }
    validate_payload("failure-mode-library-packet.schema.json", packet)
    return packet


def _resolve_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return (REPO_ROOT / p).resolve()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
