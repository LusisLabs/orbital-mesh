from __future__ import annotations

import base64
import calendar
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .json_store import LockedJsonFile


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TEAM_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
OAUTH_STATE_TTL_SECONDS = 60 * 10
PBKDF2_ITERATIONS = 210_000
SETTINGS_SCHEMA: dict[str, dict[str, Any]] = {
    "default_evaluation_mode": {
        "values": ["native", "promptfoo"],
        "default": "native",
        "description": "Default evaluation adapter for new operator-created runs.",
    },
    "default_orchestration_mode": {
        "values": ["native", "hermes", "goose", "auto"],
        "default": "native",
        "description": "Default proposal lane for new operator-created runs.",
    },
    "default_steering_mode": {
        "values": ["approval_gate", "interruptible_auto"],
        "default": "approval_gate",
        "description": "Default steering posture for new operator-created runs.",
    },
}


def settings_audit_path(identity_path: str | Path) -> Path:
    return Path(identity_path).parent / "operator-config-audit.jsonl"


def write_settings_audit(
    identity_path: str | Path,
    *,
    operator_id: str,
    reason: str,
    scope: str,
    updates: dict[str, Any],
    git_commit: str = "unknown",
) -> dict[str, Any]:
    cleaned_reason = reason.strip()
    if not cleaned_reason:
        raise ValueError("settings update reason is required")
    path = settings_audit_path(identity_path)
    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "operator_id": operator_id,
        "reason": cleaned_reason,
        "scope": scope,
        "state_slice": "mesh-settings-control",
        "fields": sorted(updates),
        "config_hash": _file_sha256(Path(identity_path)),
        "git_commit": git_commit,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return {"audit_path": str(path), "record": record}


@dataclass(frozen=True)
class CaptchaConfig:
    provider: str = "disabled"
    site_key: str = ""
    secret: str = ""
    dev_bypass_enabled: bool = False


@dataclass(frozen=True)
class OAuthProviderConfig:
    provider: str
    client_id: str = ""
    client_secret: str = ""
    redirect_uri: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


