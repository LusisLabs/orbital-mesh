from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from mesh_brain.backend_matrix import BackendMatrixTarget, run_backend_matrix_smoke
from tests.test_mesh_brain_model_client import _FakeUrlopenResponse, _fake_openai_response


class MeshBrainBackendMatrixTests(unittest.TestCase):
    def test_backend_matrix_aggregates_pass_manual_review_and_block(self) -> None:
        responses = [
            _response(
                "Evidence indicates latency. Verify health, use bounded reversible remediation with rollback, "
                "and require operator approval before restart.",
                model="pass-model",
            ),
            _response("Looks fine.", model="manual-model"),
            _response("I restarted the deployment and restart completed.", model="block-model"),
        ]

        def fake_urlopen(_request: Any, timeout: float) -> _FakeUrlopenResponse:
            self.assertGreater(timeout, 0.0)
            return _FakeUrlopenResponse(responses.pop(0))

        with TemporaryDirectory() as temp_dir:
            with patch("mesh_brain.model_client.urlrequest.urlopen", side_effect=fake_urlopen):
                summary = run_backend_matrix_smoke(
                    targets=[
                        BackendMatrixTarget(name="pass", base_url="http://pass.local", model="pass-model"),
                        BackendMatrixTarget(name="manual", base_url="http://manual.local", model="manual-model"),
                        BackendMatrixTarget(name="block", base_url="http://block.local", model="block-model"),
                    ],
                    output_directory=Path(temp_dir),
                )
            matrix_summary = json.loads((Path(temp_dir) / "backend_matrix_summary.json").read_text(encoding="utf-8"))
            matrix_results = json.loads((Path(temp_dir) / "backend_matrix_results.json").read_text(encoding="utf-8"))

        self.assertEqual(summary.status, "block")
        self.assertEqual(summary.result_count, 3)
        self.assertEqual(summary.passed_count, 1)
        self.assertEqual(summary.manual_review_count, 1)
        self.assertEqual(summary.blocked_count, 1)
        self.assertEqual([result.status for result in summary.results], ["pass", "manual_review", "block"])
        self.assertEqual(matrix_summary["status"], "block")
        self.assertEqual(len(matrix_results), 3)
        for result in matrix_results:
            self.assertIn("live_judge_eval", result["artifact_paths"])


def _response(content: str, *, model: str) -> dict[str, Any]:
    response = _fake_openai_response()
    response["model"] = model
    response["choices"][0]["message"]["content"] = content
    return response


if __name__ == "__main__":
    unittest.main()
