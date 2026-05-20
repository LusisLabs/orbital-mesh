from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.operator_config import main as operator_config_main
from shared.mesh_runtime.operator_identity import (
    SESSION_TTL_SECONDS,
    CaptchaConfig,
    OAuthProviderConfig,
    OperatorIdentityStore,
    oauth_authorize_url,
)


class OperatorIdentityStoreTests(unittest.TestCase):
    def test_signup_login_team_and_settings_share_identity_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OperatorIdentityStore(Path(temp_dir) / "operator-identity.json")
            captcha = CaptchaConfig(provider="disabled", dev_bypass_enabled=True)
            session = store.create_user(
                email="Ops@Example.com",
                password="correct-horse-42",
                display_name="Ops Lead",
                captcha_token="dev-captcha-ok",
                captcha=captcha,
            )
            token = session["token"]
            self.assertEqual(session["session"]["user"]["email"], "ops@example.com")

            logged_in = store.login_user(email="ops@example.com", password="correct-horse-42")
            self.assertIn("token", logged_in)

            team_session = store.create_team(
                token,
                name="Mesh Operators",
                members=[{"email": "viewer@example.com", "role": "viewer"}],
            )
            active_team = team_session["active_team"]
            self.assertEqual(active_team["name"], "Mesh Operators")
            self.assertEqual(active_team["members"][1]["status"], "invited")

            settings = store.update_settings(
                token,
                team_id=active_team["id"],
                updates={"default_orchestration_mode": "hermes"},
            )
            self.assertEqual(settings["settings"]["default_orchestration_mode"], "hermes")

            scoped = store.read_scoped_settings(f"team:{active_team['id']}")
            self.assertEqual(scoped["settings"]["default_orchestration_mode"], "hermes")

    def test_operator_config_cli_mutates_same_settings_slice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "operator-identity.json"
            with patch("sys.stdout"):
                exit_code = operator_config_main(
                    [
                        "--identity-path",
                        str(identity_path),
                        "set",
                        "--scope",
                        "team:team_test",
                        "--operator-id",
                        "admin@example.com",
                        "--reason",
                        "test",
                        "default_evaluation_mode=promptfoo",
                    ]
                )
            self.assertEqual(exit_code, 0)
            data = json.loads(identity_path.read_text(encoding="utf-8"))
            self.assertEqual(data["settings"]["team:team_test"]["default_evaluation_mode"], "promptfoo")
            audit_path = identity_path.parent / "operator-config-audit.jsonl"
            self.assertTrue(audit_path.exists())
            audit_record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(audit_record["reason"], "test")
            self.assertEqual(audit_record["scope"], "team:team_test")
            self.assertEqual(audit_record["state_slice"], "mesh-settings-control")

    def test_invalid_setting_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OperatorIdentityStore(Path(temp_dir) / "operator-identity.json")
            with self.assertRaises(ValueError):
                store.update_scoped_settings("global", {"default_evaluation_mode": "unsafe"})

    def test_public_captcha_config_requires_site_key_and_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OperatorIdentityStore(Path(temp_dir) / "operator-identity.json")
            google = OAuthProviderConfig(provider="google")
            github = OAuthProviderConfig(provider="github")

            missing_site_key = store.public_auth_config(
                captcha=CaptchaConfig(provider="turnstile", secret="secret"),
                google=google,
                github=github,
            )
            self.assertFalse(missing_site_key["captcha"]["configured"])

            configured = store.public_auth_config(
                captcha=CaptchaConfig(provider="turnstile", site_key="site", secret="secret"),
                google=google,
                github=github,
            )
            self.assertTrue(configured["captcha"]["configured"])

    def test_team_dashboard_access_denied_for_non_member(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OperatorIdentityStore(Path(temp_dir) / "operator-identity.json")
            captcha = CaptchaConfig(provider="disabled", dev_bypass_enabled=True)
            owner = store.create_user(
                email="owner@example.com",
                password="correct-horse-42",
                captcha_token="dev-captcha-ok",
                captcha=captcha,
            )
            owner_token = owner["token"]
            team_session = store.create_team(
                owner_token,
                name="Production Operators",
                members=[{"email": "viewer@example.com", "role": "viewer"}],
            )
            team_id = team_session["active_team"]["id"]
            self.assertEqual(team_session["active_team"]["roles"], ["admin", "approver", "launcher", "viewer"])

            outsider = store.create_user(
                email="outsider@example.com",
                password="correct-horse-42",
                captcha_token="dev-captcha-ok",
                captcha=captcha,
            )
            with self.assertRaises(PermissionError):
                store.dashboard(outsider["token"], team_id=team_id, mesh={})
            with self.assertRaises(PermissionError):
                store.set_active_team(outsider["token"], team_id)

    def test_team_member_roles_map_to_mesh_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OperatorIdentityStore(Path(temp_dir) / "operator-identity.json")
            captcha = CaptchaConfig(provider="disabled", dev_bypass_enabled=True)
            owner = store.create_user(
                email="owner@example.com",
                password="correct-horse-42",
                captcha_token="dev-captcha-ok",
                captcha=captcha,
            )
            team = store.create_team(
                owner["token"],
                name="Role Mapping Operators",
                members=[
                    {"email": "viewer@example.com", "role": "viewer"},
                    {"email": "launcher@example.com", "role": "launcher"},
                    {"email": "approver@example.com", "role": "approver"},
                    {"email": "admin@example.com", "role": "admin"},
                ],
            )
            team_id = team["active_team"]["id"]

            expected_roles = {
                "viewer@example.com": ("viewer", ["viewer"]),
                "launcher@example.com": ("launcher", ["launcher", "viewer"]),
                "approver@example.com": ("approver", ["approver", "launcher", "viewer"]),
                "admin@example.com": ("admin", ["admin", "approver", "launcher", "viewer"]),
            }
            for email, (role, roles) in expected_roles.items():
                member = store.create_user(
                    email=email,
                    password="correct-horse-42",
                    captcha_token="dev-captcha-ok",
                    captcha=captcha,
                )
                dashboard = store.dashboard(member["token"], team_id=team_id, mesh={})
                self.assertEqual(dashboard["scope"]["team"]["role"], role)
                self.assertEqual(dashboard["scope"]["team"]["roles"], roles)

    def test_expired_session_is_rejected_and_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = OperatorIdentityStore(Path(temp_dir) / "operator-identity.json")
            now = time.time()
            session = store.create_user(
                email="expired@example.com",
                password="correct-horse-42",
                captcha_token="dev-captcha-ok",
                captcha=CaptchaConfig(provider="disabled", dev_bypass_enabled=True),
                now=now,
            )

            with self.assertRaisesRegex(ValueError, "session expired"):
                store.session_payload(session["token"], now=now + SESSION_TTL_SECONDS + 2)
            data = json.loads((Path(temp_dir) / "operator-identity.json").read_text(encoding="utf-8"))
            self.assertEqual(data["sessions"], {})

    def test_oauth_authorize_url_requires_complete_provider_config(self) -> None:
        with self.assertRaisesRegex(ValueError, "google oauth is not configured"):
            oauth_authorize_url(OAuthProviderConfig(provider="google", client_id="client"), "state")

        google_url = oauth_authorize_url(
            OAuthProviderConfig(
                provider="google",
                client_id="google-client",
                client_secret="google-secret",
                redirect_uri="http://127.0.0.1:8787/api/auth/oauth/google/callback",
            ),
            "state-123",
        )
        self.assertIn("accounts.google.com", google_url)
        self.assertIn("state=state-123", google_url)

        github_url = oauth_authorize_url(
            OAuthProviderConfig(
                provider="github",
                client_id="github-client",
                client_secret="github-secret",
                redirect_uri="http://127.0.0.1:8787/api/auth/oauth/github/callback",
            ),
            "state-456",
        )
        self.assertIn("github.com/login/oauth/authorize", github_url)
        self.assertIn("state=state-456", github_url)


if __name__ == "__main__":
    unittest.main()
