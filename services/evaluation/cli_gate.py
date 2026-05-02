from __future__ import annotations

import json
import sys

from shared.mesh_runtime import Decision, Trigger

from .mesh_eval import evaluate_native_mesh


def main() -> None:
    payload = json.load(sys.stdin)
    trigger = Trigger.from_dict(payload["trigger"])
    decision = Decision.from_dict(payload["decision"])
    result = evaluate_native_mesh(trigger=trigger, decision=decision)
    trajectory_score = result["trajectory_score"]
    json.dump(
        {
            "passed": trajectory_score["passed"],
            "score": trajectory_score["score"],
            "notes": trajectory_score["notes"],
            "mode": "native_mesh_eval_cli",
            "artifacts": result,
        },
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
