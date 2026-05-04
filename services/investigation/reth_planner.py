from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from services.evidence.reth_probe_registry import (
    build_probe_dicts,
    is_sparse_reth_signal,
    known_reth_probe_names,
    probe_names_for_signatures,
    sanitize_probe_names,
)
from services.observer.client import ChatMessage, chat_completion, extract_message_content
from services.observer.redaction import redact_for_observer
from shared.mesh_runtime import InvestigationPlan, RuntimeConfig, Trigger, load_policy


class RethInvestigationPlanner:
    """Select read-only Reth probes before evidence assembly.

    The LLM mode is intentionally narrow: it can only select names from the
    registry and cannot introduce tools, commands, or production actions.
    Invalid model output falls back to the native deterministic planner.
    """

    def __init__(self, config: RuntimeConfig | None = None) -> None:
        self.config = config or RuntimeConfig.from_env()

    def plan(self, *, trigger: Trigger, signal_payload: dict[str, Any]) -> InvestigationPlan | None:
        if trigger.trigger_type != "reth_node_degraded" or signal_payload.get("signal_type") != "reth_node":
            return None
        native = self._native_plan(trigger=trigger, signal_payload=signal_payload)
        if self.config.reth_investigation_planner != "llm":
            return native
        llm = self._llm_plan(trigger=trigger, signal_payload=signal_payload, fallback=native)
        return llm or native

    def _native_plan(self, *, trigger: Trigger, signal_payload: dict[str, Any], reason: str | None = None) -> InvestigationPlan:
        signatures = list(trigger.related_context.get("error_signatures", []) or [])
        names = probe_names_for_signatures(
            signatures,
            sparse=is_sparse_reth_signal(signal_payload),
        )
        names = sanitize_probe_names(names, max_probes=self.config.reth_investigation_max_probes)
        plan = InvestigationPlan(
            plan_id=f"plan_reth_{trigger.trigger_id}_{uuid4().hex[:8]}",
            trigger_id=trigger.trigger_id,
            created_at=_now_iso(),
            objective=f"Gather read-only Reth evidence for {trigger.service} before RCA ranking.",
            probe_budget={
                "max_probes": self.config.reth_investigation_max_probes,
                "max_total_latency_ms": int(self.config.reth_investigation_budget_seconds * 1000),
                "per_probe_timeout_ms": int(self.config.reth_investigation_probe_timeout_seconds * 1000),
                "mode": "reth_native",
                "planner": "native",
                **({"fallback_reason": reason} if reason else {}),
            },
            probes=build_probe_dicts(names),
        )
        plan.validate()
        return plan

    def _llm_plan(
        self,
        *,
        trigger: Trigger,
        signal_payload: dict[str, Any],
        fallback: InvestigationPlan,
    ) -> InvestigationPlan | None:
        if not (
            self.config.observer_base_url
            and self.config.observer_api_key
            and self.config.observer_model
        ):
            return self._native_plan(
                trigger=trigger,
                signal_payload=signal_payload,
                reason="llm_planner_unconfigured",
            )
        payload = redact_for_observer(
            {
                "trigger": trigger.to_dict(),
                "signal_summary": {
                    "signal_type": signal_payload.get("signal_type"),
                    "service": signal_payload.get("service"),
                    "source": signal_payload.get("source"),
                    "sections_present": sorted(
                        key for key in ("node", "execution", "consensus", "storage", "rpc", "logs")
                        if isinstance(signal_payload.get(key), dict)
                    ),
                },
                "allowed_probe_names": list(known_reth_probe_names()),
                "native_plan": fallback.to_dict(),
                "policy_excerpt": load_policy("reth-node.policy.json"),
            }
        )
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "You select read-only Reth investigation probes. Return JSON only: "
                    "{\"probe_names\":[...],\"objective\":\"...\",\"reason\":\"...\"}. "
                    "Only use allowed_probe_names. Do not invent tools or actions."
                ),
            ),
            ChatMessage(role="user", content=json.dumps(payload, indent=2, sort_keys=True)),
        ]
        try:
            response = chat_completion(
                base_url=self.config.observer_base_url,
                api_key=self.config.observer_api_key,
                model=self.config.observer_model,
                messages=messages,
                timeout_seconds=self.config.observer_timeout_seconds,
                response_format={"type": "json_object"},
                max_tokens=min(self.config.observer_max_tokens, 512),
                temperature=0.0,
                provider=self.config.observer_provider,
                prompt_cache_enabled=self.config.observer_prompt_cache_enabled,
                prompt_cache_mode=self.config.observer_prompt_cache_mode,
                prompt_cache_ttl=self.config.observer_prompt_cache_ttl,
            )
            parsed = json.loads(extract_message_content(response))
            raw_names = parsed.get("probe_names")
            if not isinstance(raw_names, list) or not raw_names:
                raise ValueError("llm planner did not return probe_names")
            names = sanitize_probe_names(
                tuple(str(item) for item in raw_names),
                max_probes=self.config.reth_investigation_max_probes,
            )
            if not names:
                raise ValueError("llm planner returned no allowed probes")
            plan = InvestigationPlan(
                plan_id=f"plan_reth_{trigger.trigger_id}_{uuid4().hex[:8]}",
                trigger_id=trigger.trigger_id,
                created_at=_now_iso(),
                objective=str(parsed.get("objective") or fallback.objective),
                probe_budget={
                    "max_probes": self.config.reth_investigation_max_probes,
                    "max_total_latency_ms": int(self.config.reth_investigation_budget_seconds * 1000),
                    "per_probe_timeout_ms": int(self.config.reth_investigation_probe_timeout_seconds * 1000),
                    "mode": "reth_llm",
                    "planner": "llm",
                    "planner_reason": str(parsed.get("reason") or ""),
                },
                probes=build_probe_dicts(names),
            )
            plan.validate()
            return plan
        except Exception as exc:
            return self._native_plan(
                trigger=trigger,
                signal_payload=signal_payload,
                reason=f"llm_planner_fallback:{type(exc).__name__}",
            )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
