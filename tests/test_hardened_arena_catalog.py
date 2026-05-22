from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.hardened_arena_catalog import (
    CATALOG_PROVIDER,
    import_hardened_arena_catalog_from_html,
    load_hardened_arena_catalog,
    verify_hardened_arena_catalog,
)
from shared.mesh_runtime.schema_validation import validate_payload


class HardenedArenaCatalogTests(unittest.TestCase):
    def test_default_catalog_passes_without_deployment_claims(self) -> None:
        verification = verify_hardened_arena_catalog("config/hardened-arena.catalog.json")
        catalog = load_hardened_arena_catalog("config/hardened-arena.catalog.json")

        self.assertEqual(verification["status"], "pass")
        self.assertGreater(verification["entry_count"], 0)
        self.assertGreater(verification["image_count"], 0)
        self.assertGreater(verification["chart_count"], 0)
        self.assertEqual(catalog["claim_status"], "catalog_data_only")
        self.assertFalse(catalog["deployment_claim"])
        self.assertFalse(catalog["production_readiness_claim"])
        validate_payload("hardened-arena-catalog.schema.json", catalog)

    def test_importer_parses_explicit_html_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "catalog.html"
            html_path.write_text(_sample_html(), encoding="utf-8")
            catalog = import_hardened_arena_catalog_from_html(html_path, imported_at="2026-05-22T00:00:00Z")

        self.assertEqual(catalog["provider"], CATALOG_PROVIDER)
        self.assertEqual(len(catalog["entries"]), 2)
        image = catalog["entries"][0]
        chart = catalog["entries"][1]
        self.assertEqual(image["slug"], "nginx")
        self.assertEqual(image["type"], "image")
        self.assertEqual(image["os"], ["Debian"])
        self.assertEqual(image["architecture"], ["linux/amd64", "linux/arm64"])
        self.assertEqual(image["compliance_labels"], ["CIS", "FIPS"])
        self.assertEqual(image["tool_list"], ["3 tools included"])
        self.assertEqual(chart["slug"], "redis-chart")
        self.assertEqual(chart["type"], "chart")
        self.assertEqual(chart["version_family"], "23.x")
        self.assertEqual(chart["chart_dependencies"], ["Redis Exporter", "Bash", "Redis", "kubectl"])
        self.assertFalse(catalog["production_readiness_claim"])

    def test_cli_import_writes_output_from_explicit_html_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "catalog.html"
            output_path = Path(tmp) / "catalog.json"
            html_path.write_text(_sample_html(), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/import_hardened_arena_catalog.py",
                    "--html-path",
                    str(html_path),
                    "--output",
                    str(output_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            written = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(len(written["entries"]), 2)
        self.assertEqual(written["claim_status"], "catalog_data_only")

    def test_duplicate_slug_fails(self) -> None:
        catalog = _catalog_copy()
        catalog["entries"][1]["slug"] = catalog["entries"][0]["slug"]

        result = _verify_catalog(catalog)

        self.assertEqual(result["status"], "fail")
        self.assertIn(f"duplicate_slug:{catalog['entries'][0]['slug']}", result["blockers"])

    def test_production_ready_claim_fails(self) -> None:
        catalog = _catalog_copy()
        catalog["production_readiness_claim"] = True

        result = _verify_catalog(catalog)

        self.assertEqual(result["status"], "fail")
        self.assertIn("catalog_production_readiness_claim_not_false", result["blockers"])

    def test_entry_with_invalid_type_fails_closed(self) -> None:
        catalog = _catalog_copy()
        catalog["entries"][0]["type"] = "deployment"

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            path.write_text(json.dumps(catalog), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "scripts/verify_hardened_arena_catalog.py", "--catalog", str(path), "--json"],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("hardened_arena_catalog_invalid", completed.stdout)


def _catalog_copy() -> dict:
    return copy.deepcopy(load_hardened_arena_catalog("config/hardened-arena.catalog.json"))


def _verify_catalog(catalog: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "catalog.json"
        path.write_text(json.dumps(catalog), encoding="utf-8")
        return verify_hardened_arena_catalog(path)


def _sample_html() -> str:
    return """
    <span class="MuiTypography-root MuiTypography-overline product-type"><span>Hardened image</span></span>
    <h4 title="Nginx"><a data-testid="product-card-link" href="https://hub.docker.com/hardened-images/catalog/dhi/nginx">Nginx</a></h4>
    <p>3 Tools included</p><p>OS</p><p>Debian</p><p>Architecture</p><p>linux/amd64, linux/arm64</p><p>Compliance</p><p>CIS, FIPS</p>
    <span class="MuiTypography-root MuiTypography-overline product-type"><span>Helm chart</span></span>
    <h4 title="Redis Helm Chart"><a data-testid="product-card-link" href="https://hub.docker.com/hardened-images/catalog/dhi/redis-chart">Redis Helm Chart</a></h4>
    <p>Dependencies for tag Redis Helm chart 23.x</p>
    <p class="MuiTypography-root MuiTypography-body1 css-jy7h27">Redis Exporter</p>
    <p class="MuiTypography-root MuiTypography-body1 css-jy7h27">Bash</p>
    <p class="MuiTypography-root MuiTypography-body1 css-jy7h27">Redis</p>
    <p class="MuiTypography-root MuiTypography-body1 css-jy7h27">kubectl</p>
    """


if __name__ == "__main__":
    unittest.main()
