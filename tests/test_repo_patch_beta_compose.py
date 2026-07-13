from __future__ import annotations

import json
import http.client
import os
import subprocess
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from services.orchestrator.beta_loopback_ingress import (
    MAX_REQUEST_BODY_BYTES,
    BetaLoopbackIngressServer,
    _handler_type,
)


COMPOSE_PATH = Path("docker-compose.repo-patch-beta.yml")


def _mapping_block(source: str, key: str, *, indent: int = 2) -> str:
    lines = source.splitlines()
    marker = f"{' ' * indent}{key}:"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise AssertionError(f"missing compose mapping {key!r}") from exc
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if not line.strip():
            continue
        current_indent = len(line) - len(line.lstrip(" "))
        if current_indent <= indent:
            end = index
            break
    return "\n".join(lines[start:end])


class RepoPatchBetaComposeContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.compose = COMPOSE_PATH.read_text(encoding="utf-8")
        services = cls.compose.split("services:\n", 1)[1].split("\nvolumes:\n", 1)[0]
        cls.mesh = _mapping_block(services, "mesh")
        cls.authority = _mapping_block(services, "repo_patch_authority")
        cls.verifier = _mapping_block(services, "repo_patch_verifier")
        cls.volumes = cls.compose.split("\nvolumes:\n", 1)[1]
        environment = {
            **os.environ,
            "MESH_REPO_PATCH_AUTHORITY_PRIVATE_KEY_HOST_PATH": "/tmp/authority-private.pem",
            "MESH_REPO_PATCH_ORCHESTRATOR_CLIENT_PRIVATE_KEY_HOST_PATH": "/tmp/client-private.pem",
            "MESH_REPO_PATCH_CLIENT_GID": "2000",
            "MESH_REPO_PATCH_ORCHESTRATOR_CLIENT_PUBLIC_KEY_HOST_PATH": "/tmp/client-public.pem",
            "MESH_REPO_PATCH_CLIENT_UID": "2000",
            "MESH_REPO_PATCH_AUTHORITY_UID": "3000",
            "MESH_REPO_PATCH_AUTHORITY_PERMIT_KEY_HOST_PATH": "/tmp/permit.key",
            "MESH_REPO_PATCH_AUTHORITY_PUBLIC_KEY_HOST_PATH": "/tmp/authority-public.pem",
            "MESH_HSAI_LINUX_CLI_HOST_PATH": "/tmp/hsai-mesh-admission",
            "MESH_REPO_PATCH_AUTHORITY_GID": "4000",
            "MESH_REPO_PATCH_AUTHORITY_STATE_HOST_PATH": "/tmp/authority-state",
            "MESH_REPO_PATCH_MESH_STATE_HOST_PATH": "/tmp/mesh-state",
            "MESH_REPO_PATCH_AUTHORITY_CLIENT_KEYS_REGISTRY_HOST_PATH": "/tmp/clients.json",
            "MESH_REPO_PATCH_BETA_POLICY_ID": "beta-policy-v1",
            "MESH_HSAI_LINUX_CLI_SHA256": "a" * 64,
            "MESH_REPO_PATCH_TARGET_HOST_PATH": "/tmp/disposable-target",
            "MESH_REPO_PATCH_VERIFIER_IMAGE_DIGEST": "sha256:" + ("b" * 64),
            "MESH_REPO_PATCH_VERIFIER_SANDBOX_PROFILE_DIGEST": "sha256:" + ("c" * 64),
        }
        rendered = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "docker-compose.yml",
                "-f",
                str(COMPOSE_PATH),
                "config",
                "--format",
                "json",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        cls.rendered = json.loads(rendered.stdout)
        cls.rendered_mesh = cls.rendered["services"]["mesh"]
        cls.rendered_authority = cls.rendered["services"]["repo_patch_authority"]
        cls.rendered_verifier = cls.rendered["services"]["repo_patch_verifier"]
        cls.rendered_ingress = cls.rendered["services"]["repo_patch_beta_ingress"]

    def test_production_image_retains_git_for_authority_worktrees(self) -> None:
        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

        self.assertIn("apt-get install -y --no-install-recommends ca-certificates curl git", dockerfile)
        self.assertNotIn("apt-get purge -y --auto-remove curl git git-man", dockerfile)
        self.assertIn("apt-get purge -y --auto-remove curl", dockerfile)

    def test_authority_service_is_an_isolated_explicit_identity(self) -> None:
        for marker in (
            'user: "${MESH_REPO_PATCH_AUTHORITY_UID:?set distinct authority UID}:${MESH_REPO_PATCH_AUTHORITY_GID:?set distinct authority GID}"',
            "network_mode: none",
            'command: ["python3", "-m", "services.actuators.repo_patch_authority_service"]',
            "read_only: true",
            "- ALL",
            "- no-new-privileges:true",
            "restart: unless-stopped",
        ):
            self.assertIn(marker, self.authority)
        self.assertNotIn("ports:", self.authority)
        self.assertNotIn("networks:", self.authority)

    def test_verifier_sidecar_has_no_authority_assets_or_network(self) -> None:
        self.assertEqual(self.rendered_verifier["user"], "0:0")
        self.assertEqual(self.rendered_verifier["network_mode"], "none")
        self.assertTrue(self.rendered_verifier["read_only"])
        self.assertEqual(self.rendered_verifier["cap_drop"], ["ALL"])
        self.assertEqual(
            set(self.rendered_verifier["cap_add"]),
            {"CHOWN", "DAC_OVERRIDE", "FOWNER", "KILL", "SETGID", "SETUID"},
        )
        self.assertIn("no-new-privileges:true", self.rendered_verifier["security_opt"])
        self.assertEqual(self.rendered_verifier["pids_limit"], 64)
        self.assertEqual(self.rendered_verifier["mem_limit"], "268435456")
        mounts = {mount["target"]: mount for mount in self.rendered_verifier["volumes"]}
        self.assertEqual(set(mounts), {
            "/run/mesh-verifier",
            "/var/lib/mesh-verifier/input",
            "/var/lib/mesh-verifier/ledger",
        })
        self.assertTrue(mounts["/var/lib/mesh-verifier/input"]["read_only"])
        verifier_text = json.dumps(self.rendered_verifier, sort_keys=True)
        for forbidden in (
            "/workspace/target",
            "/run/mesh-authority",
            "/run/secrets",
            "/var/lib/mesh-authority",
            "/opt/hsai",
            "/var/run/docker.sock",
            "MESH_DATABASE_URL",
        ):
            self.assertNotIn(forbidden, verifier_text)

    def test_authority_delegates_verification_through_separate_handoff(self) -> None:
        authority_mounts = {mount["target"]: mount for mount in self.rendered_authority["volumes"]}
        self.assertEqual(
            authority_mounts["/var/lib/mesh-verifier/input"]["source"],
            "mesh_repo_patch_verifier_handoff",
        )
        self.assertFalse(authority_mounts["/var/lib/mesh-verifier/input"].get("read_only", False))
        self.assertTrue(authority_mounts["/run/mesh-verifier"]["read_only"])
        self.assertEqual(
            self.rendered_authority["environment"]["MESH_REPO_PATCH_VERIFIER_UID"],
            "0",
        )
        self.assertEqual(
            self.rendered_authority["depends_on"]["repo_patch_verifier"]["condition"],
            "service_healthy",
        )

    def test_merged_mesh_identity_and_hardening_are_explicit(self) -> None:
        self.assertEqual(self.rendered_mesh["user"], "2000:2000")
        self.assertEqual(self.rendered_mesh["group_add"], ["4000"])
        self.assertTrue(self.rendered_mesh["read_only"])
        self.assertEqual(self.rendered_mesh["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", self.rendered_mesh["security_opt"])
        self.assertEqual(self.rendered_mesh["deploy"]["resources"]["limits"]["pids"], 128)
        self.assertEqual(self.rendered_authority["pids_limit"], 64)
        self.assertEqual(self.rendered_authority["mem_limit"], "1073741824")

    def test_merged_beta_api_is_loopback_only(self) -> None:
        self.assertNotIn("ports", self.rendered_mesh)
        self.assertEqual(len(self.rendered_ingress["ports"]), 1)
        self.assertEqual(self.rendered_ingress["ports"][0]["host_ip"], "127.0.0.1")
        self.assertEqual(self.rendered_ingress["ports"][0]["target"], 8787)

    def test_merged_beta_mesh_network_is_internal_and_has_no_host_gateway(self) -> None:
        self.assertEqual(set(self.rendered_mesh["networks"]), {"repo_patch_beta_control"})
        self.assertTrue(self.rendered["networks"]["repo_patch_beta_control"]["internal"])
        self.assertNotIn("extra_hosts", self.rendered_mesh)
        self.assertEqual(
            set(self.rendered_ingress["networks"]),
            {"repo_patch_beta_control", "repo_patch_beta_ingress"},
        )

    def test_merged_loopback_ingress_is_credential_free_and_hardened(self) -> None:
        self.assertEqual(self.rendered_ingress["user"], "65534:65534")
        self.assertTrue(self.rendered_ingress["read_only"])
        self.assertEqual(self.rendered_ingress["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", self.rendered_ingress["security_opt"])
        self.assertEqual(self.rendered_ingress["pids_limit"], 64)
        self.assertNotIn("volumes", self.rendered_ingress)
        self.assertFalse(
            any(
                "KEY" in name or "TOKEN" in name or "SECRET" in name
                for name in self.rendered_ingress["environment"]
            )
        )

    def test_merged_beta_disables_local_model_subprocesses(self) -> None:
        environment = self.rendered_mesh["environment"]
        self.assertEqual(environment["MESH_ORCHESTRATION_MODE"], "native_hermes")
        self.assertEqual(environment["MESH_HERMES_COMMAND"], "")
        self.assertEqual(environment["MESH_GOOSE_COMMAND"], "")
        self.assertEqual(environment["MESH_EVO_COMMAND"], "")
        for name in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "OPENROUTER_API_KEY",
            "OPENAI_BASE_URL",
            "OPENAI_HOST",
            "ANTHROPIC_BASE_URL",
            "ANTHROPIC_HOST",
            "OLLAMA_HOST",
        ):
            self.assertEqual(environment[name], "")

    def test_merged_beta_removes_host_repo_and_operator_credentials(self) -> None:
        mounts = {mount["target"]: mount for mount in self.rendered_mesh["volumes"]}
        self.assertEqual(mounts["/app/.mesh-runtime-state"]["source"], "mesh_repo_patch_runtime_state")
        for target in (
            "/workspace/orbital-mesh",
            "/workspace/orbital-mesh/.hermes-local",
            "/root/.config/goose",
        ):
            self.assertEqual(mounts[target]["type"], "volume")
            self.assertTrue(mounts[target]["read_only"])
        self.assertEqual(mounts["/root/.kube/config"]["source"], "/dev/null")
        self.assertTrue(mounts["/root/.kube/config"]["read_only"])
        self.assertFalse(
            any(
                mount.get("type") == "bind" and mount.get("source") == str(Path.cwd())
                for mount in self.rendered_mesh["volumes"]
            )
        )

    def test_merged_socket_contract_matches_authority_directory_policy(self) -> None:
        options = self.rendered["volumes"]["mesh_repo_patch_authority_socket"]["driver_opts"]["o"]
        self.assertIn("uid=3000", options)
        self.assertIn("gid=4000", options)
        self.assertIn("mode=0750", options)

    def test_beta_verifier_policy_remains_fixed_during_isolation_rollout(self) -> None:
        self.assertEqual(
            self.rendered_authority["environment"]["MESH_REPO_PATCH_ALLOWED_TEST_COMMANDS_JSON"],
            '[["python3","-c","pass"]]',
        )

    def test_authority_alone_receives_writable_target_and_private_authority_material(self) -> None:
        for marker in (
            "${MESH_REPO_PATCH_TARGET_HOST_PATH:?set authority-owned beta target repository host path}",
            "target: /workspace/target",
            "MESH_REPO_PATCH_AUTHORITY_PRIVATE_KEY_PATH: /run/secrets/repo-patch/authority-private.pem",
            "MESH_REPO_PATCH_AUTHORITY_CLIENT_KEYS_PATH: /run/secrets/repo-patch/clients.json",
            "MESH_REPO_PATCH_AUTHORITY_PERMIT_KEY_PATH: /run/secrets/repo-patch/permit-hmac.key",
        ):
            self.assertIn(marker, self.authority)
        for forbidden in (
            "MESH_REPO_PATCH_TARGET_HOST_PATH",
            "MESH_REPO_PATCH_AUTHORITY_PRIVATE_KEY_PATH",
            "MESH_REPO_PATCH_AUTHORITY_CLIENT_KEYS_PATH",
            "MESH_REPO_PATCH_AUTHORITY_PERMIT_KEY_PATH",
            "MESH_REPO_PATCH_AUTHORITY_PRIVATE_KEY_HOST_PATH",
            "MESH_REPO_PATCH_AUTHORITY_CLIENT_KEYS_REGISTRY_HOST_PATH",
            "MESH_REPO_PATCH_AUTHORITY_PERMIT_KEY_HOST_PATH",
        ):
            self.assertNotIn(forbidden, self.mesh)

    def test_mesh_receives_only_client_side_authority_credentials(self) -> None:
        for marker in (
            "MESH_REPO_PATCH_AUTHORITY_SOCKET_PATH: /run/mesh-authority/repo-patch-authority.sock",
            "MESH_REPO_PATCH_AUTHORITY_CLIENT_PRIVATE_KEY_PATH: /run/secrets/repo-patch/orchestrator-client-private.pem",
            "MESH_REPO_PATCH_AUTHORITY_PUBLIC_KEY_PATH: /run/secrets/repo-patch/authority-public.pem",
            "${MESH_REPO_PATCH_ORCHESTRATOR_CLIENT_PRIVATE_KEY_HOST_PATH:?set orchestrator client private-key host path}",
            "${MESH_REPO_PATCH_AUTHORITY_PUBLIC_KEY_HOST_PATH:?set authority public-key host path}",
        ):
            self.assertIn(marker, self.mesh)

    def test_both_processes_use_the_same_pinned_real_linux_hsai_cli(self) -> None:
        for block in (self.mesh, self.authority):
            for marker in (
                "MESH_HSAI_ADMISSION_COMMAND: \"/opt/hsai/bin/hsai-mesh-admission --current-policy-id ${MESH_REPO_PATCH_BETA_POLICY_ID:?set beta repo-patch policy id}\"",
                'MESH_HSAI_ADMISSION_AUTHORITY_MODE: "rust_evidence_v2"',
                'MESH_HSAI_ADMISSION_EXECUTABLE_SHA256: "${MESH_HSAI_LINUX_CLI_SHA256:?set pinned Linux HSAI CLI SHA-256}"',
                "${MESH_HSAI_LINUX_CLI_HOST_PATH:?set real Linux HSAI CLI host path}",
                "target: /opt/hsai/bin/hsai-mesh-admission",
                "read_only: true",
            ):
                self.assertIn(marker, block)

    def test_beta_authority_uses_explicit_file_state_and_named_volumes(self) -> None:
        for marker in (
            "MESH_STATE_BACKEND: file",
            "MESH_REPO_PATCH_AUTHORITY_STORE_BACKEND: file",
            "MESH_REPO_PATCH_AUTHORITY_STATE_DIRECTORY: /var/lib/mesh-authority",
            "source: mesh_repo_patch_authority_state",
            "source: mesh_repo_patch_authority_socket",
        ):
            self.assertIn(marker, self.authority)
        for marker in (
            "mesh_repo_patch_authority_state:",
            "${MESH_REPO_PATCH_AUTHORITY_STATE_HOST_PATH:?set authority-owned durable state host path}",
            "mesh_repo_patch_authority_socket:",
            "type: tmpfs",
            "mode=0750",
        ):
            self.assertIn(marker, self.volumes)

    def test_all_secret_and_cli_bind_mounts_are_read_only(self) -> None:
        for block in (self.mesh, self.authority):
            bind_sections = block.split("- type: bind")[1:]
            self.assertTrue(bind_sections)
            for section in bind_sections:
                if "target: /workspace/target" in section:
                    continue
                self.assertIn("read_only: true", section)


class _EchoUpstreamHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        payload = b'{"status":"ok"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self) -> None:
        payload = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(201)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class BetaLoopbackIngressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), _EchoUpstreamHandler)
        upstream_host, upstream_port = self.upstream.server_address
        self.proxy = BetaLoopbackIngressServer(
            ("127.0.0.1", 0),
            _handler_type(upstream_host=str(upstream_host), upstream_port=int(upstream_port)),
        )
        self.threads = [
            threading.Thread(target=self.upstream.serve_forever, daemon=True),
            threading.Thread(target=self.proxy.serve_forever, daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    def tearDown(self) -> None:
        self.proxy.shutdown()
        self.upstream.shutdown()
        self.proxy.server_close()
        self.upstream.server_close()
        for thread in self.threads:
            thread.join(timeout=2)

    def _url(self, path: str = "/api/health") -> str:
        host, port = self.proxy.server_address
        return f"http://{host}:{port}{path}"

    def test_fixed_proxy_forwards_get_and_post(self) -> None:
        with urllib.request.urlopen(self._url(), timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read()), {"status": "ok"})

        request = urllib.request.Request(
            self._url("/api/runs"),
            data=b"bounded",
            method="POST",
            headers={"Content-Type": "application/octet-stream"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            self.assertEqual(response.status, 201)
            self.assertEqual(response.read(), b"bounded")

    def test_oversized_and_chunked_requests_are_rejected_locally(self) -> None:
        oversized = urllib.request.Request(
            self._url("/api/runs"),
            data=b"",
            method="POST",
            headers={"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)},
        )
        with self.assertRaises(urllib.error.HTTPError) as oversized_error:
            urllib.request.urlopen(oversized, timeout=2)
        self.assertEqual(oversized_error.exception.code, 413)

        chunked = urllib.request.Request(
            self._url("/api/runs"),
            data=b"bounded",
            method="POST",
            headers={"Transfer-Encoding": "chunked"},
        )
        with self.assertRaises(urllib.error.HTTPError) as chunked_error:
            urllib.request.urlopen(chunked, timeout=2)
        self.assertEqual(chunked_error.exception.code, 400)

    def test_absolute_request_target_is_rejected_locally(self) -> None:
        host, port = self.proxy.server_address
        connection = http.client.HTTPConnection(host, port, timeout=2)
        try:
            connection.putrequest("GET", "http://example.invalid/api/health", skip_host=True)
            connection.putheader("Host", "example.invalid")
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertEqual(
                json.loads(response.read())["message"],
                "absolute request targets are not supported",
            )
        finally:
            connection.close()

if __name__ == "__main__":
    unittest.main()
