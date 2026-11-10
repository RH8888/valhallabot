"""Tests for user deletion database transaction atomicity, rollback on mid-operation failure,
and verifying agent cumulative traffic accounting is preserved (not refunded).
"""
import sys
import unittest
from unittest.mock import MagicMock, patch

if "qrcode" not in sys.modules:
    sys.modules["qrcode"] = MagicMock()
if "telegram" not in sys.modules:
    sys.modules["telegram"] = MagicMock()
if "telegram.ext" not in sys.modules:
    sys.modules["telegram.ext"] = MagicMock()

import services
services.init_mysql_pool = MagicMock()
from services import database
database.init_mysql_pool = MagicMock()

import api.subscription_aggregator
from api.subscription_aggregator import flask_app
import bot


class TestUserDeletionTransactions(unittest.TestCase):
    def setUp(self):
        self.owner_id = 12345
        self.username = "victim_user"
        self.local_users = {
            (self.owner_id, self.username): {
                "id": 10,
                "owner_id": self.owner_id,
                "username": self.username,
                "used_bytes": 5 * 1024**3,
            }
        }
        self.local_user_keys = {
            10: {"local_user_id": 10, "access_key": "some_key"}
        }
        self.links = {
            (self.owner_id, self.username): {"panel_id": 1, "remote_username": "rem1"}
        }
        self.app_users = {
            (self.owner_id, self.username): {"telegram_user_id": self.owner_id, "username": self.username}
        }
        self.agent_totals = {
            self.owner_id: {"total_used_bytes": 20 * 1024**3}
        }
        self.fail_step = None

    def _create_mock_context(self):
        test_self = self

        class MockCursor:
            def __init__(self, conn):
                self.conn = conn

            def execute(self, query: str, params: tuple = ()):
                q = " ".join(query.strip().split()).upper()

                if "DELETE LUK FROM LOCAL_USER_KEYS" in q:
                    if test_self.fail_step == "keys":
                        raise RuntimeError("Simulated failure during keys deletion")
                    test_self.local_user_keys.clear()

                elif "DELETE FROM LOCAL_USER_PANEL_LINKS" in q:
                    if test_self.fail_step == "links":
                        raise RuntimeError("Simulated failure during links deletion")
                    test_self.links.pop((test_self.owner_id, test_self.username), None)

                elif "DELETE FROM LOCAL_USERS" in q:
                    if test_self.fail_step == "local_users":
                        raise RuntimeError("Simulated failure during local_users deletion")
                    test_self.local_users.pop((test_self.owner_id, test_self.username), None)

                elif "DELETE FROM APP_USERS" in q:
                    if test_self.fail_step == "app_users":
                        raise RuntimeError("Simulated failure during app_users deletion")
                    test_self.app_users.pop((test_self.owner_id, test_self.username), None)

            def fetchone(self):
                return None

            def fetchall(self):
                return []

            def close(self):
                pass

        class MockConn:
            def __init__(self):
                self._snap_users = dict(test_self.local_users)
                self._snap_keys = dict(test_self.local_user_keys)
                self._snap_links = dict(test_self.links)
                self._snap_app = dict(test_self.app_users)

            def commit(self):
                pass

            def rollback(self):
                test_self.local_users = dict(self._snap_users)
                test_self.local_user_keys = dict(self._snap_keys)
                test_self.links = dict(self._snap_links)
                test_self.app_users = dict(self._snap_app)

            def close(self):
                pass

        class MockContext:
            def __init__(self, dict_=True):
                self.conn = MockConn()
                self.cur = MockCursor(self.conn)

            def __enter__(self):
                return self.cur

            def __exit__(self, exc_type, exc, tb):
                if exc_type is None:
                    self.conn.commit()
                else:
                    self.conn.rollback()
                self.cur.close()
                self.conn.close()
                return False

        return MockContext

    def test_delete_local_user_success(self):
        """Successful delete_local_user atomically clears all tables and preserves agent cumulative traffic."""
        mock_ctx = self._create_mock_context()
        with patch("bot.with_mysql_cursor", side_effect=mock_ctx):
            bot.delete_local_user(self.owner_id, self.username)

        self.assertNotIn((self.owner_id, self.username), self.local_users)
        self.assertEqual(len(self.local_user_keys), 0)
        self.assertNotIn((self.owner_id, self.username), self.links)
        self.assertNotIn((self.owner_id, self.username), self.app_users)
        # Agent total traffic must NOT be refunded
        self.assertEqual(self.agent_totals[self.owner_id]["total_used_bytes"], 20 * 1024**3)

    def test_delete_local_user_rollback_midway_failure(self):
        """Simulate database error midway (on deleting local_users table); all earlier deletions roll back."""
        self.fail_step = "local_users"
        mock_ctx = self._create_mock_context()
        with patch("bot.with_mysql_cursor", side_effect=mock_ctx):
            with self.assertRaises(RuntimeError):
                bot.delete_local_user(self.owner_id, self.username)

        # Everything must be restored
        self.assertIn((self.owner_id, self.username), self.local_users)
        self.assertIn(10, self.local_user_keys)
        self.assertIn((self.owner_id, self.username), self.links)
        self.assertIn((self.owner_id, self.username), self.app_users)
