from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.trigger_web_provenance import verify_trigger_web_source_provenance


class TriggerWebSourceProvenanceTests(unittest.TestCase):
    def test_default_source_provenance_passes(self) -> None:
        result = verify_trigger_web_source_provenance("config/trigger-web-source.provenance.json")

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["provenance_version"], "mesh.trigger_web_source_provenance.v1")
        self.assertEqual(result["source_commit_status"], "recorded")
        self.assertEqual(result["imported_paths"], ["apps/mesh-webapp"])
        self.assertTrue(result["license_valid"])
        self.assertTrue(result["remotes_valid"])

    def test_absent_source_checkout_still_validates_recorded_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _copy_fixture(tmp)
            path = root / "config" / "trigger-web-source.provenance.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_root"] = str(root / "missing-lusistrigger.dev")
            payload["license_path"] = str(root / "missing-lusistrigger.dev" / "LICENSE")
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_trigger_web_source_provenance(path)

        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["source_root_available"])
        self.assertEqual(result["missing_existing_paths"], [])
        self.assertTrue(result["license_valid"])

    def test_missing_required_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _copy_fixture(tmp)
            path = root / "config" / "trigger-web-source.provenance.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_paths"] = [
                entry
                for entry in payload["source_paths"]
                if entry["path"] != "apps/webapp/app/components/primitives"
            ]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_trigger_web_source_provenance(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("required_source_paths_missing", result["errors"])
        self.assertEqual(
            result["missing_source_paths"],
            ["apps/webapp/app/components/primitives"],
        )

    def test_imported_path_outside_allowed_targets_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _copy_fixture(tmp)
            path = root / "config" / "trigger-web-source.provenance.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_paths"][0]["imported_paths"] = ["services/control_plane.py"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_trigger_web_source_provenance(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("imported_paths_outside_allowed_targets", result["errors"])
        self.assertEqual(result["disallowed_imported_paths"], ["services/control_plane.py"])


def _copy_fixture(tmp: str) -> Path:
    root = Path(tmp)
    shutil.copytree("config", root / "config")
    return root


if __name__ == "__main__":
    unittest.main()
