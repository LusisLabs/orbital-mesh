from __future__ import annotations

import unittest

from shared.mesh_runtime.temperature_policy import TemperatureInputs, fixed_temperature, generator_temperature


class TemperaturePolicyTests(unittest.TestCase):
    def test_generator_temperature_clamps_low_for_high_risk_contract_tasks(self) -> None:
        result = generator_temperature(
            TemperatureInputs(
                novelty=0.0,
                ambiguity=0.0,
                search_need=0.0,
                risk=1.0,
                contract_strictness=1.0,
                prior_failure_similarity=1.0,
            )
        )

        self.assertEqual(result["temperature"], 0.05)
        self.assertEqual(result["acceptance"], "deterministic_verifier_required")

    def test_generator_temperature_rises_for_low_risk_exploration(self) -> None:
        result = generator_temperature(
            {
                "novelty": 1.0,
                "ambiguity": 1.0,
                "search_need": 1.0,
                "risk": 0.0,
                "contract_strictness": 0.0,
                "prior_failure_similarity": 0.0,
            }
        )

        self.assertEqual(result["temperature"], 0.70)

    def test_verifier_temperature_is_zero(self) -> None:
        self.assertEqual(fixed_temperature("verifier")["temperature"], 0.0)
        self.assertEqual(fixed_temperature("judge")["temperature"], 0.0)
        self.assertEqual(fixed_temperature("scorer")["temperature"], 0.0)


if __name__ == "__main__":
    unittest.main()
