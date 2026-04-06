from __future__ import annotations

import json
import sys

from shared.mesh_runtime import Diagnosis, Trigger

from .service import PlannerService


def main() -> None:
    payload = json.load(sys.stdin)
    trigger = Trigger.from_dict(payload["trigger"])
    diagnosis = Diagnosis.from_dict(payload["diagnosis"])
    plan = PlannerService().plan(trigger, diagnosis)
    json.dump(plan.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
