#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.mesh_runtime.operator_identity import build_auth_provider_evidence  # noqa: E402

ROOT_ENV = REPO_ROOT / ".env.local"
FRONTEND_ENV = REPO_ROOT / "meshapp" / "frontend" / ".env.local"
DEFAULT_ARTIFACT = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "latest.json"
DEFAULT_LIVE_PROOF = REPO_ROOT / ".mesh-runtime-state" / "operator-auth-proof" / "live-provider-proof.json"
DEFAULT_IDENTITY = REPO_ROOT / ".mesh-runtime-state" / "operator-identity.json"

REQUIRED_ROOT_KEYS = [
    "MESH_AUTH_MODE",
    "MESH_CAPTCHA_PROVIDER",
    "MESH_CAPTCHA_SITE_KEY",
    "MESH_CAPTCHA_SECRET_KEY",
    "MESH_GOOGLE_OAUTH_CLIENT_ID",
    "MESH_GOOGLE_OAUTH_CLIENT_SECRET",
    "MESH_GOOGLE_OAUTH_REDIRECT_URL",
    "MESH_GITHUB_OAUTH_CLIENT_ID",
    "MESH_GITHUB_OAUTH_CLIENT_SECRET",
    "MESH_GITHUB_OAUTH_REDIRECT_URL",
]
REQUIRED_FRONTEND_KEYS = ["NEXT_PUBLIC_MESH_API_URL"]
OPTIONAL_ROOT_KEYS = ["MESH_AUTH_PRODUCT_REDIRECT_URL", "MESH_AUTH_ALLOWED_ORIGINS"]
LOCAL_CALLBACKS = {
    "google": "/api/auth/oauth/google/callback",
    "github": "/api/auth/oauth/github/callback",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a redacted local operator auth provider readiness proof.",
    )
    parser.add_argument("--env-path", default=str(ROOT_ENV))
    parser.add_argument("--frontend-env-path", default=str(FRONTEND_ENV))
    parser.add_argument("--artifact-path", default=str(DEFAULT_ARTIFACT))
    parser.add_argument("--live-proof-path", default=str(DEFAULT_LIVE_PROOF))
    parser.add_argument("--identity-path", default=str(DEFAULT_IDENTITY))
    parser.add_argument("--require-live", action="store_true")
    parser.add_argument("--print-live-proof-template", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args(argv)

    if args.print_live_proof_template:
        print(json.dumps(live_provider_proof_template(), indent=2, sort_keys=True))
        return 0

    proof = build_proof(
        Path(args.env_path),
        Path(args.frontend_env_path),
        Path(args.live_proof_path),
        identity_path=Path(args.identity_path),
    )
    if not args.no_write:
        artifact_path = Path(args.artifact_path)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(proof, indent=2, sort_keys=True))
    if args.require_live and proof["status"] != "provider_browser_proof_complete":
        return 2
    return 0 if proof["status"] in {"ready_for_browser_provider_smoke", "blocked_provider_console_unverified", "provider_browser_proof_complete"} else 2


