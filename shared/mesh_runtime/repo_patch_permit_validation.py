from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Mapping, Sequence


REPO_PATCH_EXECUTION_PERMIT_VERSION = "mesh.repo_patch_execution_permit.v1"
REPO_PATCH_EXECUTION_TRANSACTION_VERSION = "mesh.repo_patch_execution_transaction.v1"
REPO_PATCH_AUTHORITY_SCOPE = "local_disposable_repo_patch_only"
REPO_PATCH_ACTION_KIND = "repo_patch"
REPO_PATCH_PERMIT_SIGNING_PROFILE = "mesh-repo-patch-execution-permit-hmac-sha256-v1"
REPO_PATCH_PERMIT_MAX_TTL_SECONDS = 300

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256_FIELDS = (
    "hsai_request_digest",
    "hsai_decision_digest",
    "candidate_payload_digest",
    "action_proposal_digest",
    "evidence_packet_digest",
    "policy_snapshot_digest",
    "canonical_actuation_payload_digest",
    "target_preimage_digest",
    "target_postimage_digest",
    "expected_ledger_tip_before",
    "authority_entry_digest",
    "ledger_tip_after",
    "permit_digest",
)
_CLAIM_LIST_FIELDS = (
    "requested_claims",
    "accepted_claims",
    "explicit_nonclaims",
    "enforced_nonclaims",
)
_AUTHORIZATION_PROOF_FIELDS = frozenset(
    {
        "signing_profile",
        "algorithm",
        "key_id",
        "signature",
        "payload_sha256",
        "status",
        "verifier",
    }
)
_ENTRY_DERIVED_FIELDS = frozenset(
    {
        "authority_entry_digest",
        "ledger_tip_after",
        "permit_digest",
        "authorization_proof",
    }
)


class RepoPatchPermitSemanticError(ValueError):
    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = tuple(issues)
        super().__init__(
            "repo patch execution permit semantic validation failed: " + ", ".join(self.issues)
        )


def validate_repo_patch_execution_permit_semantics(permit: Mapping[str, Any]) -> None:
    issues = repo_patch_execution_permit_semantic_issues(permit)
    if issues:
        raise RepoPatchPermitSemanticError(issues)


def repo_patch_execution_permit_semantic_issues(permit: Mapping[str, Any]) -> tuple[str, ...]:
    issues: list[str] = []

    _expect_exact(
        permit,
        "schema_version",
        REPO_PATCH_EXECUTION_PERMIT_VERSION,
        "schema_version_mismatch",
        issues,
    )
    _expect_exact(
        permit,
        "transaction_version",
        REPO_PATCH_EXECUTION_TRANSACTION_VERSION,
        "transaction_version_mismatch",
        issues,
    )
    _expect_exact(
        permit,
        "authority_scope",
        REPO_PATCH_AUTHORITY_SCOPE,
        "authority_scope_mismatch",
        issues,
    )
    _expect_exact(permit, "action_kind", REPO_PATCH_ACTION_KIND, "action_kind_mismatch", issues)

    for field in ("issuer", "executor_audience", "tenant"):
        if not _nonempty_string(permit.get(field)):
            issues.append(f"{field}_missing")

    nonce = permit.get("authority_nonce")
    if not isinstance(nonce, str) or _HEX_64.fullmatch(nonce) is None:
        issues.append("authority_nonce_invalid")

    for field in _SHA256_FIELDS:
        value = permit.get(field)
        if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
            issues.append(f"{field}_invalid")

    _validate_time_window(permit, issues)
    claim_sets = _validate_claim_lists(permit, issues)
    _validate_claim_relations(claim_sets, issues)
    _validate_authorization_proof(permit, issues)
    _validate_digest_chain(permit, issues)

    return tuple(issues)


def _expect_exact(
    permit: Mapping[str, Any],
    field: str,
    expected: str,
    issue: str,
    issues: list[str],
) -> None:
    if permit.get(field) != expected:
        issues.append(issue)


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _parse_aware_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _validate_time_window(permit: Mapping[str, Any], issues: list[str]) -> None:
    issued_at = _parse_aware_time(permit.get("issued_at"))
    not_before = _parse_aware_time(permit.get("not_before"))
    expires_at = _parse_aware_time(permit.get("expires_at"))
    if issued_at is None:
        issues.append("issued_at_invalid_or_naive")
    if not_before is None:
        issues.append("not_before_invalid_or_naive")
    if expires_at is None:
        issues.append("expires_at_invalid_or_naive")
    if issued_at is None or not_before is None or expires_at is None:
        return
    if not issued_at <= not_before < expires_at:
        issues.append("permit_activation_window_not_ordered")
    window_seconds = (expires_at - issued_at).total_seconds()
    if window_seconds <= 0:
        issues.append("permit_time_window_not_ordered")
    elif window_seconds > REPO_PATCH_PERMIT_MAX_TTL_SECONDS:
        issues.append("permit_time_window_exceeds_300_seconds")


