#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import threading
import subprocess
import sys
import tempfile
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.operator_auth_provider_smoke import (  # noqa: E402
    DEFAULT_ARTIFACT,
    DEFAULT_IDENTITY,
    DEFAULT_LIVE_PROOF,
    FRONTEND_ENV,
    LOCAL_CALLBACKS,
    ROOT_ENV,
    validate_live_provider_proof,
)
from shared.mesh_runtime.operator_identity import build_auth_provider_evidence  # noqa: E402


DEFAULT_PREFLIGHT = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "live-preflight.json"
DEFAULT_STACK_SMOKE = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "live-stack-smoke.json"
DEFAULT_CHECKPOINT = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "checkpoint.json"
DEFAULT_ATTEMPT = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "live-capture-attempt.json"
NEXT_GENERATED_CONFIGS = [
    REPO_ROOT / "meshapp" / "frontend" / "next-env.d.ts",
    REPO_ROOT / "meshapp" / "frontend" / "tsconfig.json",
]
STACK_MODE_MANAGED = "managed_local_stack"
STACK_MODE_REUSED = "reused_local_stack"
STACK_MODE_UNMANAGED = "unmanaged"

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


class ManagedProcess:
    def __init__(self, name: str, cmd: list[str], env: dict[str, str], redactions: list[str]) -> None:
        self.name = name
        self.lines: deque[str] = deque(maxlen=180)
        self.redactions = redactions
        self.process = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_output, name=f"{name}-output", daemon=True)
        self._reader.start()

    def _read_output(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.append(line.rstrip("\n"))

    def output(self) -> str:
        return redact_known_values("\n".join(self.lines), self.redactions)

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)


class LocalStack:
    def __init__(
        self,
        api: ManagedProcess | None,
        web: ManagedProcess | None,
        *,
        api_url: str,
        product_url: str,
        next_dist_dir: str,
        file_snapshots: dict[Path, str | None],
        stack_mode: str,
        managed_processes_owned: bool,
    ) -> None:
        self.api = api
        self.web = web
        self.api_url = api_url
        self.product_url = product_url
        self.next_dist_dir = next_dist_dir
        self.file_snapshots = file_snapshots
        self.stack_mode = stack_mode
        self.managed_processes_owned = managed_processes_owned

    def stop(self) -> None:
        if self.web is not None:
            self.web.stop()
        if self.api is not None:
            self.api.stop()
        if self.next_dist_dir:
            shutil.rmtree(REPO_ROOT / "meshapp" / "frontend" / self.next_dist_dir, ignore_errors=True)
        restore_file_texts(self.file_snapshots)


