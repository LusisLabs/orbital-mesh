#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.operator_auth_provider_smoke import (  # noqa: E402
    DEFAULT_IDENTITY,
    DEFAULT_LIVE_PROOF,
    FRONTEND_ENV,
    ROOT_ENV,
    validate_live_provider_proof,
)
from shared.mesh_runtime.operator_identity import build_auth_provider_evidence  # noqa: E402


BROWSER_JS = """
const { chromium } = require("@playwright/test");
const userDataDir = process.argv[1];
const url = process.argv[2];
const headless = process.env.MESH_AUTH_CAPTURE_HEADLESS === "1";

(async () => {
  const context = await chromium.launchPersistentContext(userDataDir, {
    headless,
    viewport: { width: 1280, height: 900 },
  });
  const page = context.pages()[0] || await context.newPage();
  await page.goto(url);
  console.log(JSON.stringify({ event: "clean_browser_started", url }));
  const close = async () => {
    await context.close();
    process.exit(0);
  };
  process.on("SIGTERM", close);
  process.on("SIGINT", close);
  await new Promise(() => {});
})().catch((error) => {
  console.error(error && error.message ? error.message : String(error));
  process.exit(1);
});
"""


class CleanBrowser:
    def __init__(self, product_url: str, *, headless: bool) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="mesh-auth-clean-browser-")
        self.process = subprocess.Popen(
            [
                "pnpm",
                "--dir",
                "meshapp/frontend",
                "exec",
                "node",
                "-e",
                BROWSER_JS,
                self.temp_dir.name,
                product_url,
            ],
            cwd=REPO_ROOT,
            env={**os.environ, "MESH_AUTH_CAPTURE_HEADLESS": "1" if headless else "0"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.temp_dir.cleanup()


def main(argv: list[str] | None = None) -> int:
    env = _read_env(ROOT_ENV)
    frontend_env = _read_env(FRONTEND_ENV)
    parser = argparse.ArgumentParser(
        description="Capture redacted live Google/GitHub/hCaptcha auth proof from a clean browser session.",
    )
    parser.add_argument("--identity-path", default=str(DEFAULT_IDENTITY))
    parser.add_argument("--proof-path", default=str(DEFAULT_LIVE_PROOF))
    parser.add_argument(
        "--product-url",
        default=os.environ.get("MESH_AUTH_PRODUCT_REDIRECT_URL")
        or env.get("MESH_AUTH_PRODUCT_REDIRECT_URL")
        or "http://127.0.0.1:3000",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("NEXT_PUBLIC_MESH_API_URL")
        or frontend_env.get("NEXT_PUBLIC_MESH_API_URL")
        or "http://127.0.0.1:8787",
    )
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--poll-interval", type=float, default=2.0)
    parser.add_argument("--started-at", default="")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--write-partial", action="store_true")
    args = parser.parse_args(argv)

    started_at = args.started_at or _timestamp()
    clean_browser_session = not args.no_browser
    browser: CleanBrowser | None = None
    if clean_browser_session:
        if not _trusted_local_url(args.product_url):
            print(json.dumps(_blocked("product_url_not_loopback", args.product_url), indent=2, sort_keys=True))
            return 2
        browser = CleanBrowser(args.product_url, headless=args.headless)

    print(
        json.dumps(
            {
                "schema_version": "mesh.operator_auth_live_capture_session.v1",
                "state_slice": "auth-provider-proof.v1",
                "started_at": started_at,
                "clean_browser_session": clean_browser_session,
                "product_url": args.product_url,
                "api_url": args.api_url,
                "proof_path": str(Path(args.proof_path)),
                "operator_steps": [
                    "Use the launched clean Playwright browser profile only.",
                    "Complete hCaptcha-backed email signup in the product shell.",
                    "Log out, then complete Google OAuth.",
                    "Log out, then complete GitHub OAuth.",
                    "Do not paste tokens, cookies, OAuth codes, captcha responses, or secrets into proof files.",
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    _warn_if_unreachable(f"{args.api_url.rstrip('/')}/api/auth/config")
    _warn_if_unreachable(args.product_url)

    try:
        proof = wait_for_live_proof(
            Path(args.identity_path),
            clean_browser_session=clean_browser_session,
            started_at=started_at,
            timeout_seconds=args.timeout_seconds,
            poll_interval=args.poll_interval,
        )
    finally:
        if browser is not None:
            browser.stop()

    status = validate_live_provider_proof(proof, proof_path=str(Path(args.proof_path)))
    if status["status"] == "complete" or args.write_partial:
        proof_path = Path(args.proof_path)
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"proof": proof, "validation": status}, indent=2, sort_keys=True))
    return 0 if status["status"] == "complete" else 2


def wait_for_live_proof(
    identity_path: Path,
    *,
    clean_browser_session: bool,
    started_at: str,
    timeout_seconds: float,
    poll_interval: float,
) -> dict[str, Any]:
    latest = build_live_provider_proof_from_identity(
        identity_path,
        clean_browser_session=clean_browser_session,
        started_at=started_at,
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        latest = build_live_provider_proof_from_identity(
            identity_path,
            clean_browser_session=clean_browser_session,
            started_at=started_at,
        )
        if validate_live_provider_proof(latest)["status"] == "complete":
            return latest
        time.sleep(max(0.2, poll_interval))
    return latest


def build_live_provider_proof_from_identity(
    identity_path: Path,
    *,
    clean_browser_session: bool,
    started_at: str = "",
) -> dict[str, Any]:
    payload = _read_json(identity_path)
    events = payload.get("auth_events") if isinstance(payload.get("auth_events"), list) else []
    filtered_events = _events_since(events, started_at)
    evidence = build_auth_provider_evidence({"auth_events": filtered_events})
    email_signup = evidence.get("email_signup") if isinstance(evidence.get("email_signup"), dict) else {}
    providers = evidence.get("providers") if isinstance(evidence.get("providers"), dict) else {}
    google = providers.get("google_oauth") if isinstance(providers.get("google_oauth"), dict) else {}
    github = providers.get("github_oauth") if isinstance(providers.get("github_oauth"), dict) else {}
    captcha = evidence.get("captcha") if isinstance(evidence.get("captcha"), dict) else {}
    return {
        "schema_version": "mesh.operator_auth_provider_live_proof.v1",
        "state_slice": "auth-provider-proof.v1",
        "clean_browser_session": bool(clean_browser_session),
        "raw_secret_material_present": False,
        "generated_at": _timestamp(),
        "started_at": started_at,
        "runtime_identity_path": str(identity_path),
        "email_signup": {
            "browser_completed": email_signup.get("status") == "complete",
            "session_established": email_signup.get("session_established") is True,
            "hcaptcha_verified": captcha.get("status") == "complete",
            "completed_at": str(email_signup.get("completed_at") or ""),
        },
        "providers": {
            "google_oauth": _provider_proof(google, "/api/auth/oauth/google/callback"),
            "github_oauth": _provider_proof(github, "/api/auth/oauth/github/callback"),
        },
        "captcha": {
            "provider": str(captcha.get("provider") or "hcaptcha"),
            "challenge_completed": captcha.get("challenge_completed") is True,
            "browser_token_verified": captcha.get("browser_token_verified") is True,
            "completed_at": str(captcha.get("completed_at") or ""),
        },
        "authority_boundary": (
            "This proof is derived from redacted Mesh auth_events in a clean browser capture session. "
            "It does not store OAuth codes, provider tokens, captcha tokens, cookies, passwords, or client secrets."
        ),
    }


def _provider_proof(provider_status: dict[str, Any], callback_path: str) -> dict[str, Any]:
    complete = provider_status.get("status") == "complete"
    return {
        "browser_completed": complete,
        "session_established": provider_status.get("session_established") is True,
        "callback_path": callback_path,
        "completed_at": str(provider_status.get("completed_at") or ""),
    }


def _events_since(events: list[Any], started_at: str) -> list[Any]:
    if not started_at:
        return events
    started_value = _parse_timestamp(started_at)
    if started_value is None:
        return events
    filtered = []
    for event in events:
        if not isinstance(event, dict):
            continue
        recorded_value = _parse_timestamp(str(event.get("recorded_at") or ""))
        if recorded_value is not None and recorded_value >= started_value:
            filtered.append(event)
    return filtered


def _parse_timestamp(value: str) -> float | None:
    if not value:
        return None
    try:
        return time.mktime(time.strptime(value.replace("+00:00", "Z"), "%Y-%m-%dT%H:%M:%SZ"))
    except ValueError:
        return None


def _warn_if_unreachable(url: str) -> None:
    try:
        with urlopen(url, timeout=2) as response:
            if response.status < 500:
                return
    except (OSError, TimeoutError, URLError):
        pass
    print(
        json.dumps(
            {
                "state_slice": "auth-provider-proof.v1",
                "warning": "local_url_unreachable",
                "url": url,
            },
            sort_keys=True,
        )
    )


def _trusted_local_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and not parsed.username
        and not parsed.password
    )


def _blocked(blocker: str, value: str) -> dict[str, Any]:
    return {
        "schema_version": "mesh.operator_auth_live_capture_session.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": "blocked",
        "blocker": blocker,
        "value": value,
    }


def _read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
