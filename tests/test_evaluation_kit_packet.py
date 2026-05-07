from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.generate_evaluation_kit_packet import build_evaluation_kit_packet
from shared.mesh_runtime.evaluation_kit import verify_evaluation_kit_packet


class EvaluationKitPacketTests(unittest.TestCase):
    def test_generated_evaluation_kit_packet_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "evaluation-kit"
            packet = build_evaluation_kit_packet(output_dir)
            packet_path = output_dir / "evaluation-kit-packet.json"
            packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = verify_evaluation_kit_packet(packet_path)

        self.assertEqual(packet["status"], "complete")
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["checks"]["sample_export_retrieval_passed"])
        self.assertTrue(result["checks"]["benchmark_harness_present"])
        self.assertEqual(result["benchmark_scenario_ids"], ["feature_flag_latency_disable", "kubernetes_crashloop_patch"])

    def test_missing_archive_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "evaluation-kit"
            packet = build_evaluation_kit_packet(output_dir)
            archive_path = Path(packet["sample_export"]["archive_path"])
            archive_path.unlink()
            packet_path = output_dir / "evaluation-kit-packet.json"
            packet_path.write_text(json.dumps(packet, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = verify_evaluation_kit_packet(packet_path)

        self.assertEqual(result["status"], "fail")
        self.assertFalse(result["checks"]["sample_export_retrieval_passed"])
        self.assertFalse(result["checks"]["sample_archive_sha_matches"])


if __name__ == "__main__":
    unittest.main()
