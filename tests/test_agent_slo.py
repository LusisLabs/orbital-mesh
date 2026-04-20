"""Tests for AgentSLOCalculator — agent self-observability metrics."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from shared.mesh_runtime.agent_slo import (
    AgentSLOCalculator,
    report_to_prometheus,
)


def _mock_session(
    *,
    run_id: str,
    created_at: datetime,
    updated_at: datetime,
    status: str,
    stage: str = "completed",
    service: str = "search",
    decision_type: str = "restart_deployment",
    outcome: str = "successful",
    autonomy_tier: str = "autonomous",
):
    return {
        "run_id": run_id,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
        "stage": stage,
        "status": status,
        "artifacts": {
            "trigger": {
                "service": service,
                "triggered_at": (created_at + timedelta(seconds=5)).isoformat(),
            },
            "decision": {
                "decision_type": decision_type,
                "autonomy_tier": autonomy_tier,
            },
            "feedback": {"outcome": outcome},
        },
    }


class AgentSLOCalculatorTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
        self.calculator = AgentSLOCalculator(now_fn=lambda: self.now)

    def test_empty_run_list(self):
        report = self.calculator.compute([])
        self.assertEqual(report.active_runs, 0)
        self.assertEqual(report.by_window["24h"].total_runs, 0)
        self.assertEqual(report.runs_per_hour_24h, 0.0)

    def test_counts_active_and_completed(self):
        runs = [
            _mock_session(
                run_id="r1",
                created_at=self.now - timedelta(minutes=5),
                updated_at=self.now - timedelta(minutes=4),
                status="running",
                stage="decision_ready",
            ),
            _mock_session(
                run_id="r2",
                created_at=self.now - timedelta(hours=1),
                updated_at=self.now - timedelta(hours=1),
                status="completed",
            ),
        ]
        report = self.calculator.compute(runs)
        self.assertEqual(report.active_runs, 1)
        self.assertEqual(report.active_runs_by_stage["decision_ready"], 1)
        self.assertEqual(report.by_window["24h"].completed_runs, 1)

    def test_mttr_percentiles(self):
        runs = []
        for seconds, i in [(10, 1), (20, 2), (30, 3), (60, 4), (120, 5)]:
            created = self.now - timedelta(hours=1)
            runs.append(_mock_session(
                run_id=f"r{i}",
                created_at=created,
                updated_at=created + timedelta(seconds=seconds),
                status="completed",
                outcome="successful",
            ))
        report = self.calculator.compute(runs)
        metrics = report.by_window["24h"]
        self.assertEqual(metrics.successful_runs, 5)
        # p50 of [10,20,30,60,120] = 30
        self.assertEqual(metrics.mttr_p50_seconds, 30.0)
        # p95 ~ index round(4*0.95)=4 -> 120
        self.assertEqual(metrics.mttr_p95_seconds, 120.0)

    def test_success_and_escalation_counts(self):
        now = self.now
        runs = [
            _mock_session(
                run_id="r1", created_at=now - timedelta(hours=1),
                updated_at=now - timedelta(hours=1), status="completed",
                decision_type="restart_deployment", outcome="successful",
                autonomy_tier="autonomous",
            ),
            _mock_session(
                run_id="r2", created_at=now - timedelta(hours=2),
                updated_at=now - timedelta(hours=2), status="completed",
                decision_type="escalate", outcome="no_action_needed",
                autonomy_tier="escalated",
            ),
            _mock_session(
                run_id="r3", created_at=now - timedelta(hours=3),
                updated_at=now - timedelta(hours=3), status="failed",
                decision_type="restart_deployment", outcome="rolled_back",
            ),
        ]
        report = self.calculator.compute(runs)
        metrics = report.by_window["24h"]
        self.assertEqual(metrics.successful_runs, 1)
        self.assertEqual(metrics.escalated_runs, 1)
        self.assertEqual(metrics.false_positive_runs, 1)
        self.assertEqual(metrics.rolled_back_runs, 1)
        self.assertEqual(metrics.auto_execution_runs, 1)

    def test_runs_outside_window_excluded(self):
        old_ts = self.now - timedelta(days=60)
        runs = [_mock_session(
            run_id="old", created_at=old_ts, updated_at=old_ts, status="completed",
        )]
        report = self.calculator.compute(runs)
        self.assertEqual(report.by_window["24h"].total_runs, 0)
        self.assertEqual(report.by_window["30d"].total_runs, 0)

    def test_runs_per_hour(self):
        runs = []
        for i in range(12):
            ts = self.now - timedelta(hours=i + 0.5)
            runs.append(_mock_session(
                run_id=f"r{i}",
                created_at=ts,
                updated_at=ts,
                status="completed",
            ))
        report = self.calculator.compute(runs)
        self.assertAlmostEqual(report.runs_per_hour_24h, 12.0 / 24.0, places=3)

    def test_per_service_breakdown(self):
        now = self.now
        runs = [
            _mock_session(run_id="r1", created_at=now - timedelta(hours=1),
                          updated_at=now - timedelta(hours=1), status="completed",
                          service="search", outcome="successful"),
            _mock_session(run_id="r2", created_at=now - timedelta(hours=2),
                          updated_at=now - timedelta(hours=2), status="completed",
                          service="search", outcome="escalated", decision_type="escalate"),
            _mock_session(run_id="r3", created_at=now - timedelta(hours=3),
                          updated_at=now - timedelta(hours=3), status="completed",
                          service="auth", outcome="successful"),
        ]
        report = self.calculator.compute(runs)
        self.assertIn("search", report.per_service)
        self.assertEqual(report.per_service["search"]["total_runs"], 2)
        self.assertEqual(report.per_service["search"]["success_rate"], 0.5)
        self.assertEqual(report.per_service["auth"]["total_runs"], 1)

    def test_per_decision_type_breakdown(self):
        now = self.now
        runs = [
            _mock_session(run_id="r1", created_at=now - timedelta(hours=1),
                          updated_at=now - timedelta(hours=1), status="completed",
                          decision_type="restart_deployment", outcome="successful"),
            _mock_session(run_id="r2", created_at=now - timedelta(hours=2),
                          updated_at=now - timedelta(hours=2), status="completed",
                          decision_type="rollback_deployment", outcome="successful"),
            _mock_session(run_id="r3", created_at=now - timedelta(hours=3),
                          updated_at=now - timedelta(hours=3), status="failed",
                          decision_type="rollback_deployment", outcome="escalated"),
        ]
        report = self.calculator.compute(runs)
        self.assertEqual(report.per_decision_type["restart_deployment"]["success_rate"], 1.0)
        self.assertEqual(report.per_decision_type["rollback_deployment"]["success_rate"], 0.5)


class PrometheusExpositionTests(unittest.TestCase):
    def test_format_contains_expected_metrics(self):
        now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
        calculator = AgentSLOCalculator(now_fn=lambda: now)
        runs = [
            _mock_session(run_id="r1",
                          created_at=now - timedelta(hours=1),
                          updated_at=now - timedelta(hours=1),
                          status="completed", outcome="successful"),
            _mock_session(run_id="r2",
                          created_at=now - timedelta(hours=2),
                          updated_at=now - timedelta(hours=2),
                          status="completed", outcome="rolled_back"),
        ]
        report = calculator.compute(runs)
        text = report_to_prometheus(report)
        self.assertIn("# HELP mesh_agent_active_runs", text)
        self.assertIn("# TYPE mesh_agent_success_rate", text)
        self.assertIn('mesh_agent_success_rate{window="24h"}', text)
        self.assertIn("mesh_agent_runs_per_hour_24h", text)
        self.assertIn("mesh_agent_service_total_runs", text)

    def test_no_samples_when_no_data(self):
        now = datetime(2026, 4, 20, 12, 0, 0, tzinfo=timezone.utc)
        calculator = AgentSLOCalculator(now_fn=lambda: now)
        report = calculator.compute([])
        text = report_to_prometheus(report)
        # Metric declarations still present, but no sample lines for windows
        self.assertIn("# HELP mesh_agent_active_runs", text)
        self.assertIn("mesh_agent_active_runs 0", text)


if __name__ == "__main__":
    unittest.main()
