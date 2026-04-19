"""Smoke tests for scripts/mesh_showcase_research.py helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.mesh_showcase_research import (  # noqa: E402
    _build_scenarios,
    _run_scenario,
    holistic_eval_orchestration_pairs,
)


class MeshShowcaseResearchTests(unittest.TestCase):
    def test_build_scenarios_count(self) -> None:
        self.assertEqual(len(_build_scenarios()), 3)

    def test_feature_flag_happy_path_summary(self) -> None:
        name, builder = _build_scenarios()[0]
        self.assertEqual(name, "feature_flag_latency_happy")
        s = _run_scenario(name, builder, evaluation_mode="native", orchestration_mode="native")
        self.assertTrue(s["trigger_emitted"])
        self.assertEqual(s["decision_type"], "disable_flag")
        self.assertEqual(s["execution_status"], "succeeded")
        self.assertEqual(s["feedback_outcome"], "successful")
        self.assertGreater(s["stage_event_count"], 3)

    def test_no_trigger_summary(self) -> None:
        name, builder = _build_scenarios()[2]
        self.assertEqual(name, "feature_flag_no_trigger")
        s = _run_scenario(name, builder, evaluation_mode="native", orchestration_mode="native")
        self.assertFalse(s["trigger_emitted"])
        self.assertIsNone(s["decision_type"])

    def test_script_writes_digest(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "showcase-test"
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts/mesh_showcase_research.py"), "--output", str(out)],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            summaries = json.loads((out / "data" / "run_summaries.json").read_text())
            self.assertEqual(len(summaries), 3)
            self.assertTrue((out / "synthesis" / "showcase-insights.md").is_file())
            self.assertTrue((out / "manifest.json").is_file())

    def test_holistic_matrix_dimensions(self) -> None:
        self.assertEqual(len(holistic_eval_orchestration_pairs()) * len(_build_scenarios()), 12)

    def test_holistic_matrix_fast_smoke(self) -> None:
        import os
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "holistic-fast"
            env = {**os.environ, "MESH_SHOWCASE_HOLISTIC_FAST": "1"}
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts/mesh_showcase_research.py"),
                    "--output",
                    str(out),
                    "--holistic-matrix",
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            summaries = json.loads((out / "data" / "run_summaries.json").read_text())
            self.assertEqual(len(summaries), 3)
            self.assertTrue(all("matrix_row" in s for s in summaries))
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertTrue(manifest.get("holistic_matrix"))

    def test_embed_minimax_prompt_writes_long_question_and_complete_status(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "showcase-embed"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "scripts/mesh_showcase_research.py"),
                    "--output",
                    str(out),
                    "--embed-minimax-prompt",
                ],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            manifest = json.loads((out / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "showcase_complete")
            self.assertIn("Empirical run_summaries", manifest["question"])


if __name__ == "__main__":
    unittest.main()
