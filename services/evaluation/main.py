from __future__ import annotations

import json
import sys

from shared.mesh_runtime import Decision, Trigger

from .service import EvaluationService


def main() -> None:
    payload = json.load(sys.stdin)
    trigger = Trigger.from_dict(payload["trigger"])
    decision = Decision.from_dict(payload["decision"])
    evaluation = EvaluationService().evaluate(trigger, decision)
    json.dump(evaluation.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
