"""RuntimeConfig path resolution (repo-anchored relative MESH_* paths)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.mesh_runtime.config import (
    DEFAULT_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH,
    DEFAULT_CORPUS_DATABASE_PATH,
    DEFAULT_DATA_CLASSIFICATION_POLICY_PATH,
    DEFAULT_FAILURE_MODE_LIBRARY_PATH,
    DEFAULT_ON_CALL_DRILL_PATH,
    DEFAULT_RESEARCH_DIRECTORY,
    DEFAULT_STATE_DIRECTORY,
    DEFAULT_THREAT_MODEL_REGISTER_PATH,
    RuntimeConfig,
)
from shared.mesh_runtime.state import parse_state_json_file


class RuntimeConfigPathTests(unittest.TestCase):
    def test_correlation_enabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(cfg.correlation_enabled)

    def test_correlation_can_be_disabled(self) -> None:
        with patch.dict("os.environ", {"MESH_CORRELATION_ENABLED": "false"}, clear=True):
            cfg = RuntimeConfig.from_env()
        self.assertFalse(cfg.correlation_enabled)

    def test_observer_prompt_cache_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MESH_OBSERVER_PROMPT_CACHE_ENABLED": "0",
                "MESH_OBSERVER_PROMPT_CACHE_MODE": "automatic",
                "MESH_OBSERVER_PROMPT_CACHE_TTL": "1h",
            },
            clear=True,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertFalse(cfg.observer_prompt_cache_enabled)
        self.assertEqual(cfg.observer_prompt_cache_mode, "automatic")
        self.assertEqual(cfg.observer_prompt_cache_ttl, "1h")

    def test_relative_state_directory_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_STATE_DIRECTORY": ".mesh-runtime-state"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.state_directory).is_absolute())
        self.assertEqual(Path(cfg.state_directory), DEFAULT_STATE_DIRECTORY.resolve())

    def test_absolute_state_directory_unchanged(self) -> None:
        raw = str(Path("/tmp/mesh-state-absolute").resolve())
        with patch.dict(
            "os.environ",
            {"MESH_STATE_DIRECTORY": raw},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertEqual(cfg.state_directory, raw)

    def test_direct_state_directory_derives_research_directory(self) -> None:
        raw = str(Path("/tmp/mesh-state-direct").resolve())
        cfg = RuntimeConfig(state_directory=raw)
        self.assertEqual(cfg.research_directory, str(Path(raw) / "research"))
        self.assertEqual(cfg.corpus_database_path, str(Path(raw) / "corpus" / "incident_corpus.sqlite"))

    def test_relative_research_directory_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_RESEARCH_DIRECTORY": ".mesh-runtime-state/research"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.research_directory).is_absolute())
        self.assertEqual(Path(cfg.research_directory), DEFAULT_RESEARCH_DIRECTORY.resolve())

    def test_corpus_memory_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MESH_CORPUS_MEMORY_ENABLED": "1",
                "MESH_CORPUS_DATABASE_PATH": ".mesh-runtime-state/corpus/incident_corpus.sqlite",
                "MESH_CORPUS_MEMORY_PROJECTION_LIMIT": "123",
            },
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(cfg.corpus_memory_enabled)
        self.assertTrue(Path(cfg.corpus_database_path).is_absolute())
        self.assertEqual(Path(cfg.corpus_database_path), DEFAULT_CORPUS_DATABASE_PATH.resolve())
        self.assertEqual(cfg.corpus_memory_projection_limit, 123)

    def test_on_call_drill_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_ON_CALL_DRILL_PATH": ".mesh-runtime-state/on-call-drill.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertIsNotNone(cfg.on_call_drill_path)
        assert cfg.on_call_drill_path is not None
        self.assertTrue(Path(cfg.on_call_drill_path).is_absolute())
        self.assertEqual(Path(cfg.on_call_drill_path), DEFAULT_ON_CALL_DRILL_PATH.resolve())

    def test_failure_mode_library_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_FAILURE_MODE_LIBRARY_PATH": "config/failure-mode.library.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.failure_mode_library_path).is_absolute())
        self.assertEqual(Path(cfg.failure_mode_library_path), DEFAULT_FAILURE_MODE_LIBRARY_PATH.resolve())

    def test_threat_model_register_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_THREAT_MODEL_REGISTER_PATH": "config/threat-model.register.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.threat_model_register_path).is_absolute())
        self.assertEqual(Path(cfg.threat_model_register_path), DEFAULT_THREAT_MODEL_REGISTER_PATH.resolve())

    def test_data_classification_policy_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_DATA_CLASSIFICATION_POLICY_PATH": "config/data-classification.policy.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.data_classification_policy_path).is_absolute())
        self.assertEqual(Path(cfg.data_classification_policy_path), DEFAULT_DATA_CLASSIFICATION_POLICY_PATH.resolve())

    def test_agentic_operator_source_provenance_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH": "config/agentic-operator-source.provenance.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.agentic_operator_source_provenance_path).is_absolute())
        self.assertEqual(
            Path(cfg.agentic_operator_source_provenance_path),
            DEFAULT_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH.resolve(),
        )

    def test_darkharness_registry_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_DARKHARNESS_REGISTRY_PATH": ".mesh-runtime-state/darkharness-registry.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertIsNotNone(cfg.darkharness_registry_path)
        assert cfg.darkharness_registry_path is not None
        self.assertTrue(Path(cfg.darkharness_registry_path).is_absolute())
        self.assertEqual(
            Path(cfg.darkharness_registry_path),
            (DEFAULT_STATE_DIRECTORY / "darkharness-registry.json").resolve(),
        )

    def test_darkharness_packet_persistence_is_explicitly_ephemeral(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_DARKHARNESS_PACKET_PERSISTENCE_MODE": "ephemeral"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertEqual(cfg.darkharness_packet_persistence_mode, "ephemeral")

        with self.assertRaisesRegex(ValueError, "only supports ephemeral"):
            RuntimeConfig(darkharness_packet_persistence_mode="audit_artifact")

    def test_darkharness_signing_env_configures_local_hmac_key(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MESH_DARKHARNESS_SIGNING_KEY": "local-secret",
                "MESH_DARKHARNESS_SIGNING_KEY_ID": "local-key",
            },
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertEqual(cfg.darkharness_signing_key, "local-secret")
        self.assertEqual(cfg.darkharness_signing_key_id, "local-key")

    def test_darkharness_classical_signing_key_can_load_from_env_or_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "darkharness-ed25519.pem"
            key_path.write_text("file-private-key", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "MESH_DARKHARNESS_CLASSICAL_SIGNING_KEY_PATH": str(key_path),
                    "MESH_DARKHARNESS_CLASSICAL_SIGNING_KEY_ID": "file-key",
                },
                clear=False,
            ):
                file_cfg = RuntimeConfig.from_env()
            self.assertEqual(file_cfg.darkharness_classical_signing_key_pem, "file-private-key")
            self.assertEqual(file_cfg.darkharness_classical_signing_key_id, "file-key")

        with patch.dict(
            "os.environ",
            {
                "MESH_DARKHARNESS_CLASSICAL_SIGNING_KEY_PEM": "inline-private-key",
                "MESH_DARKHARNESS_CLASSICAL_SIGNING_KEY_PATH": "/ignored/key.pem",
                "MESH_DARKHARNESS_CLASSICAL_SIGNING_KEY_ID": "inline-key",
            },
            clear=False,
        ):
            inline_cfg = RuntimeConfig.from_env()
        self.assertEqual(inline_cfg.darkharness_classical_signing_key_pem, "inline-private-key")
        self.assertEqual(inline_cfg.darkharness_classical_signing_key_id, "inline-key")

    def test_parse_state_json_file_corrupt_writes_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_sessions.json"
            raw = '{"runs": [{"run_id": "x" INVALID}]}'
            self.assertEqual(parse_state_json_file(path, raw), {})
            backups = sorted(Path(tmp).glob("run_sessions.json.corrupt.*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), raw)

    def test_parse_state_json_file_valid_round_trip(self) -> None:
        payload = {"runs": [{"run_id": "run_1"}]}
        raw = json.dumps(payload)
        self.assertEqual(parse_state_json_file(Path("/tmp/ignored.json"), raw), payload)


if __name__ == "__main__":
    unittest.main()
