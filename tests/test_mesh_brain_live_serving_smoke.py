from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch

from mesh_brain.run_live_serving_smoke import run_live_serving_smoke
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

        self.assertEqual(summary["status"], "passed")
        self.assertEqual(summary["model"], "nvidia/nemotron-3-nano-4b")
        self.assertEqual(captured["url"], "http://127.0.0.1:1234/v1/chat/completions")
        self.assertEqual(captured["payload"]["model"], "nvidia/nemotron-3-nano-4b")
        self.assertEqual(execution["plan"]["backend_name"], "mlx")
        self.assertEqual(execution["completion"]["model"], "nvidia/nemotron-3-nano-4b")


if __name__ == "__main__":
    unittest.main()
