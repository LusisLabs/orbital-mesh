from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from mesh_brain.live_quality_training import (
    _build_clean_quality_examples,
    _clean_case_from_seed,
    _discover_mesh_corpus_rows,
    _generate_command,
    _hard_format_prompt,
    _read_generation_text,
    _live_status,
    _parse_training_metrics,
    _quality_bootstrap_corpus_rows,
    _remove_fused_model_shards,
    _system_prompt,
)
from mesh_brain.mlx_lm_lora_e2e import MlxLmLoraCommandResult
from shared.mesh_runtime.corpus_store import IncidentCorpusDatabase


class MeshBrainLiveQualityTrainingTests(unittest.TestCase):
    def test_parse_training_metrics_ignores_model_name_nan_substrings(self) -> None:
        with TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "train.stdout.log"
            log_path.write_text(
                "Model: mlx-community/NVIDIA-Nemotron-3-Nano-4B-BF16\n"
                "Iter 1: Val loss 6.667, Val took 0.130s\n"
                "Iter 1: loss 6.659, lr 1.000e-05\n"
                "Iter 2: Val loss 5.129, Val took 0.097s\n"
                "Iter 2: loss 5.128, lr 1.000e-05\n"
                "Saved final weights to adapters.safetensors.\n",
                encoding="utf-8",
            )

            metrics = _parse_training_metrics(stdout_paths=[log_path])

        self.assertEqual(metrics["nan_count"], 0.0)
        self.assertEqual(metrics["train_loss_start"], 6.659)
        self.assertEqual(metrics["train_loss_final"], 5.128)
        self.assertEqual(metrics["valid_loss_final"], 5.129)
        self.assertEqual(metrics["checkpoint_count"], 1.0)

    def test_live_status_accepts_adapter_saved_postsave_failure_when_gate_blocks_or_promotes(self) -> None:
        sft = _command("completed")
        preference = _command("adapter_saved_postsave_failed")
        native = _command("completed")

        self.assertEqual(
            _live_status(
                sft_result=sft,
                preference_result=preference,
                run_preference=True,
                native_result=native,
                run_native_inference=True,
                quality_decision="block",
            ),
            "blocked",
        )
        self.assertEqual(
            _live_status(
                sft_result=sft,
                preference_result=preference,
                run_preference=True,
                native_result=native,
                run_native_inference=True,
                quality_decision="promote",
            ),
            "completed",
        )

    def test_generate_command_uses_tokenizer_chat_template_inputs(self) -> None:
        command = _generate_command(model_id="model", prompt="Assess latency evidence.", adapter_directory=None)

        self.assertIn("--system-prompt", command)
        self.assertIn(_system_prompt(), command)
        self.assertIn("--prompt", command)
        self.assertIn("Assess latency evidence.", command)
        self.assertIn("--prefill-response", command)
        self.assertIn("Evidence:", command)
        self.assertIn("--extra-eos-token", command)
        self.assertNotIn("<|im_start|>user", command)

    def test_generation_text_reconstructs_prefill_for_artifacts(self) -> None:
        with TemporaryDirectory() as temp_dir:
            stdout_path = Path(temp_dir) / "generate.stdout.log"
            stdout_path.write_text("p95 latency doubled.\nApproval: required.\n", encoding="utf-8")

            text = _read_generation_text(stdout_path)

        self.assertTrue(text.startswith("Evidence: p95 latency doubled."))
        self.assertIn("Approval: required.", text)

    def test_bootstrap_corpus_and_cleanup_are_bounded(self) -> None:
        rows = _quality_bootstrap_corpus_rows()
        with TemporaryDirectory() as temp_dir:
            adapter_path = Path(temp_dir)
            (adapter_path / "adapters.safetensors").write_text("adapter", encoding="utf-8")
            (adapter_path / "model-00001-of-00002.safetensors").write_text("fused", encoding="utf-8")
            (adapter_path / "model.safetensors.index.json").write_text("{}", encoding="utf-8")

            _remove_fused_model_shards(adapter_path)

            self.assertTrue((adapter_path / "adapters.safetensors").exists())
            self.assertFalse((adapter_path / "model-00001-of-00002.safetensors").exists())
            self.assertFalse((adapter_path / "model.safetensors.index.json").exists())

        self.assertGreaterEqual(len(rows), 6)
        self.assertTrue(all("training" in row["labels"]["mesh_use"] for row in rows))

    def test_clean_examples_synthesize_policy_rows_from_corpus_without_json_fragments(self) -> None:
        corpus_row = {
            "row_id": "corpus_peer_starvation",
            "service": "reth",
            "target_class": "ethereum_execution_client",
            "source": {"kind": "reth_kurtosis"},
            "training_fact": {"outcome": "human_hold"},
            "evidence_envelope": {
                "summary": "Peer count dropped and sync stalled after network partition.",
            },
        }

        examples = _build_clean_quality_examples(corpus_rows=[corpus_row])

        self.assertGreaterEqual(len(examples["sft_rows"]), 24)
        first = examples["sft_rows"][0]
        self.assertIn("Incident evidence:", first["messages"][1]["content"])
        self.assertIn("Evidence:", first["messages"][2]["content"])
        self.assertIn("Bounded remediation:", first["messages"][2]["content"])
        self.assertIn("Approval:", first["messages"][2]["content"])
        self.assertIn("Execution:", first["messages"][2]["content"])
        self.assertTrue(any(row["row_id"].endswith("_hard_format") for row in examples["sft_rows"]))
        self.assertTrue(any("anti_repetition" in row["rationale_labels"] for row in examples["preference_rows"]))
        self.assertNotIn('{"', first["messages"][1]["content"])
        self.assertTrue(any(row["source_kind"] == "reth_kurtosis" for row in examples["provenance"]))

    def test_hard_format_prompt_uses_concrete_targets_not_placeholders(self) -> None:
        prompt = _hard_format_prompt(
            {
                "service": "api",
                "evidence": "API restart is proposed and requires human approval",
            }
        )

        self.assertIn("Evidence: API restart is proposed", prompt)
        self.assertIn("Bounded remediation: verify the finding for api", prompt)
        self.assertNotIn("<cite", prompt)
        self.assertNotIn("<safe", prompt)
        self.assertNotIn("<state", prompt)

    def test_discovers_rows_from_incident_corpus_database(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "incident_corpus.sqlite"
            database = IncidentCorpusDatabase(database_path)
            database.import_rows(
                [
                    {
                        "row_id": "db_row_1",
                        "schema_version": "mesh.incident_corpus.v1",
                        "source": {
                            "kind": "unit_db",
                            "collector": "unit",
                            "session_id": "session_1",
                            "cycle_dir": "cycle_1",
                            "profile": "unit_profile",
                            "cycle": 1,
                            "run_id": "run_1",
                        },
                        "service": "checkout",
                        "target_class": "deployment",
                        "domain": "web2",
                        "environment": "test",
                        "created_at": "2026-04-30T00:00:00+00:00",
                        "labels": {"mesh_use": ["training"]},
                        "training_fact": {"outcome": "successful", "promotion_candidate": True},
                        "evidence_envelope": {"summary": "Checkout errors recovered after bounded rollback proposal."},
                    }
                ]
            )

            rows = _discover_mesh_corpus_rows(database_path=database_path, jsonl_limit=4)
            case = _clean_case_from_seed(rows[0])

        self.assertEqual(rows[0]["row_id"], "db_row_1")
        self.assertIsNotNone(case)
        self.assertEqual(case["service"], "checkout")
        self.assertIn("Checkout errors", case["evidence"])


def _command(status: str) -> MlxLmLoraCommandResult:
    return MlxLmLoraCommandResult(
        command=["mlx_lm_lora.train"],
        status=status,
        return_code=0 if status == "completed" else 1,
        stdout_path="/tmp/stdout.log",
        stderr_path="/tmp/stderr.log",
        started_at="2026-04-30T00:00:00+00:00",
        completed_at="2026-04-30T00:00:01+00:00",
    )


if __name__ == "__main__":
    unittest.main()
