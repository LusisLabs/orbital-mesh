from __future__ import annotations

import json
import sys

from shared.mesh_runtime import RemediationPlan

from .service import EvaluationService


def main() -> None:
    plan = RemediationPlan.from_dict(json.load(sys.stdin))
    evaluation = EvaluationService().evaluate(plan)
    json.dump(evaluation.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
