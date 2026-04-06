from __future__ import annotations

import json
import sys

from shared.mesh_runtime import EventEnvelope

from .service import TriggerService


def main() -> None:
    envelope = EventEnvelope(**json.load(sys.stdin))
    trigger = TriggerService().detect(envelope)
    json.dump(trigger.to_dict() if trigger else None, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
