from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ServiceAgent:
    service: str
    scope: dict[str, list[str]] = field(default_factory=dict)
    runbook_path: str | None = None
    preferred_lanes: list[str] = field(default_factory=list)
    autonomy_overrides: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "scope": self.scope,
            "runbook_path": self.runbook_path,
            "preferred_lanes": self.preferred_lanes,
            "autonomy_overrides": self.autonomy_overrides,
        }

    def matches(self, signal_or_trigger: dict[str, Any]) -> bool:
        related = signal_or_trigger.get("related_context", {})
        if not isinstance(related, dict):
            related = {}
        values = {
            "services": [signal_or_trigger.get("service"), related.get("service")],
            "deployments": [signal_or_trigger.get("deployment_name"), related.get("deployment_name")],
            "namespaces": [signal_or_trigger.get("namespace"), related.get("namespace")],
            "flags": [signal_or_trigger.get("flag_key"), related.get("flag_key")],
            "repos": [related.get("repo_path")],
        }
        for key, patterns in self.scope.items():
            candidates = [str(item) for item in values.get(key, []) if item]
            if candidates and any(fnmatch.fnmatch(candidate, pattern) for candidate in candidates for pattern in patterns):
                return True
        return False


class ServiceAgentRegistry:
    def __init__(self, config_path: str | None):
        self.config_path = config_path
        self._agents = self._load(config_path)

    def list_agents(self) -> list[dict[str, Any]]:
        return [agent.to_dict() for agent in self._agents]

    def route(self, signal_or_trigger: dict[str, Any]) -> dict[str, Any]:
        for agent in self._agents:
            if agent.matches(signal_or_trigger):
                return {"matched": True, "agent": agent.to_dict()}
        return {
            "matched": False,
            "agent": {
                "service": "default",
                "scope": {},
                "runbook_path": None,
                "preferred_lanes": [],
                "autonomy_overrides": {},
            },
        }

    def _load(self, config_path: str | None) -> list[ServiceAgent]:
        if not config_path:
            return []
        path = Path(config_path)
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        agents = payload.get("agents", []) if isinstance(payload, dict) else []
        out: list[ServiceAgent] = []
        for raw in agents:
            if not isinstance(raw, dict) or not raw.get("service"):
                continue
            raw_scope = raw.get("scope")
            scope = raw_scope if isinstance(raw_scope, dict) else {}
            out.append(
                ServiceAgent(
                    service=str(raw["service"]),
                    scope={str(k): [str(item) for item in v] for k, v in scope.items() if isinstance(v, list)},
                    runbook_path=str(raw["runbook_path"]) if raw.get("runbook_path") else None,
                    preferred_lanes=[str(item) for item in raw.get("preferred_lanes", [])],
                    autonomy_overrides=dict(raw.get("autonomy_overrides") or {}),
                )
            )
        return out
