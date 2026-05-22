#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]


class ManagedProcess:
    def __init__(self, name: str, cmd: list[str], env: dict[str, str]) -> None:
        self.name = name
        self.cmd = cmd
        self.lines: deque[str] = deque(maxlen=240)
        self.process = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_output, name=f"{name}-output", daemon=True)
        self._reader.start()

    def _read_output(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.lines.append(line.rstrip("\n"))

    def output(self) -> str:
        return "\n".join(self.lines)

    def stop(self) -> None:
        if self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=10)


def main() -> int:
    api_port = _free_port()
    web_port = _free_port()
    api_url = f"http://127.0.0.1:{api_port}"
    web_url = f"http://127.0.0.1:{web_port}"
    next_dist_dir = f".next-e2e-{web_port}"
    next_generated_files = [
        REPO_ROOT / "meshapp" / "frontend" / "next-env.d.ts",
        REPO_ROOT / "meshapp" / "frontend" / "tsconfig.json",
    ]
    next_generated_snapshots = {
        path: path.read_text(encoding="utf-8") for path in next_generated_files if path.exists()
    }

    with tempfile.TemporaryDirectory(prefix="mesh-product-e2e-") as tmp:
        tmp_path = Path(tmp)
        env = os.environ.copy()
        env.update(
            {
                "MESH_AUTH_MODE": "app_session",
                "MESH_CAPTCHA_DEV_BYPASS": "1",
                "MESH_STATE_DIRECTORY": str(tmp_path / "state"),
                "MESH_VAULT_PATH": str(tmp_path / "vault"),
                "MESH_INTEGRATIONS_CONFIG_PATH": str(tmp_path / "integrations.json"),
                "MESH_OPERATOR_IDENTITY_PATH": str(tmp_path / "operator-identity.json"),
                "MESH_SERVER_HOST": "127.0.0.1",
                "MESH_SERVER_PORT": str(api_port),
                "MESH_PROMPTFOO_COMMAND": "/missing/promptfoo",
                "MESH_HERMES_COMMAND": "/missing/hermes",
                "MESH_GOOSE_COMMAND": "/missing/goose",
                "NEXT_PUBLIC_MESH_API_URL": api_url,
                "MESH_PRODUCT_E2E_BASE_URL": web_url,
                "MESH_PRODUCT_E2E_API_URL": api_url,
                "MESH_AUTH_PRODUCT_REDIRECT_URL": web_url,
                "MESH_AUTH_ALLOWED_ORIGINS": web_url,
                "MESH_NEXT_DIST_DIR": next_dist_dir,
            }
        )

        api = ManagedProcess("api", [sys.executable, "run_server.py"], env)
        web = ManagedProcess(
            "next",
            ["pnpm", "--dir", "meshapp/frontend", "exec", "next", "dev", "--hostname", "127.0.0.1", "--port", str(web_port)],
            env,
        )
        try:
            _wait_for_http(f"{api_url}/api/auth/config", api, timeout=35)
            _wait_for_http(web_url, web, timeout=45)
            result = subprocess.run(
                ["pnpm", "--dir", "meshapp/frontend", "run", "test:e2e"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                check=False,
            )
            return result.returncode
        except Exception as exc:
            print(f"operator product e2e failed: {exc}", file=sys.stderr)
            print(_format_process_output(api), file=sys.stderr)
            print(_format_process_output(web), file=sys.stderr)
            return 1
        finally:
            web.stop()
            api.stop()
            shutil.rmtree(REPO_ROOT / "meshapp" / "frontend" / next_dist_dir, ignore_errors=True)
            shutil.rmtree(REPO_ROOT / "meshapp" / "frontend" / ".next", ignore_errors=True)
            shutil.rmtree(REPO_ROOT / "meshapp" / "frontend" / ".next-ui-audit", ignore_errors=True)
            for path, contents in next_generated_snapshots.items():
                path.write_text(contents, encoding="utf-8")


def _wait_for_http(url: str, process: ManagedProcess, *, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if process.process.poll() is not None:
            raise RuntimeError(f"{process.name} exited early with {process.process.returncode}\n{process.output()}")
        try:
            with urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except URLError as exc:
            last_error = str(exc)
        except TimeoutError as exc:
            last_error = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"{process.name} did not become ready at {url}: {last_error}")


def _format_process_output(process: ManagedProcess) -> str:
    output = process.output()
    return f"--- {process.name} recent output ---\n{output}" if output else f"--- {process.name} produced no output ---"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
