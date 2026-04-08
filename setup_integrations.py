from __future__ import annotations

import argparse
import json

from shared.mesh_runtime import RuntimeConfig, bootstrap_integrations


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap Promptfoo, Goose, and GitNexus sidecar configuration.")
    parser.add_argument(
        "--install-missing",
        action="store_true",
        help="Attempt supported installs for missing dependencies before writing config.",
    )
    args = parser.parse_args()

    result = bootstrap_integrations(RuntimeConfig.from_env(), install_missing=args.install_missing)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
