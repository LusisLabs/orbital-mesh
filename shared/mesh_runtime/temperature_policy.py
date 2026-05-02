from __future__ import annotations

from dataclasses import dataclass
from typing import Any


T_MIN = 0.05
T_MAX = 0.70


@dataclass(frozen=True)
class TemperatureInputs:
    novelty: float = 0.0
    ambiguity: float = 0.0
    search_need: float = 0.0
    risk: float = 0.0
    contract_strictness: float = 0.0
    prior_failure_similarity: float = 0.0

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "TemperatureInputs":
        return cls(
            novelty=_unit(payload.get("novelty", 0.0)),
            ambiguity=_unit(payload.get("ambiguity", 0.0)),
            search_need=_unit(payload.get("search_need", 0.0)),
            risk=_unit(payload.get("risk", 0.0)),
            contract_strictness=_unit(payload.get("contract_strictness", 0.0)),
            prior_failure_similarity=_unit(payload.get("prior_failure_similarity", 0.0)),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "novelty": self.novelty,
            "ambiguity": self.ambiguity,
            "search_need": self.search_need,
            "risk": self.risk,
            "contract_strictness": self.contract_strictness,
            "prior_failure_similarity": self.prior_failure_similarity,
        }


def generator_temperature(inputs: TemperatureInputs | dict[str, Any]) -> dict[str, Any]:
    normalized = inputs if isinstance(inputs, TemperatureInputs) else TemperatureInputs.from_mapping(inputs)
    raw = (
        0.20
        + 0.20 * normalized.novelty
        + 0.15 * normalized.ambiguity
        + 0.20 * normalized.search_need
        - 0.30 * normalized.risk
        - 0.25 * normalized.contract_strictness
        - 0.25 * normalized.prior_failure_similarity
    )
    temperature = clamp_temperature(raw)
    return {
        "temperature": temperature,
        "raw_temperature": raw,
        "min": T_MIN,
        "max": T_MAX,
        "inputs": normalized.to_dict(),
        "policy": "dynamic_generator_v1",
        "acceptance": "deterministic_verifier_required",
    }


def fixed_temperature(component: str) -> dict[str, Any]:
    component_policy = {
        "verifier": 0.0,
        "judge": 0.0,
        "scorer": 0.0,
        "tool_executor": 0.10,
        "memory_distiller": 0.20,
    }
    temperature = component_policy.get(component, 0.0)
    return {
        "component": component,
        "temperature": temperature,
        "policy": "fixed_component_v1",
        "acceptance": "deterministic_verifier_required",
    }


def clamp_temperature(value: float) -> float:
    return max(T_MIN, min(T_MAX, float(value)))


def _unit(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))
