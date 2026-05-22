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
FIXTURES_DIR = PACKAGE_ROOT / "fixtures" / "perennial"
PILOT_PACKET_SCHEMA = "perennial/darkharness-pilot-packet.schema.json"
SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas" / "perennial"
HMAC_SECRET = "darkharness-handover-verify-secret"


def orbital_mesh_root() -> Path | None:
    env = os.environ.get("MESH_ORBITAL_ROOT", "").strip()
    if env:
        candidate = Path(env)
        if (candidate / "scripts" / "verify_darkharness_live_packet.py").exists():
            return candidate
    for candidate in (PACKAGE_ROOT.parent / "lusis-mesh", PACKAGE_ROOT.parent.parent / "lusis-mesh"):
        if (candidate / "scripts" / "verify_darkharness_live_packet.py").exists():
            return candidate
    return None


def load_packet_from_path(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "contracts" in payload and isinstance(payload["contracts"], dict):
        if "darkharness_pilot_packet" in payload["contracts"]:
            return payload["contracts"]["darkharness_pilot_packet"]
    return payload


def _load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def list_schema_files() -> dict[str, Any]:
    schemas = sorted(p.name for p in SCHEMA_DIR.glob("*.json"))
    return {"status": "pass", "summary": f"{len(schemas)} perennial schemas", "schemas": schemas}


def evaluate_policy_fixture(fixture_name: str) -> dict[str, Any]:
    allowed = _load_fixture("allowed_action.json")
    pilot_scope = allowed["contracts"]["pilot_scope"]
    if fixture_name == "allowed":
        run_export = {
            "evaluation_record": {"final_recommendation": "execute", "blocking_reasons": []},
            "approval_records": [{"event_id": "evt_approval"}],
        }
        action_records = [allowed["contracts"]["agent_action_record"]]
    else:
        denied = _load_fixture("denied_action.json")
        run_export = {
            "evaluation_record": {
                "final_recommendation": "reject",
                "blocking_reasons": ["production-impacting action requires operator approval"],
            },
            "approval_records": [],
        }
        action_records = [denied["contracts"]["agent_action_record"]]
    result = evaluate_darkharness_packet_policy(
        pilot_scope=pilot_scope,
        run_export=run_export,
        action_records=action_records,
    )
    return {
        "status": "pass" if result.allowed else "fail",
        "summary": f"policy evaluation for {fixture_name} fixture",
        "fixture": fixture_name,
        "allowed": result.allowed,
        "checks": result.checks,
        "violations": result.violations,
        "blockers": result.violations,
    }


def run_mesh_live(*, orbital_root: Path | None = None) -> dict[str, Any]:
    root = orbital_root or orbital_mesh_root()
    if root is None:
        return {
            "status": "fail",
            "summary": "Orbital Mesh checkout not found",
            "blockers": ["mesh_orbital_root_missing"],
            "hint": "Set MESH_ORBITAL_ROOT to an Orbital Mesh checkout containing scripts/verify_darkharness_live_packet.py",
        }
    script = root / "scripts" / "verify_darkharness_live_packet.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root)
    completed = subprocess.run(
        [sys.executable, str(script), "--json"],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if completed.returncode != 0 and not completed.stdout.strip():
        return {
            "status": "fail",
            "summary": "mesh live proof failed",
            "stderr": completed.stderr.strip(),
            "returncode": completed.returncode,
            "orbital_root": str(root),
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "status": "fail",
            "summary": "mesh live proof returned non-JSON output",
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
            "orbital_root": str(root),
        }
    payload["orbital_root"] = str(root)
    payload["returncode"] = completed.returncode
    payload["summary"] = "mesh live proof"
    payload["status"] = "pass" if completed.returncode == 0 else "fail"
    if payload["status"] != "pass":
        payload.setdefault("blockers", []).append("mesh_live_failed")
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

    allowed_policy = evaluate_policy_fixture("allowed")
    checks["allowed_policy_passes"] = allowed_policy["status"] == "pass"
    if not checks["allowed_policy_passes"]:
        blockers.append("allowed_policy_failed")

    denied_policy = evaluate_policy_fixture("denied")
    checks["denied_policy_passes"] = denied_policy["status"] == "pass"
    if not checks["denied_policy_passes"]:
        blockers.append("denied_policy_failed")

    boundary = _load_fixture("pilot_packet_boundary.json")
    boundary_packet = boundary["contracts"]["darkharness_pilot_packet"]
    validate_payload(PILOT_PACKET_SCHEMA, boundary_packet)
    checks["boundary_packet_valid"] = boundary_packet["boundaries"]["raw_reservoir_egress"] == "deny"

    result: dict[str, Any] = {
        "status": "pass" if not blockers else "fail",
        "summary": "darkharness SDK verify-e2e",
        "checks": checks,
        "blockers": blockers,
    }
    if with_mesh_live:
        mesh_live = run_mesh_live()
        result["mesh_live"] = mesh_live
        if mesh_live.get("status") != "pass":
            result["status"] = "fail"
            result.setdefault("blockers", []).append("mesh_live_failed")
    return result
