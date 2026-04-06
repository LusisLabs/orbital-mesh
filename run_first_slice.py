from __future__ import annotations

import json
import sys

from services.pipeline import FirstSlicePipeline


def main() -> None:
    raw_signal = json.load(sys.stdin)
    result = FirstSlicePipeline().run(raw_signal)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
