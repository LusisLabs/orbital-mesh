import json
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from scripts.operator_auth_provider_smoke import (
    build_proof,
    live_provider_proof_template,
    runtime_auth_evidence_status,
    validate_live_provider_proof,
)
from scripts.operator_auth_live_provider_capture import build_live_provider_proof_from_identity


class OperatorAuthProviderSmokeTests(unittest.TestCase):
    def test_live_provider_template_is_redacted_and_fail_closed(self) -> None:
        template = live_provider_proof_template()

        self.assertEqual(template["schema_version"], "mesh.operator_auth_provider_live_proof.v1")
        self.assertEqual(template["state_slice"], "auth-provider-proof.v1")
        self.assertFalse(template["raw_secret_material_present"])
        status = validate_live_provider_proof(template, proof_path="template")
        self.assertEqual(status["status"], "blocked")
        self.assertIn("clean_browser_session_not_proven", status["missing_or_blocked"])
        self.assertIn("email_signup_browser_completion_missing", status["missing_or_blocked"])
        self.assertIn("google_oauth_browser_completion_missing", status["missing_or_blocked"])
        self.assertIn("github_oauth_browser_completion_missing", status["missing_or_blocked"])
        self.assertIn("hcaptcha_browser_completion_missing", status["missing_or_blocked"])
        self.assertFalse(status["raw_secret_material_present"])

    def test_readiness_proof_has_no_blockers_when_live_provider_proof_is_complete(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root_env = Path(tmp_dir) / ".env.local"
            frontend_env = Path(tmp_dir) / "frontend.env.local"
            root_env.write_text(
                "\n".join(
                    [
                        "MESH_AUTH_MODE=app_session",
                        "MESH_CAPTCHA_PROVIDER=hcaptcha",
                        "MESH_CAPTCHA_SITE_KEY=site-key-redacted",
                        "MESH_CAPTCHA_SECRET_KEY=secret-key-redacted",
                        "MESH_GOOGLE_OAUTH_CLIENT_ID=google-client-redacted",
                        "MESH_GOOGLE_OAUTH_CLIENT_SECRET=google-secret-redacted",
                        "MESH_GOOGLE_OAUTH_REDIRECT_URL=http://127.0.0.1:8787/api/auth/oauth/google/callback",
                        "MESH_GITHUB_OAUTH_CLIENT_ID=github-client-redacted",
                        "MESH_GITHUB_OAUTH_CLIENT_SECRET=github-secret-redacted",
                        "MESH_GITHUB_OAUTH_REDIRECT_URL=http://127.0.0.1:8787/api/auth/oauth/github/callback",
                        "MESH_AUTH_PRODUCT_REDIRECT_URL=http://127.0.0.1:3000",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            frontend_env.write_text("NEXT_PUBLIC_MESH_API_URL=http://127.0.0.1:8787\n", encoding="utf-8")
            live_status = {
                "status": "complete",
                "blocker": "",
                "raw_secret_material_present": False,
                "captcha": {"browser_token_verified": True, "browser_token_status": "verified"},
            }
            runtime_status = {
                "status": "complete",
                "blocker": "",
                "missing_or_blocked": [],
            }
            with (
                patch("scripts.operator_auth_provider_smoke._tracked_paths", return_value=[]),
                patch("scripts.operator_auth_provider_smoke._ignored_paths", return_value=[str(root_env), str(frontend_env)]),
                patch("scripts.operator_auth_provider_smoke._tracked_secret_hits", return_value=[]),
                patch("scripts.operator_auth_provider_smoke.live_provider_proof_status", return_value=live_status),
                patch("scripts.operator_auth_provider_smoke.runtime_auth_evidence_status", return_value=runtime_status),
            ):
                proof = build_proof(root_env, frontend_env, Path(tmp_dir) / "live-provider-proof.json")

        self.assertEqual(proof["status"], "provider_browser_proof_complete")
        self.assertEqual(proof["blockers"], [])
        self.assertTrue(proof["captcha"]["browser_token_verified"])
        self.assertEqual(proof["product_redirect"]["status"], "ready")
        self.assertEqual(proof["product_redirect"]["allowed_by"], "loopback")

    def test_live_provider_proof_completes_only_with_clean_browser_evidence(self) -> None:
        proof = {
            "schema_version": "mesh.operator_auth_provider_live_proof.v1",
            "state_slice": "auth-provider-proof.v1",
            "clean_browser_session": True,
            "raw_secret_material_present": False,
            "providers": {
                "google_oauth": {
                    "browser_completed": True,
                    "session_established": True,
                    "callback_path": "/api/auth/oauth/google/callback",
                    "completed_at": "2026-05-20T00:00:00Z",
                },
                "github_oauth": {
                    "browser_completed": True,
                    "session_established": True,
                    "callback_path": "/api/auth/oauth/github/callback",
                    "completed_at": "2026-05-20T00:00:00Z",
                },
            },
            "email_signup": {
                "browser_completed": True,
                "session_established": True,
                "hcaptcha_verified": True,
                "completed_at": "2026-05-20T00:00:00Z",
            },
            "captcha": {
                "provider": "hcaptcha",
                "challenge_completed": True,
                "browser_token_verified": True,
                "completed_at": "2026-05-20T00:00:00Z",
            },
        }

        status = validate_live_provider_proof(proof, proof_path="local")

        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["browser_completion_status"], "complete")
        self.assertEqual(status["missing_or_blocked"], [])
        self.assertFalse(status["raw_secret_material_present"])

    def test_live_provider_proof_rejects_raw_secret_fields(self) -> None:
        proof = {
            "schema_version": "mesh.operator_auth_provider_live_proof.v1",
            "state_slice": "auth-provider-proof.v1",
            "clean_browser_session": True,
            "raw_secret_material_present": False,
            "providers": {
                "google_oauth": {
                    "browser_completed": True,
                    "session_established": True,
                    "callback_path": "/api/auth/oauth/google/callback",
                    "access_token": "do-not-store-token-material",
                },
                "github_oauth": {
                    "browser_completed": True,
                    "session_established": True,
                    "callback_path": "/api/auth/oauth/github/callback",
                },
            },
            "email_signup": {
                "browser_completed": True,
                "session_established": True,
                "hcaptcha_verified": True,
            },
            "captcha": {
                "provider": "hcaptcha",
                "challenge_completed": True,
                "browser_token_verified": True,
            },
        }

        status = validate_live_provider_proof(proof, proof_path="local")

        self.assertEqual(status["status"], "blocked")
        self.assertTrue(status["raw_secret_material_present"])
        self.assertIn("providers.google_oauth.access_token", status["raw_secret_fields"])
        self.assertIn("live_provider_proof_contains_raw_secret_material", status["missing_or_blocked"])

    def test_runtime_auth_evidence_completes_from_redacted_identity_events(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            identity_path = Path(tmp_dir) / "operator-identity.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "auth_events": [
                            {
                                "event_type": "password_signup",
                                "auth_method": "password",
                                "state_slice": "auth-provider-proof.v1",
                                "session_token_hash": "hash-only",
                                "captcha": {
                                    "provider": "hcaptcha",
                                    "configured": True,
                                    "verified": True,
                                    "dev_bypass": False,
                                },
                                "recorded_at": "2026-05-20T00:00:00Z",
                            },
                            {
                                "event_type": "oauth_session_established",
                                "auth_method": "oauth",
                                "provider": "google",
                                "state_slice": "auth-provider-proof.v1",
                                "session_token_hash": "hash-only-google",
                                "recorded_at": "2026-05-20T00:01:00Z",
                            },
                            {
                                "event_type": "oauth_session_established",
                                "auth_method": "oauth",
                                "provider": "github",
                                "state_slice": "auth-provider-proof.v1",
                                "session_token_hash": "hash-only-github",
                                "recorded_at": "2026-05-20T00:02:00Z",
                            },
                        ]
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            status = runtime_auth_evidence_status(identity_path)

        self.assertEqual(status["schema_version"], "mesh.operator_auth_runtime_evidence.v1")
        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["missing_or_blocked"], [])
        self.assertFalse(status["raw_secret_material_present"])
        self.assertEqual(status["providers"]["google_oauth"]["status"], "complete")
        self.assertEqual(status["providers"]["github_oauth"]["status"], "complete")
        self.assertEqual(status["captcha"]["status"], "complete")

    def test_complete_live_proof_requires_runtime_auth_evidence(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root_env = Path(tmp_dir) / ".env.local"
            frontend_env = Path(tmp_dir) / "frontend.env.local"
            root_env.write_text(
                "\n".join(
                    [
                        "MESH_AUTH_MODE=app_session",
                        "MESH_CAPTCHA_PROVIDER=hcaptcha",
                        "MESH_CAPTCHA_SITE_KEY=site-key-redacted",
                        "MESH_CAPTCHA_SECRET_KEY=secret-key-redacted",
                        "MESH_GOOGLE_OAUTH_CLIENT_ID=google-client-redacted",
                        "MESH_GOOGLE_OAUTH_CLIENT_SECRET=google-secret-redacted",
                        "MESH_GOOGLE_OAUTH_REDIRECT_URL=http://127.0.0.1:8787/api/auth/oauth/google/callback",
                        "MESH_GITHUB_OAUTH_CLIENT_ID=github-client-redacted",
                        "MESH_GITHUB_OAUTH_CLIENT_SECRET=github-secret-redacted",
                        "MESH_GITHUB_OAUTH_REDIRECT_URL=http://127.0.0.1:8787/api/auth/oauth/github/callback",
                        "MESH_AUTH_PRODUCT_REDIRECT_URL=https://evil.example.test",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            frontend_env.write_text("NEXT_PUBLIC_MESH_API_URL=http://127.0.0.1:8787\n", encoding="utf-8")
            live_status = {
                "status": "complete",
                "blocker": "",
                "raw_secret_material_present": False,
                "captcha": {"browser_token_verified": True, "browser_token_status": "verified"},
            }
            with (
                patch("scripts.operator_auth_provider_smoke._tracked_paths", return_value=[]),
                patch("scripts.operator_auth_provider_smoke._ignored_paths", return_value=[str(root_env), str(frontend_env)]),
                patch("scripts.operator_auth_provider_smoke._tracked_secret_hits", return_value=[]),
                patch("scripts.operator_auth_provider_smoke.live_provider_proof_status", return_value=live_status),
                patch(
                    "scripts.operator_auth_provider_smoke.runtime_auth_evidence_status",
                    return_value={"status": "blocked", "blocker": "runtime_auth_evidence_incomplete"},
                ),
            ):
                proof = build_proof(root_env, frontend_env, Path(tmp_dir) / "live-provider-proof.json")

        self.assertEqual(proof["status"], "blocked_configuration")
        self.assertIn("runtime_auth_evidence_incomplete", proof["blockers"])
        self.assertIn("auth_product_redirect_untrusted", proof["blockers"])

    def test_runtime_auth_evidence_requires_email_signup_event(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            identity_path = Path(tmp_dir) / "operator-identity.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "auth_events": [
                            {
                                "event_type": "oauth_session_established",
                                "auth_method": "oauth",
                                "provider": "google",
                                "state_slice": "auth-provider-proof.v1",
                                "session_token_hash": "hash-only-google",
                                "recorded_at": "2026-05-20T00:01:00Z",
                            },
                            {
                                "event_type": "oauth_session_established",
                                "auth_method": "oauth",
                                "provider": "github",
                                "state_slice": "auth-provider-proof.v1",
                                "session_token_hash": "hash-only-github",
                                "recorded_at": "2026-05-20T00:02:00Z",
                            },
                        ]
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            status = runtime_auth_evidence_status(identity_path)

        self.assertEqual(status["status"], "blocked")
        self.assertIn("runtime_email_signup_event_missing", status["missing_or_blocked"])

    def test_live_capture_builds_complete_redacted_proof_from_runtime_events(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            identity_path = Path(tmp_dir) / "operator-identity.json"
            identity_path.write_text(
                json.dumps(
                    {
                        "auth_events": [
                            {
                                "event_type": "password_signup",
                                "auth_method": "password",
                                "state_slice": "auth-provider-proof.v1",
                                "session_token_hash": "hash-only",
                                "captcha": {
                                    "provider": "hcaptcha",
                                    "configured": True,
                                    "verified": True,
                                    "dev_bypass": False,
                                },
                                "recorded_at": "2026-05-20T00:00:00Z",
                            },
                            {
                                "event_type": "oauth_session_established",
                                "auth_method": "oauth",
                                "provider": "google",
                                "state_slice": "auth-provider-proof.v1",
                                "session_token_hash": "hash-only-google",
                                "recorded_at": "2026-05-20T00:01:00Z",
                            },
                            {
                                "event_type": "oauth_session_established",
                                "auth_method": "oauth",
                                "provider": "github",
                                "state_slice": "auth-provider-proof.v1",
                                "session_token_hash": "hash-only-github",
                                "recorded_at": "2026-05-20T00:02:00Z",
                            },
                        ]
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            proof = build_live_provider_proof_from_identity(
                identity_path,
                clean_browser_session=True,
                started_at="2026-05-20T00:00:00Z",
            )
            status = validate_live_provider_proof(proof, proof_path=str(identity_path))

        self.assertEqual(status["status"], "complete")
        self.assertEqual(status["email_signup"]["status"], "complete")
        self.assertEqual(status["providers"]["google_oauth"]["status"], "complete")
        self.assertEqual(status["providers"]["github_oauth"]["status"], "complete")
        self.assertFalse(status["raw_secret_material_present"])


if __name__ == "__main__":
    unittest.main()