class OperatorIdentityStore:
    """File-backed operator identity, team, session, and UI settings store."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def public_auth_config(
        self,
        *,
        captcha: CaptchaConfig,
        google: OAuthProviderConfig,
        github: OAuthProviderConfig,
    ) -> dict[str, Any]:
        return {
            "captcha": {
                "provider": captcha.provider,
                "site_key": captcha.site_key,
                "configured": self._captcha_configured(captcha),
                "dev_bypass_enabled": captcha.dev_bypass_enabled,
            },
            "oauth": {
                "google": {"configured": google.configured},
                "github": {"configured": github.configured},
            },
        }

    def create_user(
        self,
        *,
        email: str,
        password: str,
        display_name: str = "",
        captcha_token: str = "",
        captcha: CaptchaConfig | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        if captcha is not None:
            self.verify_captcha(captcha_token, captcha)
        normalized_email = self._validate_email(email)
        self._validate_password(password)
        now_value = now or time.time()
        data = self._read()
        if normalized_email in data["email_index"]:
            raise ValueError("user already exists")
        user_id = self._new_id("usr")
        user = {
            "id": user_id,
            "email": normalized_email,
            "display_name": _clean_display_name(display_name) or normalized_email.split("@", 1)[0],
            "password_hash": _hash_password(password),
            "created_at": _iso(now_value),
            "updated_at": _iso(now_value),
        }
        data["users"][user_id] = user
        data["email_index"][normalized_email] = user_id
        data["active_team_by_user"][user_id] = None
        self._write(data)
        return self.create_session(user_id, now=now_value)

    def login_user(self, *, email: str, password: str, now: float | None = None) -> dict[str, Any]:
        normalized_email = self._validate_email(email)
        data = self._read()
        user_id = data["email_index"].get(normalized_email)
        if not user_id:
            raise ValueError("invalid email or password")
        user = data["users"].get(user_id)
        if not user or not _verify_password(password, str(user.get("password_hash") or "")):
            raise ValueError("invalid email or password")
        return self.create_session(user_id, now=now)

    def create_session(self, user_id: str, *, now: float | None = None) -> dict[str, Any]:
        now_value = now or time.time()
        data = self._read()
        if user_id not in data["users"]:
            raise ValueError("user not found")
        token = secrets.token_urlsafe(32)
        session = {
            "token_hash": _token_hash(token),
            "user_id": user_id,
            "created_at": _iso(now_value),
            "expires_at": _iso(now_value + SESSION_TTL_SECONDS),
        }
        data["sessions"][session["token_hash"]] = session
        self._write(data)
        return {"token": token, "session": self.session_payload(token)}

    def delete_session(self, token: str) -> None:
        data = self._read()
        data["sessions"].pop(_token_hash(token), None)
        self._write(data)

    def session_payload(self, token: str, *, now: float | None = None) -> dict[str, Any]:
        data = self._read()
        session = self._valid_session(data, token, now=now)
        user = data["users"][session["user_id"]]
        active_team_id = data["active_team_by_user"].get(user["id"])
        teams = self._teams_for_user(data, user["id"])
        active_team = next((team for team in teams if team["id"] == active_team_id), None)
        return {
            "user": _public_user(user),
            "teams": teams,
            "active_team": active_team,
            "settings": self._settings_for_scope(data, user_id=user["id"], team_id=active_team_id),
        }

    def operator_context_from_session(self, token: str) -> dict[str, Any] | None:
        try:
            payload = self.session_payload(token)
        except ValueError:
            return None
        user = payload["user"]
        active_team = payload.get("active_team")
        roles = ["viewer", "launcher"]
        if active_team:
            roles = sorted(set(active_team.get("roles") or roles))
        return {
            "operator_id": user["email"],
            "roles": roles,
            "source": "operator_session",
            "source_ip": None,
            "user_id": user["id"],
            "team_id": active_team.get("id") if active_team else None,
        }

    def create_team(
        self,
        token: str,
        *,
        name: str,
        display_name: str = "",
        members: list[dict[str, Any]] | None = None,
        now: float | None = None,
    ) -> dict[str, Any]:
        now_value = now or time.time()
        data = self._read()
        session = self._valid_session(data, token, now=now_value)
        owner_id = session["user_id"]
        team_name = _clean_team_name(name)
        slug = _slug(team_name)
        if not TEAM_SLUG_RE.match(slug):
            raise ValueError("team name must produce a valid slug")
        if slug in data["team_slug_index"]:
            raise ValueError("team slug already exists")
        team_id = self._new_id("team")
        team = {
            "id": team_id,
            "name": team_name,
            "display_name": _clean_display_name(display_name) or team_name,
            "slug": slug,
            "created_at": _iso(now_value),
            "updated_at": _iso(now_value),
        }
        data["teams"][team_id] = team
        data["team_slug_index"][slug] = team_id
        data["memberships"][team_id] = {
            owner_id: {
                "user_id": owner_id,
                "email": data["users"][owner_id]["email"],
                "role": "owner",
                "roles": ["admin", "approver", "launcher", "viewer"],
                "status": "active",
                "created_at": _iso(now_value),
            }
        }
        for member in members or []:
            email = str(member.get("email") or "").strip()
            if not email:
                continue
            normalized_email = self._validate_email(email)
            role = _normalize_member_role(str(member.get("role") or "viewer"))
            data["memberships"][team_id][normalized_email] = {
                "user_id": data["email_index"].get(normalized_email),
                "email": normalized_email,
                "role": role,
                "roles": _roles_for_member(role),
                "status": "invited",
                "created_at": _iso(now_value),
            }
        data["active_team_by_user"][owner_id] = team_id
        self._write(data)
        return self.session_payload(token, now=now_value)

    def set_active_team(self, token: str, team_id: str | None) -> dict[str, Any]:
        data = self._read()
        session = self._valid_session(data, token)
        user_id = session["user_id"]
        if team_id is not None and not self._membership_for_user(data, user_id, team_id):
            raise PermissionError("team access denied")
        data["active_team_by_user"][user_id] = team_id
        self._write(data)
        return self.session_payload(token)

    def dashboard(self, token: str, *, team_id: str | None, mesh: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        session = self._valid_session(data, token)
        user_id = session["user_id"]
        team_id = team_id or data["active_team_by_user"].get(user_id)
        team = None
        if team_id:
            membership = self._membership_for_user(data, user_id, team_id)
            if not membership:
                raise PermissionError("team access denied")
            team = _public_team(data["teams"][team_id], membership=membership, members=data["memberships"].get(team_id, {}))
        settings = self._settings_for_scope(data, user_id=user_id, team_id=team_id)
        return {
            "scope": {"kind": "team" if team else "solo", "team": team},
            "session": self.session_payload(token),
            "settings": settings,
            "settings_schema": SETTINGS_SCHEMA,
            "mesh": mesh,
            "authority_boundary": (
                "Dashboard identity scopes the product read model. Mesh remains the authority for "
                "policy, approvals, run state, readiness, evidence, and actuation."
            ),
        }

    def read_settings(self, token: str, *, team_id: str | None) -> dict[str, Any]:
        data = self._read()
        session = self._valid_session(data, token)
        if team_id and not self._membership_for_user(data, session["user_id"], team_id):
            raise PermissionError("team access denied")
        return {
            "settings": self._settings_for_scope(data, user_id=session["user_id"], team_id=team_id),
            "settings_schema": SETTINGS_SCHEMA,
        }

    def update_settings(self, token: str, *, team_id: str | None, updates: dict[str, Any]) -> dict[str, Any]:
        data = self._read()
        session = self._valid_session(data, token)
        user_id = session["user_id"]
        if team_id and not self._membership_for_user(data, user_id, team_id):
            raise PermissionError("team access denied")
        settings = self._settings_for_scope(data, user_id=user_id, team_id=team_id)
        for key, value in updates.items():
            if key not in SETTINGS_SCHEMA:
                raise ValueError(f"unknown setting: {key}")
            allowed = SETTINGS_SCHEMA[key]["values"]
            if value not in allowed:
                raise ValueError(f"{key} must be one of: {', '.join(allowed)}")
            settings[key] = value
        bucket = self._settings_bucket(data, user_id=user_id, team_id=team_id)
        bucket.update(settings)
        self._write(data)
        return {"settings": settings, "settings_schema": SETTINGS_SCHEMA}

    def read_scoped_settings(self, scope: str) -> dict[str, Any]:
        data = self._read()
        settings = {key: schema["default"] for key, schema in SETTINGS_SCHEMA.items()}
        settings.update(data["settings"].get(scope, {}))
        return {"scope": scope, "settings": settings, "settings_schema": SETTINGS_SCHEMA}

    def update_scoped_settings(self, scope: str, updates: dict[str, Any]) -> dict[str, Any]:
        if not scope.startswith(("user:", "team:", "global")):
            raise ValueError("scope must be global, user:<id>, or team:<id>")
        data = self._read()
        settings = self.read_scoped_settings(scope)["settings"]
        for key, value in updates.items():
            if key not in SETTINGS_SCHEMA:
                raise ValueError(f"unknown setting: {key}")
            allowed = SETTINGS_SCHEMA[key]["values"]
            if value not in allowed:
                raise ValueError(f"{key} must be one of: {', '.join(allowed)}")
            settings[key] = value
        data["settings"][scope] = settings
        self._write(data)
        return {"scope": scope, "settings": settings, "settings_schema": SETTINGS_SCHEMA}

    def create_oauth_state(self, provider: str, *, now: float | None = None) -> dict[str, str]:
        now_value = now or time.time()
        data = self._read()
        state = secrets.token_urlsafe(24)
        data["oauth_states"][state] = {
            "provider": provider,
            "created_at": _iso(now_value),
            "expires_at": _iso(now_value + OAUTH_STATE_TTL_SECONDS),
        }
        self._write(data)
        return {"state": state}

    def consume_oauth_state(self, provider: str, state: str, *, now: float | None = None) -> None:
        data = self._read()
        record = data["oauth_states"].pop(state, None)
        self._write(data)
        if not record or record.get("provider") != provider:
            raise ValueError("invalid oauth state")
        if _from_iso(record["expires_at"]) < (now or time.time()):
            raise ValueError("expired oauth state")

    def upsert_oauth_user(
        self,
        *,
        provider: str,
        provider_user_id: str,
        email: str,
        display_name: str = "",
    ) -> dict[str, Any]:
        normalized_email = self._validate_email(email)
        data = self._read()
        oauth_key = f"{provider}:{provider_user_id}"
        user_id = data["oauth_index"].get(oauth_key) or data["email_index"].get(normalized_email)
        now_value = time.time()
        if not user_id:
            user_id = self._new_id("usr")
            data["users"][user_id] = {
                "id": user_id,
                "email": normalized_email,
                "display_name": _clean_display_name(display_name) or normalized_email.split("@", 1)[0],
                "password_hash": "",
                "created_at": _iso(now_value),
                "updated_at": _iso(now_value),
            }
            data["email_index"][normalized_email] = user_id
            data["active_team_by_user"][user_id] = None
        data["oauth_index"][oauth_key] = user_id
        self._write(data)
        return self.create_session(user_id, now=now_value)

    def verify_captcha(self, token: str, captcha: CaptchaConfig) -> None:
        if self._captcha_configured(captcha):
            verify_captcha_token(token, captcha)
            return
        if captcha.dev_bypass_enabled and token == "dev-captcha-ok":
            return
        raise ValueError("captcha is not configured")

    def _read(self) -> dict[str, Any]:
        with LockedJsonFile(self.path) as data:
            return _merge_defaults(data)

    def _write(self, data: dict[str, Any]) -> None:
        with LockedJsonFile(self.path) as payload:
            payload.clear()
            payload.update(_merge_defaults(data))

    def _valid_session(self, data: dict[str, Any], token: str, *, now: float | None = None) -> dict[str, Any]:
        if not token:
            raise ValueError("session required")
        record = data["sessions"].get(_token_hash(token))
        if not record:
            raise ValueError("session expired")
        if _from_iso(record["expires_at"]) < (now or time.time()):
            data["sessions"].pop(record["token_hash"], None)
            self._write(data)
            raise ValueError("session expired")
        return record

    def _teams_for_user(self, data: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
        teams: list[dict[str, Any]] = []
        for team_id, members in data["memberships"].items():
            membership = self._membership_for_user(data, user_id, team_id)
            if membership:
                teams.append(_public_team(data["teams"][team_id], membership=membership, members=members))
        return sorted(teams, key=lambda team: team["name"].lower())

    def _membership_for_user(self, data: dict[str, Any], user_id: str, team_id: str) -> dict[str, Any] | None:
        members = data["memberships"].get(team_id) or {}
        user = data["users"].get(user_id) or {}
        return members.get(user_id) or members.get(user.get("email"))

    def _settings_bucket(self, data: dict[str, Any], *, user_id: str, team_id: str | None) -> dict[str, Any]:
        key = f"team:{team_id}" if team_id else f"user:{user_id}"
        if key not in data["settings"]:
            data["settings"][key] = {}
        return data["settings"][key]

    def _settings_for_scope(self, data: dict[str, Any], *, user_id: str, team_id: str | None) -> dict[str, Any]:
        settings = {key: schema["default"] for key, schema in SETTINGS_SCHEMA.items()}
        settings.update(self._settings_bucket(data, user_id=user_id, team_id=team_id))
        return settings

    def _captcha_configured(self, captcha: CaptchaConfig) -> bool:
        return captcha.provider in {"hcaptcha", "recaptcha", "turnstile"} and bool(captcha.site_key and captcha.secret)

    def _validate_email(self, email: str) -> str:
        normalized = email.strip().lower()
        if not EMAIL_RE.match(normalized):
            raise ValueError("valid email is required")
        return normalized

    def _validate_password(self, password: str) -> None:
        if len(password) < 12:
            raise ValueError("password must be at least 12 characters")
        if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
            raise ValueError("password must include letters and numbers")

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{secrets.token_urlsafe(12).replace('-', '').replace('_', '')[:16]}"


def verify_captcha_token(token: str, captcha: CaptchaConfig) -> None:
    if not token:
        raise ValueError("captcha token is required")
    endpoints = {
        "hcaptcha": "https://hcaptcha.com/siteverify",
        "recaptcha": "https://www.google.com/recaptcha/api/siteverify",
        "turnstile": "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    }
    endpoint = endpoints.get(captcha.provider)
    if not endpoint:
        raise ValueError("unsupported captcha provider")
    body = urlencode({"secret": captcha.secret, "response": token}).encode("utf-8")
    request = Request(endpoint, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(request, timeout=5) as response:  # noqa: S310 - configured captcha endpoint.
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("success"):
        raise ValueError("captcha verification failed")


def oauth_authorize_url(config: OAuthProviderConfig, state: str) -> str:
    if not config.configured:
        raise ValueError(f"{config.provider} oauth is not configured")
    if config.provider == "google":
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "access_type": "offline",
                "prompt": "select_account",
            }
        )
    if config.provider == "github":
        return "https://github.com/login/oauth/authorize?" + urlencode(
            {
                "client_id": config.client_id,
                "redirect_uri": config.redirect_uri,
                "scope": "user:email",
                "state": state,
            }
        )
    raise ValueError("unsupported oauth provider")


def exchange_oauth_profile(config: OAuthProviderConfig, code: str) -> dict[str, str]:
    if config.provider == "google":
        token = _post_form(
            "https://oauth2.googleapis.com/token",
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": config.redirect_uri,
            },
        )
        profile = _get_json("https://openidconnect.googleapis.com/v1/userinfo", token["access_token"])
        return {
            "provider_user_id": str(profile["sub"]),
            "email": str(profile["email"]),
            "display_name": str(profile.get("name") or ""),
        }
    if config.provider == "github":
        token = _post_form(
            "https://github.com/login/oauth/access_token",
            {
                "client_id": config.client_id,
                "client_secret": config.client_secret,
                "code": code,
                "redirect_uri": config.redirect_uri,
            },
        )
        profile = _get_json("https://api.github.com/user", token["access_token"])
        email = str(profile.get("email") or "")
        if not email:
            emails = _get_json("https://api.github.com/user/emails", token["access_token"])
            if isinstance(emails, list):
                primary = next((item for item in emails if item.get("primary") and item.get("verified")), None)
                email = str((primary or {}).get("email") or "")
        return {
            "provider_user_id": str(profile["id"]),
            "email": email,
            "display_name": str(profile.get("name") or profile.get("login") or ""),
        }
    raise ValueError("unsupported oauth provider")


def _post_form(url: str, payload: dict[str, str]) -> dict[str, Any]:
    request = Request(
        url,
        data=urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
    )
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed OAuth token endpoints.
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str, access_token: str) -> Any:
    request = Request(url, headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed OAuth profile endpoints.
        return json.loads(response.read().decode("utf-8"))


def _empty_store() -> dict[str, Any]:
    return {
        "users": {},
        "email_index": {},
        "oauth_index": {},
        "sessions": {},
        "teams": {},
        "team_slug_index": {},
        "memberships": {},
        "active_team_by_user": {},
        "settings": {},
        "oauth_states": {},
    }


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    merged = _empty_store()
    for key in merged:
        if isinstance(data.get(key), dict):
            merged[key] = data[key]
    return merged


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _iso(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _from_iso(value: str) -> float:
    return float(calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ")))


def _public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user.get("display_name") or user["email"].split("@", 1)[0],
    }


def _public_team(team: dict[str, Any], *, membership: dict[str, Any], members: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": team["id"],
        "name": team["name"],
        "display_name": team.get("display_name") or team["name"],
        "slug": team["slug"],
        "role": membership.get("role", "viewer"),
        "roles": membership.get("roles", ["viewer"]),
        "members": [
            {
                "email": member.get("email"),
                "role": member.get("role", "viewer"),
                "status": member.get("status", "active"),
            }
            for member in members.values()
        ],
    }


def _clean_display_name(value: str) -> str:
    return " ".join(value.strip().split())[:80]


def _clean_team_name(value: str) -> str:
    cleaned = " ".join(value.strip().split())[:80]
    if len(cleaned) < 2:
        raise ValueError("team name is required")
    return cleaned


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:63]


def _normalize_member_role(value: str) -> str:
    role = value.strip().lower()
    if role not in {"viewer", "launcher", "approver", "admin"}:
        raise ValueError("member role must be viewer, launcher, approver, or admin")
    return role


def _roles_for_member(role: str) -> list[str]:
    if role == "admin":
        return ["admin", "approver", "launcher", "viewer"]
    if role == "approver":
        return ["approver", "launcher", "viewer"]
    if role == "launcher":
        return ["launcher", "viewer"]
    return ["viewer"]
