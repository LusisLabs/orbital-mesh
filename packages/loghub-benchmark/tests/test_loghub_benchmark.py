from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from loghub_benchmark.harbor import (
    HarborResultImportConfig,
    LoghubCaseBuildConfig,
    LoghubHarborExportConfig,
    build_loghub_cases,
    export_loghub_harbor_dataset,
    find_oracle_leaks,
    import_harbor_results,
    score_loghub_answer,
)


class LoghubBenchmarkTests(unittest.TestCase):
    def test_build_export_verify_and_import(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "App.log"
            log_path.write_text(
                "\n".join(
                    [
                        "INFO request completed",
                        "api ERROR timeout talking to storage",
                        "INFO request completed",
                    ]
                ),
                encoding="utf-8",
            )

            cases = build_loghub_cases(
                LoghubCaseBuildConfig(
                    dataset="App",
                    input_path=log_path,
                    output_dir=root / "cases",
                    max_cases=1,
                    split_salt="unit",
                )
            )
            self.assertEqual(1, len(cases.cases))
            case = cases.cases[0]
            self.assertEqual("silver", case["track"])

            export = export_loghub_harbor_dataset(
                LoghubHarborExportConfig(
                    case_root=root / "cases",
                    output_dir=root / "harbor",
                    split="full",
                    track="all",
                )
            )
            task_dir = export.task_dirs[0]
            oracle_path = export.oracle_dir / f"{case['case_id']}.oracle.json"
            self.assertEqual([], find_oracle_leaks(task_dir, case["oracle"]))

            answer_path = root / "answer.json"
            verifier_dir = root / "verifier"
            answer_path.write_text(
                json.dumps(
                    {
                        "is_incident": True,
                        "anomaly_line_ids": case["oracle"]["anomaly_line_ids"],
                        "root_cause_type": case["oracle"]["root_cause_type"],
                        "evidence": [
                            {
                                "line_id": case["oracle"]["anomaly_line_ids"][0],
                                "quote": "ERROR timeout",
                                "reason": "incident signal",
                            }
                        ],
                        "recommended_action": "escalate",
                    }
                ),
                encoding="utf-8",
            )
            completed = subprocess.run(
                [sys.executable, str(task_dir / "tests" / "verifier.py")],
                env={
                    **os.environ,
                    "LOGHUB_HARBOR_ORACLE_PATH": str(oracle_path),
                    "LOGHUB_HARBOR_ANSWER_PATH": str(answer_path),
                    "LOGHUB_HARBOR_VERIFIER_DIR": str(verifier_dir),
                },
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual("", completed.stderr)
            self.assertEqual(0, completed.returncode)
            reward = json.loads((verifier_dir / "reward.json").read_text(encoding="utf-8"))
            self.assertEqual(1.0, reward["reward"])

            job_trial = root / "job" / case["case_id"] / "trial-1"
            job_trial.mkdir(parents=True)
            (job_trial / "result.json").write_text(
                json.dumps({"task_id": case["case_id"], "verifier_result": {"rewards": {"reward": 1.0}, "details": {"valid": True}}}),
                encoding="utf-8",
            )
            imported = import_harbor_results(
                HarborResultImportConfig(
                    job_dir=root / "job",
                    output_dir=root / "imported",
                )
            )
            self.assertEqual(1.0, imported.summary["pass_at_3"])

    def test_loghub_structured_csv_labels_create_gold_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            corpus = root / "BGL"
            corpus.mkdir()
            (corpus / "BGL_2k.log").write_text(
                "\n".join(
                    [
                        "INFO instruction cache parity error corrected",
                        "FATAL node card failed with machine check",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (corpus / "BGL_2k.log_structured.csv").write_text(
                "\n".join(
                    [
                        "LineId,Label,Content",
                        "1,-,instruction cache parity error corrected",
                        "2,FATAL,node card failed with machine check",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            cases = build_loghub_cases(
                LoghubCaseBuildConfig(
                    dataset="BGL",
                    input_path=corpus,
                    output_dir=root / "cases",
                    max_cases=5,
                    split_salt="structured-labels",
                )
            )

            self.assertTrue(cases.cases)
            self.assertEqual("gold", cases.cases[0]["track"])
            self.assertEqual(2, cases.cases[0]["source"]["line"])

    def test_scoring_penalizes_hallucinated_and_unsafe_answers(self) -> None:
        grade = score_loghub_answer(
            {
                "is_incident": True,
                "anomaly_line_ids": ["L999999"],
                "root_cause_type": "impossible_magic",
                "evidence": [{"line_id": "L999999", "quote": "invented", "reason": "invented"}],
                "recommended_action": "restart production",
            },
            {
                "is_incident": True,
                "anomaly_line_ids": ["L000002"],
                "root_cause_type": "timeout",
            },
            visible_line_ids={"L000001", "L000002"},
        )

        self.assertLess(grade["reward"], 0.5)
        self.assertIn("hallucinated_line_reference", grade["penalties"])
        self.assertIn("unsafe_remediation_recommendation", grade["penalties"])


if __name__ == "__main__":
    unittest.main()
