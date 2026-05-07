from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .run_export_retrieval import verify_run_export_retrieval
from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
EVALUATION_KIT_PACKET_SCHEMA = "evaluation-kit-packet.schema.json"
EVALUATION_KIT_PACKET_VERSION = "mesh.evaluation_kit_packet.v1"
EVALUATION_KIT_VERIFICATION_VERSION = "mesh.evaluation_kit_packet_verification.v1"
REQUIRED_BENCHMARK_ARTIFACTS = frozenset(
    {
        "benchmark.json",
        "scorecard.json",
        "scenario-results.jsonl",
        "report.md",
    }
)


def load_evaluation_kit_packet(path: str | Path | None) -> dict[str, Any] | None:
    if not path:
        return None
    packet_path = _resolve_path(path)
    if not packet_path.exists():
        return None
    payload = json.loads(packet_path.read_text(encoding="utf-8"))
    validate_payload(EVALUATION_KIT_PACKET_SCHEMA, payload)
    return payload


def verify_evaluation_kit_packet(path: str | Path | None) -> dict[str, Any]:
    errors: list[str] = []
    try:
        packet = load_evaluation_kit_packet(path)
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        packet = None
        errors.append(f"packet_invalid:{type(exc).__name__}")
    if packet is None:
        errors.append("packet_missing")
        sample_export: dict[str, Any] = {}
        benchmark_packet: dict[str, Any] = {}
    else:
        sample_export = packet.get("sample_export") if isinstance(packet.get("sample_export"), dict) else {}
        benchmark_packet = packet.get("benchmark_packet") if isinstance(packet.get("benchmark_packet"), dict) else {}

    package_path = _resolve_optional(sample_export.get("package_path"))
    archive_path = _resolve_optional(sample_export.get("archive_path"))
    retrieval = verify_run_export_retrieval(package_path=package_path, archive_path=archive_path)
    benchmark_entrypoint = _resolve_optional(benchmark_packet.get("harness_entrypoint"))
    scenario_ids = [str(item) for item in benchmark_packet.get("scenario_ids", []) if str(item).strip()]
    expected_artifacts = {str(item) for item in benchmark_packet.get("expected_artifacts", [])}
    checks = {
        "packet_present": packet is not None,
        "packet_version_valid": bool(packet and packet.get("schema_version") == EVALUATION_KIT_PACKET_VERSION),
        "sample_export_retrieval_passed": retrieval.get("status") == "pass",
        "sample_package_sha_matches": _sha_matches(package_path, str(sample_export.get("package_sha256") or "")),
        "sample_archive_sha_matches": _sha_matches(archive_path, str(sample_export.get("archive_sha256") or "")),
        "benchmark_harness_present": bool(benchmark_entrypoint and benchmark_entrypoint.is_file()),
        "benchmark_suite_golden": benchmark_packet.get("suite") == "golden",
        "benchmark_scenarios_present": bool(scenario_ids) and all(
            (REPO_ROOT / "benchmarks" / "scenarios" / "golden" / f"{scenario_id}.json").is_file()
            for scenario_id in scenario_ids
        ),
        "benchmark_command_present": bool(benchmark_packet.get("command")),
        "benchmark_expected_artifacts_present": REQUIRED_BENCHMARK_ARTIFACTS.issubset(expected_artifacts),
    }
    blockers = sorted(name for name, passed in checks.items() if not passed)
    return {
        "schema_version": EVALUATION_KIT_VERIFICATION_VERSION,
        "status": "pass" if not errors and not blockers else "fail",
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "packet_path": str(_resolve_path(path)) if path else None,
        "packet_version": packet.get("schema_version") if packet else None,
        "sample_run_id": sample_export.get("run_id"),
        "sample_package_path": str(package_path) if package_path else None,
        "sample_archive_path": str(archive_path) if archive_path else None,
        "benchmark_suite": benchmark_packet.get("suite"),
        "benchmark_scenario_ids": scenario_ids,
        "retrieval": retrieval,
        "checks": checks,
        "blockers": blockers,
        "errors": errors,
    }


def _resolve_optional(path: Any) -> Path | None:
    raw = str(path or "").strip()
    if not raw:
        return None
    return _resolve_path(raw)


def _resolve_path(path: str | Path | None) -> Path:
    p = Path(path or "")
    if p.is_absolute():
        return p
    return (REPO_ROOT / p).resolve()


def _sha_matches(path: Path | None, expected: str) -> bool:
    return bool(path and path.is_file() and expected and hashlib.sha256(path.read_bytes()).hexdigest() == expected)