def main(argv: list[str] | None = None) -> int:
    env = _read_env(ROOT_ENV)
    frontend_env = _read_env(FRONTEND_ENV)
    parser = argparse.ArgumentParser(
        description="Capture redacted live Google/GitHub/hCaptcha auth proof from a clean browser session.",
    )
    parser.add_argument("--identity-path", default=str(DEFAULT_IDENTITY))
    parser.add_argument("--proof-path", default=str(DEFAULT_LIVE_PROOF))
    parser.add_argument("--preflight-path", default=str(DEFAULT_PREFLIGHT))
    parser.add_argument("--stack-smoke-path", default=str(DEFAULT_STACK_SMOKE))
    parser.add_argument("--checkpoint-path", default=str(DEFAULT_CHECKPOINT))
    parser.add_argument("--attempt-path", default=str(DEFAULT_ATTEMPT))
    parser.add_argument("--readiness-path", default=str(DEFAULT_ARTIFACT))
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
    parser.add_argument("--manage-local-stack", action="store_true")
    parser.add_argument("--reuse-local-stack", action="store_true")
    parser.add_argument("--allow-blocked-attempt", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--stack-smoke-only", action="store_true")
    parser.add_argument("--checkpoint-only", action="store_true")
    parser.add_argument("--stack-ready-timeout", type=float, default=45.0)
    args = parser.parse_args(argv)
    if args.manage_local_stack and args.reuse_local_stack:
        parser.error("--manage-local-stack and --reuse-local-stack are mutually exclusive")

    started_at = args.started_at or _timestamp()
    clean_browser_session = not args.no_browser
    browser: CleanBrowser | None = None
    stack: LocalStack | None = None
    api_url = args.api_url.rstrip("/")
    product_url = args.product_url.rstrip("/")
    stack_mode = _requested_stack_mode(
        manage_local_stack=args.manage_local_stack,
        reuse_local_stack=args.reuse_local_stack,
        stack_smoke_only=args.stack_smoke_only,
    )
    preflight = build_live_capture_preflight(
        root_env=env,
        frontend_env=frontend_env,
        api_url=api_url,
        product_url=product_url,
        identity_path=Path(args.identity_path),
        managed_local_stack=stack_mode == STACK_MODE_MANAGED,
        stack_mode=stack_mode,
    )
    if args.preflight_only:
        preflight_path = Path(args.preflight_path)
        preflight_path.parent.mkdir(parents=True, exist_ok=True)
        preflight_path.write_text(json.dumps(preflight, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(preflight, indent=2, sort_keys=True), flush=True)
        return 0 if not preflight["blockers"] else 2
    if args.checkpoint_only:
        checkpoint = build_auth_checkpoint(
            readiness_path=Path(args.readiness_path),
            preflight_path=Path(args.preflight_path),
            stack_smoke_path=Path(args.stack_smoke_path),
            attempt_path=Path(args.attempt_path),
            live_proof_path=Path(args.proof_path),
        )
        checkpoint_path = Path(args.checkpoint_path)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(checkpoint, indent=2, sort_keys=True), flush=True)
        return 0 if checkpoint["status"] in {"complete", "blocked_external_provider_proof"} else 2
    if preflight["blockers"]:
        print(json.dumps(preflight, indent=2, sort_keys=True), flush=True)
        return 2
    if args.stack_smoke_only:
        stack_smoke_path = Path(args.stack_smoke_path)
        try:
            stack = prepare_local_stack(
                root_env=env,
                frontend_env=frontend_env,
                api_url=api_url,
                product_url=product_url,
                identity_path=Path(args.identity_path),
                ready_timeout=args.stack_ready_timeout,
                stack_mode=stack_mode,
            )
            stack_smoke = build_live_stack_smoke(preflight=preflight, stack=stack, started_at=started_at)
            stack_smoke_path.parent.mkdir(parents=True, exist_ok=True)
            stack_smoke_path.write_text(json.dumps(stack_smoke, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(stack_smoke, indent=2, sort_keys=True), flush=True)
            return 0
        except RuntimeError as exc:
            stack_smoke = build_live_stack_smoke_blocked(
                preflight=preflight,
                api_url=api_url,
                product_url=product_url,
                started_at=started_at,
                stack_mode=stack_mode,
                blocker="local_stack_unavailable",
                detail=str(exc),
            )
            stack_smoke_path.parent.mkdir(parents=True, exist_ok=True)
            stack_smoke_path.write_text(json.dumps(stack_smoke, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(stack_smoke, indent=2, sort_keys=True), flush=True)
            return 2
        finally:
            if stack is not None:
                stack.stop()
    if stack_mode in {STACK_MODE_MANAGED, STACK_MODE_REUSED}:
        try:
            stack = prepare_local_stack(
                root_env=env,
                frontend_env=frontend_env,
                api_url=api_url,
                product_url=product_url,
                identity_path=Path(args.identity_path),
                ready_timeout=args.stack_ready_timeout,
                stack_mode=stack_mode,
            )
            api_url = stack.api_url
            product_url = stack.product_url
        except RuntimeError as exc:
            print(json.dumps(_blocked("local_stack_unavailable", str(exc)), indent=2, sort_keys=True), flush=True)
            return 2
    if clean_browser_session:
        if not _trusted_local_url(product_url):
            print(json.dumps(_blocked("product_url_not_loopback", product_url), indent=2, sort_keys=True), flush=True)
            if stack is not None:
                stack.stop()
            return 2
        browser = CleanBrowser(product_url, headless=args.headless)

    print(
        json.dumps(
            {
                "schema_version": "mesh.operator_auth_live_capture_session.v1",
                "state_slice": "auth-provider-proof.v1",
                "started_at": started_at,
                "clean_browser_session": clean_browser_session,
                "managed_local_stack": stack_mode == STACK_MODE_MANAGED,
                "stack_mode": stack_mode,
                "managed_processes_owned": bool(stack and stack.managed_processes_owned),
                "product_url": product_url,
                "api_url": api_url,
                "proof_path": str(Path(args.proof_path)),
                "preflight": preflight,
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
        ),
        flush=True,
    )
    _warn_if_unreachable(f"{api_url}/api/auth/config")
    _warn_if_unreachable(product_url)

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
        if stack is not None:
            stack.stop()

    status = validate_live_provider_proof(proof, proof_path=str(Path(args.proof_path)))
    if status["status"] == "complete" or args.write_partial:
        proof_path = Path(args.proof_path)
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        proof_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    attempt = build_live_capture_attempt(
        preflight=preflight,
        proof=proof,
        validation=status,
        started_at=started_at,
        api_url=api_url,
        product_url=product_url,
        clean_browser_session=clean_browser_session,
        managed_local_stack=stack_mode == STACK_MODE_MANAGED,
        stack_mode=stack_mode,
        managed_processes_owned=bool(stack and stack.managed_processes_owned),
    )
    attempt_path = Path(args.attempt_path)
    attempt_path.parent.mkdir(parents=True, exist_ok=True)
    attempt_path.write_text(json.dumps(attempt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"proof": proof, "validation": status, "attempt_path": str(attempt_path)}, indent=2, sort_keys=True), flush=True)
    return live_capture_exit_code(attempt=attempt, allow_blocked_attempt=args.allow_blocked_attempt)


def live_capture_exit_code(*, attempt: dict[str, Any], allow_blocked_attempt: bool) -> int:
    if attempt.get("status") == "complete":
        return 0
    if not allow_blocked_attempt:
        return 2
    if attempt.get("status") != "blocked":
        return 2
    if attempt.get("preflight_status") != "ready":
        return 2
    if attempt.get("clean_browser_session") is not True:
        return 2
    if attempt.get("raw_secret_material_present") is not False:
        return 2
    return 0


def build_live_capture_attempt(
    *,
    preflight: dict[str, Any],
    proof: dict[str, Any],
    validation: dict[str, Any],
    started_at: str,
    api_url: str,
    product_url: str,
    clean_browser_session: bool,
    managed_local_stack: bool,
    stack_mode: str,
    managed_processes_owned: bool,
) -> dict[str, Any]:
    return {
        "schema_version": "mesh.operator_auth_live_capture_attempt.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": "complete" if validation.get("status") == "complete" else "blocked",
        "blockers": [str(item) for item in validation.get("missing_or_blocked", [])]
        if isinstance(validation.get("missing_or_blocked"), list)
        else [],
        "started_at": started_at,
        "generated_at": _timestamp(),
        "api_url": api_url,
        "product_url": product_url,
        "clean_browser_session": bool(clean_browser_session),
        "managed_local_stack": bool(managed_local_stack),
        "stack_mode": stack_mode,
        "managed_processes_owned": bool(managed_processes_owned),
        "preflight_status": preflight.get("status"),
        "live_provider_validation_status": validation.get("status"),
        "browser_completion_status": validation.get("browser_completion_status"),
        "runtime_identity_path": proof.get("runtime_identity_path"),
        "raw_secret_material_present": bool(
            proof.get("raw_secret_material_present") is True
            or validation.get("raw_secret_material_present") is True
        ),
        "providers": validation.get("providers") if isinstance(validation.get("providers"), dict) else {},
        "email_signup": validation.get("email_signup") if isinstance(validation.get("email_signup"), dict) else {},
        "captcha": validation.get("captcha") if isinstance(validation.get("captcha"), dict) else {},
        "authority_boundary": (
            "This artifact records a redacted clean-browser live capture attempt and its missing proof components. "
            "It does not store OAuth codes, provider tokens, captcha tokens, cookies, passwords, or client secrets."
        ),
    }


def build_auth_checkpoint(
    *,
    readiness_path: Path,
    preflight_path: Path,
    stack_smoke_path: Path,
    attempt_path: Path,
    live_proof_path: Path,
) -> dict[str, Any]:
    readiness = _read_json(readiness_path)
    preflight = _read_json(preflight_path)
    stack_smoke = _read_json(stack_smoke_path)
    attempt = _read_json(attempt_path)
    live_proof_status = _checkpoint_live_provider_status(live_proof_path)
    local_checks = [
        ("provider readiness artifact exists", readiness_path.exists()),
        ("provider readiness schema is mesh.operator_auth_provider_readiness.v1", readiness.get("schema_version") == "mesh.operator_auth_provider_readiness.v1"),
        ("provider readiness state slice is auth-provider-proof.v1", readiness.get("state_slice") == "auth-provider-proof.v1"),
        ("provider readiness contains no raw secret material", readiness.get("raw_secret_material_present") is False),
        ("provider env files are untracked", readiness.get("tracked_env_secret_material_present") is False),
        ("tracked secret hits are empty", readiness.get("tracked_secret_hits") == []),
        ("provider readiness Google callback matches", _readiness_provider_callback_ok(readiness, "google")),
        ("provider readiness GitHub callback matches", _readiness_provider_callback_ok(readiness, "github")),
        ("provider readiness hCaptcha env is ready", readiness.get("captcha", {}).get("hcaptcha_env_ready") is True),
        ("live preflight artifact exists", preflight_path.exists()),
        ("live preflight schema is mesh.operator_auth_live_capture_preflight.v1", preflight.get("schema_version") == "mesh.operator_auth_live_capture_preflight.v1"),
        ("live preflight state slice is auth-provider-proof.v1", preflight.get("state_slice") == "auth-provider-proof.v1"),
        ("live preflight is ready", preflight.get("status") == "ready"),
        ("live preflight has no blockers", preflight.get("blockers") == []),
        ("live preflight contains no raw secret material", preflight.get("raw_secret_material_present") is False),
        ("live preflight Google callback exactly matches", _preflight_provider_exact(preflight, "google")),
        ("live preflight GitHub callback exactly matches", _preflight_provider_exact(preflight, "github")),
        ("live preflight product redirect matches", _preflight_product_redirect_exact(preflight)),
        ("live preflight hCaptcha env is ready", preflight.get("captcha", {}).get("hcaptcha_env_ready") is True),
        ("live preflight identity path matches default", preflight.get("identity_path_matches_default") is True),
        ("live stack smoke artifact exists", stack_smoke_path.exists()),
        ("live stack smoke schema is mesh.operator_auth_live_stack_smoke.v1", stack_smoke.get("schema_version") == "mesh.operator_auth_live_stack_smoke.v1"),
        ("live stack smoke state slice is auth-provider-proof.v1", stack_smoke.get("state_slice") == "auth-provider-proof.v1"),
        ("live stack smoke is ready", stack_smoke.get("status") == "ready"),
        ("live stack smoke has no blockers", stack_smoke.get("blockers") == []),
        ("live stack smoke preflight was ready", stack_smoke.get("preflight_status") == "ready"),
        ("live stack smoke API auth config reachable", _stack_smoke_ready(stack_smoke, "api_auth_config")),
        ("live stack smoke product shell reachable", _stack_smoke_ready(stack_smoke, "product_shell")),
        ("live stack smoke contains no raw secret material", stack_smoke.get("raw_secret_material_present") is False),
        ("live stack smoke identity path matches default", stack_smoke.get("identity_path_matches_default") is True),
        ("live stack smoke stack provenance is explicit", _stack_provenance_ok(stack_smoke)),
        ("live capture attempt artifact exists", attempt_path.exists()),
        ("live capture attempt schema is mesh.operator_auth_live_capture_attempt.v1", attempt.get("schema_version") == "mesh.operator_auth_live_capture_attempt.v1"),
        ("live capture attempt state slice is auth-provider-proof.v1", attempt.get("state_slice") == "auth-provider-proof.v1"),
        ("live capture attempt used a clean browser", attempt.get("clean_browser_session") is True),
        ("live capture attempt preflight was ready", attempt.get("preflight_status") == "ready"),
        ("live capture attempt contains no raw secret material", attempt.get("raw_secret_material_present") is False),
        ("live capture attempt stack provenance is explicit", _stack_provenance_ok(attempt)),
    ]
    missing = [label for label, passed in local_checks if not passed]
    live_complete = readiness.get("status") == "provider_browser_proof_complete" and live_proof_status.get("status") == "complete"
    if missing:
        status = "blocked_local_evidence"
        blockers = missing
        local_evidence_status = "blocked"
    elif live_complete:
        status = "complete"
        blockers = []
        local_evidence_status = "complete"
    else:
        status = "blocked_external_provider_proof"
        blockers = _checkpoint_external_blockers(readiness, live_proof_status)
        local_evidence_status = "complete"
    return {
        "schema_version": "mesh.operator_auth_checkpoint.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": status,
        "generated_at": _timestamp(),
        "local_evidence_status": local_evidence_status,
        "blockers": blockers,
        "missing_local_evidence": missing,
        "readiness_status": str(readiness.get("status") or "missing"),
        "live_preflight_status": str(preflight.get("status") or "missing"),
        "live_stack_smoke_status": str(stack_smoke.get("status") or "missing"),
        "live_stack_smoke_stack_mode": str(stack_smoke.get("stack_mode") or "missing"),
        "live_capture_attempt_status": str(attempt.get("status") or "missing"),
        "live_capture_attempt_stack_mode": str(attempt.get("stack_mode") or "missing"),
        "live_capture_attempt_blockers": _string_list(attempt.get("blockers")),
        "live_provider_status": str(live_proof_status.get("status") or "missing"),
        "live_provider_blocker": str(live_proof_status.get("blocker") or ""),
        "evidence": {
            "provider_readiness": str(readiness_path),
            "live_preflight": str(preflight_path),
            "live_stack_smoke": str(stack_smoke_path),
            "live_capture_attempt": str(attempt_path),
            "live_provider_proof": str(live_proof_path),
        },
        "next_required_command": _checkpoint_next_required_command(stack_smoke),
        "final_verification_command": "pnpm run test:auth-provider:live",
        "raw_secret_material_present": False,
        "authority_boundary": (
            "This checkpoint binds local auth-provider readiness, live preflight, explicit local stack smoke evidence, and the latest clean-browser capture attempt. "
            "It does not complete P0 until the redacted clean-browser live provider proof and matching runtime auth evidence are present."
        ),
    }


def _checkpoint_live_provider_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "blocked", "blocker": "live_provider_proof_missing"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "blocked", "blocker": "live_provider_proof_unreadable"}
    status = validate_live_provider_proof(payload, proof_path=str(path))
    if status["status"] == "complete":
        return {"status": "complete", "blocker": ""}
    blocker = status.get("blocker") or "provider_console_and_browser_completion_unverified"
    return {"status": "blocked", "blocker": str(blocker)}


def _checkpoint_next_required_command(stack_smoke: dict[str, Any]) -> str:
    if stack_smoke.get("stack_mode") == STACK_MODE_REUSED:
        return "pnpm run auth-provider:reuse-stack"
    return "pnpm run auth-provider:live-stack"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _checkpoint_external_blockers(readiness: dict[str, Any], live_proof_status: dict[str, Any]) -> list[str]:
    blockers = readiness.get("blockers")
    if isinstance(blockers, list):
        external = [
            str(item)
            for item in blockers
            if str(item) in {"live_provider_proof_missing", "provider_console_and_browser_completion_unverified"}
        ]
        if external:
            return external
    blocker = live_proof_status.get("blocker")
    if blocker:
        return [str(blocker)]
    return ["provider_console_and_browser_completion_unverified"]


def _readiness_provider_callback_ok(readiness: dict[str, Any], provider: str) -> bool:
    oauth = readiness.get("oauth")
    if not isinstance(oauth, dict):
        return False
    status = oauth.get(provider)
    return isinstance(status, dict) and status.get("local_callback_match") is True


def _preflight_provider_exact(preflight: dict[str, Any], provider: str) -> bool:
    oauth = preflight.get("oauth")
    if not isinstance(oauth, dict):
        return False
    status = oauth.get(provider)
    return isinstance(status, dict) and status.get("exact_match") is True


def _preflight_product_redirect_exact(preflight: dict[str, Any]) -> bool:
    product_redirect = preflight.get("product_redirect")
    return isinstance(product_redirect, dict) and product_redirect.get("exact_match") is True


def _stack_smoke_ready(stack_smoke: dict[str, Any], key: str) -> bool:
    readiness = stack_smoke.get("readiness")
    return isinstance(readiness, dict) and readiness.get(key) == "reachable"


def _stack_provenance_ok(payload: dict[str, Any]) -> bool:
    stack_mode = payload.get("stack_mode")
    managed_processes_owned = payload.get("managed_processes_owned")
    if stack_mode == STACK_MODE_MANAGED:
        return managed_processes_owned is True
    if stack_mode == STACK_MODE_REUSED:
        return managed_processes_owned is False
    return False


def build_live_stack_smoke(*, preflight: dict[str, Any], stack: LocalStack, started_at: str) -> dict[str, Any]:
    return {
        "schema_version": "mesh.operator_auth_live_stack_smoke.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": "ready",
        "blockers": [],
        "started_at": started_at,
        "generated_at": _timestamp(),
        "api_url": stack.api_url,
        "product_url": stack.product_url,
        "stack_mode": stack.stack_mode,
        "managed_processes_owned": stack.managed_processes_owned,
        "preflight_status": preflight.get("status"),
        "identity_path": preflight.get("identity_path"),
        "identity_path_matches_default": preflight.get("identity_path_matches_default") is True,
        "readiness": {
            "api_auth_config": "reachable",
            "product_shell": "reachable",
        },
        "raw_secret_material_present": False,
        "authority_boundary": (
            "Stack smoke proves the local Mesh API and product shell boot with ignored provider env. "
            "It does not prove external OAuth or hCaptcha browser completion and stores no tokens, cookies, captcha responses, or secrets."
        ),
    }


def build_live_stack_smoke_blocked(
    *,
    preflight: dict[str, Any],
    api_url: str,
    product_url: str,
    started_at: str,
    stack_mode: str,
    blocker: str,
    detail: str,
) -> dict[str, Any]:
    return {
        "schema_version": "mesh.operator_auth_live_stack_smoke.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": "blocked",
        "blockers": [blocker],
        "started_at": started_at,
        "generated_at": _timestamp(),
        "api_url": api_url,
        "product_url": product_url,
        "stack_mode": stack_mode,
        "managed_processes_owned": False,
        "preflight_status": preflight.get("status"),
        "identity_path": preflight.get("identity_path"),
        "identity_path_matches_default": preflight.get("identity_path_matches_default") is True,
        "readiness": {
            "api_auth_config": "blocked",
            "product_shell": "blocked",
        },
        "detail": detail,
        "raw_secret_material_present": False,
        "authority_boundary": (
            "Stack smoke failure reports only redacted local process readiness. "
            "It does not store OAuth secrets, provider tokens, browser cookies, captcha responses, or captcha secrets."
        ),
    }


def start_local_stack(
    *,
    root_env: dict[str, str],
    frontend_env: dict[str, str],
    api_url: str,
    product_url: str,
    identity_path: Path,
    ready_timeout: float,
) -> LocalStack:
    if not _trusted_local_url(api_url):
        raise RuntimeError("api_url must be loopback for local provider capture")
    if not _trusted_local_url(product_url):
        raise RuntimeError("product_url must be loopback for local provider capture")
    api_host, api_port = _host_port(api_url)
    product_host, product_port = _host_port(product_url)
    _assert_stack_ports_available(
        [
            ("api", api_host, api_port),
            ("product", product_host, product_port),
        ]
    )
    next_dist_dir = f".next-auth-live-{product_port}"
    stack_env = build_local_stack_env(
        root_env,
        frontend_env,
        api_url=api_url,
        product_url=product_url,
        identity_path=identity_path,
        next_dist_dir=next_dist_dir,
    )
    redactions = _redaction_values(root_env, frontend_env)
    file_snapshots = snapshot_file_texts(NEXT_GENERATED_CONFIGS)
    api = ManagedProcess("api", [sys.executable, "run_server.py"], stack_env, redactions)
    web = ManagedProcess(
        "next",
        [
            "pnpm",
            "--dir",
            "meshapp/frontend",
            "exec",
            "next",
            "dev",
            "--hostname",
            product_host,
            "--port",
            str(product_port),
        ],
        stack_env,
        redactions,
    )
    stack = LocalStack(
        api,
        web,
        api_url=api_url,
        product_url=product_url,
        next_dist_dir=next_dist_dir,
        file_snapshots=file_snapshots,
        stack_mode=STACK_MODE_MANAGED,
        managed_processes_owned=True,
    )
    try:
        _wait_for_http(f"{api_url}/api/auth/config", api, timeout=ready_timeout)
        _wait_for_http(product_url, web, timeout=ready_timeout)
    except RuntimeError as exc:
        output = {
            "error": str(exc),
            "api_output": api.output(),
            "web_output": web.output(),
        }
        stack.stop()
        raise RuntimeError(json.dumps(output, sort_keys=True)) from exc
    return stack


def reuse_local_stack(*, api_url: str, product_url: str, ready_timeout: float) -> LocalStack:
    if not _trusted_local_url(api_url):
        raise RuntimeError("api_url must be loopback for reused local provider capture")
    if not _trusted_local_url(product_url):
        raise RuntimeError("product_url must be loopback for reused local provider capture")
    _wait_for_reused_http(f"{api_url}/api/auth/config", "api", timeout=ready_timeout)
    _wait_for_reused_http(product_url, "product", timeout=ready_timeout)
    return LocalStack(
        None,
        None,
        api_url=api_url,
        product_url=product_url,
        next_dist_dir="",
        file_snapshots={},
        stack_mode=STACK_MODE_REUSED,
        managed_processes_owned=False,
    )


def build_live_capture_preflight(
    *,
    root_env: dict[str, str],
    frontend_env: dict[str, str],
    api_url: str,
    product_url: str,
    identity_path: Path,
    managed_local_stack: bool,
    stack_mode: str,
) -> dict[str, Any]:
    blockers: list[str] = []
    api_trusted = _trusted_local_url(api_url)
    product_trusted = _trusted_local_url(product_url)
    identity_path_matches_default = identity_path.expanduser().resolve() == DEFAULT_IDENTITY.resolve()
    if not api_trusted:
        blockers.append("api_url_not_loopback")
    if not product_trusted:
        blockers.append("product_url_not_loopback")
    oauth = {
        "google": _oauth_redirect_preflight(root_env.get("MESH_GOOGLE_OAUTH_REDIRECT_URL", ""), api_url, LOCAL_CALLBACKS["google"]),
        "github": _oauth_redirect_preflight(root_env.get("MESH_GITHUB_OAUTH_REDIRECT_URL", ""), api_url, LOCAL_CALLBACKS["github"]),
    }
    for provider, status in oauth.items():
        if not status["exact_match"]:
            blockers.append(f"{provider}_oauth_redirect_url_mismatch")
    product_redirect = root_env.get("MESH_AUTH_PRODUCT_REDIRECT_URL", "")
    product_redirect_match = product_redirect.rstrip("/") == product_url.rstrip("/")
    if not product_redirect:
        blockers.append("auth_product_redirect_url_missing")
    elif not product_redirect_match:
        blockers.append("auth_product_redirect_url_mismatch")
    if not identity_path_matches_default:
        blockers.append("auth_identity_path_not_default")
    captcha_provider = root_env.get("MESH_CAPTCHA_PROVIDER", "")
    hcaptcha_ready = (
        captcha_provider == "hcaptcha"
        and bool(root_env.get("MESH_CAPTCHA_SITE_KEY"))
        and bool(root_env.get("MESH_CAPTCHA_SECRET_KEY"))
    )
    if not hcaptcha_ready:
        blockers.append("hcaptcha_env_incomplete")
    return {
        "schema_version": "mesh.operator_auth_live_capture_preflight.v1",
        "state_slice": "auth-provider-proof.v1",
        "status": "ready" if not blockers else "blocked",
        "blockers": blockers,
        "managed_local_stack": managed_local_stack,
        "stack_mode": stack_mode,
        "api_url": api_url,
        "product_url": product_url,
        "frontend_api_url_present": bool(frontend_env.get("NEXT_PUBLIC_MESH_API_URL")),
        "identity_path": str(identity_path),
        "identity_path_matches_default": identity_path_matches_default,
        "oauth": oauth,
        "product_redirect": {
            "configured": bool(product_redirect),
            "exact_match": product_redirect_match,
            "expected": product_url,
        },
        "captcha": {
            "provider": captcha_provider or "missing",
            "hcaptcha_env_ready": hcaptcha_ready,
        },
        "raw_secret_material_present": False,
        "authority_boundary": (
            "Preflight reports only local readiness and redirect URL shape. It does not read or emit OAuth secrets, "
            "captcha secrets, provider tokens, browser cookies, or captcha responses."
        ),
    }


def _oauth_redirect_preflight(configured_url: str, api_url: str, expected_path: str) -> dict[str, Any]:
    expected = f"{api_url.rstrip('/')}{expected_path}"
    parsed = urlparse(configured_url)
    return {
        "configured": bool(configured_url),
        "scheme": parsed.scheme or "",
        "host": parsed.hostname or "",
        "path": parsed.path,
        "expected": expected,
        "exact_match": configured_url.rstrip("/") == expected,
    }


def build_local_stack_env(
    root_env: dict[str, str],
    frontend_env: dict[str, str],
    *,
    api_url: str,
    product_url: str,
    identity_path: Path,
    next_dist_dir: str,
) -> dict[str, str]:
    api_host, api_port = _host_port(api_url)
    stack_env = os.environ.copy()
    stack_env.update(root_env)
    stack_env.update(frontend_env)
    stack_env.update(
        {
            "MESH_AUTH_MODE": stack_env.get("MESH_AUTH_MODE") or "app_session",
            "MESH_SERVER_HOST": api_host,
            "MESH_SERVER_PORT": str(api_port),
            "MESH_OPERATOR_IDENTITY_PATH": str(identity_path),
            "NEXT_PUBLIC_MESH_API_URL": api_url,
            "MESH_AUTH_PRODUCT_REDIRECT_URL": product_url,
            "MESH_AUTH_ALLOWED_ORIGINS": _merge_origins(stack_env.get("MESH_AUTH_ALLOWED_ORIGINS", ""), _origin(product_url)),
            "MESH_NEXT_DIST_DIR": next_dist_dir,
        }
    )
    return stack_env


def _requested_stack_mode(*, manage_local_stack: bool, reuse_local_stack: bool, stack_smoke_only: bool) -> str:
    if reuse_local_stack:
        return STACK_MODE_REUSED
    if manage_local_stack or stack_smoke_only:
        return STACK_MODE_MANAGED
    return STACK_MODE_UNMANAGED


def prepare_local_stack(
    *,
    root_env: dict[str, str],
    frontend_env: dict[str, str],
    api_url: str,
    product_url: str,
    identity_path: Path,
    ready_timeout: float,
    stack_mode: str,
) -> LocalStack:
    if stack_mode == STACK_MODE_MANAGED:
        return start_local_stack(
            root_env=root_env,
            frontend_env=frontend_env,
            api_url=api_url,
            product_url=product_url,
            identity_path=identity_path,
            ready_timeout=ready_timeout,
        )
    if stack_mode == STACK_MODE_REUSED:
        return reuse_local_stack(api_url=api_url, product_url=product_url, ready_timeout=ready_timeout)
    raise RuntimeError(f"unsupported local stack mode: {stack_mode}")


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


def _wait_for_http(url: str, process: ManagedProcess, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise RuntimeError(f"{process.name} exited early with {process.process.returncode}")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (OSError, TimeoutError, URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"{process.name} did not become ready at {url}: {last_error}")


def _wait_for_reused_http(url: str, label: str, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (OSError, TimeoutError, URLError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"reused {label} stack did not become ready at {url}: {last_error}")


def _assert_stack_ports_available(endpoints: list[tuple[str, str, int]]) -> None:
    seen: set[tuple[str, int]] = set()
    occupied: list[str] = []
    for label, host, port in endpoints:
        key = (host, port)
        if key in seen:
            continue
        seen.add(key)
        if _port_accepts_connection(host, port):
            occupied.append(f"{label} {host}:{port}")
    if occupied:
        joined = ", ".join(occupied)
        raise RuntimeError(f"local stack ports already in use: {joined}; rerun with --reuse-local-stack to bind explicit reused-stack provenance")


def _port_accepts_connection(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _host_port(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise RuntimeError("url host is required")
    if not parsed.port:
        raise RuntimeError("url port is required")
    return parsed.hostname, parsed.port


def snapshot_file_texts(paths: list[Path]) -> dict[Path, str | None]:
    snapshots: dict[Path, str | None] = {}
    for path in paths:
        try:
            snapshots[path] = path.read_text(encoding="utf-8")
        except OSError:
            snapshots[path] = None
    return snapshots


def restore_file_texts(snapshots: dict[Path, str | None]) -> None:
    for path, text in snapshots.items():
        if text is None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            continue
        path.write_text(text, encoding="utf-8")


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def _merge_origins(raw: str, origin: str) -> str:
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    if origin and origin not in origins:
        origins.append(origin)
    return ",".join(origins)


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


def redact_known_values(text: str, values: list[str]) -> str:
    redacted = text
    for value in values:
        if len(value) >= 8:
            redacted = redacted.replace(value, "[redacted]")
    return redacted


def _redaction_values(*envs: dict[str, str]) -> list[str]:
    values: list[str] = []
    for env in envs:
        for key, value in env.items():
            lowered = key.lower()
            if any(marker in lowered for marker in ("secret", "token", "password", "client_id", "site_key", "api_key")):
                values.append(value)
    return values


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
