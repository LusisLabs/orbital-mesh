from __future__ import annotations

import json
import sys

from shared.mesh_runtime import Trigger

from .service import DiagnosisService


def main() -> None:
    trigger = Trigger.from_dict(json.load(sys.stdin))
    diagnosis = DiagnosisService().diagnose(trigger)
    json.dump(diagnosis.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
