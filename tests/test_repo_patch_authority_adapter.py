from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from services.orchestrator.repo_patch_authority_adapter import build_repo_patch_authority_client
from shared.mesh_runtime import RuntimeConfig


class RepoPatchAuthorityAdapterTests(unittest.TestCase):
    def test_pinned_client_builds_from_owner_only_key_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client_private, _ = _write_key_pair(root, "client")
            _, authority_public = _write_key_pair(root, "authority")
            socket_path = root / "authority.sock"
            config = RuntimeConfig(
                repo_patch_authority_socket_path=str(socket_path),
                repo_patch_authority_client_private_key_path=str(client_private),
                repo_patch_authority_client_key_id="client-key",
                repo_patch_authority_public_key_path=str(authority_public),
                repo_patch_authority_key_id="authority-key",
                repo_patch_authority_timeout_seconds=4.0,
                repo_patch_authority_max_message_bytes=4096,
            )

            client = build_repo_patch_authority_client(config)

            self.assertEqual(client.socket_path, socket_path)
            self.assertEqual(client.client_key_id, "client-key")
            self.assertEqual(client.authority_key_id, "authority-key")
            self.assertEqual(client.timeout_seconds, 4.0)
            self.assertEqual(client.max_frame_bytes, 4096)

    def test_missing_socket_configuration_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "socket path is required"):
            build_repo_patch_authority_client(RuntimeConfig())

    def test_partial_authority_configuration_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = RuntimeConfig(repo_patch_authority_socket_path=str(Path(tmp) / "authority.sock"))
            with self.assertRaisesRegex(ValueError, "client private key path is required"):
                build_repo_patch_authority_client(config)

    def test_group_readable_private_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client_private, _ = _write_key_pair(root, "client")
            _, authority_public = _write_key_pair(root, "authority")
            client_private.chmod(0o640)
            config = RuntimeConfig(
                repo_patch_authority_socket_path=str(root / "authority.sock"),
                repo_patch_authority_client_private_key_path=str(client_private),
                repo_patch_authority_public_key_path=str(authority_public),
            )

            with self.assertRaisesRegex(ValueError, "permissions"):
                build_repo_patch_authority_client(config)

    def test_symlinked_public_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            client_private, _ = _write_key_pair(root, "client")
            _, authority_public = _write_key_pair(root, "authority")
            public_link = root / "authority-link.pem"
            public_link.symlink_to(authority_public)
            config = RuntimeConfig(
                repo_patch_authority_socket_path=str(root / "authority.sock"),
                repo_patch_authority_client_private_key_path=str(client_private),
                repo_patch_authority_public_key_path=str(public_link),
            )

            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                build_repo_patch_authority_client(config)


def _write_key_pair(root: Path, name: str) -> tuple[Path, Path]:
    key = Ed25519PrivateKey.generate()
    private_path = root / f"{name}-private.pem"
    public_path = root / f"{name}-public.pem"
    private_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    private_path.chmod(0o600)
    public_path.write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    public_path.chmod(0o644)
    return private_path, public_path


if __name__ == "__main__":
    unittest.main()
