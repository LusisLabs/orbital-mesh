"""Shared execution-result type for CLI-backed orchestrator adapters.

Goose and Hermes adapters previously each defined an identical
``*ExecutionResult`` dataclass. They are collapsed here to one canonical
type so downstream code can branch on status/failure without caring
which CLI produced the record. The legacy class names remain exposed
(as aliases) to avoid a large API churn in callers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CliExecutionResult:
    status: str
    external_refs: dict[str, object]
    failure: dict | None = None
    retryable: bool = False