def _validate_claim_lists(
    permit: Mapping[str, Any],
    issues: list[str],
) -> dict[str, set[str] | None]:
    claim_sets: dict[str, set[str] | None] = {}
    for field in _CLAIM_LIST_FIELDS:
        raw = permit.get(field)
        if not isinstance(raw, list) or not raw:
            issues.append(f"{field}_empty_or_invalid")
            claim_sets[field] = None
            continue
        if any(not _nonempty_string(item) for item in raw):
            issues.append(f"{field}_contains_invalid_claim")
            claim_sets[field] = None
            continue
        values = [str(item) for item in raw]
        unique = set(values)
        if len(unique) != len(values):
            issues.append(f"{field}_contains_duplicate_claim")
        claim_sets[field] = unique
    return claim_sets


def _validate_claim_relations(
    claim_sets: Mapping[str, set[str] | None],
    issues: list[str],
) -> None:
    requested = claim_sets.get("requested_claims")
    accepted = claim_sets.get("accepted_claims")
    if requested is not None and accepted is not None and not accepted.issubset(requested):
        issues.append("accepted_claims_not_subset_of_requested_claims")
    explicit = claim_sets.get("explicit_nonclaims")
    enforced = claim_sets.get("enforced_nonclaims")
    if explicit is not None and enforced is not None and not enforced.issuperset(explicit):
        issues.append("enforced_nonclaims_not_superset_of_explicit_nonclaims")


def _validate_authorization_proof(permit: Mapping[str, Any], issues: list[str]) -> None:
    raw = permit.get("authorization_proof")
    if not isinstance(raw, Mapping):
        issues.append("authorization_proof_invalid")
        return
    if frozenset(raw.keys()) != _AUTHORIZATION_PROOF_FIELDS:
        issues.append("authorization_proof_fields_mismatch")
    if raw.get("signing_profile") != REPO_PATCH_PERMIT_SIGNING_PROFILE:
        issues.append("authorization_proof_signing_profile_mismatch")
    if raw.get("algorithm") != "hmac-sha256":
        issues.append("authorization_proof_algorithm_mismatch")
    if not _nonempty_string(raw.get("key_id")):
        issues.append("authorization_proof_key_id_missing")
    for field in ("signature", "payload_sha256"):
        value = raw.get(field)
        if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
            issues.append(f"authorization_proof_{field}_invalid")
    if raw.get("status") != "verified":
        issues.append("authorization_proof_status_mismatch")
    if raw.get("verifier") != "orbital_mesh_hmac_sha256_v1":
        issues.append("authorization_proof_verifier_mismatch")

    try:
        expected_payload_sha256 = hashlib.sha256(
            _authorization_canonical_bytes(_without_fields(permit, {"authorization_proof"}))
        ).hexdigest()
    except (TypeError, ValueError):
        issues.append("authorization_proof_payload_not_canonical_json")
        return
    if raw.get("payload_sha256") != expected_payload_sha256:
        issues.append("authorization_proof_payload_sha256_mismatch")


def _validate_digest_chain(permit: Mapping[str, Any], issues: list[str]) -> None:
    try:
        expected_permit_digest = _canonical_digest(
            _without_fields(permit, {"permit_digest", "authorization_proof"})
        )
        entry_permit = _without_fields(permit, _ENTRY_DERIVED_FIELDS)
        expected_entry_digest = _canonical_digest(
            {
                "tip_before": permit.get("expected_ledger_tip_before"),
                "permit": entry_permit,
            }
        )
        expected_ledger_tip = _canonical_digest(
            {
                "tip_before": permit.get("expected_ledger_tip_before"),
                "entry_digest": permit.get("authority_entry_digest"),
            }
        )
    except (TypeError, ValueError):
        issues.append("permit_digest_chain_not_canonical_json")
        return
    if permit.get("permit_digest") != expected_permit_digest:
        issues.append("permit_digest_mismatch")
    if permit.get("authority_entry_digest") != expected_entry_digest:
        issues.append("authority_entry_digest_mismatch")
    if permit.get("ledger_tip_after") != expected_ledger_tip:
        issues.append("ledger_tip_after_mismatch")


def _without_fields(value: Mapping[str, Any], fields: set[str] | frozenset[str]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in fields}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _authorization_canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()
