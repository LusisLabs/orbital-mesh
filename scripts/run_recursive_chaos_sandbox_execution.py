#!/usr/bin/env python3
"""Run one disposable recursive-chaos sandbox execution through Mesh."""

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

from shared.mesh_runtime.schema_validation import validate_payload  # noqa: E402


STATE_SLICE = "mesh.recursive_chaos.sandbox_execution.v1"
DEFAULT_API_URL = "http://127.0.0.1:8788/api/recursive-chaos/sessions"
DEFAULT_OPERATOR = "mesh-recursive-chaos-sandbox@localhost"
DEFAULT_ROLES = "admin,approver,launcher,viewer"
DEFAULT_SUMMARY_PATH = "/opt/lusis-mesh-webapp/shared/state/recursive-chaos/sandbox-execution/last-run.json"
DEFAULT_HISTORY_DIR = "/opt/lusis-mesh-webapp/shared/state/recursive-chaos/sandbox-execution/runs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a disposable compose-backed recursive chaos execution.")
    parser.add_argument("--env-file", default=os.environ.get("MESH_RECURSIVE_CHAOS_ENV_FILE", ""))
    parser.add_argument("--profile-id", default=os.environ.get("MESH_RECURSIVE_CHAOS_SANDBOX_PROFILE_ID", "kubernetes_service_platform"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.env_file:
        _load_env_file(Path(args.env_file))

    settings = _settings_from_env()
    payload = {
        "state_slice": STATE_SLICE,
        "profile_ids": [args.profile_id],
        "max_cycles": 1,
        "seed": _seed(),
        "execute": True,
        "targets": [
            {
                "profile_id": args.profile_id,
                "context": "compose-sandbox",
                "namespace": "recursive-chaos",
                "deployment": "disposable-http-target",
                "substrate": "compose_sandbox",
                "environment": "local_disposable",
                "image_ref": os.environ.get("MESH_RECURSIVE_CHAOS_SANDBOX_IMAGE", "python:3.13-slim-trixie"),
            }
        ],
    }
    try:
        run = _post_json(settings["api_url"], payload, settings)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(json.dumps({"status": "http_error", "code": exc.code, "detail": detail}, sort_keys=True))
        return 1
    record = _record(run, payload, settings)
    _write_record(record, settings)
    print(json.dumps(record, indent=2 if args.json else None, sort_keys=True))
    return 0 if record["status"] == "completed" and record["session_status"] == "pass" else 1


def _settings_from_env() -> dict[str, Any]:
    return {
        "api_url": os.environ.get("MESH_RECURSIVE_CHAOS_API_URL", DEFAULT_API_URL),
        "operator_email": os.environ.get("MESH_RECURSIVE_CHAOS_OPERATOR_EMAIL", DEFAULT_OPERATOR),
        "operator_roles": os.environ.get("MESH_RECURSIVE_CHAOS_OPERATOR_ROLES", DEFAULT_ROLES),
        "summary_path": Path(os.environ.get("MESH_RECURSIVE_CHAOS_SANDBOX_SUMMARY_PATH", DEFAULT_SUMMARY_PATH)),
        "history_dir": Path(os.environ.get("MESH_RECURSIVE_CHAOS_SANDBOX_HISTORY_DIR", DEFAULT_HISTORY_DIR)),
    }


def _record(run: dict[str, Any], payload: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    summary = run.get("artifacts", {}).get("recursive_chaos_session_summary", {})
    feedback_gate = run.get("artifacts", {}).get("mesh_brain_recursive_chaos_feedback_gate", {})
    decision = run.get("artifacts", {}).get("decision", {})
    operator = run.get("artifacts", {}).get("operator", {})
    record = {
        "schema_version": "mesh.recursive_chaos.sandbox_execution_summary.v1",
        "state_slice": STATE_SLICE,
        "recorded_at": _now(),
        "run_id": str(run.get("run_id") or ""),
        "status": str(run.get("status") or ""),
        "stage": str(run.get("stage") or ""),
        "session_status": summary.get("status"),
        "operator_id": operator.get("operator_id") or settings["operator_email"],
        "execute": True,
        "target": payload["targets"][0],
        "cycles_total": int(summary.get("cycles_total") or 0),
        "learning_packet_count": len(summary.get("learning_packet_refs") or []),
        "decision_type": decision.get("decision_type"),
        "autonomy_tier": decision.get("autonomy_tier"),
        "feedback_gate_hash": feedback_gate.get("feedback_hash"),
        "mesh_model_training_allowed": feedback_gate.get("mesh_model_training_allowed"),
        "production_authority": feedback_gate.get("production_authority"),
        "output_dir": summary.get("output_dir"),
    }
    validate_payload("recursive-chaos-sandbox-execution-summary.schema.json", record)
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
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.loads(response.read().decode("utf-8"))


def _write_record(record: dict[str, Any], settings: dict[str, Any]) -> None:
    settings["summary_path"].parent.mkdir(parents=True, exist_ok=True)
    settings["history_dir"].mkdir(parents=True, exist_ok=True)
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    settings["summary_path"].write_text(text, encoding="utf-8")
    settings["history_dir"].joinpath(f"{record['run_id']}.json").write_text(text, encoding="utf-8")


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _seed() -> int:
    return max(int(time.time()) % 999_999_999, 1)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


if __name__ == "__main__":
    raise SystemExit(main())
