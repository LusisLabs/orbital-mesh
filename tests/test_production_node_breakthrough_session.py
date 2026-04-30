from __future__ import annotations

import unittest
from pathlib import Path

from scripts import production_node_breakthrough_session as node_session


class ProductionNodeBreakthroughSessionTests(unittest.TestCase):
    def test_default_probes_cover_non_kubernetes_domains(self) -> None:
        probes = node_session.default_probes()
        tags = {tag for probe in probes for tag in probe.tags}

        self.assertIn("reth", tags)
        self.assertIn("systemd", tags)
        self.assertIn("otel", tags)
        self.assertIn("production_node", tags)

    def test_summary_reaches_breakthrough_when_all_axes_pass(self) -> None:
        events = []
        for probe in node_session.default_probes():
            decision_type = sorted(probe.expected_decisions)[0]
            events.append({
                "probe": probe.name,
                "capability_axes": sorted(probe.capability_axes),
                "score": {"passed": True, "decision_type": decision_type},
            })

        summary = node_session.session_summary(Path("/tmp/events.jsonl"), events)

        self.assertTrue(summary["breakthrough_probe"]["ready"])
        self.assertEqual(summary["metrics"]["capability_axis_pass_rate"], 1.0)
        self.assertEqual(summary["metrics"]["correct_decision_rate"], 1.0)

    def test_score_rejects_unexpected_decision(self) -> None:
        probe = node_session.NodeProbe(
            name="p",
            description="",
            signal_payload={},
            expected_decisions=frozenset({"escalate"}),
            capability_axes=frozenset({"axis"}),
        )

        score = node_session.score_event(
            probe,
            {"mesh_run": {"decision_type": "restart_systemd_service"}},
        )

        self.assertFalse(score["passed"])
        self.assertEqual(score["reason"], "unexpected_decision")


if __name__ == "__main__":
    unittest.main()
