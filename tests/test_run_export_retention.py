from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.purge_run_exports import purge_run_exports


class RunExportRetentionTests(unittest.TestCase):
    def test_purge_run_exports_dry_run_reports_without_deleting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            package_path, archive_path = _write_export(state_dir, "run_expired", "2026-05-01T00:00:00+00:00")

            payload = purge_run_exports(
                state_dir,
                now=datetime(2026, 5, 5, tzinfo=timezone.utc),
                apply=False,
            )

            self.assertEqual(payload["expired_exports"], 1)
            self.assertEqual(payload["deleted_files"], 0)
            self.assertTrue(package_path.exists())
            self.assertTrue(archive_path.exists())
            statuses = [file_record["status"] for file_record in payload["exports"][0]["files"]]
            self.assertEqual(statuses, ["would_delete", "would_delete"])

    def test_purge_run_exports_apply_deletes_expired_json_and_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            package_path, archive_path = _write_export(state_dir, "run_expired", "2026-05-01T00:00:00+00:00")

            payload = purge_run_exports(
                state_dir,
                now=datetime(2026, 5, 5, tzinfo=timezone.utc),
                apply=True,
            )

            self.assertEqual(payload["expired_exports"], 1)
            self.assertEqual(payload["deleted_files"], 2)
            self.assertFalse(package_path.exists())
            self.assertFalse(archive_path.exists())

    def test_purge_run_exports_retains_future_delete_after(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            package_path, archive_path = _write_export(state_dir, "run_future", "2026-05-10T00:00:00+00:00")

            payload = purge_run_exports(
                state_dir,
                now=datetime(2026, 5, 5, tzinfo=timezone.utc),
                apply=True,
            )

            self.assertEqual(payload["expired_exports"], 0)
            self.assertEqual(payload["deleted_files"], 0)
            self.assertTrue(package_path.exists())
            self.assertTrue(archive_path.exists())
            self.assertEqual(payload["exports"][0]["status"], "retained")


def _write_export(state_dir: Path, run_id: str, delete_after: str) -> tuple[Path, Path]:
    export_dir = state_dir / "run_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    package_path = export_dir / f"{run_id}.json"
    archive_path = export_dir / f"{run_id}.zip"
    package_path.write_text(
        json.dumps(
            {
                "package_version": "mesh.run_export.v1",
                "run_id": run_id,
                "retention": {"delete_after": delete_after},
            },
        ),
        encoding="utf-8",
    )
    archive_path.write_bytes(b"zip")
    return package_path, archive_path


if __name__ == "__main__":
    unittest.main()
