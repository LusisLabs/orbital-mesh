from __future__ import annotations

import json
import sys

from shared.mesh_runtime import Diagnosis, ExecutionRecord, RemediationPlan, Trigger

from .service import FeedbackService


def main() -> None:
    payload = json.load(sys.stdin)
    trigger = Trigger.from_dict(payload["trigger"])
    diagnosis = Diagnosis.from_dict(payload["diagnosis"])
    plan = RemediationPlan.from_dict(payload["plan"])
    execution = ExecutionRecord.from_dict(payload["execution"])
    feedback = FeedbackService().record(trigger, diagnosis, plan, execution)
    json.dump(feedback.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
