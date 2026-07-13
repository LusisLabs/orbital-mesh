"""Credential-free fixed-upstream loopback ingress for the closed repo-patch beta."""

from __future__ import annotations

import http.client
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


STATE_SLICE = "mesh.repo_patch_beta_loopback_ingress.v1"
MAX_REQUEST_BODY_BYTES = 1024 * 1024
FORWARDED_REQUEST_HEADERS = frozenset(
    {"accept", "authorization", "content-type", "if-none-match", "last-event-id"}
)
FORWARDED_RESPONSE_HEADERS = frozenset(
    {
        "cache-control",
        "content-length",
        "content-type",
        "etag",
        "retry-after",
        "x-content-type-options",
        "x-frame-options",
        "x-request-id",
    }
)


class BetaLoopbackIngressServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def build_server(
    *,
    listen_host: str,
    listen_port: int,
    upstream_host: str,
    upstream_port: int,
) -> BetaLoopbackIngressServer:
    if upstream_host != "mesh" or upstream_port != 8787:
        raise ValueError("beta loopback ingress upstream is fixed to mesh:8787")
    if not 0 <= listen_port <= 65535:
        raise ValueError("beta loopback ingress listen port is invalid")
    handler = _handler_type(upstream_host=upstream_host, upstream_port=upstream_port)
    return BetaLoopbackIngressServer((listen_host, listen_port), handler)


def _handler_type(*, upstream_host: str, upstream_port: int) -> type[BaseHTTPRequestHandler]:
    class BetaLoopbackIngressHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._proxy()

        def do_HEAD(self) -> None:
            self._proxy()

        def do_POST(self) -> None:
            self._proxy()

        def do_PUT(self) -> None:
            self._proxy()

        def do_PATCH(self) -> None:
            self._proxy()

        def do_DELETE(self) -> None:
            self._proxy()

        def do_OPTIONS(self) -> None:
            self._proxy()

        def _proxy(self) -> None:
            if not self.path.startswith("/") or self.path.startswith("//"):
                self._json_error(400, "absolute request targets are not supported")
                return
            if self.headers.get("Transfer-Encoding"):
                self._json_error(400, "chunked request bodies are not supported")
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._json_error(400, "invalid content length")
                return
            if content_length < 0 or content_length > MAX_REQUEST_BODY_BYTES:
                self._json_error(413, "request body exceeds beta ingress limit")
                return
            body = self.rfile.read(content_length) if content_length else None
            request_headers = {
                name: value
                for name, value in self.headers.items()
                if name.lower() in FORWARDED_REQUEST_HEADERS
            }
            connection = http.client.HTTPConnection(upstream_host, upstream_port, timeout=300)
            response_started = False
            try:
                connection.request(self.command, self.path, body=body, headers=request_headers)
                response = connection.getresponse()
                self.send_response(response.status, response.reason)
                response_started = True
                has_content_length = False
                for name, value in response.getheaders():
                    if name.lower() in FORWARDED_RESPONSE_HEADERS:
                        self.send_header(name, value)
                        has_content_length = has_content_length or name.lower() == "content-length"
                if not has_content_length:
                    self.send_header("Connection", "close")
                    self.close_connection = True
                self.end_headers()
                if self.command != "HEAD":
                    while chunk := response.read(64 * 1024):
                        self.wfile.write(chunk)
                    self.wfile.flush()
            except (OSError, TimeoutError, http.client.HTTPException):
                if response_started:
                    self.close_connection = True
                else:
                    self._json_error(502, "beta ingress upstream unavailable")
            finally:
                connection.close()

        def _json_error(self, status: int, message: str) -> None:
            payload = json.dumps(
                {"state_slice": STATE_SLICE, "status": "rejected", "message": message},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return BetaLoopbackIngressHandler


def main() -> int:
    with build_server(
        listen_host=os.environ.get("MESH_BETA_INGRESS_HOST", "0.0.0.0"),
        listen_port=int(os.environ.get("MESH_BETA_INGRESS_PORT", "8787")),
        upstream_host=os.environ.get("MESH_BETA_INGRESS_UPSTREAM_HOST", "mesh"),
        upstream_port=int(os.environ.get("MESH_BETA_INGRESS_UPSTREAM_PORT", "8787")),
    ) as server:
        server.serve_forever(poll_interval=0.2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
