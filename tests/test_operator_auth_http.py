from __future__ import annotations

import json
import tempfile
import time
import unittest
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from control_plane_server import start_server_in_thread
from shared.mesh_runtime import RuntimeConfig


class OperatorAuthHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = RuntimeConfig(
            state_directory=self.temp_dir.name,
            vault_path=str(Path(self.temp_dir.name) / "vault"),
            integrations_config_path=str(Path(self.temp_dir.name) / "integrations.json"),
            operator_identity_path=str(Path(self.temp_dir.name) / "operator-identity.json"),
            server_host="127.0.0.1",
            server_port=0,
            auth_mode="app_session",
            captcha_dev_bypass_enabled=True,
            promptfoo_command="/missing/promptfoo",
            hermes_command="/missing/hermes",
            goose_command="/missing/goose",
        )
        self.server, self.thread = start_server_in_thread(self.config, start_sidecar=False)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with self.server.coordinator._lock:
                active_workers = list(self.server.coordinator._threads.values())
            if not any(worker.is_alive() for worker in active_workers):
                break
            time.sleep(0.05)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_signup_team_dashboard_and_protected_run_creation(self) -> None:
        with self.assertRaises(HTTPError) as unauth:
            self._request("GET", "/api/operator/dashboard")
        self.assertEqual(unauth.exception.code, HTTPStatus.UNAUTHORIZED)

        payload, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "operator@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
            },
            include_cookie=True,
        )
        self.assertEqual(payload["user"]["email"], "operator@example.com")
        self.assertIn("mesh_session=", cookie)

        team_payload, _ = self._request(
            "POST",
            "/api/auth/team",
            {"name": "Mesh Operators", "members": [{"email": "viewer@example.com", "role": "viewer"}]},
            cookie=cookie,
            include_cookie=True,
        )
        self.assertEqual(team_payload["active_team"]["name"], "Mesh Operators")

        dashboard, _ = self._request("GET", "/api/operator/dashboard", cookie=cookie, include_cookie=True)
        self.assertEqual(dashboard["scope"]["kind"], "team")
        self.assertIn("Mesh remains the authority", dashboard["authority_boundary"])
        self.assertIn("readiness", dashboard["mesh"])

        run, _ = self._request(
            "POST",
            "/api/runs",
            {"scenario_key": "reth_peer_starvation"},
            cookie=cookie,
            include_cookie=True,
        )
        self.assertIn("run_id", run)
        self.assertIn(run["status"], {"queued", "pending", "running", "completed", "failed"})

    def test_dashboard_read_model_degrades_failed_sections_explicitly(self) -> None:
        def broken_readiness():
            raise RuntimeError("readiness unavailable")

        self.server.coordinator.build_readiness = broken_readiness
        _, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "dashboard@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
            },
            include_cookie=True,
        )

        dashboard, _ = self._request("GET", "/api/operator/dashboard", cookie=cookie, include_cookie=True)
        self.assertEqual(dashboard["mesh"]["read_model"]["authority"], "read_only")
        self.assertEqual(dashboard["mesh"]["readiness"]["status"], "unavailable")
        self.assertEqual(dashboard["mesh"]["readiness"]["error"], "readiness unavailable")

    def test_logout_login_and_dashboard_recovery(self) -> None:
        _, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "recover@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
            },
            include_cookie=True,
        )
        self._request("POST", "/api/auth/team", {"name": "Recovery Operators"}, cookie=cookie)
        logout, clear_cookie = self._request("POST", "/api/auth/logout", {}, cookie=cookie, include_cookie=True)
        self.assertEqual(logout["status"], "logged_out")
        self.assertIn("Max-Age=0", clear_cookie)

        with self.assertRaises(HTTPError) as expired:
            self._request("GET", "/api/operator/dashboard", cookie=cookie)
        self.assertEqual(expired.exception.code, HTTPStatus.UNAUTHORIZED)

        logged_in, login_cookie = self._request(
            "POST",
            "/api/auth/login",
            {"email": "recover@example.com", "password": "correct-horse-42"},
            include_cookie=True,
        )
        self.assertEqual(logged_in["user"]["email"], "recover@example.com")
        dashboard, _ = self._request("GET", "/api/operator/dashboard", cookie=login_cookie, include_cookie=True)
        self.assertEqual(dashboard["scope"]["kind"], "team")

    def test_expired_session_recovery_clears_cookie_across_product_routes(self) -> None:
        routes = [
            ("GET", "/api/auth/me", None),
            ("GET", "/api/operator/dashboard", None),
            ("POST", "/api/auth/team", {"name": "Expired Operators"}),
        ]
        for index, (method, path, payload) in enumerate(routes):
            with self.subTest(path=path):
                _, cookie = self._request(
                    "POST",
                    "/api/auth/signup",
                    {
                        "email": f"expired-{index}@example.com",
                        "password": "correct-horse-42",
                        "captcha_token": "dev-captcha-ok",
                    },
                    include_cookie=True,
                )
                self._expire_all_sessions()

                with self.assertRaises(HTTPError) as expired:
                    self._request(method, path, payload, cookie=cookie)
                self.assertEqual(expired.exception.code, HTTPStatus.UNAUTHORIZED)
                self.assertIn("Max-Age=0", expired.exception.headers.get("Set-Cookie", ""))

    def test_team_isolation_and_scoped_settings_are_forbidden_for_non_member(self) -> None:
        _, owner_cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "owner@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
            },
            include_cookie=True,
        )
        team_payload, _ = self._request("POST", "/api/auth/team", {"name": "Private Operators"}, cookie=owner_cookie, include_cookie=True)
        team_id = team_payload["active_team"]["id"]

        _, outsider_cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "outsider@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
            },
            include_cookie=True,
        )
        with self.assertRaises(HTTPError) as dashboard_error:
            self._request("GET", f"/api/operator/dashboard?team_id={team_id}", cookie=outsider_cookie)
        self.assertEqual(dashboard_error.exception.code, HTTPStatus.FORBIDDEN)

        with self.assertRaises(HTTPError) as switch_error:
            self._request("POST", "/api/auth/switch-team", {"team_id": team_id}, cookie=outsider_cookie)
        self.assertEqual(switch_error.exception.code, HTTPStatus.FORBIDDEN)

        with self.assertRaises(HTTPError) as settings_error:
            self._request(
                "POST",
                "/api/operator/settings",
                {"team_id": team_id, "settings": {"default_evaluation_mode": "promptfoo"}, "reason": "verify team isolation"},
                cookie=outsider_cookie,
            )
        self.assertEqual(settings_error.exception.code, HTTPStatus.FORBIDDEN)

    def test_operator_settings_requires_reason_and_writes_shared_audit(self) -> None:
        payload, cookie = self._request(
            "POST",
            "/api/auth/signup",
            {
                "email": "settings@example.com",
                "password": "correct-horse-42",
                "captcha_token": "dev-captcha-ok",
            },
            include_cookie=True,
        )

        with self.assertRaises(HTTPError) as missing_reason:
            self._request(
                "POST",
                "/api/operator/settings",
                {"settings": {"default_evaluation_mode": "promptfoo"}},
                cookie=cookie,
            )
        self.assertEqual(missing_reason.exception.code, HTTPStatus.BAD_REQUEST)

        updated, _ = self._request(
            "POST",
            "/api/operator/settings",
            {
                "settings": {"default_evaluation_mode": "promptfoo"},
                "reason": "P6 parity test",
            },
            cookie=cookie,
            include_cookie=True,
        )
        scope = f"user:{payload['user']['id']}"
        self.assertEqual(updated["settings"]["default_evaluation_mode"], "promptfoo")
        self.assertEqual(updated["audit"]["scope"], scope)
        self.assertEqual(updated["audit"]["state_slice"], "mesh-settings-control")

        identity_path = Path(self.config.operator_identity_path)
        data = json.loads(identity_path.read_text(encoding="utf-8"))
        self.assertEqual(data["settings"][scope]["default_evaluation_mode"], "promptfoo")
        audit_path = identity_path.parent / "operator-config-audit.jsonl"
        audit_record = json.loads(audit_path.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(audit_record["operator_id"], "settings@example.com")
        self.assertEqual(audit_record["reason"], "P6 parity test")
        self.assertEqual(audit_record["fields"], ["default_evaluation_mode"])

    def test_oauth_start_urls_and_callback_failures_are_clear(self) -> None:
        self.server.config.google_oauth_client_id = "google-client"
        self.server.config.google_oauth_client_secret = "google-secret"
        self.server.config.google_oauth_redirect_url = "http://127.0.0.1:8787/api/auth/oauth/google/callback"
        self.server.config.github_oauth_client_id = "github-client"
        self.server.config.github_oauth_client_secret = "github-secret"
        self.server.config.github_oauth_redirect_url = "http://127.0.0.1:8787/api/auth/oauth/github/callback"

        google, _ = self._request("GET", "/api/auth/oauth/google/start", include_cookie=True)
        google_url = urlparse(google["authorize_url"])
        google_query = parse_qs(google_url.query)
        self.assertEqual(google_url.netloc, "accounts.google.com")
        self.assertEqual(google_query["client_id"], ["google-client"])
        self.assertEqual(google_query["redirect_uri"], ["http://127.0.0.1:8787/api/auth/oauth/google/callback"])
        self.assertTrue(google_query["state"][0])

        github, _ = self._request("GET", "/api/auth/oauth/github/start", include_cookie=True)
        github_url = urlparse(github["authorize_url"])
        github_query = parse_qs(github_url.query)
        self.assertEqual(github_url.netloc, "github.com")
        self.assertEqual(github_query["client_id"], ["github-client"])
        self.assertEqual(github_query["redirect_uri"], ["http://127.0.0.1:8787/api/auth/oauth/github/callback"])
        self.assertTrue(github_query["state"][0])

        with self.assertRaises(HTTPError) as missing_code:
            self._request_no_redirect("GET", "/api/auth/oauth/google/callback")
        self.assertEqual(missing_code.exception.code, HTTPStatus.FOUND)
        self.assertEqual(missing_code.exception.headers["Location"], "/?auth_error=missing_oauth_code")

    def test_oauth_start_routes_fail_closed_without_provider_config(self) -> None:
        for provider in ("google", "github"):
            with self.subTest(provider=provider):
                with self.assertRaises(HTTPError) as oauth_error:
                    self._request("GET", f"/api/auth/oauth/{provider}/start")

                self.assertEqual(oauth_error.exception.code, HTTPStatus.SERVICE_UNAVAILABLE)
                body = json.loads(oauth_error.exception.read().decode("utf-8"))
                self.assertEqual(body["error"], f"{provider} oauth is not configured")

    def test_captcha_missing_provider_secret_fails_closed(self) -> None:
        self.server.config.captcha_dev_bypass_enabled = False
        self.server.config.captcha_provider = "hcaptcha"
        self.server.config.captcha_site_key = "site-key"
        self.server.config.captcha_secret_key = ""

        with self.assertRaises(HTTPError) as signup_error:
            self._request(
                "POST",
                "/api/auth/signup",
                {
                    "email": "blocked@example.com",
                    "password": "correct-horse-42",
                    "captcha_token": "",
                },
            )
        self.assertEqual(signup_error.exception.code, HTTPStatus.BAD_REQUEST)

    def _expire_all_sessions(self) -> None:
        identity_path = Path(self.config.operator_identity_path)
        data = json.loads(identity_path.read_text(encoding="utf-8"))
        for record in data["sessions"].values():
            record["expires_at"] = "2000-01-01T00:00:00Z"
        identity_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        cookie: str = "",
        include_cookie: bool = False,
    ):
        body = json.dumps(payload or {}).encode("utf-8") if method != "GET" else None
        headers = {"Content-Type": "application/json"}
        if cookie:
            headers["Cookie"] = cookie
        req = Request(f"{self.base_url}{path}", data=body, method=method, headers=headers)
        with urlopen(req, timeout=10) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            if include_cookie:
                return parsed, response.headers.get("Set-Cookie", "")
            return parsed

    def _request_no_redirect(self, method: str, path: str, payload: dict | None = None):
        body = json.dumps(payload or {}).encode("utf-8") if method != "GET" else None
        req = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        opener = build_opener(_NoRedirectHandler)
        with opener.open(req, timeout=10) as response:
            return response


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


if __name__ == "__main__":
    unittest.main()
