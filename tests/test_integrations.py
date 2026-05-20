from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.evaluation.promptfoo_bridge import _parse_promptfoo_output
from services.orchestrator.goose_adapter import GooseCliAdapter
from services.orchestrator.goose_bridge import _command_env, _parse_review_text, _profile_timeout_seconds, _run_goose_prompt
from services.orchestrator.hermes_bridge import _hermes_chat_timeout_seconds
from shared.mesh_runtime import RuntimeConfig, resolve_integrations_config
from shared.mesh_runtime.integrations import build_readiness


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

            # Set env vars so goose profile resolution picks up ollama
            ollama_env = {
                "GOOSE_PROVIDER": "ollama",
                "GOOSE_MODEL": "qwen2.5:0.5b",
                "OLLAMA_HOST": "http://127.0.0.1:11434",
            }

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
                patch.dict(os.environ, ollama_env),
            ):
                resolved = resolve_integrations_config(config)

        self.assertIn("services.evaluation.promptfoo_bridge", resolved.promptfoo_command or "")
        self.assertIn("/usr/local/bin/promptfoo", resolved.promptfoo_command or "")
        self.assertIn("services.orchestrator.goose_bridge", resolved.goose_command or "")
        self.assertIn("--provider ollama", resolved.goose_command or "")
        self.assertIn("--model qwen2.5:0.5b", resolved.goose_command or "")

    def test_resolve_integrations_ignores_legacy_evo_saved_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "integrations.json"
            config_path.write_text(json.dumps({"evo_command": "evo"}), encoding="utf-8")

            resolved = resolve_integrations_config(
                RuntimeConfig(
                    state_directory=temp_dir,
                    integrations_config_path=str(config_path),
                )
            )

        self.assertNotIn("evo_command", resolved.to_dict())

    def test_staging_profile_brings_all_non_evo_connectors_online(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("shared.mesh_runtime.integrations.shutil.which", return_value=None):
                readiness = build_readiness(
                    RuntimeConfig(
                        state_directory=temp_dir,
                        vault_path=str(Path(temp_dir) / "vault"),
                        integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                        readiness_profile="staging",
                        feature_flag_credentials_available=False,
                        incident_credentials_available=False,
                    ),
                    force=True,
                ).to_dict()

        connectors = readiness["connector_certification"]
        self.assertNotIn("evo", connectors)
        self.assertIn("codex", connectors)
        self.assertIn("claudecode", connectors)
        self.assertIn("openclaw", connectors)
        optional_sidecars = {"zaxy", "eventloom", "neo4j_projection", "zaxy_mcp", "langgraph_checkpointing"}
        for connector_id, connector in connectors.items():
            if connector_id in optional_sidecars:
                self.assertEqual(connector["state"], "disabled", connector_id)
                continue
            if connector_id == "kubernetes":
                self.assertIn(connector["state"], {"staging-ready", "pilot-ready"})
            else:
                self.assertEqual(connector["state"], "staging-ready", connector_id)
            self.assertEqual(connector["blockers"], [], connector_id)
        self.assertFalse(connectors["codex"]["credential_boundary"]["repo_write_credentials_allowed"])
        self.assertFalse(connectors["openclaw"]["credential_boundary"]["production_actuator_credentials_allowed"])
        self.assertTrue(readiness["orchestration_topology"]["org_profile_ready"])
        self.assertTrue(readiness["promptfoo"]["ready"])
        self.assertTrue(readiness["hermes"]["ready"])
        self.assertTrue(readiness["goose"]["ready"])
        self.assertTrue(readiness["latentmas"]["ready"])
        self.assertTrue(readiness["deepagents"]["ready"])
        self.assertFalse(readiness["zaxy"]["ready"])
        self.assertFalse(readiness["eventloom"]["ready"])
        self.assertFalse(readiness["neo4j_projection"]["ready"])
        self.assertFalse(readiness["zaxy_mcp"]["ready"])
        self.assertFalse(readiness["langgraph_checkpointing"]["ready"])

    def test_zaxy_langgraph_readiness_is_optional_and_degraded_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            readiness = build_readiness(
                RuntimeConfig(
                    state_directory=temp_dir,
                    vault_path=str(Path(temp_dir) / "vault"),
                    integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                    zaxy_enabled=True,
                    zaxy_eventloom_outbox_path=str(Path(temp_dir) / "zaxy.jsonl"),
                    zaxy_neo4j_projection_enabled=True,
                    langgraph_enabled=True,
                    langgraph_checkpointer_url="file:///tmp/langgraph-checkpoints",
                    feature_flag_credentials_available=False,
                    incident_credentials_available=False,
                ),
                force=True,
            ).to_dict()

        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["zaxy"]["ready"])
        self.assertTrue(readiness["eventloom"]["ready"])
        self.assertTrue(readiness["neo4j_projection"]["ready"])
        self.assertFalse(readiness["zaxy_mcp"]["ready"])
        self.assertIn("zaxy_mcp_checkout_missing", readiness["zaxy_mcp"]["warnings"])
        self.assertIn("langgraph_checkpointing", readiness)
        self.assertNotIn("langgraph_checkpointing", readiness["blockers"])

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

    def test_resolve_integrations_wraps_hermes_binary_with_bridge_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
            )

            def fake_which(name: str) -> str | None:
                mapping = {
                    "promptfoo": "/usr/local/bin/promptfoo",
                    "hermes": "/Users/test/.local/bin/hermes",
                }
                return mapping.get(name)

            with patch("shared.mesh_runtime.integrations.shutil.which", side_effect=fake_which):
                resolved = resolve_integrations_config(config)

        self.assertIn("services.orchestrator.hermes_bridge", resolved.hermes_command or "")
        self.assertIn("/Users/test/.local/bin/hermes", resolved.hermes_command or "")

    def test_resolve_integrations_wraps_complex_hermes_command_with_bridge_command(self) -> None:
        config = RuntimeConfig(
            hermes_command="hermes"
        )

        resolved = resolve_integrations_config(config)

        self.assertIn("services.orchestrator.hermes_bridge", resolved.hermes_command or "")
        self.assertIn("--hermes-command hermes", resolved.hermes_command or "")
    def test_promptfoo_output_parser_supports_current_results_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            results_path = Path(temp_dir) / "results.json"
            results_path.write_text(
                json.dumps(
                    {
                        "results": {
                            "results": [
                                {
                                    "gradingResult": {
                                        "pass": True,
                                        "score": 1.0,
                                        "componentResults": [
                                            {
                                                "assertion": {"type": "python"},
                                                "pass": True,
                                                "score": 1.0,
                                                "reason": "observed latency exceeds baseline",
                                            }
                                        ],
                                    }
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
        self.assertEqual(artifact["score"], 1.0)
        self.assertEqual(artifact["assertions"][0]["reason"], "observed latency exceeds baseline")

    def test_resolve_integrations_prefers_configured_openai_compatible_goose_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
            )
            with (
                patch("shared.mesh_runtime.integrations.shutil.which", side_effect=lambda name: "/usr/local/bin/goose" if name == "goose" else None),
                patch.dict(
                    "os.environ",
                    {
                        "HERMES_INFERENCE_PROVIDER": "auto",
                        "HERMES_MODEL": "MiniMax-M2.5",
                        "LLM_MODEL": "MiniMax-M2.5",
                        "OPENAI_BASE_URL": "https://api.minimax.io/v1",
                    },
                    clear=False,
                ),
            ):
                resolved = resolve_integrations_config(config)

        self.assertIn("services.orchestrator.goose_bridge", resolved.goose_command or "")
        self.assertIn("--provider openai", resolved.goose_command or "")
        self.assertIn("--model MiniMax-M2.5", resolved.goose_command or "")

    def test_resolve_integrations_prefers_local_ollama_with_openai_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
            )
            with (
                patch("shared.mesh_runtime.integrations.shutil.which", side_effect=lambda name: "/usr/local/bin/goose" if name == "goose" else None),
                patch.dict(
                    "os.environ",
                    {
                        "GOOSE_PROVIDER": "ollama",
                        "GOOSE_MODEL": "gemma4:31b-it-q4_K_M",
                        "GOOSE_FALLBACK_PROVIDER": "openai",
                        "GOOSE_FALLBACK_MODEL": "MiniMax-M2.5",
                        "OPENAI_BASE_URL": "https://api.minimax.io/v1",
                    },
                    clear=False,
                ),
            ):
                resolved = resolve_integrations_config(config)

        self.assertIn("--provider ollama", resolved.goose_command or "")
        self.assertIn("--model gemma4:31b-it-q4_K_M", resolved.goose_command or "")
        self.assertIn("--fallback-provider openai", resolved.goose_command or "")
        self.assertIn("--fallback-model MiniMax-M2.5", resolved.goose_command or "")

    def test_goose_bridge_tries_fallback_profile_after_primary_cli_failure(self) -> None:
        args = argparse.Namespace(
            goose_bin="/usr/local/bin/goose",
            provider="ollama",
            model="gemma4:31b-it-q4_K_M",
            fallback_provider="openai",
            fallback_model="MiniMax-M2.5",
        )
        calls: list[list[str]] = []

        def fake_run(
            args: list[str],
            cwd: Path | str | None = None,
            capture_output: bool = False,
            text: bool = False,
            check: bool = False,
            timeout: int | float | None = None,
            env: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if "--provider" in args and args[args.index("--provider") + 1] == "ollama":
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="ollama unavailable")
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps({"messages": [{"role": "assistant", "content": [{"type": "text", "text": "ACK"}]}]}),
                stderr="",
            )

        with patch("services.orchestrator.goose_bridge.subprocess.run", side_effect=fake_run):
            payload, error = _run_goose_prompt(args, "Reply with ACK.", "System prompt")

        self.assertIsNone(error)
        self.assertIsNotNone(payload)
        self.assertEqual(len(calls), 2)
        self.assertIn("--provider", calls[0])
        self.assertEqual(calls[0][calls[0].index("--provider") + 1], "ollama")
        self.assertIn("--provider", calls[1])
        self.assertEqual(calls[1][calls[1].index("--provider") + 1], "openai")

    def test_goose_bridge_tries_fallback_profile_after_primary_timeout(self) -> None:
        args = argparse.Namespace(
            goose_bin="/usr/local/bin/goose",
            provider="ollama",
            model="gemma4:31b-it-q4_K_M",
            fallback_provider="openai",
            fallback_model="MiniMax-M2.5",
        )
        calls: list[list[str]] = []

        def fake_run(
            args: list[str],
            cwd: Path | str | None = None,
            capture_output: bool = False,
            text: bool = False,
            check: bool = False,
            timeout: int | float | None = None,
            env: dict[str, str] | None = None,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(args)
            if "--provider" in args and args[args.index("--provider") + 1] == "ollama":
                raise subprocess.TimeoutExpired(args, timeout or 0)
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps({"messages": [{"role": "assistant", "content": [{"type": "text", "text": "ACK"}]}]}),
                stderr="",
            )

        with patch("services.orchestrator.goose_bridge.subprocess.run", side_effect=fake_run):
            payload, error = _run_goose_prompt(args, "Reply with ACK.", "System prompt")

        self.assertIsNone(error)
        self.assertIsNotNone(payload)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][calls[0].index("--provider") + 1], "ollama")
        self.assertEqual(calls[1][calls[1].index("--provider") + 1], "openai")

    def test_goose_cli_adapter_uses_configured_timeout_budget(self) -> None:
        observed: dict[str, int | float | None] = {"timeout": None}

        def fake_run(
            args: list[str],
            input: str | None = None,
            capture_output: bool = False,
            text: bool = False,
            cwd: Path | str | None = None,
            check: bool = False,
            timeout: int | float | None = None,
        ) -> subprocess.CompletedProcess[str]:
            observed["timeout"] = timeout
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=json.dumps({"status": "succeeded", "external_refs": {}}),
                stderr="",
            )

        adapter = GooseCliAdapter(command="python3 -m services.orchestrator.goose_bridge", timeout_seconds=180)
        with patch("services.orchestrator.goose_adapter.subprocess.run", side_effect=fake_run):
            result = adapter._invoke({"mode": "execute", "decision": {}, "idempotency_key": "k"})

        self.assertEqual(observed["timeout"], 180)
        self.assertEqual(result["status"], "succeeded")

    def test_goose_bridge_run_timeout_env_overrides_provider_timeouts(self) -> None:
        with patch.dict("os.environ", {"MESH_GOOSE_RUN_TIMEOUT_SECONDS": "180"}, clear=False):
            self.assertEqual(_profile_timeout_seconds("ollama", False), 180)
            self.assertEqual(_profile_timeout_seconds("openai", True), 180)

    def test_hermes_bridge_chat_timeout_uses_command_budget(self) -> None:
        with patch.dict("os.environ", {"MESH_HERMES_COMMAND_TIMEOUT_SECONDS": "180"}, clear=False):
            self.assertEqual(_hermes_chat_timeout_seconds(), 180.0)

    def test_goose_openai_profile_preserves_base_url_without_host_alias(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_BASE_URL": "https://api.minimax.io/v1",
            },
            clear=False,
        ):
            env = _command_env("openai")

        self.assertEqual(env["OPENAI_BASE_URL"], "https://api.minimax.io/v1")
        self.assertNotIn("OPENAI_HOST", env)

    def test_parse_review_text_accepts_fenced_json(self) -> None:
        parsed = _parse_review_text(
            """```json
{"approved": true, "summary": "Proceed", "risk_flags": [], "next_action": "execute"}
```"""
        )

        self.assertTrue(parsed["approved"])
        self.assertEqual(parsed["summary"], "Proceed")

    def test_goose_anthropic_profile_preserves_base_url_without_host_alias(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
            },
            clear=False,
        ):
            env = _command_env("anthropic")

        self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://api.minimax.io/anthropic")
        self.assertNotIn("ANTHROPIC_HOST", env)

    def test_readiness_warns_when_ollama_model_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = RuntimeConfig(
                state_directory=temp_dir,
                integrations_config_path=str(Path(temp_dir) / "integrations.json"),
                goose_command="/usr/local/bin/goose",
            )

            def fake_run(
                args: list[str],
                capture_output: bool = False,
                text: bool = False,
                check: bool = False,
                timeout: int | float | None = None,
            ) -> subprocess.CompletedProcess[str]:
                if len(args) >= 4 and args[1:3] == ["-m", "services.orchestrator.goose_bridge"] and args[-1] == "--version":
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="1.30.0\n", stderr="")
                raise AssertionError(f"unexpected subprocess args: {args}")

            class FakeResponse:
                def __init__(self, payload: dict):
                    self.payload = payload
                    self.status = 200

                def read(self) -> bytes:
                    return json.dumps(self.payload).encode("utf-8")

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            with (
                patch.dict(
                    "os.environ",
                    {
                        "GOOSE_PROVIDER": "ollama",
                        "GOOSE_MODEL": "gemma4:31b-it-q4_K_M",
                        "GOOSE_FALLBACK_PROVIDER": "openai",
                        "GOOSE_FALLBACK_MODEL": "MiniMax-M2.5",
                        "OLLAMA_HOST": "http://ollama.local:11434",
                    },
                    clear=False,
                ),
                patch("shared.mesh_runtime.integrations.shutil.which", side_effect=lambda name: "/usr/local/bin/goose" if name == "goose" else None),
                patch("shared.mesh_runtime.integrations.subprocess.run", side_effect=fake_run),
                patch(
                    "shared.mesh_runtime.integrations.urlopen",
                    return_value=FakeResponse({"models": [{"name": "qwen2.5:0.5b"}]}),
                ),
            ):
                readiness = build_readiness(config)

        self.assertTrue(readiness.goose.ready)
        self.assertEqual(readiness.goose.primary_route, "ollama/gemma4:31b-it-q4_K_M")
        self.assertEqual(readiness.goose.fallback_route, "openai/MiniMax-M2.5")
        self.assertTrue(readiness.goose.warnings)
        self.assertIn("ollama reachable but model `gemma4:31b-it-q4_K_M` is not loaded", readiness.goose.warnings[0])

    def test_goose_review_parser_accepts_json_review(self) -> None:
        review = _parse_review_text(
            json.dumps(
                {
                    "approved": True,
                    "summary": "bounded execution looks safe",
                    "risk_flags": ["none"],
                    "next_action": "proceed",
                    "patch": {
                        "target_file": "app/search.py",
                        "find": "old",
                        "replace": "new",
                    },
                    "test_commands": ["python3 -m unittest discover -s tests"],
                }
            )
        )
        self.assertTrue(review["approved"])
        self.assertEqual(review["summary"], "bounded execution looks safe")
        self.assertEqual(review["next_action"], "proceed")
        self.assertEqual(review["patch"]["target_file"], "app/search.py")
        self.assertEqual(review["test_commands"][0], "python3 -m unittest discover -s tests")


if __name__ == "__main__":
    unittest.main()
