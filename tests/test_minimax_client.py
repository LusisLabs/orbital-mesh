"""Tests for MiniMax client used by goose-autoresearch scripts (OpenAI + Anthropic-compatible)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / ".cursor/skills/goose-autoresearch/scripts"
sys.path.insert(0, str(SCRIPTS))

from minimax_client import (  # noqa: E402
    chat_completion,
    minimax_openai_base_url,
    minimax_route_label,
    research_chat_timeout_seconds,
)


class TestMinimaxClient(unittest.TestCase):
    def test_minimax_openai_base_url_respects_env(self) -> None:
        with patch.dict("os.environ", {"OPENAI_BASE_URL": "https://custom.example/v1"}, clear=False):
            self.assertEqual(minimax_openai_base_url(), "https://custom.example/v1")

    def test_chat_completion_openai_parses_message(self) -> None:
        payload = {
            "choices": [{"message": {"role": "assistant", "content": "Hello from MiniMax"}}],
        }
        raw = json.dumps(payload).encode()

        class FakeResp:
            def read(self) -> bytes:
                return raw

            def __enter__(self) -> FakeResp:
                return self

            def __exit__(self, *a: object) -> None:
                return None

        with (
            patch.dict(
                "os.environ",
                {"OPENAI_API_KEY": "sk-test", "OPENAI_BASE_URL": "https://api.minimax.io/v1"},
                clear=False,
            ),
            patch("minimax_client.urllib.request.urlopen", return_value=FakeResp()),
        ):
            out = chat_completion([{"role": "user", "content": "Hi"}], model="MiniMax-M2.5")
        self.assertEqual(out, "Hello from MiniMax")

    def test_chat_completion_anthropic_parses_text_blocks(self) -> None:
        payload = {
            "content": [{"type": "text", "text": "Hello via Anthropic-compatible"}],
        }
        raw = json.dumps(payload).encode()

        class FakeResp:
            def read(self) -> bytes:
                return raw

            def __enter__(self) -> FakeResp:
                return self

            def __exit__(self, *a: object) -> None:
                return None

        with (
            patch.dict(
                "os.environ",
                {
                    "OPENAI_API_KEY": "",
                    "MINIMAX_API_KEY": "",
                    "ANTHROPIC_API_KEY": "sk-anthropic-test",
                    "ANTHROPIC_BASE_URL": "https://api.minimax.io/anthropic",
                },
                clear=False,
            ),
            patch("minimax_client.urllib.request.urlopen", return_value=FakeResp()) as m,
        ):
            out = chat_completion(
                [
                    {"role": "system", "content": "You are helpful."},
                    {"role": "user", "content": "Hi"},
                ],
                model="MiniMax-M2.5",
            )
        self.assertEqual(out, "Hello via Anthropic-compatible")
        self.assertIn("/v1/messages", m.call_args[0][0].full_url)

    def test_chat_completion_missing_key(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "",
                "MINIMAX_API_KEY": "",
                "ANTHROPIC_API_KEY": "",
                "ANTHROPIC_AUTH_TOKEN": "",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                chat_completion([{"role": "user", "content": "x"}])
        self.assertIn("OPENAI_API_KEY", str(ctx.exception))
        self.assertIn("ANTHROPIC", str(ctx.exception))

    def test_minimax_route_label(self) -> None:
        with patch.dict("os.environ", {"OPENAI_API_KEY": "x"}, clear=False):
            self.assertEqual(minimax_route_label(), "openai")
        with patch.dict(
            "os.environ",
            {"OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "y"},
            clear=False,
        ):
            self.assertEqual(minimax_route_label(), "anthropic")

    def test_research_chat_timeout_seconds_default(self) -> None:
        with patch.dict(
            "os.environ",
            {"MINIMAX_CHAT_TIMEOUT_SECONDS": "", "MESH_MINIMAX_TIMEOUT_SECONDS": ""},
            clear=False,
        ):
            self.assertEqual(research_chat_timeout_seconds(), 600.0)

    def test_research_chat_timeout_seconds_from_env(self) -> None:
        with patch.dict(
            "os.environ",
            {"MINIMAX_CHAT_TIMEOUT_SECONDS": "120"},
            clear=False,
        ):
            self.assertEqual(research_chat_timeout_seconds(), 120.0)
        with patch.dict(
            "os.environ",
            {"MINIMAX_CHAT_TIMEOUT_SECONDS": "", "MESH_MINIMAX_TIMEOUT_SECONDS": "90"},
            clear=False,
        ):
            self.assertEqual(research_chat_timeout_seconds(), 90.0)


if __name__ == "__main__":
    unittest.main()
