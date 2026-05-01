from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain.readiness_gaps import build_readiness_gap_report, write_readiness_gap_report


class MeshBrainReadinessGapTests(unittest.TestCase):
    def test_readiness_gap_report_tracks_real_posttraining_and_moe_gaps(self) -> None:
        report = build_readiness_gap_report()
        capabilities = {gap.capability for gap in report.gaps}

        self.assertTrue(report.ready_for_live_smoke)
        self.assertFalse(report.ready_for_real_posttraining)
        self.assertFalse(report.ready_for_moe)
        self.assertIn("posttraining_execution", capabilities)
        self.assertIn("llm_as_judge", capabilities)
        self.assertIn("moe_training_and_serving", capabilities)
        self.assertIn("serving_load", capabilities)

    def test_readiness_gap_report_writes_artifact(self) -> None:
        with TemporaryDirectory() as temp_dir:
            paths = write_readiness_gap_report(output_directory=Path(temp_dir))
            report = json.loads(Path(paths["readiness_gap_report"]).read_text(encoding="utf-8"))

        self.assertIn("report_id", report)
        self.assertFalse(report["ready_for_real_posttraining"])
        self.assertGreaterEqual(len(report["gaps"]), 4)


if __name__ == "__main__":
    unittest.main()
