from __future__ import annotations

import unittest

from mesh_brain import (
    get_research_influence,
    list_backends,
    list_research_influences,
    research_adoption_plan,
    research_capability_report,
)


class MeshBrainResearchRegistryTests(unittest.TestCase):
    def test_registry_captures_required_research_influences(self) -> None:
        names = {influence.name for influence in list_research_influences()}

        self.assertIn("NVIDIA/NeMo-RL", names)
        self.assertIn("stanford-futuredata/megablocks", names)
        self.assertIn("google-research/google-research", names)
        self.assertIn("google-deepmind/open_spiel", names)
        self.assertIn("Nydhal/microgpt.apl", names)
        self.assertIn("AlexCheema/talos-vs-macbook", names)

    def test_research_registry_is_not_backend_catalog(self) -> None:
        backend_names = {backend.name for backend in list_backends()}
        research_names = {influence.name for influence in list_research_influences()}

        self.assertIn("sgl-project/sglang", backend_names)
        self.assertNotIn("sgl-project/sglang", research_names)
        self.assertIn("NVIDIA/NeMo-RL", research_names)
        self.assertNotIn("NVIDIA/NeMo-RL", backend_names)

    def test_capability_report_maps_research_to_mesh_brain_planes(self) -> None:
        report = research_capability_report(
            plane="training_jobs",
            required_capabilities=["distributed rollout", "block-sparse MoE", "replay buffers"],
        )

        self.assertEqual(report["missing_capabilities"], [])
        self.assertIn("NVIDIA/NeMo-RL", report["coverage"]["distributed rollout"])
        self.assertIn("stanford-futuredata/megablocks", report["coverage"]["block-sparse MoE"])
        self.assertIn("google-deepmind/acme", report["coverage"]["replay buffers"])

    def test_adoption_plan_promotes_only_bounded_micro_kernel_sources_to_mvp(self) -> None:
        nemo = get_research_influence("NVIDIA/NeMo-RL")
        plan = research_adoption_plan(plane="agent_runtime")
        serving_plan = research_adoption_plan(plane="serving")

        self.assertEqual(nemo.mvp_relevance, "defer")
        self.assertIn("reward hacking", nemo.risks)
        self.assertEqual(plan[0]["mvp_relevance"], "reference_only")
        self.assertEqual(serving_plan[0]["name"], "AlexCheema/talos-vs-macbook")
        self.assertEqual(serving_plan[1]["name"], "Nydhal/microgpt.apl")
        self.assertTrue(any(item["name"] == "NVIDIA/NeMo-RL" and item["mvp_relevance"] == "defer" for item in plan))


if __name__ == "__main__":
    unittest.main()
