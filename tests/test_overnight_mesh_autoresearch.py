"""Unit tests for overnight_mesh_autoresearch helpers."""

from __future__ import annotations

import os
import sys
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.overnight_mesh_autoresearch import (  # noqa: E402
    _falsy,
    _minimax_env_configured,
    _truthy,
)


class OvernightEnvParsingTests(unittest.TestCase):
    def test_truthy(self) -> None:
        self.assertTrue(_truthy("1", False))
        self.assertFalse(_truthy("0", True))
        self.assertTrue(_truthy(None, True))

    def test_falsy_default_true(self) -> None:
        self.assertTrue(_falsy(None, True))
        self.assertTrue(_falsy("", True))
        self.assertFalse(_falsy("0", True))
        self.assertFalse(_falsy("false", True))
        self.assertTrue(_falsy("1", False))


class MinimaxEnvTests(unittest.TestCase):
    def test_minimax_env_openai(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            self.assertTrue(_minimax_env_configured())

    def test_minimax_env_empty(self) -> None:
        removed: dict[str, str | None] = {}
        for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
            if key in os.environ:
                removed[key] = os.environ.pop(key)
        try:
            self.assertFalse(_minimax_env_configured())
        finally:
            for key, val in removed.items():
                if val is not None:
                    os.environ[key] = val


if __name__ == "__main__":
    unittest.main()
