from __future__ import annotations

import logging
import os
import signal
import threading

from control_plane_server import build_server


def main() -> None:
    if os.getenv("MESH_ACCESS_LOG", "").lower() in ("1", "true", "yes"):
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    server = build_server()
    server.coordinator.ensure_sidecar()
    shutdown_started = threading.Event()

    def _shutdown(signum: int, frame: object) -> None:
        logging.getLogger("mesh.control_plane").info("Received signal %s, shutting down", signum)
        if shutdown_started.is_set():
            return
        shutdown_started.set()
        threading.Thread(target=server.shutdown, name="mesh-control-plane-shutdown", daemon=True).start()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        server.serve_forever()
    finally:
        server.coordinator.sidecar.stop()
        server.server_close()


if __name__ == "__main__":
    main()
