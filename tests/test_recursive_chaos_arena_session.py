from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import recursive_chaos_arena_session as arena
from shared.mesh_runtime.recursive_chaos import (
    get_recursive_chaos_arena_profile,
    validate_arena_evidence_bundle,
    validate_chaos_learning_packet,
    validate_ghost_state_recovery_packet,
    validate_recursive_chaos_cycle_packet,
    validate_recursive_chaos_experiment_manifest,
)
from tests.e2e.chaos.portfolio import DEFAULT_PORTFOLIO


class RecursiveChaosArenaSessionTests(unittest.TestCase):
    def test_catalog_session_emits_sealed_packets_for_p0_profiles(self) -> None:
        targets = [
            arena.ArenaTarget(
                profile_id="kubernetes_service_platform",
                context="kind-mesh",
                namespace="mesh",
                deployment="api",
                substrate="kubernetes",
                environment="local",
                image_ref="registry.local/api@sha256:test",
            ),
            arena.ArenaTarget(
                profile_id="observability_signal_trust",
                context="kind-mesh",
                namespace="mesh",
                deployment="otel-collector",
                substrate="kubernetes",
                environment="local",
                image_ref="registry.local/otel@sha256:test",
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            summary = arena.run_recursive_chaos_arena_session(
                targets=targets,
                output_dir=tmp,
                max_cycles=2,
                seed=7,
                execute=False,
            )

            self.assertEqual(summary["status"], "pass")
            self.assertEqual(summary["cycles_total"], 2)
            for cycle_id in summary["cycle_packet_refs"]:
                cycle_dir = Path(tmp) / cycle_id
                self.assertTrue((cycle_dir / "manifest.json").exists())
                validate_recursive_chaos_experiment_manifest(_read_json(cycle_dir / "manifest.json"))
                validate_recursive_chaos_cycle_packet(_read_json(cycle_dir / "cycle-packet.json"))
                validate_ghost_state_recovery_packet(_read_json(cycle_dir / "ghost-recovery-packet.json"))
                validate_chaos_learning_packet(_read_json(cycle_dir / "learning-packet.json"))
                validate_arena_evidence_bundle(_read_json(cycle_dir / "evidence-bundle.json"))

    def test_hetzner_target_is_probe_only_and_does_not_select_mutating_experiment(self) -> None:
        target = arena.ArenaTarget(
            profile_id="multi_region_provider_plane",
            context="hetzner-prod",
            namespace="mesh",
            deployment="api",
            substrate="kubernetes",
            environment="hetzner",
            image_ref="registry.example/api@sha256:test",
        )

        profile = get_recursive_chaos_arena_profile("multi_region_provider_plane")
        safety_class = "production_probe_only"
        experiment = arena.select_arena_experiment(profile, arena.random.Random(1), safety_class=safety_class)
        manifest = arena.build_experiment_manifest(profile, target, experiment, safety_class)

        self.assertIsNone(experiment)
        self.assertEqual(manifest["experiments"][0]["experiment_id"], "probe_only_observation")
        self.assertFalse(manifest["experiments"][0]["mutates_target"])
        self.assertTrue(manifest["safety_gates"]["requires_probe_only"])
        self.assertFalse(manifest["safety_gates"]["allow_mutation"])

    def test_execute_refuses_probe_only_targets_before_injector_use(self) -> None:
        target = arena.ArenaTarget(
            profile_id="crypto_rpc_node_mesh",
            context="prod",
            namespace="mesh",
            deployment="reth",
            substrate="kubernetes",
            environment="production",
            image_ref="registry.example/reth@sha256:test",
        )

        with tempfile.TemporaryDirectory() as tmp:
            summary = arena.run_recursive_chaos_arena_session(
                targets=[target],
                output_dir=tmp,
                max_cycles=1,
                execute=True,
            )

        self.assertEqual(summary["status"], "fail")
        self.assertIn("production_probe_only", summary["blockers"][0])
        self.assertIn("refusing mutating compose/k8s execution", summary["blockers"][0])

    def test_execute_compose_sandbox_runs_disposable_fault_lane(self) -> None:
        target = arena.ArenaTarget(
            profile_id="kubernetes_service_platform",
            context="compose-sandbox",
            namespace="recursive-chaos",
            deployment="disposable-http-target",
            substrate="compose_sandbox",
            environment="local_disposable",
            image_ref="python:3.13-slim-trixie",
        )

        def fake_compose(
            _compose_path: Path,
            _project: str,
            *args: str,
            check: bool = True,
        ) -> subprocess.CompletedProcess[str]:
            command = " ".join(args)
            if command == "ps --format json":
                return subprocess.CompletedProcess(args=list(args), returncode=0, stdout='[{"Service":"target","State":"running"}]')
            return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="")

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(arena.shutil, "which", return_value="/usr/bin/docker"):
                with mock.patch.object(arena, "_docker_compose", side_effect=fake_compose) as docker_compose:
                    summary = arena.run_recursive_chaos_arena_session(
                        targets=[target],
                        output_dir=tmp,
                        max_cycles=1,
                        execute=True,
                    )

        self.assertEqual(summary["status"], "pass")
        self.assertEqual(summary["cycles_total"], 1)
        commands = [" ".join(call.args[2:]) for call in docker_compose.call_args_list]
        self.assertIn("up -d --wait", commands)
        self.assertIn("stop target", commands)
        self.assertIn("start target", commands)
        self.assertIn("down --volumes --remove-orphans", commands)

    def test_profile_selection_uses_existing_compose_portfolio(self) -> None:
        profile = get_recursive_chaos_arena_profile("kubernetes_service_platform")
        observed = {
            arena.select_arena_experiment(profile, arena.random.Random(seed), safety_class="staging_owned").name
            for seed in range(20)
        }
        portfolio_names = {experiment.name for experiment in DEFAULT_PORTFOLIO}

        self.assertTrue(observed)
        self.assertTrue(observed.issubset(portfolio_names))
        self.assertTrue(observed.intersection(set(arena.PROFILE_EXPERIMENTS["kubernetes_service_platform"])))

    def test_cli_plan_only_writes_summary_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/recursive_chaos_arena_session.py",
                    "--profile-id",
                    "kubernetes_service_platform",
                    "--max-cycles",
                    "1",
                    "--output-dir",
                    tmp,
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "pass")
            self.assertEqual(payload["cycles_total"], 1)
            self.assertTrue((Path(tmp) / payload["cycle_packet_refs"][0] / "evidence-bundle.json").exists())


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
