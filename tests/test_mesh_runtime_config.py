"""RuntimeConfig path resolution (repo-anchored relative MESH_* paths)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shared.mesh_runtime.config import (
    DEFAULT_AGENTIC_OPERATOR_SOURCE_PROVENANCE_PATH,
    DEFAULT_AUDIT_SINK_CERTIFICATION_PATH,
    DEFAULT_AUTHENTICATED_INGRESS_PROOF_PATH,
    DEFAULT_CORPUS_DATABASE_PATH,
    DEFAULT_DATA_CLASSIFICATION_POLICY_PATH,
    DEFAULT_DESIGN_PARTNER_PACKET_PATH,
    DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH,
    DEFAULT_FAILURE_MODE_LIBRARY_PATH,
    DEFAULT_FEATURE_FLAG_PROVIDER_PROOF_PATH,
    DEFAULT_INCIDENT_PROVIDER_PROOF_PATH,
    DEFAULT_LOAD_CONCURRENCY_REHEARSAL_PATH,
    DEFAULT_ON_CALL_DRILL_PATH,
    DEFAULT_ORCHESTRATION_TOPOLOGY_DRILL_PATH,
    DEFAULT_PROCUREMENT_SECURITY_PACKAGE_PATH,
    DEFAULT_PUBLIC_PROOF_PACKAGE_PATH,
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

    def test_non_local_app_session_signup_requires_captcha_provider(self) -> None:
        for environment in ("staging", "pilot"):
            with self.subTest(environment=environment):
                with self.assertRaisesRegex(
                    ValueError,
                    "captcha must be configured for app_session signup outside local",
                ):
                    RuntimeConfig(
                        environment=environment,
                        auth_mode="app_session",
                        operator_identity_path="/tmp/operator-identity.json",
                        signup_enabled=True,
                        password_auth_enabled=True,
                        captcha_provider="disabled",
                    )

        with self.assertRaisesRegex(
            ValueError,
            "captcha must be configured for app_session signup outside local",
        ):
            RuntimeConfig(
                environment="staging",
                auth_mode="app_session",
                operator_identity_path="/tmp/operator-identity.json",
                signup_enabled=True,
                password_auth_enabled=True,
                captcha_provider="hcaptcha",
                captcha_site_key="site-key",
                captcha_secret_key="",
            )

    def test_non_local_app_session_signup_accepts_complete_captcha_provider(self) -> None:
        cfg = RuntimeConfig(
            environment="staging",
            auth_mode="app_session",
            operator_identity_path="/tmp/operator-identity.json",
            signup_enabled=True,
            password_auth_enabled=True,
            captcha_provider="hcaptcha",
            captcha_site_key="site-key",
            captcha_secret_key="secret-key",
        )

        self.assertEqual(cfg.auth_mode, "app_session")
        self.assertEqual(cfg.captcha_provider, "hcaptcha")

    def test_correlation_can_be_disabled(self) -> None:
        with patch.dict("os.environ", {"MESH_CORRELATION_ENABLED": "false"}, clear=True):
            cfg = RuntimeConfig.from_env()
        self.assertFalse(cfg.correlation_enabled)

    def test_livekit_agent_flow_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MESH_LIVEKIT_URL": "wss://livekit.example.test",
                "MESH_LIVEKIT_API_KEY": "lk-key",
                "MESH_LIVEKIT_API_SECRET": "lk-secret",
                "MESH_LIVEKIT_ACCESS_TOKEN": "preminted-browser-token",
                "MESH_LIVEKIT_TOKEN_TTL_SECONDS": "900",
                "MESH_LIVEKIT_AGENT_NAME": "Harper-696",
            },
            clear=True,
        ):
            cfg = RuntimeConfig.from_env()

        self.assertEqual(cfg.livekit_url, "wss://livekit.example.test")
        self.assertEqual(cfg.livekit_api_key, "lk-key")
        self.assertEqual(cfg.livekit_api_secret, "lk-secret")
        self.assertEqual(cfg.livekit_access_token, "preminted-browser-token")
        self.assertEqual(cfg.livekit_token_ttl_seconds, 900)
        self.assertEqual(cfg.livekit_agent_name, "Harper-696")

    def test_livekit_agent_flow_ttl_must_be_positive(self) -> None:
        with self.assertRaisesRegex(ValueError, "livekit_token_ttl_seconds must be > 0"):
            RuntimeConfig(livekit_token_ttl_seconds=0)

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

    def test_helix_memory_graph_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "MESH_MEMORY_GRAPH_BACKEND": "helix",
                "MESH_HELIX_API_ENDPOINT": "https://helix.example.test",
                "MESH_HELIX_PORT": "7979",
                "MESH_HELIX_QUERY_NAMESPACE": "meshPilot",
            },
            clear=True,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertEqual(cfg.memory_graph_backend, "helix")
        self.assertEqual(cfg.helix_api_endpoint, "https://helix.example.test")
        self.assertEqual(cfg.helix_port, 7979)
        self.assertEqual(cfg.helix_query_namespace, "meshPilot")

    def test_invalid_helix_memory_graph_backend_fails_closed(self) -> None:
        with patch.dict("os.environ", {"MESH_MEMORY_GRAPH_BACKEND": "maybe"}, clear=True):
            with self.assertRaises(ValueError):
                RuntimeConfig.from_env()

    def test_invalid_helix_query_namespace_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeConfig(memory_graph_backend="helix", helix_query_namespace="mesh-prod")

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

    def test_deployment_compatibility_registry_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH": "config/deployment-compatibility.registry.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.deployment_compatibility_registry_path).is_absolute())
        self.assertEqual(
            Path(cfg.deployment_compatibility_registry_path),
            DEFAULT_DEPLOYMENT_COMPATIBILITY_REGISTRY_PATH.resolve(),
        )

    def test_procurement_security_package_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_PROCUREMENT_SECURITY_PACKAGE_PATH": "config/procurement-security.package.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.procurement_security_package_path).is_absolute())
        self.assertEqual(
            Path(cfg.procurement_security_package_path),
            DEFAULT_PROCUREMENT_SECURITY_PACKAGE_PATH.resolve(),
        )

    def test_public_proof_package_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_PUBLIC_PROOF_PACKAGE_PATH": "config/public-proof.package.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.public_proof_package_path).is_absolute())
        self.assertEqual(
            Path(cfg.public_proof_package_path),
            DEFAULT_PUBLIC_PROOF_PACKAGE_PATH.resolve(),
        )

    def test_authenticated_ingress_proof_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_AUTHENTICATED_INGRESS_PROOF_PATH": ".mesh-runtime-state/proofs/authenticated-ingress-deployment-proof.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertIsNotNone(cfg.authenticated_ingress_proof_path)
        assert cfg.authenticated_ingress_proof_path is not None
        self.assertTrue(Path(cfg.authenticated_ingress_proof_path).is_absolute())
        self.assertEqual(
            Path(cfg.authenticated_ingress_proof_path),
            DEFAULT_AUTHENTICATED_INGRESS_PROOF_PATH.resolve(),
        )

    def test_design_partner_packet_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_DESIGN_PARTNER_PACKET_PATH": ".mesh-runtime-state/proofs/design-partner-packet.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertIsNotNone(cfg.design_partner_packet_path)
        assert cfg.design_partner_packet_path is not None
        self.assertTrue(Path(cfg.design_partner_packet_path).is_absolute())
        self.assertEqual(Path(cfg.design_partner_packet_path), DEFAULT_DESIGN_PARTNER_PACKET_PATH.resolve())

    def test_load_concurrency_rehearsal_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_LOAD_CONCURRENCY_REHEARSAL_PATH": ".mesh-runtime-state/load-concurrency-rehearsal.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertIsNotNone(cfg.load_concurrency_rehearsal_path)
        assert cfg.load_concurrency_rehearsal_path is not None
        self.assertTrue(Path(cfg.load_concurrency_rehearsal_path).is_absolute())
        self.assertEqual(
            Path(cfg.load_concurrency_rehearsal_path),
            DEFAULT_LOAD_CONCURRENCY_REHEARSAL_PATH.resolve(),
        )

    def test_orchestration_topology_drill_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_ORCHESTRATION_TOPOLOGY_DRILL_PATH": ".mesh-runtime-state/orchestration-topology-drill.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertIsNotNone(cfg.orchestration_topology_drill_path)
        assert cfg.orchestration_topology_drill_path is not None
        self.assertTrue(Path(cfg.orchestration_topology_drill_path).is_absolute())
        self.assertEqual(
            Path(cfg.orchestration_topology_drill_path),
            DEFAULT_ORCHESTRATION_TOPOLOGY_DRILL_PATH.resolve(),
        )

    def test_audit_sink_certification_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_AUDIT_SINK_CERTIFICATION_PATH": ".mesh-runtime-state/audit-sink-certification.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertIsNotNone(cfg.audit_sink_certification_path)
        assert cfg.audit_sink_certification_path is not None
        self.assertTrue(Path(cfg.audit_sink_certification_path).is_absolute())
        self.assertEqual(
            Path(cfg.audit_sink_certification_path),
            DEFAULT_AUDIT_SINK_CERTIFICATION_PATH.resolve(),
        )

    def test_feature_flag_provider_proof_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_FEATURE_FLAG_PROVIDER_PROOF_PATH": ".mesh-runtime-state/feature-flag-provider-proof.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertIsNotNone(cfg.feature_flag_provider_proof_path)
        assert cfg.feature_flag_provider_proof_path is not None
        self.assertTrue(Path(cfg.feature_flag_provider_proof_path).is_absolute())
        self.assertEqual(
            Path(cfg.feature_flag_provider_proof_path),
            DEFAULT_FEATURE_FLAG_PROVIDER_PROOF_PATH.resolve(),
        )

    def test_incident_provider_proof_path_env_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_INCIDENT_PROVIDER_PROOF_PATH": ".mesh-runtime-state/incident-provider-proof.json"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertIsNotNone(cfg.incident_provider_proof_path)
        assert cfg.incident_provider_proof_path is not None
        self.assertTrue(Path(cfg.incident_provider_proof_path).is_absolute())
        self.assertEqual(
            Path(cfg.incident_provider_proof_path),
            DEFAULT_INCIDENT_PROVIDER_PROOF_PATH.resolve(),
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
