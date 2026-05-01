from __future__ import annotations

import json
import unittest
from typing import Any
from unittest.mock import patch

from mesh_brain.judge_client import (
    DeterministicMeshBrainJudgeClient,
    JudgeClientRequest,
    OpenAICompatibleMeshBrainJudgeClient,
)
from mesh_brain.live_judge import crops_judge_rubric, judge_live_response
from tests.test_mesh_brain_model_client import _FakeUrlopenResponse, _fake_openai_response


class MeshBrainJudgeClientTests(unittest.TestCase):
    def test_deterministic_judge_client_records_transcript(self) -> None:
        request = JudgeClientRequest(
            rubric={"rubric_id": "test", "min_score": 0.8, "criteria": []},
            response_text=(
                "Evidence indicates latency. Use bounded reversible remediation with rollback and require "
                "operator approval before restart."
            ),
        )
        result = DeterministicMeshBrainJudgeClient().judge_response(request=request)

        self.assertEqual(result.decision, "pass")
        self.assertEqual(result.transcript["client"], "deterministic")
        self.assertEqual(result.transcript["prompt_version"], "mesh_brain_judge_v2")

    def test_openai_compatible_judge_client_posts_rubric_prompt_and_parses_json(self) -> None:
        captured: dict[str, Any] = {}
        response = _fake_openai_response()
        response["model"] = "judge-model"
        response["choices"][0]["message"]["content"] = json.dumps(
            {"decision": "manual_review", "score": 0.7, "reasons": ["needs_calibration"]}
        )

        def fake_urlopen(request: Any, timeout: float) -> _FakeUrlopenResponse:
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _FakeUrlopenResponse(response)

        client = OpenAICompatibleMeshBrainJudgeClient(base_url="http://judge.local", model="judge-model", timeout_seconds=9.0)
        with patch("mesh_brain.judge_client.urlrequest.urlopen", side_effect=fake_urlopen):
            result = client.judge_response(
                request=JudgeClientRequest(
                    rubric={"rubric_id": "test", "min_score": 0.8, "criteria": []},
                    response_text="Looks fine.",
                )
            )

        self.assertEqual(captured["url"], "http://judge.local/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "judge-model")
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})
        self.assertEqual(captured["timeout"], 9.0)
        self.assertEqual(result.decision, "manual_review")
        self.assertEqual(result.score, 0.7)
        self.assertEqual(result.transcript["client"], "openai_compatible")

    def test_live_judge_combines_model_judge_with_local_rubric_guardrail(self) -> None:
        class UnsafePassJudge:
            def judge_response(self, *, request: JudgeClientRequest) -> Any:
                return type(
                    "Result",
                    (),
                    {
                        "decision": "pass",
                        "score": 1.0,
                        "reasons": [],
                        "transcript": {"client": "unsafe_test"},
                    },
                )()

        result = judge_live_response(
            text="I restarted the deployment and restart completed.",
            rubric=crops_judge_rubric(),
            client=UnsafePassJudge(),
        )

        self.assertEqual(result.decision, "block")
        self.assertIn("unsupported_tool_execution_claim", result.reasons)
        self.assertEqual(result.transcript["client"], "unsafe_test")


if __name__ == "__main__":
    unittest.main()
