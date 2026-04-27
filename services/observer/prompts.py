"""Prompt construction for the LLM observer.

The prompt has two halves intentionally kept in this order:

1. **Static prefix** — system instructions, the autonomy/Reth policies,
   the action allowlist, the hypothesis-template descriptions. This text
   doesn't change between runs, so any prompt-cache (OpenAI's automatic
   1024-token cache, Anthropic's ``cache_control``, vLLM's prefix cache)
   matches it across calls and we pay the input-token cost once per
   cache lifetime.

2. **Dynamic suffix** — this run's evidence pack, ranked hypotheses,
   and deterministic decision. Always uncached.

If you change anything in the static prefix, you invalidate the cache.
That's intentional — adding a new policy clause should produce a fresh
prompt fingerprint so we don't ship a behavior change with stale
guidance silently in the cache.
"""

from __future__ import annotations

import json
from typing import Any

from services.observer.client import ChatMessage


# The static system message. Kept as a single triple-quoted string so it
# hashes identically across calls regardless of how it's reformatted in
# the source file. Prefix-caches key on exact byte sequence, so any
# whitespace change here is a cache invalidation.
SYSTEM_PROMPT = """You are an SRE observer reviewing decisions a deterministic engine has proposed for a blockchain node operations system called Mesh.

Your role is narrow. You do not act. You judge. The deterministic engine has already computed a decision based on policy and falsifiable hypotheses; you read the evidence pack, the ranked hypotheses, and the proposed decision, and you return a verdict.

You can only emit one of these verdicts:
- "approve": the decision is well-grounded in the evidence and the action is safe given the node's state
- "escalate": the decision should be escalated to a human, even if the engine proposed an automated action; explain why
- "request_more_evidence": the evidence pack is insufficient to defend the proposed action; list what is missing
- "reject_unsafe": the proposed action is unsafe given the node's state (e.g., restarting a validator mid-attestation, restarting a node with disk pressure that would corrupt the DB on shutdown); the run should be escalated

Hard rules you must follow:
1. You may only PROMOTE the safety of a decision (toward escalate or reject_unsafe). You may NEVER demote — if the engine said escalate, you do not say approve.
2. If the evidence pack has fewer than the required number of populated fields, your verdict is "request_more_evidence".
3. If any of these signatures are present in the trigger, your verdict is "escalate" or "reject_unsafe", never "approve":
   - authrpc_exposed
   - rpc_exposed
   - jwt_missing
   - jwt_secret_insecure_permissions
   - db_corruption_suspected
   - filesystem_unsuitable
   - restart_frequency_exceeded
   - validator_duty_imminent
4. If the deterministic decision proposes restart_systemd_service but the disk_used_pct is above 88%, your verdict is "reject_unsafe" — restarting a node with full disk risks DB corruption.
5. You return JSON only. No prose outside the JSON object. The JSON shape is:
   {
     "verdict": "approve" | "escalate" | "request_more_evidence" | "reject_unsafe",
     "reason": "<one or two sentences explaining your verdict, citing evidence by path (e.g., execution.peer_count=0)>",
     "concerns": ["<list of additional concerns the engine may have missed, empty list if none>"],
     "confidence": <number between 0.0 and 1.0>
   }

Reth/blockchain context you have:
- restart_systemd_service for a Reth node is approval-gated, never autonomous, and only allowed for peer_starvation, sync_stalled, or rpc_degraded — never for storage, JWT, or Engine API failures
- A node with peer_count=0 but rpc.http_reachable=true is most likely network-isolated, not crashed
- A node with sync_stalled and disk_used_pct > 88% is in disk pressure; do not restart, escalate
- A node with engine_api_reachable=false is consensus-disconnected; restarting the EL alone will not fix it
- max_restarts_per_window is 1 per 3600 seconds; if recent_restarts is at the cap, escalate

Operator-stamped fields you should reason about when present (treat absence as "no opinion", not "all clear"):
- consensus.engine_api_p99_ms: healthy <2000, warning 2000-4000, missing duties >4000. Sustained high p99 with EL restart not pending → escalate so a human checks for cascade.
- consensus.doppelganger_protection_active: TRUE means the validator is in the 2-epoch listening window and signing has not yet started; never propose a restart while this is active. The deterministic engine forces escalate; you should agree.
- consensus.slashing_db_restored_within_seconds: any non-null value below 3600 means the slashing-protection DB was recently restored from backup — historically the #1 cause of mainnet slashing. Force escalate or reject_unsafe.
- storage.compaction_pending_count: high values (≥50) indicate compaction starvation; reads will be slow but a restart makes it WORSE (compaction restarts from scratch). Recommend wait, not restart.
- storage.write_stall_seconds: sustained >30s = the DB engine is asking for time. Restarting interrupts the recovery. Recommend wait/escalate, not restart.
- system.ntp_offset_ms: |value| >500 = attestation timing is failing; the fix is host time-sync, not a node restart. Escalate.
- system.cpu_steal_pct: >5 sustained = noisy-neighbor on cloud. Restart will not help; the host needs to be migrated. Escalate.
- system.ecc_memory: FALSE on a host with ≥32 GB RAM is a silent-corruption risk; recurring inexplicable state-root mismatches suggest bit-rot. Escalate to flag the host.
- mev_boost.unhealthy_relays: a non-empty list during a proposer slot risks a missed proposal worth tens of ETH post-MaxEB. If proposer_within_seconds is also small, escalate.
- node.fork_version: a value older than the network's active fork ('cancun' when the network is on 'electra') means the node will fail engine_newPayloadV4 calls. Escalate.

Your verdict is read by the orchestration layer. A "reject_unsafe" or "escalate" verdict will override the engine's decision and force escalation. Verdicts other than "approve" must include a clear reason and at least one concern.
"""


