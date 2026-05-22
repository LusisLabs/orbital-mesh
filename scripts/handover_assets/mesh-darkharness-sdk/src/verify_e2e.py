from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mesh_darkharness.perennial.policy import evaluate_darkharness_packet_policy
from mesh_darkharness.perennial.signing import build_hmac_signature_proof, verify_hmac_signature_proof
from mesh_darkharness.schema_validation import validate_payload

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parent.parent
FIXTURES_DIR = PACKAGE_ROOT / "fixtures" / "perennial"
PILOT_PACKET_SCHEMA = "perennial/darkharness-pilot-packet.schema.json"
HMAC_SECRET = "darkharness-handover-verify-secret"


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def verify_packet_file(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "contracts" in payload and isinstance(payload["contracts"], dict):
        if "darkharness_pilot_packet" in payload["contracts"]:
            payload = payload["contracts"]["darkharness_pilot_packet"]
    validate_payload(PILOT_PACKET_SCHEMA, payload)
    proof = build_hmac_signature_proof(payload, key_id="handover-verify", secret=HMAC_SECRET)
    verified = verify_hmac_signature_proof(payload, proof, secret=HMAC_SECRET)
    return {
        "status": "pass" if verified else "fail",
        "packet_id": payload.get("packet_id"),
        "hmac_verified": verified,
        "blockers": [] if verified else ["hmac_sign_verify_failed"],
    }


def _run_mesh_live() -> dict[str, Any]:
    script = REPO_ROOT / "scripts" / "verify_darkharness_live_packet.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    completed = subprocess.run(
        [sys.executable, str(script), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0 and not completed.stdout.strip():
        return {"status": "fail", "stderr": completed.stderr.strip(), "returncode": completed.returncode}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "fail",
            "stderr": completed.stderr.strip() or completed.stdout.strip(),
            "returncode": completed.returncode,
        }
    payload["returncode"] = completed.returncode
    return payload


def verify_package_e2e(*, with_mesh_live: bool = False) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    blockers: list[str] = []

    allowed = _load_fixture("allowed_action.json")
    packet = allowed["contracts"]["darkharness_pilot_packet"]
    validate_payload(PILOT_PACKET_SCHEMA, packet)
    checks["allowed_packet_schema_valid"] = True

    proof = build_hmac_signature_proof(packet, key_id="handover-verify", secret=HMAC_SECRET)
    checks["hmac_sign_verify"] = verify_hmac_signature_proof(packet, proof, secret=HMAC_SECRET)
    if not checks["hmac_sign_verify"]:
        blockers.append("hmac_sign_verify_failed")

    pilot_scope = allowed["contracts"]["pilot_scope"]
    allowed_policy = evaluate_darkharness_packet_policy(
        pilot_scope=pilot_scope,
        run_export={
            "evaluation_record": {"final_recommendation": "execute", "blocking_reasons": []},
            "approval_records": [{"event_id": "evt_approval"}],
        },
        action_records=[allowed["contracts"]["agent_action_record"]],
    )
    checks["allowed_policy_passes"] = allowed_policy.allowed
    if not allowed_policy.allowed:
        blockers.append("allowed_policy_failed")

    denied = _load_fixture("denied_action.json")
    denied_policy = evaluate_darkharness_packet_policy(
        pilot_scope=pilot_scope,
        run_export={
            "evaluation_record": {
                "final_recommendation": "reject",
                "blocking_reasons": ["production-impacting action requires operator approval"],
            },
            "approval_records": [],
        },
        action_records=[denied["contracts"]["agent_action_record"]],
    )
    checks["denied_policy_passes"] = denied_policy.allowed
    if not denied_policy.allowed:
        blockers.append("denied_policy_failed")

    boundary = _load_fixture("pilot_packet_boundary.json")
    boundary_packet = boundary["contracts"]["darkharness_pilot_packet"]
    validate_payload(PILOT_PACKET_SCHEMA, boundary_packet)
    boundary_scope = boundary["contracts"]["pilot_scope"]
    checks["boundary_scope_enforced"] = boundary_scope["data_boundary"]["raw_reservoir_egress"] == "deny"
    checks["boundary_packet_valid"] = boundary_packet["boundaries"]["raw_reservoir_egress"] == "deny"
    if not checks["boundary_scope_enforced"]:
        blockers.append("boundary_scope_check_failed")
    if not checks["boundary_packet_valid"]:
        blockers.append("boundary_packet_check_failed")

    mesh_live: dict[str, Any] | None = None
    if with_mesh_live:
        mesh_live = _run_mesh_live()
        checks["mesh_live_passes"] = mesh_live.get("status") == "pass"
        if not checks["mesh_live_passes"]:
            blockers.append("mesh_live_failed")

    result: dict[str, Any] = {
        "status": "pass" if not blockers else "fail",
        "checks": checks,
        "blockers": blockers,
    }
    if mesh_live is not None:
        result["mesh_live"] = mesh_live
    return result
