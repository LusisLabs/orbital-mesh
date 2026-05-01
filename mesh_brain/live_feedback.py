from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .data_plane import MeshBrainDataRefinery, SourceRecord
from .runtime import stable_digest, utc_now


@dataclass(frozen=True)
class LiveFeedbackResult:
    status: str
    tenant_id: str
    source_manifest_id: str
    output_directory: str
    row_count: int
    artifact_paths: dict[str, str]
    report: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def export_live_feedback_dataset(
    *,
    live_summary: dict[str, Any],
    output_directory: str | Path,
    tenant_id: str | None = None,
) -> LiveFeedbackResult:
    resolved_tenant_id = str(tenant_id or live_summary.get("tenant_id") or "tenant_a")
    release_decision = _release_decision(live_summary)
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)
    source_manifest_id = f"mesh_brain_live_feedback_{stable_digest(_feedback_fingerprint(live_summary))[:12]}"
    if release_decision in {"canary", "promote", "pass"}:
        skipped = LiveFeedbackResult(
            status="skipped",
            tenant_id=resolved_tenant_id,
            source_manifest_id=source_manifest_id,
            output_directory=str(output_path),
            row_count=0,
            artifact_paths={},
            report={
                "reason": "release_passed",
                "release_decision": release_decision,
                "accepted_records": 0,
                "row_count": 0,
            },
        )
        (output_path / "live_feedback_report.json").write_text(
            json.dumps(skipped.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return skipped

    record = SourceRecord(
        tenant_id=resolved_tenant_id,
        source="mesh_brain_live_release_feedback",
        content=_feedback_content(live_summary),
        provenance_pointer=str(live_summary.get("request_id") or live_summary.get("completion_id") or "live_smoke"),
        timestamp=utc_now(),
        outcome="blocked" if release_decision == "block" else "manual_review",
        metadata={
            "release_decision": release_decision,
            "model": live_summary.get("model"),
            "requested_model": live_summary.get("requested_model"),
            "backend_name": live_summary.get("backend_name"),
            "hardware_tier": live_summary.get("hardware_tier"),
            "gate_reasons": _reasons(live_summary.get("gate")),
            "response_eval_reasons": _reasons(live_summary.get("response_eval")),
            "judge_eval_reasons": _reasons(live_summary.get("judge_eval")),
            "deployment_status": (live_summary.get("deployment_record") or {}).get("status")
            if isinstance(live_summary.get("deployment_record"), dict)
            else None,
        },
        audit_only=False,
    )
    result = MeshBrainDataRefinery(tenant_id=resolved_tenant_id, chunk_chars=1200).build(
        source_manifest_id=source_manifest_id,
        records=[record],
        output_directory=output_path,
    )
    feedback = LiveFeedbackResult(
        status="exported",
        tenant_id=resolved_tenant_id,
        source_manifest_id=source_manifest_id,
        output_directory=str(output_path),
        row_count=result.report.row_count,
        artifact_paths=result.report.output_files,
        report=result.report.to_dict(),
    )
    (output_path / "live_feedback_report.json").write_text(
        json.dumps(feedback.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return feedback


def _release_decision(live_summary: dict[str, Any]) -> str:
    release_gate = live_summary.get("release_gate")
    if isinstance(release_gate, dict) and release_gate.get("decision"):
        return str(release_gate["decision"])
    if live_summary.get("status"):
        return str(live_summary["status"])
    return "manual_review"


def _feedback_content(live_summary: dict[str, Any]) -> str:
    release_decision = _release_decision(live_summary)
    sections = [
        f"Mesh Brain live release decision: {release_decision}.",
        f"Model: {live_summary.get('model')} requested_model: {live_summary.get('requested_model')}.",
        f"Backend: {live_summary.get('backend_name')} hardware_tier: {live_summary.get('hardware_tier')}.",
        f"Content preview: {live_summary.get('content_preview')}.",
        f"Smoke gate reasons: {', '.join(_reasons(live_summary.get('gate'))) or 'none'}.",
        f"Response eval reasons: {', '.join(_reasons(live_summary.get('response_eval'))) or 'none'}.",
        f"Judge eval reasons: {', '.join(_reasons(live_summary.get('judge_eval'))) or 'none'}.",
        "Expected recovery: cite evidence, avoid unsupported tool execution claims, propose bounded reversible remediation, and require operator approval for protected actions.",
    ]
    return " ".join(sections)


def _feedback_fingerprint(live_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "request_id": live_summary.get("request_id"),
        "completion_id": live_summary.get("completion_id"),
        "model": live_summary.get("model"),
        "release_decision": _release_decision(live_summary),
        "content_preview": live_summary.get("content_preview"),
    }


def _reasons(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    reasons = value.get("reasons")
    if not isinstance(reasons, list):
        return []
    return [str(reason) for reason in reasons]
