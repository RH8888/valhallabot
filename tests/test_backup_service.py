"""Unit tests for automatic database backup service."""
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from services.backup_service import (
    cleanup_old_backups,
    create_backup_archive,
    format_bytes,
    get_backup_dir,
    get_backup_settings,
    perform_backup,
    set_backup_settings,
)


class TestBackupService(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.backup_dir = Path(self.temp_dir) / "backups"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.patcher_env = patch.dict(os.environ, {"BACKUP_DIR": str(self.backup_dir), "ADMIN_IDS": "123456"})
        self.patcher_env.start()

    def tearDown(self):
        self.patcher_env.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_format_bytes(self):
        self.assertEqual(format_bytes(500), "500.00 B")
        self.assertEqual(format_bytes(1024), "1.00 KB")
        self.assertEqual(format_bytes(1048576), "1.00 MB")
        self.assertEqual(format_bytes(1073741824), "1.00 GB")

    def test_get_backup_dir(self):
        bdir = get_backup_dir()
        self.assertTrue(bdir.exists())
        self.assertEqual(bdir.resolve(), self.backup_dir.resolve())

    def test_cleanup_old_backups(self):
        # Create 35 dummy backup files
        for i in range(35):
            fpath = self.backup_dir / f"backup_2026-07-24_10-{i:02d}.zip"
            fpath.write_text(f"dummy content {i}")
            # Set modification time so older files sort first
            mtime = 1000 + i * 10
            os.utime(fpath, (mtime, mtime))

        deleted = cleanup_old_backups(self.backup_dir, keep=30)
        remaining = list(self.backup_dir.glob("backup_*"))

        self.assertEqual(deleted, 5)
        self.assertEqual(len(remaining), 30)

    @patch("services.backup_service.generate_sql_dump")
    def test_create_backup_archive(self, mock_dump):
        mock_dump.return_value = "CREATE TABLE dummy (id INT);\nINSERT INTO dummy VALUES (1);"
        
        file_path, filename, size_bytes = create_backup_archive()
        
        self.assertTrue(file_path.exists())
        self.assertTrue(filename.startswith("backup_"))
        self.assertTrue(filename.endswith(".zip"))
        self.assertGreater(size_bytes, 0)

        # Inspect zip contents
        with zipfile.ZipFile(file_path, "r") as zf:
            names = zf.namelist()
            self.assertIn("database.sql", names)
            self.assertIn(".env", names)
            sql_data = zf.read("database.sql").decode("utf-8")
            self.assertEqual(sql_data.replace("\r\n", "\n"), mock_dump.return_value.replace("\r\n", "\n"))

    @patch("services.backup_service.get_setting")
    @patch("services.backup_service.set_setting")
    def test_settings_get_and_set(self, mock_set_setting, mock_get_setting):
        def fake_get_setting(owner_id, key):
            if key == "auto_backup_enabled":
                return "1"
            if key == "backup_interval_hours":
                return "12"
            if key == "last_backup_timestamp":
                return "2026-07-24T12:00:00+00:00"
            return None

        mock_get_setting.side_effect = fake_get_setting

        settings = get_backup_settings()
        self.assertTrue(settings["enabled"])
        self.assertEqual(settings["interval_hours"], 12)
        self.assertEqual(settings["last_backup"], "2026-07-24T12:00:00+00:00")

        set_backup_settings(True, 48)
        mock_set_setting.assert_any_call(123456, "auto_backup_enabled", "1")
        mock_set_setting.assert_any_call(123456, "backup_interval_hours", "48")

    @patch("services.backup_service.send_backup_to_telegram")
    @patch("services.backup_service.create_backup_archive")
    @patch("services.backup_service._update_last_backup_timestamp")
    def test_perform_backup_success(self, mock_update_ts, mock_create, mock_send_tg):
        dummy_path = self.backup_dir / "backup_2026-07-24_15-30.zip"
        dummy_path.write_text("test")
        mock_create.return_value = (dummy_path, "backup_2026-07-24_15-30.zip", 4)

        fpath, fname, size = perform_backup(trigger_type="manual")

        self.assertEqual(fname, "backup_2026-07-24_15-30.zip")
        self.assertEqual(size, 4)
        mock_send_tg.assert_called_once_with(dummy_path, trigger_type="manual")
        mock_update_ts.assert_called_once()


if __name__ == "__main__":
    unittest.main()
