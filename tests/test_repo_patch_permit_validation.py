from __future__ import annotations

import hashlib
import json
import unittest
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from shared.mesh_runtime.repo_patch_permit_validation import (
    RepoPatchPermitSemanticError,
    repo_patch_execution_permit_semantic_issues,
    validate_repo_patch_execution_permit_semantics,
)


class RepoPatchPermitSemanticValidationTests(unittest.TestCase):
    def test_valid_permit_passes(self) -> None:
        validate_repo_patch_execution_permit_semantics(_valid_permit())
        self.assertEqual(repo_patch_execution_permit_semantic_issues(_valid_permit()), ())

    def test_nonempty_tenant_is_required(self) -> None:
        validate_repo_patch_execution_permit_semantics(_valid_permit(tenant="ténant-alpha"))
        permit = _valid_permit()
        permit.pop("tenant")
        self.assertIn("tenant_missing", repo_patch_execution_permit_semantic_issues(permit))

    def test_exact_versions_scope_and_action_are_required(self) -> None:
        cases = {
            "schema_version": ("mesh.repo_patch_execution_permit.v2", "schema_version_mismatch"),
            "transaction_version": (
                "mesh.repo_patch_execution_transaction.v2",
                "transaction_version_mismatch",
            ),
            "authority_scope": ("unbounded", "authority_scope_mismatch"),
            "action_kind": ("deployment", "action_kind_mismatch"),
        }
        for field, (value, expected_issue) in cases.items():
            with self.subTest(field=field):
                permit = _valid_permit()
                permit[field] = value
                self.assertIn(expected_issue, repo_patch_execution_permit_semantic_issues(permit))

    def test_issuer_audience_and_tenant_must_be_nonempty(self) -> None:
        for field in ("issuer", "executor_audience", "tenant"):
            with self.subTest(field=field):
                permit = _valid_permit(tenant="tenant-alpha")
                permit[field] = "   "
                self.assertIn(f"{field}_missing", repo_patch_execution_permit_semantic_issues(permit))

    def test_nonce_must_be_exact_lowercase_64_hex(self) -> None:
        for value in ("a" * 63, "A" * 64, "g" * 64, 7, None):
            with self.subTest(value=value):
                permit = _valid_permit()
                permit["authority_nonce"] = value
                self.assertIn("authority_nonce_invalid", repo_patch_execution_permit_semantic_issues(permit))

    def test_every_sha256_field_is_validated(self) -> None:
        digest_fields = (
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
        for field in digest_fields:
            with self.subTest(field=field):
                permit = _valid_permit()
                permit[field] = "sha256:" + ("A" * 64)
                self.assertIn(f"{field}_invalid", repo_patch_execution_permit_semantic_issues(permit))

    def test_time_window_requires_aware_ordered_maximum_300_seconds(self) -> None:
        cases = (
            ({"issued_at": "2026-07-12T12:00:00"}, "issued_at_invalid_or_naive"),
            ({"not_before": "2026-07-12T12:00:00"}, "not_before_invalid_or_naive"),
            ({"expires_at": "2026-07-12T12:05:00"}, "expires_at_invalid_or_naive"),
            (
                {"expires_at": "2026-07-12T11:59:59Z"},
                "permit_time_window_not_ordered",
            ),
            (
                {"expires_at": "2026-07-12T12:05:01Z"},
                "permit_time_window_exceeds_300_seconds",
            ),
        )
        for changes, expected_issue in cases:
            with self.subTest(expected_issue=expected_issue):
                permit = _valid_permit()
                permit.update(changes)
                self.assertIn(expected_issue, repo_patch_execution_permit_semantic_issues(permit))

    def test_claim_lists_are_nonempty_unique_and_canonical(self) -> None:
        for field in (
            "requested_claims",
            "accepted_claims",
            "explicit_nonclaims",
            "enforced_nonclaims",
        ):
            with self.subTest(field=field, case="empty"):
                permit = _valid_permit()
                permit[field] = []
                self.assertIn(f"{field}_empty_or_invalid", repo_patch_execution_permit_semantic_issues(permit))
            with self.subTest(field=field, case="blank"):
                permit = _valid_permit()
                permit[field] = [" "]
                self.assertIn(f"{field}_contains_invalid_claim", repo_patch_execution_permit_semantic_issues(permit))
            with self.subTest(field=field, case="duplicate"):
                permit = _valid_permit()
                permit[field] = ["claim", "claim"]
                self.assertIn(f"{field}_contains_duplicate_claim", repo_patch_execution_permit_semantic_issues(permit))

    def test_claim_relations_are_enforced(self) -> None:
        permit = _valid_permit()
        permit["accepted_claims"] = ["unrequested"]
        self.assertIn(
            "accepted_claims_not_subset_of_requested_claims",
            repo_patch_execution_permit_semantic_issues(permit),
        )

        permit = _valid_permit()
        permit["enforced_nonclaims"] = ["does_not_claim_production_certification"]
        self.assertIn(
            "enforced_nonclaims_not_superset_of_explicit_nonclaims",
            repo_patch_execution_permit_semantic_issues(permit),
        )

    def test_authorization_proof_shape_is_exact(self) -> None:
        cases: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
            "fields": (
                lambda proof: proof.update({"extra": True}),
                "authorization_proof_fields_mismatch",
            ),
            "profile": (
                lambda proof: proof.update({"signing_profile": "wrong"}),
                "authorization_proof_signing_profile_mismatch",
            ),
            "algorithm": (
                lambda proof: proof.update({"algorithm": "none"}),
                "authorization_proof_algorithm_mismatch",
            ),
            "key": (
                lambda proof: proof.update({"key_id": ""}),
                "authorization_proof_key_id_missing",
            ),
            "signature": (
                lambda proof: proof.update({"signature": "A" * 64}),
                "authorization_proof_signature_invalid",
            ),
            "payload": (
                lambda proof: proof.update({"payload_sha256": "A" * 64}),
                "authorization_proof_payload_sha256_invalid",
            ),
            "status": (
                lambda proof: proof.update({"status": "unverified"}),
                "authorization_proof_status_mismatch",
            ),
            "verifier": (
                lambda proof: proof.update({"verifier": "unknown"}),
                "authorization_proof_verifier_mismatch",
            ),
        }
        for label, (mutate, expected_issue) in cases.items():
            with self.subTest(label=label):
                permit = _valid_permit()
                proof = permit["authorization_proof"]
                assert isinstance(proof, dict)
                mutate(proof)
                self.assertIn(expected_issue, repo_patch_execution_permit_semantic_issues(permit))

        permit = _valid_permit()
        permit["authorization_proof"] = None
        self.assertIn("authorization_proof_invalid", repo_patch_execution_permit_semantic_issues(permit))

    def test_authorization_payload_digest_is_bound(self) -> None:
        permit = _valid_permit()
        permit["authorization_proof"]["payload_sha256"] = "0" * 64
        self.assertIn(
            "authorization_proof_payload_sha256_mismatch",
            repo_patch_execution_permit_semantic_issues(permit),
        )

    def test_permit_digest_authority_entry_and_ledger_tip_are_recomputed(self) -> None:
        cases = (
            ("permit_digest", "permit_digest_mismatch"),
            ("authority_entry_digest", "authority_entry_digest_mismatch"),
            ("ledger_tip_after", "ledger_tip_after_mismatch"),
        )
        for field, expected_issue in cases:
            with self.subTest(field=field):
                permit = _valid_permit()
                permit[field] = "sha256:" + ("f" * 64)
                self.assertIn(expected_issue, repo_patch_execution_permit_semantic_issues(permit))

    def test_validate_raises_typed_error_with_deterministic_issues(self) -> None:
        permit = _valid_permit()
        permit["action_kind"] = "wrong"
        with self.assertRaises(RepoPatchPermitSemanticError) as raised:
            validate_repo_patch_execution_permit_semantics(permit)
        self.assertEqual(raised.exception.issues[0], "action_kind_mismatch")


