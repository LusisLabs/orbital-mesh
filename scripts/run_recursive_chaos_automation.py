#!/usr/bin/env python3
"""Run advisory-only recursive chaos through the live Mesh API."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.recursive_chaos_intelligence import (  # noqa: E402
    RECURSIVE_CHAOS_AUTOMATION_SUMMARY_VERSION,
    build_recursive_chaos_feedback_gate,
    build_recursive_chaos_intelligence_score,
    validate_recursive_chaos_automation_summary,
)


STATE_SLICE = "mesh.recursive_chaos.automation.v1"
DEFAULT_API_URL = "http://127.0.0.1:8788/api/recursive-chaos/sessions"
DEFAULT_PROFILES_URL = "http://127.0.0.1:8788/api/recursive-chaos/profiles"
DEFAULT_OPERATOR = "mesh-recursive-chaos@localhost"
DEFAULT_ROLES = "admin,approver,launcher,viewer"
DEFAULT_SUMMARY_PATH = "/opt/lusis-mesh-webapp/shared/state/recursive-chaos/automation/last-run.json"
DEFAULT_HISTORY_DIR = "/opt/lusis-mesh-webapp/shared/state/recursive-chaos/automation/runs"
DEFAULT_STATIC_PROFILES = (
    "kubernetes_service_platform",
    "hardened_image_supply_chain",
    "ai_model_serving_inference",
    "durable_data_plane",
    "observability_signal_trust",
    "crypto_rpc_node_mesh",
    "queue_event_workflow_plane",
    "ai_agent_tool_execution",
    "vector_rag_retrieval",
    "cross_chain_verifier_signer",
    "identity_authority_secrets",
    "network_gateway_service_mesh",
    "cicd_gitops_release",
    "multi_region_provider_plane",
    "capacity_scheduler_finops",
    "evidence_audit_forensics",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run source-controlled recursive chaos automation.")
    parser.add_argument("--env-file", default=os.environ.get("MESH_RECURSIVE_CHAOS_ENV_FILE", ""))
    parser.add_argument("--json", action="store_true", help="Print the automation summary as formatted JSON.")
    args = parser.parse_args(argv)
    if args.env_file:
        _load_env_file(Path(args.env_file))

    settings = _settings_from_env()
    started_at = _now()
    prior_records = _load_prior_records(settings["history_dir"])
    profile_ids, profile_source, selected_profiles = _resolve_profiles(settings)
    payload = {
        "state_slice": STATE_SLICE,
        "profile_ids": profile_ids,
        "max_cycles": _resolve_max_cycles(settings["max_cycles"], len(profile_ids)),
        "seed": _resolve_seed(settings["seed"]),
        "execute": settings["execute"],
    }
    try:
        run = _post_json(settings["api_url"], payload, settings)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"status": "http_error", "code": exc.code, "detail": detail}, sort_keys=True))
        return 1

    record = _automation_record(
        run=run,
        settings=settings,
        payload=payload,
        profile_source=profile_source,
        selected_profiles=selected_profiles,
        prior_records=prior_records,
        started_at=started_at,
    )
    _write_record(record, settings)
    print(json.dumps(record, indent=2 if args.json else None, sort_keys=True))
    return 0 if record["status"] == "completed" and record["session_status"] == "pass" else 1


def _settings_from_env() -> dict[str, Any]:
    return {
        "api_url": os.environ.get("MESH_RECURSIVE_CHAOS_API_URL", DEFAULT_API_URL),
        "profiles_url": os.environ.get("MESH_RECURSIVE_CHAOS_PROFILES_URL", DEFAULT_PROFILES_URL),
        "operator_email": os.environ.get("MESH_RECURSIVE_CHAOS_OPERATOR_EMAIL", DEFAULT_OPERATOR),
        "operator_roles": os.environ.get("MESH_RECURSIVE_CHAOS_OPERATOR_ROLES", DEFAULT_ROLES),
        "profile_mode": os.environ.get("MESH_RECURSIVE_CHAOS_PROFILE_MODE", "registry_all"),
        "priority_phases": _csv(os.environ.get("MESH_RECURSIVE_CHAOS_PRIORITY_PHASES", "")),
        "static_profiles": _csv(os.environ.get("MESH_RECURSIVE_CHAOS_PROFILE_IDS", ",".join(DEFAULT_STATIC_PROFILES))),
        "max_cycles": os.environ.get("MESH_RECURSIVE_CHAOS_MAX_CYCLES", "auto"),
        "seed": os.environ.get("MESH_RECURSIVE_CHAOS_SEED", "auto"),
        "execute": os.environ.get("MESH_RECURSIVE_CHAOS_EXECUTE", "false").lower() == "true",
        "summary_path": Path(os.environ.get("MESH_RECURSIVE_CHAOS_SUMMARY_PATH", DEFAULT_SUMMARY_PATH)),
        "history_dir": Path(os.environ.get("MESH_RECURSIVE_CHAOS_HISTORY_DIR", DEFAULT_HISTORY_DIR)),
    }


def _resolve_profiles(settings: dict[str, Any]) -> tuple[list[str], str, list[dict[str, Any]]]:
    if settings["profile_mode"] == "static" and settings["static_profiles"]:
        return list(settings["static_profiles"]), "static_env", []
    try:
        registry = _fetch_json(settings["profiles_url"])
        profiles = [
            profile
            for profile in registry.get("profiles", [])
            if isinstance(profile, dict)
            and profile.get("profile_id")
            and (not settings["priority_phases"] or profile.get("priority_phase") in settings["priority_phases"])
        ]
        phase_order = {"p0": 0, "p1": 1, "p2": 2}
        profiles.sort(key=lambda profile: (phase_order.get(str(profile.get("priority_phase")), 99), str(profile["profile_id"])))
        if profiles:
            return [str(profile["profile_id"]) for profile in profiles], "registry", profiles
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        if not settings["static_profiles"]:
            raise
        return list(settings["static_profiles"]), "static_fallback_after_registry_error", []
    return list(settings["static_profiles"]), "static_fallback_empty_registry", []


def _automation_record(
    *,
    run: dict[str, Any],
    settings: dict[str, Any],
    payload: dict[str, Any],
    profile_source: str,
    selected_profiles: list[dict[str, Any]],
    prior_records: list[dict[str, Any]],
    started_at: str,
) -> dict[str, Any]:
    summary = run.get("artifacts", {}).get("recursive_chaos_session_summary", {})
    operator = run.get("artifacts", {}).get("operator", {})
    advisory = run.get("artifacts", {}).get("mesh_brain_recursive_chaos_advisory", {})
    profiles_executed = list(summary.get("profiles") or [])
    record = {
        "schema_version": RECURSIVE_CHAOS_AUTOMATION_SUMMARY_VERSION,
        "state_slice": STATE_SLICE,
        "started_at": started_at,
        "finished_at": _now(),
        "run_id": str(run.get("run_id") or ""),
        "stage": run.get("stage"),
        "status": str(run.get("status") or ""),
        "operator_id": operator.get("operator_id") or settings["operator_email"],
        "profile_source": profile_source,
        "profiles_requested": list(payload["profile_ids"]),
        "profiles_executed": profiles_executed,
        "priority_phases": settings["priority_phases"] or "all",
        "seed": int(payload["seed"]),
        "max_cycles": int(payload["max_cycles"]),
        "execute": bool(payload["execute"]),
        "session_status": summary.get("status"),
        "cycles_total": int(summary.get("cycles_total") or 0),
        "learning_packet_count": len(summary.get("learning_packet_refs") or []),
        "advisory_hash": advisory.get("advisory_hash"),
        "output_dir": summary.get("output_dir"),
    }
    registry_profiles = selected_profiles or [{"profile_id": profile_id, "priority_phase": "unknown"} for profile_id in payload["profile_ids"]]
    record["intelligence_score"] = build_recursive_chaos_intelligence_score(
        automation_record=record,
        registry_profiles=registry_profiles,
        prior_records=prior_records,
    )
    record["feedback_gate"] = build_recursive_chaos_feedback_gate(
        run_id=record["run_id"],
        summary=summary,
        advisory=advisory,
        intelligence_score=record["intelligence_score"],
    )
    validate_recursive_chaos_automation_summary(record)
    return record


def _post_json(url: str, payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, sort_keys=True).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Auth-Request-Email": settings["operator_email"],
            "X-Mesh-Role": settings["operator_roles"],
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_record(record: dict[str, Any], settings: dict[str, Any]) -> None:
    settings["summary_path"].parent.mkdir(parents=True, exist_ok=True)
    settings["history_dir"].mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    settings["summary_path"].write_text(text, encoding="utf-8")
    settings["history_dir"].joinpath(f"{record['run_id']}.json").write_text(text, encoding="utf-8")


def _load_prior_records(history_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not history_dir.exists():
        return records
    for path in sorted(history_dir.glob("*.json"))[-50:]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _resolve_seed(value: str) -> int:
    if not value or value.lower() == "auto":
        return max(int(time.time()) % 999_999_999, 1)
    return max(min(int(value), 999_999_999), 1)


def _resolve_max_cycles(value: str, profile_count: int) -> int:
    if not value or value.lower() == "auto":
        return max(min(profile_count, 16), 1)
    return max(min(int(value), profile_count, 16), 1)


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
