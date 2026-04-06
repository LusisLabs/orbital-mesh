from __future__ import annotations

import json
import sys

from .service import IngestService


def main() -> None:
    raw_signal = json.load(sys.stdin)
    envelope = IngestService().normalize_signal(raw_signal)
    json.dump(envelope.to_dict(), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