def _valid_permit(*, tenant: str = "tenant-alpha") -> dict[str, Any]:
    digest = "sha256:" + ("1" * 64)
    permit: dict[str, Any] = {
        "schema_version": "mesh.repo_patch_execution_permit.v1",
        "transaction_version": "mesh.repo_patch_execution_transaction.v1",
        "permit_id": "permit_12345678",
        "authority_scope": "local_disposable_repo_patch_only",
        "issuer": "mesh.orchestrator",
        "executor_audience": "mesh.repo_patch_actuator",
        "tenant": tenant,
        "mesh_run_id": "run_test",
        "mesh_action_id": "action_test",
        "action_kind": "repo_patch",
        "authority_nonce": "a" * 64,
        "idempotency_key": "decision:investigate_and_patch",
        "hsai_request_digest": digest,
        "hsai_decision_digest": digest,
        "candidate_payload_digest": digest,
        "action_proposal_digest": digest,
        "evidence_packet_digest": digest,
        "mesh_policy_id": "mesh_policy://repo-patch/test",
        "policy_snapshot_digest": digest,
        "canonical_actuation_payload_digest": digest,
        "repo_path": "/tmp/repo",
        "target_path": "/tmp/repo/app.py",
        "target_preimage_digest": digest,
        "target_postimage_digest": digest,
        "requested_claims": ["patch_applies_cleanly", "tests_passed"],
        "accepted_claims": ["patch_applies_cleanly"],
        "explicit_nonclaims": [
            "does_not_claim_production_certification",
            "does_not_claim_security_review_complete",
        ],
        "enforced_nonclaims": [
            "does_not_claim_production_certification",
            "does_not_claim_security_review_complete",
            "does_not_claim_formal_proof",
        ],
        "expected_ledger_tip_before": "sha256:" + ("0" * 64),
        "issued_at": "2026-07-12T12:00:00Z",
        "not_before": "2026-07-12T12:00:00Z",
        "expires_at": "2026-07-12T12:05:00Z",
    }
    permit["authority_entry_digest"] = _canonical_digest(
        {
            "tip_before": permit["expected_ledger_tip_before"],
            "permit": permit,
        }
    )
    permit["ledger_tip_after"] = _canonical_digest(
        {
            "tip_before": permit["expected_ledger_tip_before"],
            "entry_digest": permit["authority_entry_digest"],
        }
    )
    permit["permit_digest"] = _canonical_digest(permit)
    signed_payload = deepcopy(permit)
    permit["authorization_proof"] = {
        "signing_profile": "mesh-repo-patch-execution-permit-hmac-sha256-v1",
        "algorithm": "hmac-sha256",
        "key_id": "repo-patch-permit-hmac",
        "signature": "b" * 64,
        "payload_sha256": hashlib.sha256(_authorization_canonical_bytes(signed_payload)).hexdigest(),
        "status": "verified",
        "verifier": "orbital_mesh_hmac_sha256_v1",
    }
    return permit


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _authorization_canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