def build_proof(
    env_path: Path,
    frontend_env_path: Path,
    live_proof_path: Path | None = None,
    *,
    identity_path: Path | None = None,
) -> dict[str, Any]:
    root_env = _read_env(env_path)
    frontend_env = _read_env(frontend_env_path)
    missing_root = [key for key in REQUIRED_ROOT_KEYS if not root_env.get(key)]
    missing_frontend = [key for key in REQUIRED_FRONTEND_KEYS if not frontend_env.get(key)]
    tracked_env_files = _tracked_paths([env_path, frontend_env_path])
    ignored_env_files = _ignored_paths([env_path, frontend_env_path])
    tracked_secret_hits = _tracked_secret_hits(root_env, frontend_env)
    callbacks = {
        "google": _callback_status(root_env.get("MESH_GOOGLE_OAUTH_REDIRECT_URL", ""), LOCAL_CALLBACKS["google"]),
        "github": _callback_status(root_env.get("MESH_GITHUB_OAUTH_REDIRECT_URL", ""), LOCAL_CALLBACKS["github"]),
    }
    product_redirect = _product_redirect_status(
        root_env.get("MESH_AUTH_PRODUCT_REDIRECT_URL", ""),
        root_env.get("MESH_AUTH_ALLOWED_ORIGINS", ""),
    )
    live_provider_proof = live_provider_proof_status(live_proof_path or DEFAULT_LIVE_PROOF)
    runtime_auth_evidence = runtime_auth_evidence_status(identity_path or DEFAULT_IDENTITY)
    captcha_provider = root_env.get("MESH_CAPTCHA_PROVIDER", "")
    hcaptcha_ready = (
        captcha_provider == "hcaptcha"
        and bool(root_env.get("MESH_CAPTCHA_SITE_KEY"))
        and bool(root_env.get("MESH_CAPTCHA_SECRET_KEY"))
    )
    blockers: list[str] = []
    if missing_root:
        blockers.append("missing_root_env_values")
    if missing_frontend:
        blockers.append("missing_frontend_env_values")
    if tracked_env_files:
        blockers.append("env_files_tracked")
    if set(ignored_env_files) != {str(env_path), str(frontend_env_path)}:
        blockers.append("env_files_not_ignored")
    if tracked_secret_hits:
        blockers.append("tracked_secret_material_present")
    if not all(item["local_callback_match"] for item in callbacks.values()):
        blockers.append("oauth_local_callback_mismatch")
    if not hcaptcha_ready:
        blockers.append("hcaptcha_env_incomplete")
    if product_redirect["configured"] and product_redirect["status"] != "ready":
        blockers.append("auth_product_redirect_untrusted")
    if live_provider_proof["status"] != "complete":
        blockers.append(live_provider_proof["blocker"])
    elif runtime_auth_evidence["status"] != "complete":
        blockers.append(runtime_auth_evidence["blocker"])
    if not blockers and live_provider_proof["status"] != "complete":
        blockers.append("provider_console_and_browser_completion_unverified")
    config_blockers = [
        item for item in blockers
        if item not in {"provider_console_and_browser_completion_unverified", "live_provider_proof_missing"}
    ]
    if live_provider_proof["status"] == "complete" and runtime_auth_evidence["status"] == "complete" and not config_blockers:
        status = "provider_browser_proof_complete"
    else:
        status = "blocked_configuration" if config_blockers else "blocked_provider_console_unverified"
    return {
        "schema_version": "mesh.operator_auth_provider_readiness.v1",
        "generated_at": _timestamp(),
        "state_slice": "auth-provider-proof.v1",
        "status": status,
        "raw_secret_material_present": bool(tracked_secret_hits or tracked_env_files),
        "tracked_env_secret_material_present": bool(tracked_env_files),
        "env_files": {
            "root_env_local": {
                "path": str(env_path),
                "exists": env_path.exists(),
                "ignored": str(env_path) in ignored_env_files,
                "tracked": str(env_path) in tracked_env_files,
                "present_keys": sorted(key for key in REQUIRED_ROOT_KEYS if root_env.get(key)),
                "present_optional_keys": sorted(key for key in OPTIONAL_ROOT_KEYS if root_env.get(key)),
                "missing_keys": missing_root,
            },
            "frontend_env_local": {
                "path": str(frontend_env_path),
                "exists": frontend_env_path.exists(),
                "ignored": str(frontend_env_path) in ignored_env_files,
                "tracked": str(frontend_env_path) in tracked_env_files,
                "present_keys": sorted(key for key in REQUIRED_FRONTEND_KEYS if frontend_env.get(key)),
                "missing_keys": missing_frontend,
            },
        },
        "oauth": callbacks,
        "product_redirect": product_redirect,
        "captcha": {
            "provider": captcha_provider or "missing",
            "hcaptcha_env_ready": hcaptcha_ready,
            "browser_token_verified": live_provider_proof["captcha"]["browser_token_verified"],
            "browser_token_status": live_provider_proof["captcha"]["browser_token_status"],
        },
        "live_provider_proof": live_provider_proof,
        "runtime_auth_evidence": runtime_auth_evidence,
        "tracked_secret_hits": tracked_secret_hits,
        "blockers": blockers,
        "browser_flow_coverage": {
            "email_signup": "covered_by_pnpm_run_test_product_e2e",
            "solo_dashboard": "covered_by_pnpm_run_test_product_e2e",
            "team_dashboard": "covered_by_pnpm_run_test_product_e2e",
            "logout": "covered_by_pnpm_run_test_product_e2e",
            "expired_session_recovery": "covered_by_pnpm_run_test_product_e2e",
            "google_oauth": "requires_external_provider_login",
            "github_oauth": "requires_external_provider_login",
            "hcaptcha": "requires_external_provider_challenge",
        },
        "authority_boundary": "This artifact records provider readiness only. Mesh auth/session state remains authoritative, and no raw OAuth or captcha secret is written.",
    }


