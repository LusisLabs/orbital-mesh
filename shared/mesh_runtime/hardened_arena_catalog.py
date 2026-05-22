from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
from pathlib import Path
from typing import Any

from .schema_validation import SchemaValidationError, validate_payload


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HARDENED_ARENA_CATALOG = REPO_ROOT / "config" / "hardened-arena.catalog.json"
DEFAULT_DHI_CATALOG_HTML = Path("/Users/shaanp/Downloads/Hardened Images catalog _ Docker Hub.html")
HARDENED_ARENA_CATALOG_SCHEMA = "hardened-arena-catalog.schema.json"
HARDENED_ARENA_CATALOG_VERSION = "mesh.hardened_arena.catalog.v1"
HARDENED_ARENA_CATALOG_VERIFICATION_VERSION = "mesh.hardened_arena.catalog_verification.v1"
ALLOWED_ENTRY_TYPES = frozenset({"image", "chart"})
CATALOG_PROVIDER = "docker_hardened_images"
SOURCE_PREFIX = "https://hub.docker.com/hardened-images/catalog/dhi/"

_ANCHOR_RE = re.compile(
    r'<a[^>]+data-testid="product-card-link"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_PRODUCT_TYPE_MARKER = '<span class="MuiTypography-root MuiTypography-overline product-type'


def load_hardened_arena_catalog(path: str | Path | None = None) -> dict[str, Any]:
    catalog_path = _resolve_path(path or DEFAULT_HARDENED_ARENA_CATALOG)
    payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    validate_payload(HARDENED_ARENA_CATALOG_SCHEMA, payload)
    return payload


def import_hardened_arena_catalog_from_html(html_path: str | Path, *, imported_at: str | None = None) -> dict[str, Any]:
    source_path = Path(html_path)
    raw_html = source_path.read_text(encoding="utf-8", errors="replace")
    checked_at = imported_at or _timestamp()
    parsed_entries = [_entry_from_card(card, checked_at) for card in _catalog_cards(raw_html)]
    entries = _dedupe_entries([entry for entry in parsed_entries if entry is not None])
    payload = {
        "schema_version": HARDENED_ARENA_CATALOG_VERSION,
        "provider": CATALOG_PROVIDER,
        "source": _display_path(source_path),
        "imported_at": checked_at,
        "claim_status": "catalog_data_only",
        "deployment_claim": False,
        "production_readiness_claim": False,
        "entries": entries,
    }
    validate_payload(HARDENED_ARENA_CATALOG_SCHEMA, payload)
    return payload


def write_hardened_arena_catalog(payload: dict[str, Any], output_path: str | Path) -> None:
    validate_payload(HARDENED_ARENA_CATALOG_SCHEMA, payload)
    path = _resolve_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def verify_hardened_arena_catalog(path: str | Path | None = None) -> dict[str, Any]:
    resolved_path = _resolve_path(path or DEFAULT_HARDENED_ARENA_CATALOG)
    blockers: list[str] = []
    entries: list[dict[str, Any]] = []
    catalog_sha256: str | None = None
    try:
        catalog = load_hardened_arena_catalog(resolved_path)
        entries = [entry for entry in catalog.get("entries", []) if isinstance(entry, dict)]
        catalog_sha256 = _sha256(resolved_path)
        blockers.extend(_catalog_blockers(catalog, entries))
    except (OSError, json.JSONDecodeError, SchemaValidationError) as exc:
        blockers.append(f"hardened_arena_catalog_invalid:{type(exc).__name__}")
        if not resolved_path.exists():
            blockers.append("hardened_arena_catalog_missing")
    return {
        "schema_version": HARDENED_ARENA_CATALOG_VERIFICATION_VERSION,
        "status": "pass" if not blockers else "fail",
        "checked_at": _timestamp(),
        "catalog_path": _display_path(resolved_path),
        "catalog_sha256": catalog_sha256,
        "entry_count": len(entries),
        "image_count": sum(1 for entry in entries if entry.get("type") == "image"),
        "chart_count": sum(1 for entry in entries if entry.get("type") == "chart"),
        "blockers": sorted(set(blockers)),
    }


def _catalog_cards(raw_html: str) -> list[str]:
    anchors = list(_ANCHOR_RE.finditer(raw_html))
    cards: list[str] = []
    starts = [raw_html.rfind(_PRODUCT_TYPE_MARKER, 0, anchor.start()) for anchor in anchors]
    for index, anchor in enumerate(anchors):
        start = starts[index] if starts[index] >= 0 else anchor.start()
        end = starts[index + 1] if index + 1 < len(starts) and starts[index + 1] >= 0 else len(raw_html)
        cards.append(raw_html[start:end])
    return cards


def _entry_from_card(card_html: str, imported_at: str) -> dict[str, Any] | None:
    anchor = _ANCHOR_RE.search(card_html)
    if not anchor:
        return None
    source_url = html.unescape(anchor.group(1))
    display_name = _strip_tags(anchor.group(2))
    slug = source_url.rstrip("/").split("/")[-1]
    clean = _clean_text(card_html)
    entry_type = _entry_type(clean, display_name, slug)
    detail_names = _detail_names(card_html)
    tool_list = _tool_list(clean, detail_names, entry_type)
    chart_dependencies = detail_names if entry_type == "chart" else []
    version_family = _version_family(clean)
    return {
        "provider": CATALOG_PROVIDER,
        "slug": slug,
        "display_name": display_name,
        "type": entry_type,
        "os": _split_list(_between(clean, " OS ", " Architecture ")),
        "architecture": _split_list(_between(clean, " Architecture ", " Compliance ")),
        "compliance_labels": _split_list(_between(clean, " Compliance ", None)),
        "tool_list": tool_list,
        "chart_dependencies": chart_dependencies,
        "version_family": version_family,
        "source_url": source_url,
        "source_ref": f"dhi/{slug}",
        "imported_at": imported_at,
        "proof_placeholders": _proof_placeholders(),
    }


def _dedupe_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        slug = str(entry.get("slug") or "")
        if slug in seen:
            continue
        seen.add(slug)
        deduped.append(entry)
    return deduped


def _catalog_blockers(catalog: dict[str, Any], entries: list[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    if catalog.get("claim_status") != "catalog_data_only":
        blockers.append("catalog_claim_status_not_data_only")
    if catalog.get("deployment_claim") is not False:
        blockers.append("catalog_deployment_claim_not_false")
    if catalog.get("production_readiness_claim") is not False:
        blockers.append("catalog_production_readiness_claim_not_false")
    slugs = [str(entry.get("slug") or "") for entry in entries]
    duplicate_slugs = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    blockers.extend(f"duplicate_slug:{slug}" for slug in duplicate_slugs)
    if not entries:
        blockers.append("catalog_entries_missing")
    for entry in entries:
        blockers.extend(_entry_blockers(entry))
    return blockers


def _entry_blockers(entry: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    slug = str(entry.get("slug") or "unknown")
    for field_name in ("provider", "slug", "display_name", "type", "source_url", "source_ref", "imported_at"):
        if not str(entry.get(field_name) or "").strip():
            blockers.append(f"{slug}:{field_name}_missing")
    if entry.get("provider") != CATALOG_PROVIDER:
        blockers.append(f"{slug}:provider_invalid")
    if entry.get("type") not in ALLOWED_ENTRY_TYPES:
        blockers.append(f"{slug}:type_invalid")
    if str(entry.get("source_url") or "") and not str(entry.get("source_url")).startswith(SOURCE_PREFIX):
        blockers.append(f"{slug}:source_url_invalid")
    for list_field in ("os", "architecture", "compliance_labels", "tool_list", "chart_dependencies"):
        if not isinstance(entry.get(list_field), list):
            blockers.append(f"{slug}:{list_field}_not_list")
    proof = entry.get("proof_placeholders") if isinstance(entry.get("proof_placeholders"), dict) else {}
    if proof.get("observed_evidence"):
        blockers.append(f"{slug}:catalog_import_contains_observed_evidence")
    if not proof.get("blockers"):
        blockers.append(f"{slug}:proof_blockers_missing")
    return blockers


def _entry_type(clean: str, display_name: str, slug: str) -> str:
    prefix = clean[: max(clean.find(display_name), 0)] if display_name in clean else clean[:80]
    if "Helm chart" in prefix or display_name.endswith("Helm Chart") or slug.endswith("-chart"):
        return "chart"
    return "image"


def _detail_names(card_html: str) -> list[str]:
    names = []
    for raw in re.findall(r'<p[^>]*class="[^"]*css-jy7h27[^"]*"[^>]*>(.*?)</p>', card_html, re.DOTALL):
        name = _strip_tags(raw)
        if name and name not in names:
            names.append(name)
    return names


def _tool_list(clean: str, detail_names: list[str], entry_type: str) -> list[str]:
    if entry_type == "image" and detail_names:
        return detail_names
    match = re.search(r"(\d+) Tools included", clean)
    if match:
        return [f"{match.group(1)} tools included"]
    return []


def _version_family(clean: str) -> str | None:
    match = re.search(r"Dependencies for tag .*? ([0-9][A-Za-z0-9_.-]*\.x)", clean)
    if match:
        return match.group(1)
    return None


def _proof_placeholders() -> dict[str, Any]:
    return {
        "digest_ref": None,
        "sbom_ref": None,
        "provenance_ref": None,
        "vulnerability_scan_ref": None,
        "attestation_refs": [],
        "observed_evidence": [],
        "blockers": [
            "catalog_import_only_no_digest_pin_verified",
            "catalog_import_only_no_sbom_verified",
            "catalog_import_only_no_provenance_verified",
            "catalog_import_only_no_target_smoke_evidence",
        ],
    }


def _between(clean: str, start_marker: str, end_marker: str | None) -> str:
    start = clean.find(start_marker)
    if start < 0:
        return ""
    value_start = start + len(start_marker)
    if end_marker is None:
        end_candidates = [clean.find(marker, value_start) for marker in (" Hardened image", " Helm chart")]
        end_candidates = [candidate for candidate in end_candidates if candidate >= 0]
        value_end = min(end_candidates) if end_candidates else len(clean)
    else:
        value_end = clean.find(end_marker, value_start)
        if value_end < 0:
            value_end = len(clean)
    return clean[value_start:value_end].strip()


def _split_list(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",")]
    return [item for item in items if item]


def _clean_text(raw: str) -> str:
    without_svg = re.sub(r"<svg.*?</svg>", " ", raw, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", _strip_tags(without_svg)).strip()


def _strip_tags(raw: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", raw)).strip()


def _resolve_path(raw: str | Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def import_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import the Docker Hardened Images catalog HTML into Mesh catalog JSON.")
    parser.add_argument("--html-path", default=str(DEFAULT_DHI_CATALOG_HTML), help="Path to saved Docker Hardened Images catalog HTML.")
    parser.add_argument("--output", default=str(DEFAULT_HARDENED_ARENA_CATALOG), help="Output catalog JSON path.")
    parser.add_argument("--json", action="store_true", help="Emit the imported catalog JSON to stdout instead of a summary.")
    args = parser.parse_args(argv)

    payload = import_hardened_arena_catalog_from_html(args.html_path)
    write_hardened_arena_catalog(payload, args.output)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"imported {len(payload['entries'])} Docker Hardened Images catalog entries to {_display_path(_resolve_path(args.output))}")
    return 0
