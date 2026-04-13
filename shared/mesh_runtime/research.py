from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?</think>\s*", re.IGNORECASE | re.DOTALL)
_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<text>.+?)\s*$")

_DOC_GLOBS = (
    "synthesis/*.md",
    "results/*.md",
    "notes/*.md",
)

_ANCHOR_DEFINITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "stage_machine",
        "Explicit stage graph and run events",
        ("firstslicepipeline", "run_events", "event_chain", "stage_event_count", "feedback_recorded"),
    ),
    (
        "evaluation_gate",
        "Evaluation gates execution",
        ("evaluation_recommendation", "evaluation_passed", "execution_status", "human_review", "rejected"),
    ),
    (
        "operator_control",
        "Operator steering and bounded approval",
        ("operator steering", "approval gate", "approve", "override", "pause"),
    ),
    (
        "auditability",
        "Auditability through vault and Merkle records",
        ("audit", "merkle", "vault", "proof", "provenance"),
    ),
    (
        "signal_contract",
        "Multiple signal families share one contract",
        ("feature_flag", "kubernetes", "trigger_type", "signals in", "bounded actions"),
    ),
    (
        "integration_modes",
        "Native, Promptfoo, Goose, and Hermes modes are separated",
        ("promptfoo", "goose", "hermes", "native", "orchestration_mode", "evaluation_mode"),
    ),
)

_REPO_GROUNDING_TERMS = tuple(sorted({term for _, _, terms in _ANCHOR_DEFINITIONS for term in terms}))

_OFF_DOMAIN_TERMS = (
    "wireless",
    "wi-fi",
    "wifi",
    "cabling",
    "coverage extension",
    "network coverage",
    "access point",
    "multi-hop routing",
    "sd-wan",
    "lan/wlan",
    "eero",
    "aruba",
    "cisco",
    "throughput increase",
    "rtt increases",
)

_UNSUPPORTED_CLAIM_TERMS = (
    "#1",
    "number one",
    "industry-leading",
    "best-in-class",
    "fastest",
    "guaranteed roi",
    "universal latency",
)

_LIMIT_TERMS = (
    "n=3",
    "sample size",
    "no comparative",
    "not evidenced",
    "cannot defensibly",
    "does not support",
)


def sanitize_research_markdown(text: str) -> str:
    """Remove model reasoning blocks before research markdown reaches API/UI callers."""
    return _THINK_BLOCK_RE.sub("", text).strip()


def build_research_session_intelligence(
    session_dir: Path,
    manifest: dict[str, Any] | None = None,
    *,
    max_chars: int = 320_000,
) -> dict[str, Any]:
    documents, redacted_blocks = _read_research_documents(session_dir, max_chars=max_chars)
    text = "\n\n".join(doc["text"] for doc in documents)
    manifest_question = str((manifest or {}).get("question", ""))
    combined = f"{manifest_question}\n\n{text}".lower()

    anchor_hits = _anchor_hits(combined)
    repo_terms = _term_hits(combined, _REPO_GROUNDING_TERMS)
    off_domain_terms = _term_hits(combined, _OFF_DOMAIN_TERMS)
    unsupported_terms = _term_hits(combined, _UNSUPPORTED_CLAIM_TERMS)
    limit_terms = _term_hits(combined, _LIMIT_TERMS)

    repo_grounding_score = min(1.0, len(repo_terms) / 10)
    off_domain_score = min(1.0, len(off_domain_terms) / 5)
    classification = _classify_grounding(repo_grounding_score, off_domain_score, anchor_hits)

    flags: list[str] = []
    if off_domain_terms:
        flags.append("off_domain_drift")
    if unsupported_terms:
        flags.append("unsupported_superlative_risk")
    if limit_terms:
        flags.append("evidence_scope_limit")
    if redacted_blocks:
        flags.append("reasoning_block_redacted")
    if not documents:
        flags.append("no_research_markdown")

    return {
        "classification": classification,
        "repo_grounding_score": round(repo_grounding_score, 2),
        "off_domain_score": round(off_domain_score, 2),
        "flags": flags,
        "repo_terms": repo_terms[:20],
        "off_domain_terms": off_domain_terms[:20],
        "unsupported_claim_terms": unsupported_terms[:20],
        "evidence_limit_terms": limit_terms[:20],
        "anchors": anchor_hits,
        "extracted_claims": _extract_section_items(
            text,
            section_keywords=("key findings", "strongest findings", "insights"),
            fallback_keywords=("stage", "evaluation", "audit", "operator", "kubernetes", "merkle", "trigger"),
            limit=6,
        ),
        "extracted_risks": _extract_section_items(
            text,
            section_keywords=("risks", "unknowns", "gaps", "what this data does not support", "limits"),
            fallback_keywords=("risk", "unknown", "gap", "not support", "sample size", "unsupported"),
            limit=6,
        ),
        "extracted_actions": _extract_section_items(
            text,
            section_keywords=("recommended next action", "recommendations before public release", "immediate actions"),
            fallback_keywords=(
                "action",
                "mitigation",
                "publish",
                "document",
                "instrument",
                "add",
                "replace",
                "remove",
                "define",
                "validate",
                "adopt",
                "clarify",
                "create",
                "run ",
            ),
            limit=6,
            require_keyword_when_active=True,
            allow_fallback=False,
        ),
        "documents_read": [doc["path"] for doc in documents],
        "redacted_reasoning_blocks": redacted_blocks,
    }


