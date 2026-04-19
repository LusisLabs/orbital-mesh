from __future__ import annotations

import logging
import os
import signal

from control_plane_server import build_server


def main() -> None:
    if os.getenv("MESH_ACCESS_LOG", "").lower() in ("1", "true", "yes"):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    server = build_server()
    server.coordinator.ensure_sidecar()

    def _shutdown(signum: int, frame: object) -> None:
        logging.getLogger("mesh.control_plane").info("Received signal %s, shutting down", signum)
        server.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        server.serve_forever()
    finally:
        server.coordinator.sidecar.stop()
        server.server_close()


if __name__ == "__main__":
    main()
