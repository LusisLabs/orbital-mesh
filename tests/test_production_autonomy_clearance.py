from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.mesh_runtime.production_autonomy_clearance import verify_production_autonomy_clearance
from tests.test_incident_coverage import _proof as _incident_proof
from tests.test_on_call_drill import _proof as _on_call_drill_proof
from tests.test_production_target_proof import _proof as _target_proof
from tests.test_provider_action_scope import _proof as _provider_proof
from tests.test_repeatability_proof import _HEAD, _proof as _repeatability_proof
from tests.test_watch_mode_proof import _proof as _watch_proof


class ProductionAutonomyClearanceTests(unittest.TestCase):
    def test_clearance_passes_when_all_live_packets_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_bundle(Path(tmp), evidence_level="live")

            result = verify_production_autonomy_clearance(
                repeatability_proof=paths["repeatability"],
                production_target_proof=paths["production_target"],
                provider_action_scope_proof=paths["provider_actions"],
                watch_mode_proof=paths["watch_mode"],
                incident_coverage_proof=paths["incident_coverage"],
                on_call_drill_proof=paths["governance"],
                expected_head=_HEAD,
                expected_environment="pilot",
            )

            self.assertEqual(result["schema_version"], "mesh.production_autonomy_clearance.v1")
            self.assertEqual(result["status"], "pass")
            self.assertEqual(result["missing"], [])

    def test_clearance_rejects_fixture_packets_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_bundle(Path(tmp), evidence_level="fixture")

            result = verify_production_autonomy_clearance(
                repeatability_proof=paths["repeatability"],
                production_target_proof=paths["production_target"],
                provider_action_scope_proof=paths["provider_actions"],
                watch_mode_proof=paths["watch_mode"],
                incident_coverage_proof=paths["incident_coverage"],
                on_call_drill_proof=paths["governance"],
                expected_head=_HEAD,
                expected_environment="pilot",
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("production_target_passed", result["missing"])
            self.assertIn("watch_mode_passed", result["missing"])
            self.assertIn("incident_coverage_passed", result["missing"])
            self.assertIn("live_evidence_required", result["missing"])

    def test_clearance_fixture_mode_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_bundle(Path(tmp), evidence_level="fixture")

            result = verify_production_autonomy_clearance(
                repeatability_proof=paths["repeatability"],
                production_target_proof=paths["production_target"],
                provider_action_scope_proof=paths["provider_actions"],
                watch_mode_proof=paths["watch_mode"],
                incident_coverage_proof=paths["incident_coverage"],
                on_call_drill_proof=paths["governance"],
                expected_head=_HEAD,
                expected_environment="pilot",
                require_live=False,
            )

            self.assertEqual(result["status"], "pass")
            self.assertFalse(result["require_live"])

    def test_clearance_rejects_environment_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_bundle(Path(tmp), evidence_level="live")

            result = verify_production_autonomy_clearance(
                repeatability_proof=paths["repeatability"],
                production_target_proof=paths["production_target"],
                provider_action_scope_proof=paths["provider_actions"],
                watch_mode_proof=paths["watch_mode"],
                incident_coverage_proof=paths["incident_coverage"],
                on_call_drill_proof=paths["governance"],
                expected_head=_HEAD,
                expected_environment="production",
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("production_target_passed", result["missing"])
            self.assertIn("watch_mode_passed", result["missing"])
            self.assertIn("governance_drill_passed", result["missing"])
            self.assertIn("environments_match_expected", result["missing"])

    def test_clearance_rejects_packets_without_shared_run_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_bundle(Path(tmp), evidence_level="live", bind_shared_run=False)

            result = verify_production_autonomy_clearance(
                repeatability_proof=paths["repeatability"],
                production_target_proof=paths["production_target"],
                provider_action_scope_proof=paths["provider_actions"],
                watch_mode_proof=paths["watch_mode"],
                incident_coverage_proof=paths["incident_coverage"],
                on_call_drill_proof=paths["governance"],
                expected_head=_HEAD,
                expected_environment="pilot",
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("target_bound_to_watch_mode", result["missing"])
            self.assertIn("run_bound_to_repeatability", result["missing"])
            self.assertIn("run_bound_to_watch_mode", result["missing"])
            self.assertIn("run_bound_to_incident_coverage", result["missing"])
            self.assertIn("provider_action_bound_to_run_export", result["missing"])

    def test_clearance_rejects_missing_governance_break_glass_and_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_bundle(Path(tmp), evidence_level="live")
            governance = json.loads(paths["governance"].read_text(encoding="utf-8"))
            governance["provider_key_rotation"]["break_glass_recorded"] = False
            governance["provider_key_rotation"]["status"] = "fail"
            paths["governance"].write_text(json.dumps(governance), encoding="utf-8")

            result = verify_production_autonomy_clearance(
                repeatability_proof=paths["repeatability"],
                production_target_proof=paths["production_target"],
                provider_action_scope_proof=paths["provider_actions"],
                watch_mode_proof=paths["watch_mode"],
                incident_coverage_proof=paths["incident_coverage"],
                on_call_drill_proof=paths["governance"],
                expected_head=_HEAD,
                expected_environment="pilot",
            )

            self.assertEqual(result["status"], "fail")
            self.assertIn("governance_drill_passed", result["missing"])
            self.assertIn("governance_break_glass_verified", result["missing"])
            self.assertIn("governance_credential_rotation_verified", result["missing"])

    def test_cli_verifies_clearance_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = _write_bundle(Path(tmp), evidence_level="live")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/verify_production_autonomy_clearance.py",
                    "--repeatability-proof",
                    str(paths["repeatability"]),
                    "--production-target-proof",
                    str(paths["production_target"]),
                    "--provider-action-scope-proof",
                    str(paths["provider_actions"]),
                    "--watch-mode-proof",
                    str(paths["watch_mode"]),
                    "--incident-coverage-proof",
                    str(paths["incident_coverage"]),
                    "--on-call-drill-proof",
                    str(paths["governance"]),
                    "--expected-head",
                    _HEAD,
                    "--expected-environment",
                    "pilot",
                    "--json",
                ],
                check=True,
                cwd=Path(__file__).resolve().parents[1],
                text=True,
                capture_output=True,
            )

            payload = json.loads(completed.stdout)
            self.assertEqual(payload["status"], "pass")


def _write_bundle(root: Path, *, evidence_level: str, bind_shared_run: bool = True) -> dict[str, Path]:
    repeatability = _repeatability_proof()
    production_target = _target_proof(evidence_level=evidence_level)
    if evidence_level == "fixture":
        production_target["live_artifact_refs"] = []
    provider_actions = _provider_proof()
    provider_actions["evidence_level"] = evidence_level
    watch_mode = _watch_proof(evidence_level=evidence_level)
    watch_mode["environment"] = "pilot"
    incident_coverage = _incident_proof(evidence_level=evidence_level)
    governance = _on_call_drill_proof()
    if bind_shared_run:
        _bind_shared_run(
            repeatability=repeatability,
            production_target=production_target,
            provider_actions=provider_actions,
            watch_mode=watch_mode,
            incident_coverage=incident_coverage,
        )

    payloads = {
        "repeatability": repeatability,
        "production_target": production_target,
        "provider_actions": provider_actions,
        "watch_mode": watch_mode,
        "incident_coverage": incident_coverage,
        "governance": governance,
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = root / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    return paths


def _bind_shared_run(
    *,
    repeatability: dict,
    production_target: dict,
    provider_actions: dict,
    watch_mode: dict,
    incident_coverage: dict,
) -> None:
    run_id = "run_prod_target_fixture"
    target_ref = "kubernetes://pilot/default/search"
    production_target["target_ref"] = target_ref
    production_target["run"]["run_id"] = run_id
    production_target["run"]["run_export_ref"] = f"artifact://runs/{run_id}/run-export-package.json"
    repeatability["runs"][0]["run_id"] = run_id
    repeatability["runs"][0]["artifact_refs"] = [
        f"artifact://runs/{run_id}/run-export-package.json",
        f"artifact://runs/{run_id}/timeline-proof.json",
    ]
    provider_actions["action_scopes"][0]["run_export_ref"] = f"artifact://runs/{run_id}/run-export-package.json"
    watch_mode["ticks"][0]["target_ref"] = target_ref
    watch_mode["ticks"][0]["run_id"] = run_id
    watch_mode["runs"][0]["target_ref"] = target_ref
    watch_mode["runs"][0]["run_id"] = run_id
    incident_coverage["coverage"][0]["run_ids"] = [run_id]


if __name__ == "__main__":
    unittest.main()
