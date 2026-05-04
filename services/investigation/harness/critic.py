"""Pre-flight critic for harness loop decisions.

The critic is the first defense between an LLM (or any planner) and the
tool registry. It rejects:

* Tools that are not registered.
* Tools whose mutation class is not on the allow-list (read-only by
  default — mutating tools never reach the investigation loop).
* Calls whose args don't satisfy the tool's declared schema.
* Calls that duplicate an already-executed call (same domain + name +
  args). Repeated useless calls drain budget without new evidence.

Args validation is intentionally minimal: the schema is a flat
``{field_name: {"type": str, "required": bool}}`` shape. Adding a real
JSONSchema validator would buy correctness for nothing today; tools
have small, predictable arg shapes and a richer schema is a future
slice.
"""

from __future__ import annotations

from typing import Any, Iterable

from .contracts import (
    InvestigationLoopState,
    LoopDecision,
    LoopRejection,
    ToolCall,
    _stable_args_signature,
)
from .registry import ToolRegistry


_TYPE_NAME_TO_CHECK = {
    "str": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "dict": lambda v: isinstance(v, dict),
    "list": lambda v: isinstance(v, list),
    "any": lambda v: True,
}


class LoopCritic:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        allowed_mutation_classes: Iterable[str] = ("read_only",),
    ) -> None:
        self.registry = registry
        self._allowed = frozenset(allowed_mutation_classes)

    def review(
        self,
        state: InvestigationLoopState,
        decision: LoopDecision,
    ) -> tuple[LoopDecision, list[LoopRejection]]:
        """Filter ``decision`` to only the calls that pass critic checks.

        Returns the (possibly-narrowed) decision plus the per-call
        rejection records so the caller can attach them to loop state.
        If every call in a non-empty decision is rejected, the decision
        is converted to ``stop`` so the loop doesn't spin.
        """
        approved: list[ToolCall] = []
        rejections: list[LoopRejection] = []
        seen = state.call_signatures()
        for call in decision.next_calls:
            rejection = self._check_call(call, seen)
            if rejection is not None:
                rejections.append(rejection)
                continue
            approved.append(call)
            seen.add((call.domain, call.tool_name, _stable_args_signature(call.args)))
        if decision.next_calls and not approved:
            return (
                LoopDecision(
                    action="stop",
                    next_calls=(),
                    reason="critic_rejected_all_calls",
                    confidence=decision.confidence,
                ),
                rejections,
            )
        return (
            LoopDecision(
                action=decision.action,
                next_calls=tuple(approved),
                reason=decision.reason,
                confidence=decision.confidence,
            ),
            rejections,
        )

    def _check_call(
        self,
        call: ToolCall,
        seen_signatures: set[tuple[str, str, str]],
    ) -> LoopRejection | None:
        entry = self.registry.get(call.domain, call.tool_name)
        if entry is None:
            return _rejection(call, "tool_not_registered")
        definition, _ = entry
        if definition.mutation_class not in self._allowed:
            return _rejection(
                call,
                "mutation_class_not_allowed",
                {"mutation_class": definition.mutation_class, "allowed": sorted(self._allowed)},
            )
        signature = (call.domain, call.tool_name, _stable_args_signature(call.args))
        if signature in seen_signatures:
            return _rejection(call, "duplicate_call")
        violations = _validate_args(call.args, definition.args_schema)
        if violations:
            return _rejection(call, "invalid_args", {"violations": violations})
        return None


def _rejection(call: ToolCall, reason: str, details: dict[str, Any] | None = None) -> LoopRejection:
    return LoopRejection(
        call_id=call.call_id,
        qualified_name=call.qualified_name,
        reason=reason,
        details=dict(details or {}),
    )


def _validate_args(args: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Return human-readable reasons the args don't satisfy ``schema``."""
    violations: list[str] = []
    for field_name, field_schema in (schema or {}).items():
        if not isinstance(field_schema, dict):
            continue
        required = bool(field_schema.get("required"))
        present = field_name in args
        if required and not present:
            violations.append(f"missing required arg {field_name!r}")
            continue
        if not present:
            continue
        expected_type = str(field_schema.get("type") or "any").lower()
        check = _TYPE_NAME_TO_CHECK.get(expected_type, _TYPE_NAME_TO_CHECK["any"])
        value = args[field_name]
        if value is None and not field_schema.get("nullable"):
            violations.append(f"{field_name} must not be null")
            continue
        if value is not None and not check(value):
            violations.append(f"{field_name} must be {expected_type}, got {type(value).__name__}")
    extra = {key for key in args if key not in (schema or {})}
    if extra and schema:
        violations.append(f"unknown args: {sorted(extra)}")
    return violations
