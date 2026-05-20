import json
import socket
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from scripts.operator_auth_provider_smoke import (
    DEFAULT_IDENTITY,
    build_proof,
    live_provider_proof_template,
    runtime_auth_evidence_status,
    validate_live_provider_proof,
)
from scripts.operator_auth_live_provider_capture import (
    build_auth_checkpoint,
    build_live_capture_preflight,
    build_live_capture_attempt,
    build_live_provider_proof_from_identity,
    build_live_stack_smoke,
    build_live_stack_smoke_blocked,
    build_local_stack_env,
    live_capture_exit_code,
    redact_known_values,
    restore_file_texts,
    snapshot_file_texts,
    _assert_stack_ports_available,
)


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

    def test_live_stack_env_uses_default_identity_path_and_redacts_secret_values(self) -> None:
        root_env = {
            "MESH_GOOGLE_OAUTH_CLIENT_SECRET": "google-secret-redacted",
            "MESH_CAPTCHA_SECRET_KEY": "captcha-secret-redacted",
            "MESH_AUTH_ALLOWED_ORIGINS": "http://127.0.0.1:4000",
        }
        frontend_env = {"NEXT_PUBLIC_MESH_API_URL": "http://127.0.0.1:8787"}
        identity_path = Path("/tmp/operator-identity.json")

        stack_env = build_local_stack_env(
            root_env,
            frontend_env,
            api_url="http://127.0.0.1:8787",
            product_url="http://127.0.0.1:3000",
            identity_path=identity_path,
            next_dist_dir=".next-auth-live-test",
        )
        redacted = redact_known_values(
            "google-secret-redacted captcha-secret-redacted visible",
            [root_env["MESH_GOOGLE_OAUTH_CLIENT_SECRET"], root_env["MESH_CAPTCHA_SECRET_KEY"]],
        )

        self.assertEqual(stack_env["MESH_AUTH_MODE"], "app_session")
        self.assertEqual(stack_env["MESH_SERVER_HOST"], "127.0.0.1")
        self.assertEqual(stack_env["MESH_SERVER_PORT"], "8787")
        self.assertEqual(stack_env["MESH_OPERATOR_IDENTITY_PATH"], str(identity_path))
        self.assertEqual(stack_env["NEXT_PUBLIC_MESH_API_URL"], "http://127.0.0.1:8787")
        self.assertEqual(stack_env["MESH_AUTH_PRODUCT_REDIRECT_URL"], "http://127.0.0.1:3000")
        self.assertIn("http://127.0.0.1:3000", stack_env["MESH_AUTH_ALLOWED_ORIGINS"])
        self.assertNotIn("google-secret-redacted", redacted)
        self.assertNotIn("captcha-secret-redacted", redacted)
        self.assertIn("visible", redacted)

    def test_live_capture_preflight_blocks_redirect_mismatch_without_secret_material(self) -> None:
        preflight = build_live_capture_preflight(
            root_env={
                "MESH_CAPTCHA_PROVIDER": "hcaptcha",
                "MESH_CAPTCHA_SITE_KEY": "site-key-redacted",
                "MESH_CAPTCHA_SECRET_KEY": "secret-key-redacted",
                "MESH_GOOGLE_OAUTH_REDIRECT_URL": "http://127.0.0.1:8787/api/auth/oauth/google/callback",
                "MESH_GITHUB_OAUTH_REDIRECT_URL": "http://127.0.0.1:9999/api/auth/oauth/github/callback",
                "MESH_AUTH_PRODUCT_REDIRECT_URL": "http://127.0.0.1:4000",
            },
            frontend_env={"NEXT_PUBLIC_MESH_API_URL": "http://127.0.0.1:8787"},
            api_url="http://127.0.0.1:8787",
            product_url="http://127.0.0.1:3000",
            identity_path=DEFAULT_IDENTITY,
            managed_local_stack=True,
            stack_mode="managed_local_stack",
        )

        self.assertEqual(preflight["schema_version"], "mesh.operator_auth_live_capture_preflight.v1")
        self.assertEqual(preflight["state_slice"], "auth-provider-proof.v1")
        self.assertEqual(preflight["status"], "blocked")
        self.assertIn("github_oauth_redirect_url_mismatch", preflight["blockers"])
        self.assertIn("auth_product_redirect_url_mismatch", preflight["blockers"])
        self.assertTrue(preflight["oauth"]["google"]["exact_match"])
        self.assertFalse(preflight["oauth"]["github"]["exact_match"])
        self.assertFalse(preflight["raw_secret_material_present"])

    def test_live_capture_preflight_blocks_missing_product_redirect_and_nondefault_identity(self) -> None:
        preflight = build_live_capture_preflight(
            root_env={
                "MESH_CAPTCHA_PROVIDER": "hcaptcha",
                "MESH_CAPTCHA_SITE_KEY": "site-key-redacted",
                "MESH_CAPTCHA_SECRET_KEY": "secret-key-redacted",
                "MESH_GOOGLE_OAUTH_REDIRECT_URL": "http://127.0.0.1:8787/api/auth/oauth/google/callback",
                "MESH_GITHUB_OAUTH_REDIRECT_URL": "http://127.0.0.1:8787/api/auth/oauth/github/callback",
            },
            frontend_env={"NEXT_PUBLIC_MESH_API_URL": "http://127.0.0.1:8787"},
            api_url="http://127.0.0.1:8787",
            product_url="http://127.0.0.1:3000",
            identity_path=Path("/tmp/operator-identity.json"),
            managed_local_stack=False,
            stack_mode="unmanaged",
        )

        self.assertEqual(preflight["status"], "blocked")
        self.assertIn("auth_product_redirect_url_missing", preflight["blockers"])
        self.assertIn("auth_identity_path_not_default", preflight["blockers"])
        self.assertFalse(preflight["identity_path_matches_default"])
        self.assertFalse(preflight["raw_secret_material_present"])

    def test_live_capture_preflight_ready_when_redirects_and_hcaptcha_match(self) -> None:
        preflight = build_live_capture_preflight(
            root_env={
                "MESH_CAPTCHA_PROVIDER": "hcaptcha",
                "MESH_CAPTCHA_SITE_KEY": "site-key-redacted",
                "MESH_CAPTCHA_SECRET_KEY": "secret-key-redacted",
                "MESH_GOOGLE_OAUTH_REDIRECT_URL": "http://127.0.0.1:8787/api/auth/oauth/google/callback",
                "MESH_GITHUB_OAUTH_REDIRECT_URL": "http://127.0.0.1:8787/api/auth/oauth/github/callback",
                "MESH_AUTH_PRODUCT_REDIRECT_URL": "http://127.0.0.1:3000",
            },
            frontend_env={"NEXT_PUBLIC_MESH_API_URL": "http://127.0.0.1:8787"},
            api_url="http://127.0.0.1:8787",
            product_url="http://127.0.0.1:3000",
            identity_path=DEFAULT_IDENTITY,
            managed_local_stack=True,
            stack_mode="managed_local_stack",
        )

        self.assertEqual(preflight["status"], "ready")
        self.assertEqual(preflight["blockers"], [])
        self.assertTrue(preflight["oauth"]["google"]["exact_match"])
        self.assertTrue(preflight["oauth"]["github"]["exact_match"])
        self.assertTrue(preflight["product_redirect"]["exact_match"])
        self.assertTrue(preflight["captcha"]["hcaptcha_env_ready"])
        self.assertFalse(preflight["raw_secret_material_present"])

    def test_live_stack_smoke_artifacts_are_redacted_and_do_not_claim_provider_completion(self) -> None:
        class Stack:
            api_url = "http://127.0.0.1:8787"
            product_url = "http://127.0.0.1:3000"
            stack_mode = "managed_local_stack"
            managed_processes_owned = True

        preflight = {
            "status": "ready",
            "identity_path": str(DEFAULT_IDENTITY),
            "identity_path_matches_default": True,
        }

        ready = build_live_stack_smoke(preflight=preflight, stack=Stack(), started_at="2026-05-20T00:00:00Z")
        blocked = build_live_stack_smoke_blocked(
            preflight=preflight,
            api_url="http://127.0.0.1:8787",
            product_url="http://127.0.0.1:3000",
            started_at="2026-05-20T00:00:00Z",
            stack_mode="managed_local_stack",
            blocker="local_stack_unavailable",
            detail="redacted failure",
        )

        self.assertEqual(ready["schema_version"], "mesh.operator_auth_live_stack_smoke.v1")
        self.assertEqual(ready["state_slice"], "auth-provider-proof.v1")
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["readiness"]["api_auth_config"], "reachable")
        self.assertEqual(ready["readiness"]["product_shell"], "reachable")
        self.assertEqual(ready["stack_mode"], "managed_local_stack")
        self.assertTrue(ready["managed_processes_owned"])
        self.assertFalse(ready["raw_secret_material_present"])
        self.assertNotIn("OAuth", ready["status"])
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("local_stack_unavailable", blocked["blockers"])
        self.assertEqual(blocked["stack_mode"], "managed_local_stack")
        self.assertFalse(blocked["managed_processes_owned"])
        self.assertFalse(blocked["raw_secret_material_present"])

    def test_managed_stack_fails_closed_when_requested_port_is_already_in_use(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        try:
            with self.assertRaisesRegex(RuntimeError, "--reuse-local-stack"):
                _assert_stack_ports_available([("api", "127.0.0.1", port)])
        finally:
            listener.close()

    def test_live_stack_file_snapshots_restore_next_generated_churn(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            kept = Path(tmp_dir) / "next-env.d.ts"
            missing = Path(tmp_dir) / "generated.d.ts"
            kept.write_text("original\n", encoding="utf-8")
            snapshots = snapshot_file_texts([kept, missing])

            kept.write_text("mutated\n", encoding="utf-8")
            missing.write_text("created\n", encoding="utf-8")
            restore_file_texts(snapshots)

            self.assertEqual(kept.read_text(encoding="utf-8"), "original\n")
            self.assertFalse(missing.exists())

    def test_auth_checkpoint_binds_local_evidence_without_claiming_live_provider_completion(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readiness_path = root / "latest.json"
            preflight_path = root / "live-preflight.json"
            stack_smoke_path = root / "live-stack-smoke.json"
            attempt_path = root / "live-capture-attempt.json"
            live_proof_path = root / "live-provider-proof.json"
            readiness_path.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.operator_auth_provider_readiness.v1",
                        "state_slice": "auth-provider-proof.v1",
                        "status": "blocked_provider_console_unverified",
                        "raw_secret_material_present": False,
                        "tracked_env_secret_material_present": False,
                        "tracked_secret_hits": [],
                        "blockers": ["live_provider_proof_missing"],
                        "oauth": {
                            "google": {"local_callback_match": True},
                            "github": {"local_callback_match": True},
                        },
                        "captcha": {"hcaptcha_env_ready": True},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            preflight_path.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.operator_auth_live_capture_preflight.v1",
                        "state_slice": "auth-provider-proof.v1",
                        "status": "ready",
                        "blockers": [],
                        "raw_secret_material_present": False,
                        "identity_path_matches_default": True,
                        "oauth": {
                            "google": {"exact_match": True},
                            "github": {"exact_match": True},
                        },
                        "product_redirect": {"exact_match": True},
                        "captcha": {"hcaptcha_env_ready": True},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            stack_smoke_path.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.operator_auth_live_stack_smoke.v1",
                        "state_slice": "auth-provider-proof.v1",
                        "status": "ready",
                        "blockers": [],
                        "preflight_status": "ready",
                        "stack_mode": "managed_local_stack",
                        "managed_processes_owned": True,
                        "raw_secret_material_present": False,
                        "identity_path_matches_default": True,
                        "readiness": {
                            "api_auth_config": "reachable",
                            "product_shell": "reachable",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            attempt_path.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.operator_auth_live_capture_attempt.v1",
                        "state_slice": "auth-provider-proof.v1",
                        "status": "blocked",
                        "blockers": ["google_oauth_browser_completion_missing"],
                        "clean_browser_session": True,
                        "preflight_status": "ready",
                        "stack_mode": "managed_local_stack",
                        "managed_processes_owned": True,
                        "raw_secret_material_present": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            checkpoint = build_auth_checkpoint(
                readiness_path=readiness_path,
                preflight_path=preflight_path,
                stack_smoke_path=stack_smoke_path,
                attempt_path=attempt_path,
                live_proof_path=live_proof_path,
            )

        self.assertEqual(checkpoint["schema_version"], "mesh.operator_auth_checkpoint.v1")
        self.assertEqual(checkpoint["state_slice"], "auth-provider-proof.v1")
        self.assertEqual(checkpoint["status"], "blocked_external_provider_proof")
        self.assertEqual(checkpoint["local_evidence_status"], "complete")
        self.assertEqual(checkpoint["blockers"], ["live_provider_proof_missing"])
        self.assertEqual(checkpoint["missing_local_evidence"], [])
        self.assertFalse(checkpoint["raw_secret_material_present"])
        self.assertEqual(checkpoint["live_capture_attempt_status"], "blocked")
        self.assertEqual(checkpoint["live_capture_attempt_stack_mode"], "managed_local_stack")
        self.assertEqual(checkpoint["live_capture_attempt_blockers"], ["google_oauth_browser_completion_missing"])
        self.assertEqual(checkpoint["next_required_command"], "pnpm run auth-provider:live-stack")

    def test_auth_checkpoint_points_reused_stack_evidence_to_reuse_stack_command(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            readiness_path = root / "latest.json"
            preflight_path = root / "live-preflight.json"
            stack_smoke_path = root / "live-stack-smoke.json"
            attempt_path = root / "live-capture-attempt.json"
            live_proof_path = root / "live-provider-proof.json"
            readiness_path.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.operator_auth_provider_readiness.v1",
                        "state_slice": "auth-provider-proof.v1",
                        "status": "blocked_provider_console_unverified",
                        "raw_secret_material_present": False,
                        "tracked_env_secret_material_present": False,
                        "tracked_secret_hits": [],
                        "blockers": ["live_provider_proof_missing"],
                        "oauth": {
                            "google": {"local_callback_match": True},
                            "github": {"local_callback_match": True},
                        },
                        "captcha": {"hcaptcha_env_ready": True},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            preflight_path.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.operator_auth_live_capture_preflight.v1",
                        "state_slice": "auth-provider-proof.v1",
                        "status": "ready",
                        "blockers": [],
                        "raw_secret_material_present": False,
                        "identity_path_matches_default": True,
                        "oauth": {
                            "google": {"exact_match": True},
                            "github": {"exact_match": True},
                        },
                        "product_redirect": {"exact_match": True},
                        "captcha": {"hcaptcha_env_ready": True},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            stack_smoke_path.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.operator_auth_live_stack_smoke.v1",
                        "state_slice": "auth-provider-proof.v1",
                        "status": "ready",
                        "blockers": [],
                        "preflight_status": "ready",
                        "stack_mode": "reused_local_stack",
                        "managed_processes_owned": False,
                        "raw_secret_material_present": False,
                        "identity_path_matches_default": True,
                        "readiness": {
                            "api_auth_config": "reachable",
                            "product_shell": "reachable",
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            attempt_path.write_text(
                json.dumps(
                    {
                        "schema_version": "mesh.operator_auth_live_capture_attempt.v1",
                        "state_slice": "auth-provider-proof.v1",
                        "status": "blocked",
                        "blockers": ["github_oauth_browser_completion_missing"],
                        "clean_browser_session": True,
                        "preflight_status": "ready",
                        "stack_mode": "reused_local_stack",
                        "managed_processes_owned": False,
                        "raw_secret_material_present": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            checkpoint = build_auth_checkpoint(
                readiness_path=readiness_path,
                preflight_path=preflight_path,
                stack_smoke_path=stack_smoke_path,
                attempt_path=attempt_path,
                live_proof_path=live_proof_path,
            )

        self.assertEqual(checkpoint["local_evidence_status"], "complete")
        self.assertEqual(checkpoint["next_required_command"], "pnpm run auth-provider:reuse-stack")

    def test_live_capture_attempt_records_missing_components_without_secret_material(self) -> None:
        attempt = build_live_capture_attempt(
            preflight={"status": "ready"},
            proof={
                "runtime_identity_path": "/tmp/operator-identity.json",
                "raw_secret_material_present": False,
            },
            validation={
                "status": "blocked",
                "browser_completion_status": "requires_clean_browser_provider_completion",
                "missing_or_blocked": [
                    "email_signup_browser_completion_missing",
                    "google_oauth_browser_completion_missing",
                ],
                "raw_secret_material_present": False,
                "providers": {"google_oauth": {"status": "blocked"}},
                "email_signup": {"status": "blocked"},
                "captcha": {"status": "blocked"},
            },
            started_at="2026-05-20T00:00:00Z",
            api_url="http://127.0.0.1:8787",
            product_url="http://127.0.0.1:3000",
            clean_browser_session=True,
            managed_local_stack=True,
            stack_mode="managed_local_stack",
            managed_processes_owned=True,
        )

        self.assertEqual(attempt["schema_version"], "mesh.operator_auth_live_capture_attempt.v1")
        self.assertEqual(attempt["state_slice"], "auth-provider-proof.v1")
        self.assertEqual(attempt["status"], "blocked")
        self.assertEqual(attempt["preflight_status"], "ready")
        self.assertTrue(attempt["clean_browser_session"])
        self.assertTrue(attempt["managed_local_stack"])
        self.assertEqual(attempt["stack_mode"], "managed_local_stack")
        self.assertTrue(attempt["managed_processes_owned"])
        self.assertIn("email_signup_browser_completion_missing", attempt["blockers"])
        self.assertFalse(attempt["raw_secret_material_present"])

    def test_blocked_attempt_exit_code_is_allowed_only_for_clean_local_evidence(self) -> None:
        blocked_attempt = {
            "status": "blocked",
            "preflight_status": "ready",
            "clean_browser_session": True,
            "raw_secret_material_present": False,
        }
        dirty_attempt = {**blocked_attempt, "raw_secret_material_present": True}
        incomplete_attempt = {**blocked_attempt, "preflight_status": "blocked"}

        self.assertEqual(live_capture_exit_code(attempt={"status": "complete"}, allow_blocked_attempt=False), 0)
        self.assertEqual(live_capture_exit_code(attempt=blocked_attempt, allow_blocked_attempt=False), 2)
        self.assertEqual(live_capture_exit_code(attempt=blocked_attempt, allow_blocked_attempt=True), 0)
        self.assertEqual(live_capture_exit_code(attempt=dirty_attempt, allow_blocked_attempt=True), 2)
        self.assertEqual(live_capture_exit_code(attempt=incomplete_attempt, allow_blocked_attempt=True), 2)


if __name__ == "__main__":
    unittest.main()
