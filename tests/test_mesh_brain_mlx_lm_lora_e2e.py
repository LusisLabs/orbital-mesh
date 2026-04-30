from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain.mlx_lm_lora_e2e import (
    DEFAULT_MODEL_ID,
    prepare_mlx_lm_lora_sft_data,
    run_mlx_lm_lora_e2e,
)


class MeshBrainMlxLmLoraE2ETests(unittest.TestCase):
    def test_prepare_mlx_lm_lora_sft_data_writes_message_splits(self) -> None:
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "sft.jsonl"
            source.write_text(
                json.dumps(
                    {
                        "row_id": "row_1",
                        "excluded_from_training": False,
                        "provenance_pointer": "runtime://row_1",
                        "payload": {
                            "instruction": "Respect approval boundaries.",
                            "context": "Search p95 latency increased after deploy.",
                            "expected_response": "Inspect evidence and request approval before protected action.",
                        },
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            paths = prepare_mlx_lm_lora_sft_data(
                mesh_sft_path=source,
                output_directory=Path(temp_dir) / "mlx",
            )
            train = json.loads(Path(paths["train.jsonl"]).read_text(encoding="utf-8").splitlines()[0])

        self.assertEqual(set(paths), {"train.jsonl", "valid.jsonl", "test.jsonl", "dataset_manifest.json"})
        self.assertEqual([message["role"] for message in train["messages"]], ["system", "user", "assistant"])
        self.assertIn("Search p95 latency", train["messages"][1]["content"])
        self.assertIn("request approval", train["messages"][2]["content"])

    def test_run_mlx_lm_lora_e2e_can_prepare_plan_without_native_execution(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result = run_mlx_lm_lora_e2e(
                output_directory=Path(temp_dir),
                train=False,
                native_inference=False,
                fuse=False,
                lm_studio=False,
            )
            command_plan = json.loads(Path(result.artifact_paths["command_plan"]).read_text(encoding="utf-8"))

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.model_id, DEFAULT_MODEL_ID)
        self.assertEqual(result.adapter_export["export_format"], "mlx_lm_lora")
        self.assertIn("--model", command_plan["train"])
        self.assertIn(DEFAULT_MODEL_ID, command_plan["train"])
        self.assertIn("--adapter-path", command_plan["native_inference"])


if __name__ == "__main__":
    unittest.main()
