from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .incident_coverage import verify_incident_coverage_proof
from .on_call_drill import verify_on_call_drill
from .production_target import verify_production_target_proof
from .provider_action_scope import verify_provider_action_scope_proof
from .repeatability import verify_repeatability_proof
from .watch_mode_proof import verify_watch_mode_proof


PRODUCTION_AUTONOMY_CLEARANCE_VERSION = "mesh.production_autonomy_clearance.v1"


def verify_production_autonomy_clearance(
    *,
    repeatability_proof: str | Path | None,
    production_target_proof: str | Path | None,
    provider_action_scope_proof: str | Path | None,
    watch_mode_proof: str | Path | None,
    incident_coverage_proof: str | Path | None,
    on_call_drill_proof: str | Path | None,
    expected_head: str | None = None,
    expected_environment: str | None = None,
    registry_path: str | Path | None = None,
    require_live: bool = True,
    require_clean_env: bool = True,
) -> dict[str, Any]:
    repeatability = verify_repeatability_proof(
        repeatability_proof,
        expected_head=expected_head,
        require_clean_env=require_clean_env,
    )
    production_target = verify_production_target_proof(
        production_target_proof,
        expected_environment=expected_environment,
        require_live=require_live,
    )
    provider_actions = verify_provider_action_scope_proof(
        provider_action_scope_proof,
        registry_path=registry_path,
        require_live=require_live,
    )
    watch_mode = verify_watch_mode_proof(
        watch_mode_proof,
        expected_environment=expected_environment,
        require_live=require_live,
    )
    incident_coverage = verify_incident_coverage_proof(
        incident_coverage_proof,
        require_live=require_live,
    )
    governance = verify_on_call_drill(
        on_call_drill_proof,
        expected_environment=expected_environment,
    )
    artifacts = {
        "repeatability": repeatability,
        "production_target": production_target,
        "provider_actions": provider_actions,
        "watch_mode": watch_mode,
        "incident_coverage": incident_coverage,
        "governance": governance,
    }
    checks = _clearance_checks(
        artifacts,
        expected_environment=expected_environment,
        require_live=require_live,
    )
    return {
        "schema_version": PRODUCTION_AUTONOMY_CLEARANCE_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "expected_head": expected_head,
        "expected_environment": expected_environment,
        "require_live": require_live,
        "require_clean_env": require_clean_env,
        "checks": checks,
        "missing": [name for name, passed in checks.items() if not passed],
        "artifacts": artifacts,
    }


def _clearance_checks(
    artifacts: dict[str, dict[str, Any]],
    *,
    expected_environment: str | None,
    require_live: bool,
) -> dict[str, bool]:
    environment = (expected_environment or "").strip()
    checks = {
        "repeatability_passed": artifacts["repeatability"].get("status") == "pass",
        "production_target_passed": artifacts["production_target"].get("status") == "pass",
        "provider_actions_passed": artifacts["provider_actions"].get("status") == "pass",
        "watch_mode_passed": artifacts["watch_mode"].get("status") == "pass",
        "incident_coverage_passed": artifacts["incident_coverage"].get("status") == "pass",
        "governance_drill_passed": artifacts["governance"].get("status") == "pass",
        "live_evidence_required": _live_evidence_required(artifacts) if require_live else True,
        "environments_match_expected": _environments_match(artifacts, environment) if environment else True,
        "all_proof_paths_present": _all_proof_packets_present(artifacts),
        "target_bound_to_watch_mode": _target_bound_to_watch_mode(artifacts),
        "run_bound_to_repeatability": _run_bound_to_repeatability(artifacts),
        "run_bound_to_watch_mode": _run_bound_to_watch_mode(artifacts),
        "run_bound_to_incident_coverage": _run_bound_to_incident_coverage(artifacts),
        "provider_action_bound_to_run_export": _provider_action_bound_to_run_export(artifacts),
        "governance_environment_bound": _governance_check(artifacts, "environment_matches_expected", environment),
        "governance_kill_switch_verified": _governance_checks_all(
            artifacts,
            ("kill_switch_stopped_live_execution", "kill_switch_paused_watchers", "kill_switch_forced_approval_gate"),
        ),
        "governance_break_glass_verified": _governance_check(artifacts, "provider_key_break_glass_recorded"),
        "governance_credential_rotation_verified": _governance_check(artifacts, "provider_key_rotation_verified"),
        "governance_state_restore_verified": _governance_check(artifacts, "state_restore_verified"),
        "replay_artifact_bound": _replay_artifact_bound(artifacts),
    }
    return checks


