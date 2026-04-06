from __future__ import annotations

import json
import sys

from shared.mesh_runtime import Decision, EvaluationResult

from .service import OrchestratorService


def main() -> None:
    payload = json.load(sys.stdin)
    decision = Decision.from_dict(payload["decision"])
    evaluation = EvaluationResult.from_dict(payload["evaluation"])
    execution = OrchestratorService().execute(decision, evaluation)
    json.dump(execution.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
