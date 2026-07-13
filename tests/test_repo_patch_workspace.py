from __future__ import annotations

import subprocess
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import services.actuators.repo_patch_workspace as workspace_module
from services.actuators.repo_patch_workspace import RepoPatchWorkspaceManager


class RepoPatchWorkspaceTests(unittest.TestCase):
    def test_verified_patch_promotes_only_after_explicit_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _git_repo(root / "repo")
            target = repo / "app.py"
            manager = RepoPatchWorkspaceManager(root / "authority" / "worktrees")

            with manager.prepare(
                repo_path=repo,
                target_file="app.py",
                allowed_paths=["app.py"],
                find_text="old",
                replace_text="new",
                workspace_id="permit-success",
            ) as prepared:
                receipt = prepared.verify(
                    [["python3", "-c", "from pathlib import Path; assert 'new' in Path('app.py').read_text()"]]
                )
                self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'old'\n")
                self.assertEqual(receipt.changed_paths, ("app.py",))
                promoted = prepared.promote()
                self.assertEqual(promoted.target_postimage_digest, receipt.target_postimage_digest)

            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'new'\n")
            self.assertEqual(list((root / "authority" / "worktrees").iterdir()), [])

    def test_failed_verification_leaves_source_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _git_repo(root / "repo")
            target = repo / "app.py"
            manager = RepoPatchWorkspaceManager(root / "authority" / "worktrees")

            with manager.prepare(
                repo_path=repo,
                target_file="app.py",
                allowed_paths=["app.py"],
                find_text="old",
                replace_text="new",
                workspace_id="permit-failed-check",
            ) as prepared:
                with self.assertRaisesRegex(ValueError, "verification command failed"):
                    prepared.verify([["python3", "-c", "raise SystemExit(4)"]])

            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'old'\n")

    def test_test_side_mutation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _git_repo(root / "repo")
            target = repo / "app.py"
            manager = RepoPatchWorkspaceManager(root / "authority" / "worktrees")

            with manager.prepare(
                repo_path=repo,
                target_file="app.py",
                allowed_paths=["app.py"],
                find_text="old",
                replace_text="new",
                workspace_id="permit-side-effect",
            ) as prepared:
                with self.assertRaisesRegex(ValueError, "undeclared changes"):
                    prepared.verify(
                        [["python3", "-c", "from pathlib import Path; Path('unexpected.txt').write_text('x')"]]
                    )

            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'old'\n")
            self.assertFalse((repo / "unexpected.txt").exists())

    def test_source_drift_after_verification_blocks_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _git_repo(root / "repo")
            target = repo / "app.py"
            manager = RepoPatchWorkspaceManager(root / "authority" / "worktrees")

            with manager.prepare(
                repo_path=repo,
                target_file="app.py",
                allowed_paths=["app.py"],
                find_text="old",
                replace_text="new",
                workspace_id="permit-drift",
            ) as prepared:
                prepared.verify([])
                target.write_text("VALUE = 'external'\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "preimage changed|became dirty"):
                    prepared.promote()

            self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 'external'\n")

    def test_dirty_source_is_rejected_before_worktree_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _git_repo(root / "repo")
            (repo / "app.py").write_text("VALUE = 'dirty'\n", encoding="utf-8")
            manager = RepoPatchWorkspaceManager(root / "authority" / "worktrees")

            with self.assertRaisesRegex(ValueError, "must be clean"):
                manager.prepare(
                    repo_path=repo,
                    target_file="app.py",
                    allowed_paths=["app.py"],
                    find_text="old",
                    replace_text="new",
                    workspace_id="permit-dirty",
                )

    def test_hard_link_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _git_repo(root / "repo")
            (repo / "alias.py").hardlink_to(repo / "app.py")
            subprocess.run(["git", "-C", str(repo), "add", "alias.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add hard-link fixture"], check=True)
            manager = RepoPatchWorkspaceManager(root / "authority" / "worktrees")

            with self.assertRaisesRegex(ValueError, "hard linked"):
                manager.prepare(
                    repo_path=repo,
                    target_file="app.py",
                    allowed_paths=["app.py"],
                    find_text="old",
                    replace_text="new",
                    workspace_id="permit-hardlink",
                )

    def test_absolute_symlink_parent_cannot_escape_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _git_repo(root / "repo")
            external = root / "authority-state"
            external.mkdir()
            external_target = external / "store.json"
            external_target.write_text("old external state\n", encoding="utf-8")
            before = sha256(external_target.read_bytes()).hexdigest()
            (repo / "escape").symlink_to(external, target_is_directory=True)
            subprocess.run(["git", "-C", str(repo), "add", "escape"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add absolute escape"], check=True)
            manager = RepoPatchWorkspaceManager(root / "worktrees")

            with self.assertRaisesRegex(ValueError, "Git-indexed regular blob|symlink"):
                manager.prepare(
                    repo_path=repo,
                    target_file="escape/store.json",
                    allowed_paths=["escape/store.json"],
                    find_text="old",
                    replace_text="corrupted",
                    workspace_id="permit-absolute-symlink-parent",
                )

            self.assertEqual(sha256(external_target.read_bytes()).hexdigest(), before)

    def test_relative_symlink_parent_cannot_escape_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external = root / "outside"
            external.mkdir()
            external_target = external / "app.py"
            external_target.write_text("VALUE = 'old'\n", encoding="utf-8")
            before = sha256(external_target.read_bytes()).hexdigest()
            repo = _git_repo(root / "repo")
            (repo / "escape").symlink_to("../../outside", target_is_directory=True)
            subprocess.run(["git", "-C", str(repo), "add", "escape"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add relative escape"], check=True)
            manager = RepoPatchWorkspaceManager(root / "worktrees")

            with self.assertRaisesRegex(ValueError, "Git-indexed regular blob|symlink"):
                manager.prepare(
                    repo_path=repo,
                    target_file="escape/app.py",
                    allowed_paths=["escape/app.py"],
                    find_text="old",
                    replace_text="corrupted",
                    workspace_id="permit-relative-symlink-parent",
                )

            self.assertEqual(sha256(external_target.read_bytes()).hexdigest(), before)

    def test_parent_component_swap_between_index_check_and_open_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = _git_repo(root / "repo")
            package = repo / "package"
            package.mkdir()
            target = package / "app.py"
            target.write_text("VALUE = 'old'\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "package/app.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "add nested target"], check=True)
            external = root / "outside"
            external.mkdir()
            external_target = external / "app.py"
            external_target.write_text("VALUE = 'old'\n", encoding="utf-8")
            before = sha256(external_target.read_bytes()).hexdigest()
            original_index_check = workspace_module._validate_git_index_regular_blob

            def swap_parent(repo_path: Path, relative_path: Path, label: str) -> None:
                original_index_check(repo_path, relative_path, label)
                package.rename(repo / "package-original")
                (repo / "package").symlink_to(external, target_is_directory=True)

            manager = RepoPatchWorkspaceManager(root / "worktrees")
            with patch.object(workspace_module, "_validate_git_index_regular_blob", side_effect=swap_parent):
                with self.assertRaisesRegex(ValueError, "symlink or non-directory"):
                    manager.prepare(
                        repo_path=repo,
                        target_file="package/app.py",
                        allowed_paths=["package/app.py"],
                        find_text="old",
                        replace_text="corrupted",
                        workspace_id="permit-parent-swap",
                    )

            self.assertEqual(sha256(external_target.read_bytes()).hexdigest(), before)


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "app.py").write_text("VALUE = 'old'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Mesh Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "mesh@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(path), "add", "app.py"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return path.resolve()


if __name__ == "__main__":
    unittest.main()
