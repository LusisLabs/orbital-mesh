from __future__ import annotations

import json
import time
from typing import Any


CREDENTIAL_EGRESS_POLICY_VERSION = "mesh.credential_egress_policy.v1"
CREDENTIAL_EGRESS_VERIFICATION_VERSION = "mesh.credential_egress_verification.v1"


def verify_credential_egress_policy(
    policy: dict[str, Any] | None,
    *,
    agent_attempt_outputs: list[dict[str, Any]] | None = None,
    sandbox_logs: list[str] | None = None,
    exported_artifacts: list[dict[str, Any]] | None = None,
    raw_secret_values: list[str] | None = None,
    proxy_runtime: dict[str, Any] | None = None,
    egress_audit_events: list[dict[str, Any]] | None = None,
    require_proxy_runtime: bool = False,
) -> dict[str, Any]:
    records = policy.get("records") if isinstance(policy, dict) else None
    record_list = [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []
    proof = policy.get("proof") if isinstance(policy, dict) and isinstance(policy.get("proof"), dict) else {}
    raw_secrets = list(raw_secret_values or proof.get("raw_secret_fixture_values") or [])
    runtime = proxy_runtime if proxy_runtime is not None else proof.get("proxy_runtime")
    audit_events = egress_audit_events if egress_audit_events is not None else proof.get("egress_audit_events")
    attempt_outputs = agent_attempt_outputs if agent_attempt_outputs is not None else proof.get("agent_attempt_outputs")
    logs = sandbox_logs if sandbox_logs is not None else proof.get("sandbox_logs")
    exports = exported_artifacts if exported_artifacts is not None else proof.get("exported_artifacts")
    checks = {
        "policy_present": isinstance(policy, dict),
        "schema_version_matches": isinstance(policy, dict)
        and policy.get("schema_version") == CREDENTIAL_EGRESS_POLICY_VERSION,
        "records_present": bool(record_list),
        "secret_name_present": all(bool(str(record.get("secret_name") or "").strip()) for record in record_list),
        "allowed_hosts_present": all(_non_empty_string_list(record.get("allowed_hosts")) for record in record_list),
        "allowed_location_present": all(_allowed_location_present(record) for record in record_list),
        "sandbox_placeholder_only": all(record.get("sandbox_placeholder_only") is True for record in record_list),
        "egress_audit_event_id_present": all(bool(str(record.get("egress_audit_event_id") or "").strip()) for record in record_list),
        "no_raw_secret_in_attempt_output": _no_raw_secret_in_outputs(
            _dict_list(attempt_outputs),
            raw_secrets,
        ),
        "no_raw_secret_in_sandbox_logs": _no_raw_secret_in_texts(_string_list(logs), raw_secrets),
        "no_raw_secret_in_exports": _no_raw_secret_in_outputs(_dict_list(exports), raw_secrets),
        "proxy_runtime_present": (not require_proxy_runtime) or _proxy_runtime_present(runtime),
        "proxy_runtime_live_audit_proven": (not require_proxy_runtime) or _proxy_runtime_live_audit_proven(runtime),
        "proxy_runtime_host_bound": (not require_proxy_runtime) or _proxy_runtime_host_bound(runtime),
        "proxy_runtime_forbids_raw_secret_env": (not require_proxy_runtime)
        or _proxy_runtime_forbids_raw_secret_env(runtime, raw_secrets),
        "egress_audit_events_present": (not require_proxy_runtime)
        or _egress_audit_events_cover_policy(record_list, _dict_list(audit_events)),
    }
    return {
        "schema_version": CREDENTIAL_EGRESS_VERIFICATION_VERSION,
        "generated_at": _timestamp(),
        "status": "pass" if all(checks.values()) else "fail",
        "checks": checks,
        "record_count": len(record_list),
        "authority": {
            "mesh_control_plane_authoritative": True,
            "sandbox_receives_raw_credentials": False,
            "proxy_mediated_egress_required": True,
        },
    }


def _proxy_runtime_present(proxy_runtime: dict[str, Any] | None) -> bool:
    if not isinstance(proxy_runtime, dict):
        return False
    return str(proxy_runtime.get("runtime") or proxy_runtime.get("type") or "") in {
        "iron-proxy",
        "credential-egress-proxy",
    }


def _proxy_runtime_live_audit_proven(proxy_runtime: dict[str, Any] | None) -> bool:
    if not isinstance(proxy_runtime, dict):
        return False
    return (
        proxy_runtime.get("proof_mode") == "live_proxy_audit"
        and bool(str(proxy_runtime.get("proxy_instance_id") or "").strip())
        and bool(str(proxy_runtime.get("last_audit_event_id") or "").strip())
    )


def _proxy_runtime_host_bound(proxy_runtime: dict[str, Any] | None) -> bool:
    if not isinstance(proxy_runtime, dict):
        return False
    return (
        proxy_runtime.get("sandbox_placeholder_only") is True
        and proxy_runtime.get("host_bound_substitution") is True
        and _non_empty_string_list(proxy_runtime.get("allowed_hosts"))
    )


def _proxy_runtime_forbids_raw_secret_env(
    proxy_runtime: dict[str, Any] | None,
    raw_secret_values: list[str],
) -> bool:
    if not isinstance(proxy_runtime, dict):
        return False
    env = proxy_runtime.get("sandbox_env")
    if not isinstance(env, dict):
        return True
    serialized = json.dumps(env, sort_keys=True, default=str)
    return not any(secret and secret in serialized for secret in raw_secret_values)


def _egress_audit_events_cover_policy(records: list[dict[str, Any]], audit_events: list[dict[str, Any]]) -> bool:
    required_ids = {str(record.get("egress_audit_event_id") or "") for record in records}
    required_ids.discard("")
    observed_ids = {str(event.get("event_id") or "") for event in audit_events if isinstance(event, dict)}
    return bool(required_ids) and required_ids.issubset(observed_ids)


def _allowed_location_present(record: dict[str, Any]) -> bool:
    locations = record.get("allowed_locations")
    if not isinstance(locations, dict):
        return False
    return any(_non_empty_string_list(locations.get(key)) for key in ("header", "query", "path"))


def _non_empty_string_list(value: Any) -> bool:
    return isinstance(value, list) and any(isinstance(item, str) and item.strip() for item in value)


def _no_raw_secret_in_outputs(outputs: list[dict[str, Any]], raw_secret_values: list[str]) -> bool:
    non_empty_secret_values = [value for value in raw_secret_values if value]
    if not non_empty_secret_values:
        return True
    serialized = json.dumps(outputs, sort_keys=True, default=str)
    return not any(secret in serialized for secret in non_empty_secret_values)


def _no_raw_secret_in_texts(texts: list[str], raw_secret_values: list[str]) -> bool:
    non_empty_secret_values = [value for value in raw_secret_values if value]
    if not non_empty_secret_values:
        return True
    serialized = "\n".join(texts)
    return not any(secret in serialized for secret in non_empty_secret_values)


def _dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
