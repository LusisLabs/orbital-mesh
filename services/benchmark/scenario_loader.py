from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from .models import BenchmarkScenario


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCENARIO_ROOT = REPO_ROOT / "benchmarks" / "scenarios"
DEFAULT_SIGNAL_FIXTURE_ROOT = REPO_ROOT / "fixtures" / "signals"


def load_suite(
    suite: str = "golden",
    *,
    scenario_root: Path | None = None,
    scenario_ids: set[str] | None = None,
) -> list[BenchmarkScenario]:
    suite_dir = (scenario_root or DEFAULT_SCENARIO_ROOT) / suite
    if not suite_dir.exists():
        raise FileNotFoundError(f"benchmark suite not found: {suite_dir}")
    scenarios: list[BenchmarkScenario] = []
    for path in sorted(suite_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        scenario = BenchmarkScenario.from_dict(payload)
        if scenario_ids is not None and scenario.scenario_id not in scenario_ids:
            continue
        scenarios.append(scenario)
    if not scenarios:
        raise ValueError(f"benchmark suite {suite!r} did not load any scenarios")
    return scenarios


def load_signal(scenario: BenchmarkScenario, *, fixture_root: Path | None = None) -> dict[str, Any]:
    if scenario.raw_signal is not None:
        return dict(scenario.raw_signal)
    if scenario.signal_fixture is None:
        raise ValueError(f"{scenario.scenario_id} has no signal fixture")
    path = (fixture_root or DEFAULT_SIGNAL_FIXTURE_ROOT) / scenario.signal_fixture
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
