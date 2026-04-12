"""RuntimeConfig path resolution (repo-anchored relative MESH_* paths)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from shared.mesh_runtime.config import DEFAULT_RESEARCH_DIRECTORY, DEFAULT_STATE_DIRECTORY, RuntimeConfig


class RuntimeConfigPathTests(unittest.TestCase):
    def test_relative_state_directory_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_STATE_DIRECTORY": ".mesh-runtime-state"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.state_directory).is_absolute())
        self.assertEqual(Path(cfg.state_directory), DEFAULT_STATE_DIRECTORY.resolve())

    def test_absolute_state_directory_unchanged(self) -> None:
        raw = str(Path("/tmp/mesh-state-absolute").resolve())
        with patch.dict(
            "os.environ",
            {"MESH_STATE_DIRECTORY": raw},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertEqual(cfg.state_directory, raw)

    def test_direct_state_directory_derives_research_directory(self) -> None:
        raw = str(Path("/tmp/mesh-state-direct").resolve())
        cfg = RuntimeConfig(state_directory=raw)
        self.assertEqual(cfg.research_directory, str(Path(raw) / "research"))

    def test_relative_research_directory_is_repo_anchored(self) -> None:
        with patch.dict(
            "os.environ",
            {"MESH_RESEARCH_DIRECTORY": ".mesh-runtime-state/research"},
            clear=False,
        ):
            cfg = RuntimeConfig.from_env()
        self.assertTrue(Path(cfg.research_directory).is_absolute())
        self.assertEqual(Path(cfg.research_directory), DEFAULT_RESEARCH_DIRECTORY.resolve())


if __name__ == "__main__":
    unittest.main()