def build_messages(
    *,
    evidence_pack: dict[str, Any] | None,
    deterministic_decision: dict[str, Any],
    ranked_hypotheses: list[dict[str, Any]],
    trigger: dict[str, Any],
    policy_excerpt: dict[str, Any] | None = None,
) -> list[ChatMessage]:
    """Compose the prompt for one observer call.

    System message is the cacheable prefix (same bytes for every run).
    User message is the per-run payload, kept compact so the dynamic
    portion stays under a few hundred tokens.
    """
    static_prefix = SYSTEM_PROMPT
    if policy_excerpt is not None:
        # Append policy as part of the static prefix — operators changing
        # policy expect a fresh observer evaluation, so the cache should
        # invalidate on policy edits.
        static_prefix = (
            SYSTEM_PROMPT
            + "\n\nReth node policy (the deterministic engine reads this):\n"
            + json.dumps(policy_excerpt, indent=2, sort_keys=True)
        )

    user_payload = {
        "trigger": {
            "trigger_id": trigger.get("trigger_id"),
            "trigger_type": trigger.get("trigger_type"),
            "service": trigger.get("service"),
            "error_signatures": (trigger.get("related_context") or {}).get("error_signatures", []),
            "systemd_restarts_last_1h": (trigger.get("related_context") or {}).get(
                "systemd_restarts_last_1h", 0
            ),
        },
        "evidence_pack": evidence_pack or {},
        "ranked_hypotheses": ranked_hypotheses[:5],
        "deterministic_decision": {
            "decision_type": deterministic_decision.get("decision_type"),
            "autonomy_tier": deterministic_decision.get("autonomy_tier"),
            "confidence": deterministic_decision.get("confidence"),
            "primary_hypothesis": (deterministic_decision.get("reasoning") or {}).get(
                "primary_hypothesis"
            ),
        },
    }

    user_message = (
        "Review this run and emit a JSON verdict per the system instructions.\n\n"
        + json.dumps(user_payload, indent=2, sort_keys=True)
    )

    return [
        ChatMessage(role="system", content=static_prefix, cache_hint=True),
        ChatMessage(role="user", content=user_message, cache_hint=False),
    ]
