"""ArgoCD adapter — sync and rollback ArgoCD applications via REST API.

Config:
    MESH_ARGOCD_URL        — base URL of the ArgoCD API server
    MESH_ARGOCD_TOKEN      — bearer token (from `argocd account generate-token`)
    MESH_ARGOCD_CA_BUNDLE  — optional path to CA bundle for TLS verification

Runs in dry-run mode (synthetic IDs, no HTTP) when ``url`` or ``token`` are
unset, matching the pattern used elsewhere in the actuator layer.
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from typing import Any, TypedDict


class ArgoCDParameters(TypedDict, total=False):
    application: str
    revision: str
    prune: bool
    target_revision: str


class ArgoCDAdapter:
    def __init__(
        self,
        *,
        url: str | None = None,
        token: str | None = None,
        ca_bundle: str | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self.url = (url or "").rstrip("/") or None
        self.token = token or None
        self.ca_bundle = ca_bundle or None
        self.timeout_seconds = timeout_seconds

    @property
    def live(self) -> bool:
        return bool(self.url and self.token)

    # ------------------------------------------------------------------
    # Public actions
    # ------------------------------------------------------------------

    def sync_application(self, parameters: ArgoCDParameters) -> dict[str, Any]:
        application = parameters.get("application")
        if not application:
            return _failure("missing_parameter", "application is required")
        if not self.live:
            return _synthetic_success("argocd_sync", application)
        body: dict[str, Any] = {}
        if parameters.get("revision"):
            body["revision"] = parameters["revision"]
        if parameters.get("prune"):
            body["prune"] = bool(parameters["prune"])
        status, payload = self._request(
            "POST", f"/api/v1/applications/{application}/sync", body=body or None,
        )
        if status // 100 != 2:
            return _failure("argocd_sync_failed", f"status={status}: {payload}")
        return {
            "status": "succeeded",
            "external_refs": {
                "argocd_application": application,
                "argocd_sync_revision": payload.get("revision") if isinstance(payload, dict) else None,
                "rollout_action": "argocd_sync",
            },
        }

    def rollback_application(self, parameters: ArgoCDParameters) -> dict[str, Any]:
        application = parameters.get("application")
        target_revision = parameters.get("target_revision")
        if not application:
            return _failure("missing_parameter", "application is required")
        if not self.live:
            return _synthetic_success("argocd_rollback", application, target_revision=target_revision)
        body = {"id": 0}  # ArgoCD expects numeric history id; 0 = previous
        if target_revision:
            body["id"] = _safe_int(target_revision, default=0)
        status, payload = self._request(
            "POST", f"/api/v1/applications/{application}/rollback", body=body,
        )
        if status // 100 != 2:
            return _failure("argocd_rollback_failed", f"status={status}: {payload}")
        return {
            "status": "succeeded",
            "external_refs": {
                "argocd_application": application,
                "argocd_target_revision": target_revision,
                "rollout_action": "argocd_rollback",
            },
        }

    def get_application(self, parameters: ArgoCDParameters) -> dict[str, Any]:
        application = parameters.get("application")
        if not application:
            return _failure("missing_parameter", "application is required")
        if not self.live:
            return {
                "status": "succeeded",
                "external_refs": {"argocd_application": application, "dry_run": True},
                "application": {"name": application, "health": "Unknown", "sync_status": "Unknown"},
            }
        status, payload = self._request("GET", f"/api/v1/applications/{application}")
        if status // 100 != 2:
            return _failure("argocd_get_failed", f"status={status}: {payload}")
        app_status = payload.get("status", {}) if isinstance(payload, dict) else {}
        return {
            "status": "succeeded",
            "external_refs": {"argocd_application": application},
            "application": {
                "name": application,
                "health": app_status.get("health", {}).get("status"),
                "sync_status": app_status.get("sync", {}).get("status"),
                "current_revision": app_status.get("sync", {}).get("revision"),
            },
        }

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        url = f"{self.url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        context: ssl.SSLContext | None = None
        if self.ca_bundle:
            context = ssl.create_default_context(cafile=self.ca_bundle)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=context) as resp:
                raw = resp.read().decode("utf-8") or "{}"
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = raw
                return resp.status, parsed
        except urllib.error.HTTPError as exc:
            try:
                parsed = json.loads(exc.read().decode("utf-8") or "{}")
            except Exception:
                parsed = {"error": str(exc)}
            return exc.code, parsed
        except urllib.error.URLError as exc:
            return 0, {"error": f"URLError: {exc}"}


# ----------------------------------------------------------------------


def _failure(reason: str, detail: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "failure": {"reason": reason, "detail": detail},
        "external_refs": {},
    }


def _synthetic_success(action: str, application: str, *, target_revision: str | None = None) -> dict[str, Any]:
    refs = {
        "argocd_application": application,
        "rollout_action": action,
        "dry_run": True,
    }
    if target_revision:
        refs["argocd_target_revision"] = target_revision
    return {"status": "succeeded", "external_refs": refs}


def _safe_int(value: str | int | None, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
