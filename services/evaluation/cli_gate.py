from __future__ import annotations

import json
import sys

from shared.mesh_runtime import Decision, Trigger

from .promptfoo_adapter import evaluate_decision_contract


def main() -> None:
    payload = json.load(sys.stdin)
    trigger = Trigger.from_dict(payload["trigger"])
    decision = Decision.from_dict(payload["decision"])
    result = evaluate_decision_contract(trigger, decision, mode="cli")
    json.dump(
        {
            "passed": result.passed,
            "score": result.score,
            "notes": result.notes,
            "mode": result.mode,
            "artifacts": result.artifacts,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
