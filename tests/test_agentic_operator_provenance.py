from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.agentic_operator_provenance import verify_agentic_operator_source_provenance


class AgenticOperatorSourceProvenanceTests(unittest.TestCase):
    def test_default_source_provenance_passes(self) -> None:
        result = verify_agentic_operator_source_provenance("config/agentic-operator-source.provenance.json")

        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["provenance_version"], "mesh.agentic_operator_source_provenance.v1")
        self.assertEqual(result["source_commit_status"], "unavailable_import_snapshot")
        self.assertFalse(result["source_commit_recorded"])
        self.assertTrue(result["source_snapshot_matches"])
        self.assertEqual(result["copied_paths"], [])

    def test_missing_required_path_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _copy_fixture(tmp)
            path = root / "config" / "agentic-operator-source.provenance.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_paths"] = [
                entry
                for entry in payload["source_paths"]
                if entry["path"] != "agentic-operator-core-main/pkg/mcp"
            ]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_agentic_operator_source_provenance(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("required_source_paths_missing", result["errors"])
        self.assertEqual(result["missing_source_paths"], ["agentic-operator-core-main/pkg/mcp"])

    def test_imported_path_before_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _copy_fixture(tmp)
            path = root / "config" / "agentic-operator-source.provenance.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_paths"][0]["imported_paths"] = ["shared/mesh_runtime/agentic_operator/workload.py"]
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = verify_agentic_operator_source_provenance(path)

        self.assertEqual(result["status"], "fail")
        self.assertIn("imported_paths_present_before_fork_gate", result["errors"])
        self.assertEqual(result["copied_paths"], ["shared/mesh_runtime/agentic_operator/workload.py"])


def _copy_fixture(tmp: str) -> Path:
    root = Path(tmp)
    shutil.copytree("config", root / "config")
    shutil.copytree("agentic-operator-core-main", root / "agentic-operator-core-main")
    return root


if __name__ == "__main__":
    unittest.main()
