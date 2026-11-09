"""Unit tests for automatic database backup service."""
import gzip
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from services.backup_service import (
    _dump_mysql_python,
    cleanup_old_backups,
    create_backup_archive,
    format_bytes,
    generate_sql_dump,
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

    @patch("services.backup_service.with_mysql_cursor")
    def test_dump_mysql_python_large_table_streaming(self, mock_with_cursor):
        """Verify rows are streamed in batches with fetchmany instead of fetchall."""
        mock_cur = MagicMock()
        mock_with_cursor.return_value.__enter__.return_value = mock_cur

        # Tables: users
        # 250 rows simulated
        all_rows = [(i, f"user_{i}", 100 + i) for i in range(1, 251)]
        row_batches = [all_rows[0:100], all_rows[100:200], all_rows[200:250], []]

        def fake_execute(query, *args, **kwargs):
            mock_cur._last_query = query

        def fake_fetchall():
            q = getattr(mock_cur, "_last_query", "")
            if "SHOW TABLES" in q:
                return [("users",)]
            if "SHOW COLUMNS" in q:
                return [("id",), ("username",), ("score",)]
            # If fetchall is called for SELECT *, fail the test
            if "SELECT * FROM" in q:
                raise AssertionError("cur.fetchall() must NOT be called for table data rows!")
            return []

        def fake_fetchone():
            q = getattr(mock_cur, "_last_query", "")
            if "SHOW CREATE TABLE" in q:
                return ("users", "CREATE TABLE `users` (`id` int, `username` varchar(255), `score` int)")
            return None

        mock_cur.execute.side_effect = fake_execute
        mock_cur.fetchall.side_effect = fake_fetchall
        mock_cur.fetchone.side_effect = fake_fetchone
        mock_cur.fetchmany.side_effect = row_batches

        dump_str = _dump_mysql_python(batch_size=100)

        # Ensure fetchmany was called 4 times (batch 1, batch 2, batch 3, empty termination batch)
        self.assertEqual(mock_cur.fetchmany.call_count, 4)
        mock_cur.fetchmany.assert_called_with(100)

        # Verify dump has all 250 rows and 3 INSERT INTO statements
        insert_count = dump_str.count("INSERT INTO `users` (`id`, `username`, `score`) VALUES")
        self.assertEqual(insert_count, 3)
        self.assertIn("(1, 'user_1', 101)", dump_str)
        self.assertIn("(100, 'user_100', 200)", dump_str)
        self.assertIn("(250, 'user_250', 350)", dump_str)

    @patch("services.backup_service.with_mysql_cursor")
    def test_dump_mysql_python_transaction_consistency_and_no_locks(self, mock_with_cursor):
        """Verify transaction-consistent snapshot is used and LOCK TABLES is eliminated."""
        mock_cur = MagicMock()
        mock_with_cursor.return_value.__enter__.return_value = mock_cur

        executed_statements = []

        def fake_execute(stmt):
            executed_statements.append(stmt)

        mock_cur.execute.side_effect = fake_execute
        mock_cur.fetchall.side_effect = lambda: [("orders",)] if "SHOW TABLES" in executed_statements[-1] else [("id",)]
        mock_cur.fetchone.return_value = ("orders", "CREATE TABLE `orders` (`id` int)")
        mock_cur.fetchmany.side_effect = [[(1,), (2,)], []]

        dump_str = _dump_mysql_python()

        # Check transaction-consistent setup was executed
        self.assertIn("SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ", executed_statements)
        self.assertIn("START TRANSACTION WITH CONSISTENT SNAPSHOT", executed_statements)
        self.assertIn("COMMIT", executed_statements)

        # Verify no LOCK TABLES statement was ever executed on the cursor
        for stmt in executed_statements:
            self.assertNotIn("LOCK TABLES", stmt)

        # Verify no LOCK TABLES or UNLOCK TABLES in the emitted SQL dump
        self.assertNotIn("LOCK TABLES", dump_str)
        self.assertNotIn("UNLOCK TABLES", dump_str)

    @patch("services.backup_service.with_mysql_cursor")
    def test_dump_mysql_python_direct_file_and_gzip(self, mock_with_cursor):
        """Verify writing directly to a file and gzip-compressed file without memory build."""
        mock_cur = MagicMock()
        mock_with_cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.side_effect = lambda: [("items",)] if "SHOW TABLES" in str(mock_cur.execute.call_args) else [("id",)]
        mock_cur.fetchone.return_value = ("items", "CREATE TABLE `items` (`id` int)")
        mock_cur.fetchmany.side_effect = [[(10,), (20,)], []]

        # 1. Plain direct file output
        plain_file = self.backup_dir / "dump.sql"
        res_plain = _dump_mysql_python(target=plain_file)
        self.assertIsNone(res_plain)
        self.assertTrue(plain_file.exists())
        plain_content = plain_file.read_text(encoding="utf-8")
        self.assertIn("INSERT INTO `items` (`id`) VALUES", plain_content)
        self.assertIn("(10),\n(20);", plain_content)

        # Reset mocks for gzip test
        mock_cur.fetchmany.side_effect = [[(10,), (20,)], []]

        # 2. Gzip direct file output
        gz_file = self.backup_dir / "dump.sql.gz"
        res_gz = _dump_mysql_python(target=gz_file, use_gzip=True)
        self.assertIsNone(res_gz)
        self.assertTrue(gz_file.exists())

        # Decompress gzip file and compare
        with gzip.open(gz_file, "rt", encoding="utf-8") as gf:
            decompressed_content = gf.read()
        self.assertIn("INSERT INTO `items` (`id`) VALUES", decompressed_content)
        self.assertIn("(10),\n(20);", decompressed_content)

    @patch("services.backup_service.with_mysql_cursor")
    def test_dump_mysql_python_data_types_and_restore_compatibility(self, mock_with_cursor):
        """Verify data formatting and restore syntax compatibility for complex types."""
        mock_cur = MagicMock()
        mock_with_cursor.return_value.__enter__.return_value = mock_cur

        executed = []
        def fake_exec(query):
            executed.append(query)
        mock_cur.execute.side_effect = fake_exec

        def fake_fetchall():
            last = executed[-1] if executed else ""
            if "SHOW TABLES" in last:
                return [("test_types",)]
            if "SHOW COLUMNS" in last:
                return [("id",), ("is_active",), ("price",), ("notes",), ("raw_data",), ("empty_col",)]
            return []

        mock_cur.fetchall.side_effect = fake_fetchall
        mock_cur.fetchone.return_value = ("test_types", "CREATE TABLE `test_types` (`id` int, `is_active` tinyint(1), `price` float, `notes` text, `raw_data` blob, `empty_col` varchar(50))")
        
        sample_row = (
            1,
            True,
            19.99,
            "Special: 'single quote', \"double quote\", backslash \\, newline \n, return \r, null \0",
            b"\xde\xad\xbe\xef",
            None,
        )
        mock_cur.fetchmany.side_effect = [[sample_row], []]

        dump_str = _dump_mysql_python()

        # Check foreign key checks wrapping
        self.assertTrue(dump_str.startswith("-- Valhalla MySQL Backup Dump\n"))
        self.assertIn("SET FOREIGN_KEY_CHECKS=0;", dump_str)
        self.assertTrue(dump_str.endswith("SET FOREIGN_KEY_CHECKS=1;\n"))

        # Check properly formatted values
        self.assertIn("1", dump_str) # boolean True formatted as 1
        self.assertIn("19.99", dump_str)
        self.assertIn(r"\'single quote\'", dump_str)
        self.assertIn(r"\\", dump_str)
        self.assertIn(r"\n", dump_str)
        self.assertIn(r"\r", dump_str)
        self.assertIn(r"\0", dump_str)
        self.assertIn("0xdeadbeef", dump_str)
        self.assertIn("NULL", dump_str)

    @patch("services.backup_service._dump_mysql_cli")
    @patch("services.backup_service._dump_mysql_python")
    def test_generate_sql_dump_fallback_when_cli_unavailable(self, mock_py_dump, mock_cli_dump):
        """Verify Python fallback is used when mysqldump CLI is unavailable."""
        # 1. CLI is unavailable (returns None) -> calls Python fallback
        mock_cli_dump.return_value = None
        mock_py_dump.return_value = "-- python dump"

        res = generate_sql_dump()

        self.assertEqual(res, "-- python dump")
        mock_cli_dump.assert_called_once()
        mock_py_dump.assert_called_once()

        # 2. CLI is available (returns string) -> uses CLI dump
        mock_cli_dump.reset_mock()
        mock_py_dump.reset_mock()
        mock_cli_dump.return_value = "-- cli dump"

        res2 = generate_sql_dump()

        self.assertEqual(res2, "-- cli dump")
        mock_cli_dump.assert_called_once()
        mock_py_dump.assert_not_called()


if __name__ == "__main__":
    unittest.main()
