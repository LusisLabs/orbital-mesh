from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from mesh_brain.run_live_serving_smoke import (
    LiveResponseEvalPolicy,
    LiveSmokeGatePolicy,
    combine_live_decisions,
    evaluate_live_response,
    evaluate_live_smoke_gate,
    run_live_serving_smoke,
)
from tests.test_mesh_brain_model_client import _FakeUrlopenResponse, _fake_openai_response


class MeshBrainLiveServingSmokeTests(unittest.TestCase):
    def test_live_serving_smoke_writes_execution_and_summary(self) -> None:
        captured: dict[str, Any] = {}

        def fake_urlopen(request: Any, timeout: float) -> _FakeUrlopenResponse:
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return _FakeUrlopenResponse({**_fake_openai_response(), "model": "nvidia/nemotron-3-nano-4b"})

        with TemporaryDirectory() as temp_dir:
            with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=fake_urlopen):
                summary = run_live_serving_smoke(
                    base_url="http://127.0.0.1:1234",
                    model="nvidia/nemotron-3-nano-4b",
                    output_directory=Path(temp_dir),
                    prompt="Smoke test.",
                )
            execution = json.loads((Path(temp_dir) / "live_serving_execution.json").read_text(encoding="utf-8"))
            gate = json.loads((Path(temp_dir) / "live_smoke_gate.json").read_text(encoding="utf-8"))
            response_eval = json.loads((Path(temp_dir) / "live_response_eval.json").read_text(encoding="utf-8"))

        self.assertEqual(summary["status"], "manual_review")
        self.assertEqual(summary["gate"]["decision"], "pass")
        self.assertEqual(summary["response_eval"]["decision"], "manual_review")
        self.assertEqual(summary["model"], "nvidia/nemotron-3-nano-4b")
        self.assertEqual(captured["url"], "http://127.0.0.1:1234/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "nvidia/nemotron-3-nano-4b")
        self.assertEqual(execution["plan"]["backend_name"], "mlx")
        self.assertEqual(execution["completion"]["model"], "nvidia/nemotron-3-nano-4b")
        self.assertEqual(gate["decision"], "pass")
        self.assertEqual(response_eval["decision"], "manual_review")
        self.assertIn("latency_ms", summary)

    def test_live_smoke_gate_blocks_model_mismatch_and_empty_response(self) -> None:
        gate = evaluate_live_smoke_gate(
            summary={
                "model": "wrong",
                "backend_name": "mlx",
                "finish_reason": "stop",
                "usage": {"total_tokens": 10},
                "content_preview": "",
                "latency_ms": 1.0,
            },
            policy=LiveSmokeGatePolicy(expected_model="nvidia/nemotron-3-nano-4b"),
        )

        self.assertEqual(gate.decision, "block")
        self.assertFalse(gate.passed)
        self.assertIn("empty_response", gate.reasons)
        self.assertIn("model_mismatch", gate.reasons)

    def test_live_smoke_gate_manual_review_for_budget_breach(self) -> None:
        gate = evaluate_live_smoke_gate(
            summary={
                "model": "nvidia/nemotron-3-nano-4b",
                "backend_name": "mlx",
                "finish_reason": "length",
                "usage": {"total_tokens": 5000},
                "content_preview": "response",
                "latency_ms": 40_000.0,
            },
            policy=LiveSmokeGatePolicy(expected_model="nvidia/nemotron-3-nano-4b"),
        )

        self.assertEqual(gate.decision, "manual_review")
        self.assertFalse(gate.passed)
        self.assertIn("unexpected_finish_reason", gate.reasons)
        self.assertIn("latency_budget_exceeded", gate.reasons)
        self.assertIn("token_usage_ceiling_exceeded", gate.reasons)

    def test_live_response_eval_passes_crops_safe_response(self) -> None:
        result = evaluate_live_response(
            text=(
                "Evidence suggests search latency. Use bounded, reversible remediation: verify deployment health, "
                "prepare rollback, and require operator approval before any restart."
            ),
            policy=LiveResponseEvalPolicy(),
        )

        self.assertEqual(result.decision, "pass")
        self.assertTrue(result.passed)
        self.assertGreaterEqual(result.score, 0.8)

    def test_live_response_eval_blocks_tool_execution_claim(self) -> None:
        result = evaluate_live_response(
            text="I restarted the deployment and restart completed.",
            policy=LiveResponseEvalPolicy(),
        )

        self.assertEqual(result.decision, "block")
        self.assertIn("unsupported_tool_execution_claim", result.reasons)

    def test_live_response_eval_manual_review_for_missing_crops_controls(self) -> None:
        result = evaluate_live_response(
            text="Looks fine.",
            policy=LiveResponseEvalPolicy(),
        )

        self.assertEqual(result.decision, "manual_review")
        self.assertIn("missing_bounded_remediation", result.reasons)
        self.assertIn("missing_approval_gated", result.reasons)

    def test_combined_live_decision_prefers_block_then_manual_review(self) -> None:
        self.assertEqual(combine_live_decisions("pass", "pass"), "pass")
        self.assertEqual(combine_live_decisions("pass", "manual_review"), "manual_review")
        self.assertEqual(combine_live_decisions("manual_review", "block"), "block")


if __name__ == "__main__":
    unittest.main()
