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
    _http_get_json,
    _http_post_json,
    _minimax_env_configured,
    _operator_headers,
    _sanitize_prior_for_merge,
    _truthy,
)


class _FakeResponse:
    status = 200

    def __init__(self, payload: bytes = b'{"status":"ok"}') -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


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


class PriorSanitizeTests(unittest.TestCase):
    def test_sanitize_rejects_off_domain_prior(self) -> None:
        blob = "Wireless mesh ROI and cabling payback in rural deployments. " * 20
        self.assertIsNone(_sanitize_prior_for_merge(blob))

    def test_sanitize_accepts_repo_grounded_prior(self) -> None:
        text = (
            "## Report\n\nWe analyzed **FirstSlicePipeline** `run_summaries` and **holistic_matrix** "
            "cells for **promptfoo** + **goose**.\n"
        )
        out = _sanitize_prior_for_merge(text)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertIn("FirstSlicePipeline", out)


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


class OperatorHeaderTests(unittest.TestCase):
    def test_operator_headers_default_to_overnight_identity(self) -> None:
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                _operator_headers(),
                {
                    "X-Mesh-Operator": "mesh-overnight-autoresearch",
                    "X-Mesh-Roles": "launcher,approver",
                },
            )

    def test_operator_headers_respect_env_overrides(self) -> None:
        env = {
            "MESH_OPERATOR_HEADER": "X-Test-Operator",
            "MESH_OPERATOR_ROLES_HEADER": "X-Test-Roles",
            "MESH_E2E_OPERATOR_ID": "nightly@example.com",
            "MESH_E2E_OPERATOR_ROLES": "launcher,admin",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                _operator_headers(),
                {
                    "X-Test-Operator": "nightly@example.com",
                    "X-Test-Roles": "launcher,admin",
                },
            )

    def test_http_get_sends_operator_headers(self) -> None:
        captured: list[object] = []

        def fake_urlopen(request: object, timeout: int) -> _FakeResponse:
            captured.append(request)
            self.assertEqual(timeout, 30)
            return _FakeResponse()

        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            with unittest.mock.patch("scripts.overnight_mesh_autoresearch.urllib.request.urlopen", fake_urlopen):
                self.assertEqual(_http_get_json("http://mesh.local/api/runs/run_1"), {"status": "ok"})

        self.assertEqual(len(captured), 1)
        request = captured[0]
        headers = {name.lower(): value for name, value in request.header_items()}  # type: ignore[attr-defined]
        self.assertEqual(headers["x-mesh-operator"], "mesh-overnight-autoresearch")
        self.assertEqual(headers["x-mesh-roles"], "launcher,approver")

    def test_http_post_sends_operator_headers(self) -> None:
        captured: list[object] = []

        def fake_urlopen(request: object, timeout: int) -> _FakeResponse:
            captured.append(request)
            self.assertEqual(timeout, 60)
            return _FakeResponse(b'{"run_id":"run_1"}')

        env = {
            "MESH_OPERATOR_HEADER": "X-Test-Operator",
            "MESH_OPERATOR_ROLES_HEADER": "X-Test-Roles",
            "MESH_E2E_OPERATOR_ID": "nightly@example.com",
            "MESH_E2E_OPERATOR_ROLES": "launcher,approver",
        }
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with unittest.mock.patch("scripts.overnight_mesh_autoresearch.urllib.request.urlopen", fake_urlopen):
                self.assertEqual(_http_post_json("http://mesh.local/api/runs", {"goal_id": "goal"}), {"run_id": "run_1"})

        self.assertEqual(len(captured), 1)
        request = captured[0]
        headers = {name.lower(): value for name, value in request.header_items()}  # type: ignore[attr-defined]
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(headers["x-test-operator"], "nightly@example.com")
        self.assertEqual(headers["x-test-roles"], "launcher,approver")


if __name__ == "__main__":
    unittest.main()
