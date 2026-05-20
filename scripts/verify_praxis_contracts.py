#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.schema_validation import SchemaValidationError, validate_payload

FIXTURE_PATH = REPO_ROOT / "fixtures" / "praxis" / "p1_contracts.json"
CONTRACT_SCHEMAS = {
    "mcp_generation_request": "praxis/mcp-generation-request.schema.json",
    "source_bundle": "praxis/source-bundle.schema.json",
    "generated_mcp_contract": "praxis/generated-mcp-contract.schema.json",
    "akto_security_evidence": "praxis/akto-security-evidence.schema.json",
    "acp_agent_session": "praxis/acp-agent-session.schema.json",
    "certification_binding": "praxis/certification-binding.schema.json",
}
FORBIDDEN_RAW_CREDENTIAL_KEYS = {
    "api_key",
    "authorization",
    "bearer_token",
    "client_secret",
    "cookie",
    "kubeconfig",
    "password",
    "private_key",
    "raw_credentials",
    "raw_secret",
    "raw_value",
    "secret_value",
    "token",
}


def main() -> int:
    try:
        payloads = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        for fixture_key, schema_name in CONTRACT_SCHEMAS.items():
            if fixture_key not in payloads:
                raise SchemaValidationError(f"{FIXTURE_PATH}: missing fixture key {fixture_key!r}")
            validate_payload(schema_name, payloads[fixture_key])
            _reject_forbidden_raw_credential_keys(payloads[fixture_key], f"$.{fixture_key}")
        _assert_mutating_tools_fail_closed(payloads["generated_mcp_contract"])
    except (OSError, json.JSONDecodeError, SchemaValidationError, AssertionError) as exc:
        print(f"Praxis contract verification failed: {exc}", file=sys.stderr)
        return 1
    print("Praxis contract verification passed")
    return 0


def _reject_forbidden_raw_credential_keys(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in FORBIDDEN_RAW_CREDENTIAL_KEYS:
                raise SchemaValidationError(f"{path}.{key}: raw credential field is forbidden")
            _reject_forbidden_raw_credential_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_raw_credential_keys(child, f"{path}[{index}]")


def _assert_mutating_tools_fail_closed(contract: dict[str, Any]) -> None:
    for tool in contract["tool_candidates"]:
        if tool["mutation_class"] in {"idempotent_write", "mutation", "destructive_mutation"}:
            if tool["approval_posture"] not in {"denied", "approval_required"}:
                raise SchemaValidationError(
                    f"$.generated_mcp_contract.tool_candidates[{tool['tool_id']}].approval_posture: "
                    "mutating tools must default to denied or approval_required"
                )
            if not tool["blockers"]:
                raise SchemaValidationError(
                    f"$.generated_mcp_contract.tool_candidates[{tool['tool_id']}].blockers: "
                    "mutating tools require explicit blockers until certified"
                )


if __name__ == "__main__":
    raise SystemExit(main())