def _live_evidence_required(artifacts: dict[str, dict[str, Any]]) -> bool:
    for key in ("production_target", "provider_actions", "watch_mode"):
        checks = artifacts[key].get("checks")
        if not isinstance(checks, dict) or checks.get("live_evidence_required") is not True:
            return False
    incident_checks = artifacts["incident_coverage"].get("checks")
    if not isinstance(incident_checks, dict) or incident_checks.get("live_evidence_required") is not True:
        return False
    return True


def _all_proof_packets_present(artifacts: dict[str, dict[str, Any]]) -> bool:
    for record in artifacts.values():
        checks = record.get("checks")
        if not isinstance(checks, dict) or checks.get("proof_present") is not True:
            return False
    return True


def _environments_match(artifacts: dict[str, dict[str, Any]], expected_environment: str) -> bool:
    for key in ("production_target", "provider_actions", "watch_mode", "incident_coverage", "governance"):
        if artifacts[key].get("environment") != expected_environment:
            return False
    return True


def _target_bound_to_watch_mode(artifacts: dict[str, dict[str, Any]]) -> bool:
    target_ref = str(artifacts["production_target"].get("target_ref") or "").strip()
    return bool(target_ref) and target_ref in _strings(artifacts["watch_mode"].get("target_refs"))


def _run_bound_to_repeatability(artifacts: dict[str, dict[str, Any]]) -> bool:
    run_id = _production_target_run_id(artifacts)
    return bool(run_id) and run_id in _strings(artifacts["repeatability"].get("run_ids"))


def _run_bound_to_watch_mode(artifacts: dict[str, dict[str, Any]]) -> bool:
    run_id = _production_target_run_id(artifacts)
    return bool(run_id) and run_id in _strings(artifacts["watch_mode"].get("run_ids"))


def _run_bound_to_incident_coverage(artifacts: dict[str, dict[str, Any]]) -> bool:
    run_id = _production_target_run_id(artifacts)
    return bool(run_id) and run_id in _strings(artifacts["incident_coverage"].get("run_ids"))


def _provider_action_bound_to_run_export(artifacts: dict[str, dict[str, Any]]) -> bool:
    run_id = _production_target_run_id(artifacts)
    if not run_id:
        return False
    return any(run_id in ref for ref in _strings(artifacts["provider_actions"].get("run_export_refs")))


def _replay_artifact_bound(artifacts: dict[str, dict[str, Any]]) -> bool:
    return bool(str(artifacts["production_target"].get("third_party_replay_ref") or "").strip())


def _governance_checks_all(artifacts: dict[str, dict[str, Any]], names: tuple[str, ...]) -> bool:
    return all(_governance_check(artifacts, name) for name in names)


def _governance_check(
    artifacts: dict[str, dict[str, Any]],
    name: str,
    expected_environment: str = "",
) -> bool:
    if name == "environment_matches_expected" and not expected_environment:
        return True
    checks = artifacts["governance"].get("checks")
    return isinstance(checks, dict) and checks.get(name) is True


def _production_target_run_id(artifacts: dict[str, dict[str, Any]]) -> str:
    return str(artifacts["production_target"].get("run_id") or "").strip()


def _strings(raw: Any) -> list[str]:
    return [str(item) for item in raw if str(item).strip()] if isinstance(raw, list) else []


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