def build_research_corpus_intelligence(root: Path, *, limit: int = 80) -> dict[str, Any]:
    if not root.is_dir():
        return {
            "sessions_analyzed": 0,
            "classification_counts": {},
            "recurring_flags": {},
            "accepted_anchors": [],
            "drift_sessions": [],
            "next_actions": [],
        }

    analyzed: list[dict[str, Any]] = []
    for session_dir in sorted((p for p in root.iterdir() if p.is_dir()), reverse=True)[:limit]:
        manifest = _read_manifest(session_dir)
        if manifest is None:
            continue
        intelligence = build_research_session_intelligence(session_dir, manifest)
        analyzed.append(
            {
                "session_id": str(manifest.get("session_id") or session_dir.name),
                "directory": session_dir.name,
                "intelligence": intelligence,
            }
        )

    class_counts = Counter(item["intelligence"]["classification"] for item in analyzed)
    flag_counts = Counter(flag for item in analyzed for flag in item["intelligence"]["flags"])
    anchor_counts = Counter(
        anchor["key"]
        for item in analyzed
        for anchor in item["intelligence"]["anchors"]
        if item["intelligence"]["classification"] in {"repo_grounded", "mixed"}
    )
    anchor_labels = {
        key: label for key, label, _terms in _ANCHOR_DEFINITIONS
    }
    drift_sessions = [
        {
            "session_id": item["session_id"],
            "directory": item["directory"],
            "off_domain_terms": item["intelligence"]["off_domain_terms"][:6],
        }
        for item in analyzed
        if item["intelligence"]["classification"] in {"off_domain", "mixed"}
    ]

    return {
        "sessions_analyzed": len(analyzed),
        "classification_counts": dict(class_counts),
        "recurring_flags": dict(flag_counts),
        "accepted_anchors": [
            {"key": key, "label": anchor_labels.get(key, key), "session_count": count}
            for key, count in anchor_counts.most_common()
        ],
        "drift_sessions": drift_sessions,
        "next_actions": _dedupe(
            action
            for item in analyzed
            if item["intelligence"]["classification"] == "repo_grounded"
            for action in item["intelligence"]["extracted_actions"]
        )[:12],
    }


def _read_manifest(session_dir: Path) -> dict[str, Any] | None:
    manifest_path = session_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        import json

        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_research_documents(session_dir: Path, *, max_chars: int) -> tuple[list[dict[str, str]], int]:
    seen: set[Path] = set()
    documents: list[dict[str, str]] = []
    redacted_blocks = 0
    remaining = max_chars
    for pattern in _DOC_GLOBS:
        for path in sorted(session_dir.glob(pattern)):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            if remaining <= 0:
                break
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            redacted_blocks += len(_THINK_BLOCK_RE.findall(raw))
            text = sanitize_research_markdown(raw)
            if not text:
                continue
            text = text[:remaining]
            remaining -= len(text)
            documents.append({"path": str(path.relative_to(session_dir)), "text": text})
    return documents, redacted_blocks


def _anchor_hits(text: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for key, label, terms in _ANCHOR_DEFINITIONS:
        matched = [term for term in terms if term in text]
        if matched:
            hits.append({"key": key, "label": label, "terms": matched, "score": len(matched)})
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits


def _term_hits(text: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term in text]


def _classify_grounding(repo_grounding_score: float, off_domain_score: float, anchors: list[dict[str, Any]]) -> str:
    core_anchor_count = len(
        {
            anchor["key"]
            for anchor in anchors
            if anchor["key"] in {"stage_machine", "evaluation_gate", "signal_contract", "integration_modes"}
        }
    )
    if off_domain_score >= 0.8 and core_anchor_count < 2:
        return "off_domain"
    if off_domain_score >= 0.6 and repo_grounding_score < 0.4:
        return "off_domain"
    if off_domain_score >= 0.4:
        return "mixed"
    if repo_grounding_score >= 0.4 or len(anchors) >= 2:
        return "repo_grounded"
    return "needs_review"


def _extract_section_items(
    text: str,
    *,
    section_keywords: tuple[str, ...],
    fallback_keywords: tuple[str, ...],
    limit: int,
    require_keyword_when_active: bool = False,
    allow_fallback: bool = True,
) -> list[str]:
    selected: list[str] = []
    active = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if not line:
            continue
        if line.startswith("#"):
            active = any(keyword in lower for keyword in section_keywords)
            continue
        item = _clean_item(line)
        if active and item:
            if not require_keyword_when_active or any(keyword in item.lower() for keyword in fallback_keywords):
                selected.append(item)
        if len(selected) >= limit:
            return _dedupe(selected)[:limit]

    if not allow_fallback:
        return _dedupe(selected)[:limit]

    for raw_line in text.splitlines():
        item = _clean_item(raw_line.strip())
        if not item:
            continue
        lower = item.lower()
        if any(keyword in lower for keyword in fallback_keywords):
            selected.append(item)
        if len(selected) >= limit:
            break
    return _dedupe(selected)[:limit]


def _clean_item(line: str) -> str | None:
    if not line or line.startswith("|") or line.startswith("```") or line.startswith("---"):
        return None
    match = _ITEM_RE.match(line)
    if match:
        line = match.group("text")
    elif not line.startswith(("**", "`")):
        return None
    line = re.sub(r"\s+", " ", line)
    line = line.strip(" -")
    if len(line) < 18:
        return None
    if len(line) > 320:
        line = line[:317].rstrip() + "..."
    return line


def _dedupe(items: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = re.sub(r"[^a-z0-9]+", " ", str(item).lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(item))
    return out
