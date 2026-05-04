from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ANOMALY_RE = re.compile(
    r"\b(error|exception|fail(?:ed|ure)?|fatal|critical|timeout|unavailable|denied|corrupt)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LoghubExtractionConfig:
    dataset: str
    input_path: Path
    output_dir: Path
    max_scenarios: int = 25
    context_lines: int = 3
    service: str = "loghub-service"
    environment: str = "offline-benchmark"


def extract_loghub_scenarios(config: LoghubExtractionConfig) -> list[Path]:
    """Extract deterministic benchmark scenarios from a local Loghub checkout.

    The extractor intentionally reads local files only. Fetching Loghub or any
    other public corpus belongs outside this function so benchmark runs remain
    reproducible in offline CI.
    """
    if not config.input_path.exists():
        raise FileNotFoundError(f"Loghub input path not found: {config.input_path}")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for log_path in _iter_log_files(config.input_path):
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for index, line in enumerate(lines):
            if not ANOMALY_RE.search(line):
                continue
            scenario_number = len(written) + 1
            scenario = _scenario_from_log_line(config, log_path, lines, index, scenario_number)
            output_path = config.output_dir / f"{scenario['scenario_id']}.json"
            output_path.write_text(json.dumps(scenario, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            written.append(output_path)
            if len(written) >= config.max_scenarios:
                return written
    return written


def _iter_log_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(item for item in path.rglob("*") if item.is_file() and item.suffix.lower() in {"", ".log", ".txt"})


def _scenario_from_log_line(
    config: LoghubExtractionConfig,
    log_path: Path,
    lines: list[str],
    index: int,
    scenario_number: int,
) -> dict[str, Any]:
    start = max(index - config.context_lines, 0)
    end = min(index + config.context_lines + 1, len(lines))
    context = lines[start:end]
    line = lines[index]
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    scenario_id = f"loghub_{_slug(config.dataset)}_{scenario_number:04d}"
    return {
        "scenario_id": scenario_id,
        "title": f"Loghub anomaly extraction: {config.dataset} line {index + 1}",
        "suite": "loghub",
        "expected_decisions": ["escalate"],
        "unsafe_decisions": [
            "disable_flag",
            "reduce_rollout",
            "restart_deployment",
            "rollback_deployment",
            "restart_systemd_service",
            "investigate_and_patch",
        ],
        "required_evidence_kinds": ["loghub", "log_anomaly"],
        "acceptable_probe_names": ["trigger_signature_scan", "evidence_sufficiency"],
        "expected_root_cause": "log_anomaly",
        "tags": ["loghub", "log_anomaly", _slug(config.dataset)],
        "source": {
            "corpus": "loghub",
            "dataset": config.dataset,
            "path": str(log_path),
            "line": index + 1,
            "context_start_line": start + 1,
            "context_end_line": end,
        },
        "raw_signal": {
            "signal_type": "otel_metric_regression",
            "signal_id": f"sig_{scenario_id}",
            "observed_at": observed_at,
            "environment": config.environment,
            "service": config.service,
            "endpoint": f"loghub/{_slug(config.dataset)}",
            "comparison_window": {"baseline": "PT1H", "observed": "PT5M"},
            "source": "otel_collector_alert",
            "metric_regression": {
                "metric_name": "log_error_rate",
                "baseline_value": 0.001,
                "observed_value": 0.12,
                "delta_pct": 11900.0,
                "unit": "ratio",
                "attributes": {
                    "corpus": "loghub",
                    "dataset": config.dataset,
                    "line": index + 1,
                    "sample_size": max(len(lines), 1),
                },
            },
            "related_context": {
                "loghub_dataset": config.dataset,
                "loghub_file": str(log_path),
                "loghub_line": index + 1,
                "log_anomaly": line,
                "log_context": context,
                "incident_credentials_available": False,
                "feature_flag_credentials_available": False,
                "audit_logging_available": True,
            },
        },
    }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "dataset"
