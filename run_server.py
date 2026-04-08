from __future__ import annotations

import logging
import os

from control_plane_server import serve_forever


def main() -> None:
    if os.getenv("MESH_ACCESS_LOG", "").lower() in ("1", "true", "yes"):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    serve_forever()


if __name__ == "__main__":
    main()