def live_provider_proof_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_live_provider_proof("live_provider_proof_missing", str(path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_live_provider_proof("live_provider_proof_unreadable", str(path))
    return validate_live_provider_proof(payload, proof_path=str(path))


def runtime_auth_evidence_status(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_runtime_auth_evidence("runtime_identity_missing", str(path))
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_runtime_auth_evidence("runtime_identity_unreadable", str(path))
    if not isinstance(payload, dict):
        return _empty_runtime_auth_evidence("runtime_identity_not_object", str(path))
    evidence = build_auth_provider_evidence(payload)
    raw_secret_fields = _raw_secret_fields({"auth_events": payload.get("auth_events", [])})
    missing_or_blocked = runtime_auth_evidence_blockers(evidence)
    if raw_secret_fields:
        missing_or_blocked.append("runtime_auth_events_contain_raw_secret_material")
    status = "complete" if not missing_or_blocked else "blocked"
    evidence["path"] = str(path)
    evidence["status"] = status
    evidence["blocker"] = "" if status == "complete" else "runtime_auth_evidence_incomplete"
    evidence["raw_secret_material_present"] = bool(raw_secret_fields)
    evidence["raw_secret_fields"] = raw_secret_fields
    evidence["missing_or_blocked"] = missing_or_blocked
    return evidence


def runtime_auth_evidence_blockers(evidence: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    providers = evidence.get("providers") if isinstance(evidence.get("providers"), dict) else {}
    google = providers.get("google_oauth") if isinstance(providers.get("google_oauth"), dict) else {}
    github = providers.get("github_oauth") if isinstance(providers.get("github_oauth"), dict) else {}
    captcha = evidence.get("captcha") if isinstance(evidence.get("captcha"), dict) else {}
    email_signup = evidence.get("email_signup") if isinstance(evidence.get("email_signup"), dict) else {}
    if email_signup.get("status") != "complete":
        blockers.append("runtime_email_signup_event_missing")
    if google.get("status") != "complete":
        blockers.append("runtime_google_oauth_event_missing")
    if github.get("status") != "complete":
        blockers.append("runtime_github_oauth_event_missing")
    if captcha.get("status") != "complete":
        blockers.append("runtime_hcaptcha_verification_event_missing")
    return blockers


def live_provider_proof_template() -> dict[str, Any]:
    return {
        "schema_version": "mesh.operator_auth_provider_live_proof.v1",
        "state_slice": "auth-provider-proof.v1",
        "clean_browser_session": False,
        "raw_secret_material_present": False,
        "providers": {
            "google_oauth": {
                "browser_completed": False,
                "session_established": False,
                "callback_path": "/api/auth/oauth/google/callback",
                "completed_at": "",
            },
            "github_oauth": {
                "browser_completed": False,
                "session_established": False,
                "callback_path": "/api/auth/oauth/github/callback",
                "completed_at": "",
            },
        },
        "email_signup": {
            "browser_completed": False,
            "session_established": False,
            "hcaptcha_verified": False,
            "completed_at": "",
        },
        "captcha": {
            "provider": "hcaptcha",
            "challenge_completed": False,
            "browser_token_verified": False,
            "completed_at": "",
        },
    }


def validate_live_provider_proof(payload: Any, *, proof_path: str = "") -> dict[str, Any]:
    blockers: list[str] = []
    if not isinstance(payload, dict):
        return _empty_live_provider_proof("live_provider_proof_not_object", proof_path)
    raw_secret_fields = _raw_secret_fields(payload)
    if raw_secret_fields or payload.get("raw_secret_material_present") is True:
        blockers.append("live_provider_proof_contains_raw_secret_material")
    if payload.get("schema_version") != "mesh.operator_auth_provider_live_proof.v1":
        blockers.append("live_provider_proof_schema_version_mismatch")
    if payload.get("state_slice") != "auth-provider-proof.v1":
        blockers.append("live_provider_proof_state_slice_mismatch")
    if payload.get("clean_browser_session") is not True:
        blockers.append("clean_browser_session_not_proven")
    email_signup = _email_signup_live_status(payload.get("email_signup"))
    providers = payload.get("providers") if isinstance(payload.get("providers"), dict) else {}
    google = _provider_live_status(providers.get("google_oauth"), LOCAL_CALLBACKS["google"])
    github = _provider_live_status(providers.get("github_oauth"), LOCAL_CALLBACKS["github"])
    captcha = _captcha_live_status(payload.get("captcha"))
    for label, status in [("email_signup", email_signup), ("google_oauth", google), ("github_oauth", github), ("hcaptcha", captcha)]:
        if status["status"] != "complete":
            blockers.append(f"{label}_browser_completion_missing")
    status = "blocked" if blockers else "complete"
    return {
        "path": proof_path,
        "status": status,
        "blocker": "provider_console_and_browser_completion_unverified" if status == "blocked" else "",
        "raw_secret_material_present": bool(raw_secret_fields or payload.get("raw_secret_material_present") is True),
        "raw_secret_fields": raw_secret_fields,
        "clean_browser_session": payload.get("clean_browser_session") is True,
        "email_signup": email_signup,
        "providers": {
            "google_oauth": google,
            "github_oauth": github,
        },
        "captcha": captcha,
        "browser_completion_status": "complete" if status == "complete" else "requires_clean_browser_provider_completion",
        "missing_or_blocked": blockers,
    }


def _empty_live_provider_proof(blocker: str, path: str) -> dict[str, Any]:
    return {
        "path": path,
        "status": "blocked",
        "blocker": blocker,
        "raw_secret_material_present": False,
        "raw_secret_fields": [],
        "clean_browser_session": False,
        "email_signup": {
            "status": "blocked",
            "browser_completed": False,
            "session_established": False,
            "hcaptcha_verified": False,
        },
        "providers": {
            "google_oauth": {"status": "blocked", "browser_completed": False, "session_established": False, "callback_path_match": False},
            "github_oauth": {"status": "blocked", "browser_completed": False, "session_established": False, "callback_path_match": False},
        },
        "captcha": {
            "status": "blocked",
            "provider": "hcaptcha",
            "browser_token_verified": False,
            "browser_token_status": "requires_clean_browser_provider_completion",
        },
        "browser_completion_status": "requires_clean_browser_provider_completion",
        "missing_or_blocked": [blocker],
    }


def _empty_runtime_auth_evidence(blocker: str, path: str) -> dict[str, Any]:
    return {
        "schema_version": "mesh.operator_auth_runtime_evidence.v1",
        "state_slice": "auth-provider-proof.v1",
        "path": path,
        "status": "blocked",
        "blocker": blocker,
        "email_signup": {"status": "blocked", "session_established": False},
        "providers": {
            "google_oauth": {"status": "blocked", "session_established": False, "callback_path_match": False},
            "github_oauth": {"status": "blocked", "session_established": False, "callback_path_match": False},
        },
        "captcha": {
            "status": "blocked",
            "provider": "hcaptcha",
            "browser_token_verified": False,
            "browser_token_status": "requires_clean_browser_provider_completion",
        },
        "event_count": 0,
        "raw_secret_material_present": False,
        "raw_secret_fields": [],
        "missing_or_blocked": [blocker],
        "authority_boundary": "Runtime auth evidence records only redacted session-establishment metadata.",
    }


def _provider_live_status(value: Any, expected_path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "blocked", "browser_completed": False, "session_established": False, "callback_path_match": False}
    browser_completed = value.get("browser_completed") is True
    session_established = value.get("session_established") is True
    callback_path_match = value.get("callback_path") == expected_path
    return {
        "status": "complete" if browser_completed and session_established and callback_path_match else "blocked",
        "browser_completed": browser_completed,
        "session_established": session_established,
        "callback_path_match": callback_path_match,
        "callback_path": str(value.get("callback_path") or ""),
        "completed_at": str(value.get("completed_at") or ""),
    }


def _email_signup_live_status(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"status": "blocked", "browser_completed": False, "session_established": False, "hcaptcha_verified": False}
    browser_completed = value.get("browser_completed") is True
    session_established = value.get("session_established") is True
    hcaptcha_verified = value.get("hcaptcha_verified") is True
    return {
        "status": "complete" if browser_completed and session_established and hcaptcha_verified else "blocked",
        "browser_completed": browser_completed,
        "session_established": session_established,
        "hcaptcha_verified": hcaptcha_verified,
        "completed_at": str(value.get("completed_at") or ""),
    }


def _captcha_live_status(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "status": "blocked",
            "provider": "hcaptcha",
            "browser_token_verified": False,
            "browser_token_status": "requires_clean_browser_provider_completion",
        }
    provider = str(value.get("provider") or "")
    challenge_completed = value.get("challenge_completed") is True
    browser_token_verified = value.get("browser_token_verified") is True
    complete = provider == "hcaptcha" and challenge_completed and browser_token_verified
    return {
        "status": "complete" if complete else "blocked",
        "provider": provider or "missing",
        "challenge_completed": challenge_completed,
        "browser_token_verified": browser_token_verified,
        "browser_token_status": "verified" if complete else "requires_clean_browser_provider_completion",
        "completed_at": str(value.get("completed_at") or ""),
    }


def _raw_secret_fields(value: Any, path: str = "") -> list[str]:
    fields: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if _looks_raw_secret_field(str(key)) and not _empty_secret_value(child):
                fields.append(child_path)
            fields.extend(_raw_secret_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            fields.extend(_raw_secret_fields(child, f"{path}[{index}]"))
    return fields


_RAW_SECRET_FIELD_RE = re.compile(r"(^|_)(access_token|refresh_token|id_token|client_secret|secret|authorization|cookie|password|private_key|api_key|token)$", re.IGNORECASE)


def _looks_raw_secret_field(key: str) -> bool:
    if key == "browser_token_verified":
        return False
    return bool(_RAW_SECRET_FIELD_RE.search(key))


def _empty_secret_value(value: Any) -> bool:
    return value is None or value is False or value == ""


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


def _tracked_paths(paths: list[Path]) -> list[str]:
    tracked: list[str] = []
    for path in paths:
        rel = _rel(path)
        result = _git(["ls-files", "--", rel])
        if result.stdout.strip():
            tracked.append(str(path))
    return tracked


def _ignored_paths(paths: list[Path]) -> list[str]:
    ignored: list[str] = []
    for path in paths:
        rel = _rel(path)
        result = _git(["check-ignore", "-q", rel])
        if result.returncode == 0:
            ignored.append(str(path))
    return ignored


def _tracked_secret_hits(*envs: dict[str, str]) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    secret_keys = [key for env in envs for key in env if _looks_secret_key(key)]
    for env in envs:
        for key in secret_keys:
            value = env.get(key, "")
            if len(value) < 8:
                continue
            result = _git(["grep", "-n", "-F", "--", value, "--", ":!package-lock.json"])
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    path, _, _rest = line.partition(":")
                    if path.endswith(".env.local"):
                        continue
                    hits.append({"key": key, "tracked_path": path})
    return hits


def _callback_status(url: str, expected_path: str) -> dict[str, Any]:
    parsed = urlparse(url)
    local_host = parsed.hostname in {"127.0.0.1", "localhost"}
    return {
        "configured": bool(url),
        "scheme": parsed.scheme or "",
        "host": parsed.hostname or "",
        "path": parsed.path,
        "local_callback_match": bool(url and local_host and parsed.path == expected_path),
    }


def _product_redirect_status(url: str, raw_allowed_origins: str) -> dict[str, Any]:
    if not url:
        return {
            "configured": False,
            "status": "not_configured",
            "trusted": False,
            "origin": "",
            "reason": "OAuth callback falls back to the API host. Configure MESH_AUTH_PRODUCT_REDIRECT_URL for split API/product local dev.",
        }
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    allowed_origins = {item.strip() for item in raw_allowed_origins.split(",") if item.strip()}
    local_host = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    trusted = (
        parsed.scheme in {"http", "https"}
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
        and (local_host or origin in allowed_origins)
    )
    return {
        "configured": True,
        "status": "ready" if trusted else "blocked",
        "trusted": trusted,
        "origin": origin,
        "host": parsed.hostname or "",
        "path": parsed.path or "/",
        "allowed_by": "loopback" if local_host else "auth_allowed_origins" if origin in allowed_origins else "",
        "reason": "OAuth callbacks return to the product shell after provider completion." if trusted else "MESH_AUTH_PRODUCT_REDIRECT_URL must be loopback or listed in MESH_AUTH_ALLOWED_ORIGINS.",
    }


def _looks_secret_key(key: str) -> bool:
    lowered = key.lower()
    return "secret" in lowered or lowered.endswith("_key") or "client_id" in lowered


def _git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


if __name__ == "__main__":
    raise SystemExit(main())
