"""Native rule-based probe selector for the investigation loop.

The selector is the shared substrate between deterministic domain logic
and a future LLM planner: rule packs describe what evidence is valuable,
while the generic selector turns the first eligible rule into a normal
``ToolCall`` for the existing registry / critic / loop pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable, Protocol, Sequence

from .contracts import InvestigationLoopState, LoopDecision, ToolDefinition, _stable_args_signature
from .registry import make_call


class RankedCauseLike(Protocol):
    root_cause: str
    confidence: float
    matched_patterns: tuple[str, ...]


RootCauseRanker = Callable[[Iterable[str]], Sequence[RankedCauseLike]]
RulePredicate = Callable[["ObservationIndex"], bool]
RuleArgsBuilder = Callable[["ObservationIndex"], dict[str, Any]]
RuleReasonBuilder = Callable[["ObservationIndex"], str]


@dataclass(frozen=True)
class RootCauseCandidate:
    root_cause: str
    confidence: float
    matched_patterns: tuple[str, ...]
    supporting_tools: tuple[str, ...]

    def to_dict(self, *, rank: int) -> dict[str, Any]:
        return {
            "rank": rank,
            "root_cause": self.root_cause,
            "confidence": self.confidence,
            "matched_patterns": list(self.matched_patterns),
            "supporting_tools": list(self.supporting_tools),
            "citation_ids": [f"rca_ontology:{self.root_cause}"],
        }


@dataclass(frozen=True)
class ObservationIndex:
    """Derived signal view over the mutable loop state."""

    state: InvestigationLoopState
    trigger_context: dict[str, Any]
    called_tool_names: frozenset[str]
    call_signatures: frozenset[tuple[str, str, str]]
    observed_text: tuple[str, ...]
    observed_tool_text: tuple[tuple[str, str], ...]
    haystack: str
    root_cause_candidates: tuple[RootCauseCandidate, ...]

    @classmethod
    def from_state(
        cls,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
        root_cause_ranker: RootCauseRanker | None = None,
    ) -> "ObservationIndex":
        observed_text = tuple(state.observed_text)
        observed_tool_text = tuple(
            (result.tool_name, result.output_summary)
            for result in state.tool_results
            if result.output_summary
        )
        ranked = tuple(root_cause_ranker(observed_text)) if root_cause_ranker is not None else ()
        candidates = tuple(
            RootCauseCandidate(
                root_cause=cause.root_cause,
                confidence=cause.confidence,
                matched_patterns=tuple(cause.matched_patterns),
                supporting_tools=_supporting_tools(cause.matched_patterns, observed_tool_text),
            )
            for cause in ranked
        )
        return cls(
            state=state,
            trigger_context=dict(trigger_context),
            called_tool_names=frozenset(call.tool_name for call in state.tool_calls),
            call_signatures=frozenset(state.call_signatures()),
            observed_text=observed_text,
            observed_tool_text=observed_tool_text,
            haystack="\n".join(observed_text).lower(),
            root_cause_candidates=candidates,
        )

    def tool_called(self, tool_name: str) -> bool:
        return tool_name in self.called_tool_names

    def output_for(self, tool_name: str) -> Any:
        for call, result in reversed(list(zip(self.state.tool_calls, self.state.tool_results))):
            if call.tool_name == tool_name:
                return result.output
        return None

    def summary_for(self, tool_name: str) -> str | None:
        for call, result in reversed(list(zip(self.state.tool_calls, self.state.tool_results))):
            if call.tool_name == tool_name and result.output_summary:
                return result.output_summary
        return None

    def contains_any(self, needles: tuple[str, ...]) -> bool:
        return any(needle in self.haystack for needle in needles)

    def top_root_cause(self) -> RootCauseCandidate | None:
        return self.root_cause_candidates[0] if self.root_cause_candidates else None


@dataclass(frozen=True)
class ProbeRule:
    """One typed native rule that can select a diagnostic probe."""

    name: str
    tool_name: str
    when: RulePredicate
    build_args: RuleArgsBuilder
    selection_reason: RuleReasonBuilder
    priority: int = 100
    confidence: float = 0.5


class ProbeRulePack(Protocol):
    domain: str
    tool_definitions: Sequence[ToolDefinition]
    rules: Sequence[ProbeRule]
    root_cause_ranker: RootCauseRanker | None
    sufficient_stop_reason: str
    exhausted_stop_reason: str

    def sufficient_root_cause(self, index: ObservationIndex) -> RootCauseCandidate | None: ...


class NativeProbeSelector:
    """LoopPlanner implementation backed by typed probe rules."""

    def __init__(
        self,
        rule_pack: ProbeRulePack,
        *,
        tool_definitions: Iterable[ToolDefinition] | None = None,
    ) -> None:
        self._rule_pack = rule_pack
        definitions = tuple(tool_definitions) if tool_definitions is not None else tuple(rule_pack.tool_definitions)
        self._tool_definitions = {
            definition.name: definition
            for definition in definitions
            if definition.domain == rule_pack.domain
        }

    @property
    def domain(self) -> str:
        return self._rule_pack.domain

    def plan(
        self,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
    ) -> LoopDecision:
        index = ObservationIndex.from_state(
            state=state,
            trigger_context=trigger_context,
            root_cause_ranker=self._rule_pack.root_cause_ranker,
        )
        candidate = self._rule_pack.sufficient_root_cause(index)
        if candidate is not None:
            return LoopDecision(
                action="stop",
                reason=self._rule_pack.sufficient_stop_reason,
                confidence=candidate.confidence,
                debug=_selector_debug(index, mode="native", stop_policy=self._rule_pack.sufficient_stop_reason),
            )
        for rule in sorted(self._rule_pack.rules, key=lambda item: item.priority):
            definition = self._tool_definitions.get(rule.tool_name)
            if definition is None or not rule.when(index):
                continue
            args = rule.build_args(index)
            signature = (definition.domain, definition.name, _stable_args_signature(args))
            if signature in index.call_signatures:
                continue
            reason = rule.selection_reason(index)
            return LoopDecision(
                action="continue",
                next_calls=(make_call(tool=definition, args=args, purpose=reason),),
                reason=reason,
                confidence=rule.confidence,
                debug=_selector_debug(index, mode="native", selected_rule=rule.name, selected_tool=definition.name),
            )
        return LoopDecision(
            action="stop",
            reason=self._rule_pack.exhausted_stop_reason,
            confidence=0.0,
            debug=_selector_debug(index, mode="native", stop_policy=self._rule_pack.exhausted_stop_reason),
        )


class LlmProbeSelector:
    """Gated LLM-backed selector behind the same LoopPlanner surface.

    The selector is inert unless ``enabled`` and ``decision_provider`` are both
    set. This lets callers run it in shadow mode without granting it authority
    over the actual probe loop.
    """

    def __init__(
        self,
        rule_pack: ProbeRulePack,
        *,
        tool_definitions: Iterable[ToolDefinition] | None = None,
        decision_provider: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        enabled: bool = False,
    ) -> None:
        self._rule_pack = rule_pack
        definitions = tuple(tool_definitions) if tool_definitions is not None else tuple(rule_pack.tool_definitions)
        # Index by qualified name (``{domain}:{name}``) so the LLM can
        # see and pick from every read-only tool the harness exposes
        # — CloudOps snapshot tools alongside always-on Prometheus,
        # AWS, kubectl, GitHub, etc. The legacy domain-only filter is
        # gone: the LLM should decide which source is most useful for
        # the current trigger, and the critic + registry enforce the
        # read-only floor regardless of which domain the call lands in.
        self._tool_definitions = {
            definition.qualified_name: definition
            for definition in definitions
            if definition.mutation_class == "read_only"
        }
        # Also keep a per-domain unqualified index so a planner that
        # passes ``tool_name`` without a domain (legacy LLM output, or
        # a model trained against a single-domain prompt) still resolves
        # against its own rule pack's domain. Cross-domain calls must
        # use qualified names — the dict-by-name path cannot disambiguate.
        self._unqualified_in_domain = {
            definition.name: definition
            for definition in definitions
            if definition.domain == rule_pack.domain and definition.mutation_class == "read_only"
        }
        self._decision_provider = decision_provider
        self._enabled = enabled

    @property
    def domain(self) -> str:
        return self._rule_pack.domain

    def plan(
        self,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
    ) -> LoopDecision:
        index = ObservationIndex.from_state(
            state=state,
            trigger_context=trigger_context,
            root_cause_ranker=self._rule_pack.root_cause_ranker,
        )
        base_debug = _selector_debug(index, mode="llm", enabled=self._enabled)
        if not self._enabled or self._decision_provider is None:
            return LoopDecision(action="stop", reason="llm_selector_disabled", confidence=0.0, debug=base_debug)
        try:
            proposed = self._decision_provider(_llm_selector_context(index, self._tool_definitions.values()))
        except Exception as exc:
            return LoopDecision(
                action="stop",
                reason=f"llm_selector_provider_error:{type(exc).__name__}",
                confidence=0.0,
                debug={**base_debug, "error": str(exc)},
            )
        action = str(proposed.get("action") or "stop")
        confidence = float(proposed.get("confidence") or 0.0)
        reason = str(proposed.get("reason") or "llm_selector_proposed_stop")
        if action != "continue":
            return LoopDecision(action="stop", reason=reason, confidence=confidence, debug={**base_debug, "proposal": proposed})
        # Resolve the LLM-proposed tool. Two acceptable shapes from the
        # model:
        #   1. ``tool_name="cloudops:GetResources"`` — qualified, the
        #      preferred form. Required for cross-domain calls.
        #   2. ``tool_name="GetResources"`` — unqualified, falls back
        #      to the planner's own rule_pack domain. Backward-compat
        #      for single-domain prompts.
        # Optional ``domain`` field is also honored; if present it
        # combines with ``tool_name`` to form a qualified key.
        tool_name = str(proposed.get("tool_name") or "")
        proposed_domain = str(proposed.get("domain") or "")
        if proposed_domain and ":" not in tool_name:
            qualified = f"{proposed_domain}:{tool_name}"
        elif ":" in tool_name:
            qualified = tool_name
        else:
            qualified = f"{self._rule_pack.domain}:{tool_name}"
        definition = self._tool_definitions.get(qualified) or self._unqualified_in_domain.get(tool_name)
        if definition is None:
            return LoopDecision(
                action="stop",
                reason="llm_selector_invalid_tool",
                confidence=0.0,
                debug={**base_debug, "proposal": proposed, "resolved_qualified": qualified},
            )
        args = proposed.get("args") if isinstance(proposed.get("args"), dict) else {}
        return LoopDecision(
            action="continue",
            next_calls=(make_call(tool=definition, args=args, purpose=reason),),
            reason=reason,
            confidence=confidence,
            debug={**base_debug, "proposal": proposed, "selected_tool": tool_name},
        )


class ShadowProbeSelector:
    """Run a shadow selector beside a primary selector without changing action."""

    def __init__(self, primary: Any, shadow: Any, *, shadow_name: str = "llm") -> None:
        self._primary = primary
        self._shadow = shadow
        self._shadow_name = shadow_name

    @property
    def domain(self) -> str:
        return getattr(self._primary, "domain", "")

    def plan(
        self,
        *,
        state: InvestigationLoopState,
        trigger_context: dict[str, Any],
    ) -> LoopDecision:
        primary = self._primary.plan(state=state, trigger_context=trigger_context)
        try:
            shadow = self._shadow.plan(state=state, trigger_context=trigger_context)
            shadow_payload = shadow.to_dict()
        except Exception as exc:
            shadow_payload = {"action": "stop", "reason": f"shadow_selector_error:{type(exc).__name__}", "error": str(exc)}
        return LoopDecision(
            action=primary.action,
            next_calls=primary.next_calls,
            reason=primary.reason,
            confidence=primary.confidence,
            debug={**primary.debug, "shadow_selector": self._shadow_name, "shadow_decision": shadow_payload},
        )


def _supporting_tools(
    matched_patterns: tuple[str, ...],
    observed_tool_text: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    tools = {
        tool_name
        for tool_name, output_text in observed_tool_text
        if any(pattern.lower() in output_text.lower() for pattern in matched_patterns)
    }
    return tuple(sorted(tools))


def _selector_debug(
    index: ObservationIndex,
    *,
    mode: str,
    selected_rule: str | None = None,
    selected_tool: str | None = None,
    stop_policy: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    debug: dict[str, Any] = {
        "selector_mode": mode,
        "called_tools": sorted(index.called_tool_names),
        "observed_text_count": len(index.observed_text),
        "root_cause_candidates": [
            candidate.to_dict(rank=rank)
            for rank, candidate in enumerate(index.root_cause_candidates[:3], start=1)
        ],
    }
    top = index.top_root_cause()
    debug["top_root_cause"] = top.to_dict(rank=1) if top is not None else None
    if selected_rule is not None:
        debug["selected_rule"] = selected_rule
    if selected_tool is not None:
        debug["selected_tool"] = selected_tool
    if stop_policy is not None:
        debug["stop_policy"] = stop_policy
    if enabled is not None:
        debug["enabled"] = enabled
    return debug


def _llm_selector_context(
    index: ObservationIndex,
    tool_definitions: Iterable[ToolDefinition],
) -> dict[str, Any]:
    return {
        "trigger_context": dict(index.trigger_context),
        "called_tools": sorted(index.called_tool_names),
        "observed_text": list(index.observed_text[-8:]),
        "root_cause_candidates": [
            candidate.to_dict(rank=rank)
            for rank, candidate in enumerate(index.root_cause_candidates[:3], start=1)
        ],
        "available_tools": [definition.to_dict() for definition in tool_definitions],
    }
