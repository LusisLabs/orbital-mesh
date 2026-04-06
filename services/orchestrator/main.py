from __future__ import annotations

import json
import sys

from shared.mesh_runtime import EvaluationResult, RemediationPlan

from .service import OrchestratorService


def main() -> None:
    payload = json.load(sys.stdin)
    plan = RemediationPlan.from_dict(payload["plan"])
    evaluation = EvaluationResult.from_dict(payload["evaluation"])
    execution = OrchestratorService().execute(plan, evaluation)
    json.dump(execution.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
