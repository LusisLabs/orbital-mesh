"""Tests for the ArgoCDAdapter (sync + rollback via REST API)."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch

from services.actuators.argocd import ArgoCDAdapter


class DryRunTests(unittest.TestCase):
    def test_no_credentials_means_dry_run(self):
        adapter = ArgoCDAdapter()
        self.assertFalse(adapter.live)
        result = adapter.sync_application({"application": "web"})
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(result["external_refs"]["dry_run"])

    def test_missing_application_fails(self):
        adapter = ArgoCDAdapter()
        result = adapter.sync_application({})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "missing_parameter")

    def test_dry_run_rollback_includes_target_revision(self):
        adapter = ArgoCDAdapter()
        result = adapter.rollback_application({"application": "web", "target_revision": "abc123"})
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["external_refs"]["argocd_target_revision"], "abc123")


class LiveHttpTests(unittest.TestCase):
    def _mock_response(self, status: int, body: dict):
        resp = MagicMock()
        resp.status = status
        resp.read.return_value = json.dumps(body).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    @patch("services.actuators.argocd.urllib.request.urlopen")
    def test_sync_success(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response(
            200, {"revision": "abc123"},
        )
        adapter = ArgoCDAdapter(url="https://argo.test", token="tok")
        self.assertTrue(adapter.live)
        result = adapter.sync_application({"application": "web", "revision": "HEAD"})
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["external_refs"]["argocd_sync_revision"], "abc123")
        # Verify Authorization header was set
        request = mock_urlopen.call_args[0][0]
        self.assertEqual(request.headers["Authorization"], "Bearer tok")
        self.assertEqual(request.get_method(), "POST")

    @patch("services.actuators.argocd.urllib.request.urlopen")
    def test_sync_http_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://argo.test", code=403, msg="forbidden",
            hdrs=None, fp=io.BytesIO(b'{"error": "forbidden"}'),
        )
        adapter = ArgoCDAdapter(url="https://argo.test", token="tok")
        result = adapter.sync_application({"application": "web"})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure"]["reason"], "argocd_sync_failed")

    @patch("services.actuators.argocd.urllib.request.urlopen")
    def test_rollback_uses_numeric_id(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response(200, {})
        adapter = ArgoCDAdapter(url="https://argo.test", token="tok")
        result = adapter.rollback_application({"application": "web", "target_revision": "5"})
        self.assertEqual(result["status"], "succeeded")
        request = mock_urlopen.call_args[0][0]
        body = json.loads(request.data.decode())
        self.assertEqual(body["id"], 5)

    @patch("services.actuators.argocd.urllib.request.urlopen")
    def test_get_application_success(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response(
            200,
            {
                "status": {
                    "health": {"status": "Healthy"},
                    "sync": {"status": "Synced", "revision": "abc"},
                }
            },
        )
        adapter = ArgoCDAdapter(url="https://argo.test", token="tok")
        result = adapter.get_application({"application": "web"})
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["application"]["health"], "Healthy")
        self.assertEqual(result["application"]["sync_status"], "Synced")


if __name__ == "__main__":
    unittest.main()
