from __future__ import annotations

import re
import time
from typing import Any

from .schema_validation import validate_payload


POSTMORTEM_REVIEW_SCHEMA = "postmortem-review.schema.json"
POSTMORTEM_REVIEW_VERSION = "mesh.postmortem_review.v1"
POSTMORTEM_REVIEW_VERDICTS = frozenset({"accepted", "needs_followup", "rejected"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def build_postmortem_review(
    *,
    run_id: str,
    review_id: str,
    reviewer: dict[str, Any],
    launcher_operator_id: str | None,
    verdict: str,
    findings: list[str],
    action_items: list[str],
    reviewed_export_id: str | None = None,
    reviewed_package_sha256: str | None = None,
    related_event_id: str | None = None,
) -> dict[str, Any]:
    if not run_id.strip():
        raise ValueError("run_id is required")
    if not review_id.strip():
        raise ValueError("review_id is required")
    normalized_verdict = verdict.strip().lower()
    if normalized_verdict not in POSTMORTEM_REVIEW_VERDICTS:
        raise ValueError(f"unsupported postmortem review verdict: {verdict}")
    reviewer_record = _operator_record(reviewer)
    launcher_id = launcher_operator_id.strip() if isinstance(launcher_operator_id, str) and launcher_operator_id.strip() else None
    independent = launcher_id is None or launcher_id != reviewer_record["operator_id"]
    if not independent:
        raise ValueError("postmortem reviewer must differ from launch operator")
    package_sha = reviewed_package_sha256.strip() if isinstance(reviewed_package_sha256, str) and reviewed_package_sha256.strip() else None
    if package_sha is not None and not _SHA256_RE.match(package_sha):
        raise ValueError("reviewed_package_sha256 must be a lowercase SHA-256 hex digest")
    packet = {
        "schema_version": POSTMORTEM_REVIEW_VERSION,
        "review_id": review_id.strip(),
        "run_id": run_id.strip(),
        "created_at": _timestamp(),
        "reviewer": reviewer_record,
        "launcher_operator_id": launcher_id,
        "independent_reviewer": independent,
        "verdict": normalized_verdict,
        "findings": _strings(findings),
        "action_items": _strings(action_items),
        "reviewed_export_id": reviewed_export_id.strip()
        if isinstance(reviewed_export_id, str) and reviewed_export_id.strip()
        else None,
        "reviewed_package_sha256": package_sha,
        "related_event_id": related_event_id,
    }
    validate_payload(POSTMORTEM_REVIEW_SCHEMA, packet)
    return packet


def _operator_record(operator: dict[str, Any]) -> dict[str, Any]:
    operator_id = str(operator.get("operator_id") or "").strip()
    if not operator_id:
        raise ValueError("operator_id is required")
    return {
        "operator_id": operator_id,
        "roles": sorted(_roles(operator.get("roles"))),
        "source": str(operator.get("source") or "proxy_header").strip(),
    }


def _roles(raw: Any) -> set[str]:
    if isinstance(raw, str):
        return {item.strip() for item in raw.split(",") if item.strip()}
    if isinstance(raw, list):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def _strings(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
