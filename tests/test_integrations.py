from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.evaluation.promptfoo_bridge import _parse_promptfoo_output
from services.orchestrator.goose_bridge import _parse_review_text
from shared.mesh_runtime import RuntimeConfig, resolve_integrations_config


class IntegrationsTests(unittest.TestCase):
    def test_resolve_integrations_wraps_vendor_binaries_with_bridge_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
            )

            def fake_which(name: str) -> str | None:
                mapping = {
                    "promptfoo": "/usr/local/bin/promptfoo",
                    "goose": "/opt/homebrew/bin/goose",
                    "ollama": "/usr/local/bin/ollama",
                }
                return mapping.get(name)

            def fake_run(
                args: list[str],
                capture_output: bool = False,
                text: bool = False,
                check: bool = False,
                timeout: int | float | None = None,
            ) -> subprocess.CompletedProcess[str]:
                if args == ["/usr/local/bin/ollama", "list"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="NAME ID SIZE MODIFIED\nqwen2.5:0.5b abc 1 GB now\n",
                        stderr="",
                    )
                if args[:2] == ["/opt/homebrew/bin/goose", "run"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout=json.dumps(
                            {
                                "messages": [
                                    {
                                        "role": "assistant",
                                        "content": [{"type": "text", "text": "ACK"}],
                                    }
                                ]
                            }
                        ),
                        stderr="",
                    )
                raise AssertionError(f"unexpected subprocess args: {args}")

            with (
                patch("shared.mesh_runtime.integrations.shutil.which", side_effect=fake_which),
                patch("shared.mesh_runtime.integrations.subprocess.run", side_effect=fake_run),
            ):
                resolved = resolve_integrations_config(config)

        self.assertIn("services.evaluation.promptfoo_bridge", resolved.promptfoo_command or "")
        self.assertIn("/usr/local/bin/promptfoo", resolved.promptfoo_command or "")
        self.assertIn("services.orchestrator.goose_bridge", resolved.goose_command or "")
        self.assertIn("--provider ollama", resolved.goose_command or "")
        self.assertIn("--model qwen2.5:0.5b", resolved.goose_command or "")

    def test_promptfoo_output_parser_extracts_real_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            results_path = Path(temp_dir) / "results.json"
            results_path.write_text(
                json.dumps(
                    {
                        "results": {
                            "outputs": [
                                {
                                    "pass": True,
                                    "score": 0.88,
                                    "gradingResult": {
                                        "componentResults": [
                                            {
                                                "assertion": {"type": "python"},
                                                "pass": True,
                                                "score": 1.0,
                                                "reason": "confidence meets minimum threshold",
                                            }
                                        ]
                                    },
                                }
                            ],
                            "stats": {"successes": 1, "failures": 0},
                        }
                    }
                )
            )

            artifact = _parse_promptfoo_output(results_path)

        self.assertIsNotNone(artifact)
        self.assertTrue(artifact["passed"])
        self.assertEqual(artifact["score"], 0.88)
        self.assertEqual(artifact["assertions"][0]["reason"], "confidence meets minimum threshold")

    def test_goose_review_parser_accepts_json_review(self) -> None:
        review = _parse_review_text(
            json.dumps(
                {
                    "approved": True,
                    "summary": "bounded execution looks safe",
                    "risk_flags": ["none"],
                    "next_action": "proceed",
                }
            )
        )
        self.assertTrue(review["approved"])
        self.assertEqual(review["summary"], "bounded execution looks safe")
        self.assertEqual(review["next_action"], "proceed")


if __name__ == "__main__":
    unittest.main()
