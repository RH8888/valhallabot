"""Unit and integration tests for API and Telegram user creation, atomic credential generation,
and subscription link resolution.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Ensure missing telegram/qrcode/db-pool dependencies can be safely mocked
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
from api.users import create_user, UserCreate
from api.auth import Identity


class TestUserCreationAndSubscriptionLinks(unittest.TestCase):
    def setUp(self):
        # Build in-memory mock DB tables
        self.local_users: dict[tuple[int, str], dict] = {}
        self.local_user_keys: dict[int, dict] = {}
        self.app_users: dict[tuple[int, str], dict] = {}
        self.next_local_user_id = 1
        self.next_app_user_id = 1

    def _create_mock_cursor(self, should_fail_on_app_user: bool = False):
        test_self = self

        class MockCursor:
            def __init__(self, conn):
                self.conn = conn
                self._last_result = None

            def execute(self, query: str, params: tuple = ()):
                q = " ".join(query.strip().split())
                q_upper = q.upper()

                if "INSERT INTO LOCAL_USERS" in q_upper:
                    owner_id, username, plan_limit_bytes, expire_at = params[:4]
                    key = (owner_id, username)
                    if key not in test_self.local_users:
                        user_id = test_self.next_local_user_id
                        test_self.next_local_user_id += 1
                        test_self.local_users[key] = {
                            "id": user_id,
                            "owner_id": owner_id,
                            "username": username,
                            "plan_limit_bytes": plan_limit_bytes,
                            "used_bytes": 0,
                            "expire_at": expire_at,
                            "manual_disabled": 0,
                            "disabled_pushed": 0,
                            "service_id": None,
                        }
                    else:
                        test_self.local_users[key]["plan_limit_bytes"] = plan_limit_bytes
                        test_self.local_users[key]["expire_at"] = expire_at
                    self._last_result = None

                elif "SELECT ID FROM LOCAL_USERS" in q_upper:
                    owner_id, username = params[0], params[1]
                    user = test_self.local_users.get((owner_id, username))
                    self._last_result = [{"id": user["id"]}] if user else []

                elif "SELECT ACCESS_KEY, EXPIRES_AT FROM LOCAL_USER_KEYS" in q_upper:
                    local_user_id = params[0]
                    key_row = test_self.local_user_keys.get(local_user_id)
                    self._last_result = [key_row] if key_row else []

                elif "SELECT 1 FROM LOCAL_USER_KEYS WHERE ACCESS_KEY=" in q_upper:
                    candidate = params[0]
                    found = any(k["access_key"] == candidate for k in test_self.local_user_keys.values())
                    self._last_result = [{"1": 1}] if found else []

                elif "INSERT INTO LOCAL_USER_KEYS" in q_upper:
                    local_user_id, access_key, expires_at = params[0], params[1], params[2]
                    test_self.local_user_keys[local_user_id] = {
                        "local_user_id": local_user_id,
                        "access_key": access_key,
                        "expires_at": expires_at,
                    }
                    self._last_result = None

                elif "SELECT APP_KEY FROM APP_USERS" in q_upper:
                    # telegram_user_id IN (...) AND username=%s
                    username = params[-1]
                    owner_ids = params[:-1]
                    found = None
                    for oid in owner_ids:
                        if (oid, username) in test_self.app_users:
                            found = test_self.app_users[(oid, username)]
                            break
                    self._last_result = [found] if found else []

                elif "INSERT INTO APP_USERS" in q_upper:
                    if should_fail_on_app_user:
                        raise RuntimeError("Simulated DB failure during app_users insertion")
                    telegram_user_id, username, app_key = params[0], params[1], params[2]
                    test_self.app_users[(telegram_user_id, username)] = {
                        "id": test_self.next_app_user_id,
                        "telegram_user_id": telegram_user_id,
                        "username": username,
                        "app_key": app_key,
                    }
                    test_self.next_app_user_id += 1
                    self._last_result = None

                elif "SELECT TELEGRAM_USER_ID FROM APP_USERS" in q_upper:
                    # For flask_app get_owner_id
                    username, app_key = params[0], params[1]
                    found = None
                    for (oid, u), row in test_self.app_users.items():
                        if u == username and row["app_key"] == app_key:
                            found = row
                            break
                    self._last_result = [found] if found else []

                elif "SELECT OWNER_ID, USERNAME, PLAN_LIMIT_BYTES" in q_upper:
                    # For flask_app get_local_user
                    username = params[-1]
                    owner_ids = params[:-1]
                    found = None
                    for oid in owner_ids:
                        if (oid, username) in test_self.local_users:
                            found = test_self.local_users[(oid, username)]
                            break
                    self._last_result = [found] if found else []

                elif "SELECT LU.USERNAME" in q_upper:
                    # For api/users _fetch_user
                    username = params[-1]
                    owner_ids = params[:-1]
                    found = None
                    for oid in owner_ids:
                        if (oid, username) in test_self.local_users:
                            u = test_self.local_users[(oid, username)]
                            k = test_self.local_user_keys.get(u["id"], {})
                            found = {
                                **u,
                                "access_key": k.get("access_key"),
                                "key_expires_at": k.get("expires_at"),
                            }
                            break
                    self._last_result = [found] if found else []

                else:
                    self._last_result = []

            def fetchone(self):
                if self._last_result:
                    return self._last_result.pop(0)
                return None

            def fetchall(self):
                res = self._last_result or []
                self._last_result = []
                return res

            def close(self):
                pass

        class MockConn:
            def __init__(self):
                self._snapshot_local_users = dict(test_self.local_users)
                self._snapshot_local_user_keys = dict(test_self.local_user_keys)
                self._snapshot_app_users = dict(test_self.app_users)

            def commit(self):
                pass

            def rollback(self):
                test_self.local_users = dict(self._snapshot_local_users)
                test_self.local_user_keys = dict(self._snapshot_local_user_keys)
                test_self.app_users = dict(self._snapshot_app_users)

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

    def test_telegram_created_user_creates_app_users_and_subscription_links_work(self):
        """Simulate telegram user creation via upsert_local_user and test subscription link resolution."""
        mock_ctx = self._create_mock_cursor()
        owner_id = 999
        username = "tguser1"

        with patch("bot.with_mysql_cursor", side_effect=mock_ctx), \
             patch("api.subscription_aggregator.flask_app.with_mysql_cursor", side_effect=mock_ctx):

            bot.upsert_local_user(owner_id, username, 10 * 1024**3, 30)

            # Check that local_user, local_user_keys, and app_users were all created
            self.assertIn((owner_id, username), self.local_users)
            user_id = self.local_users[(owner_id, username)]["id"]
            self.assertIn(user_id, self.local_user_keys)
            self.assertIn((owner_id, username), self.app_users)

            app_key = self.app_users[(owner_id, username)]["app_key"]
            self.assertTrue(bool(app_key))

            # Test subscription link resolution in flask_app
            client = flask_app.app.test_client()
            with patch("api.subscription_aggregator.flask_app.list_mapped_links", return_value=[]), \
                 patch("api.subscription_aggregator.flask_app.list_user_links", return_value=[]), \
                 patch("api.subscription_aggregator.flask_app.get_agent_total_used", return_value=0), \
                 patch("api.subscription_aggregator.flask_app.get_agent", return_value={"traffic_limit_bytes": 0, "expire_at": None}):
                resp = client.get(f"/sub/{username}/{app_key}/links")
                self.assertEqual(resp.status_code, 200)

    def test_api_created_user_creates_app_users_and_subscription_links_work(self):
        """Users created via POST /api/v1/users/create receive app_users mapping and valid subscription link."""
        mock_ctx = self._create_mock_cursor()
        owner_id = 555
        username = "apiuser1"

        identity = Identity(agent_id=owner_id, role="agent")
        create_data = UserCreate(
            username=username,
            limit_bytes=10 * 1024**3,
            duration_days=30,
        )

        with patch("bot.with_mysql_cursor", side_effect=mock_ctx), \
             patch("api.users.with_mysql_cursor", side_effect=mock_ctx), \
             patch("api.subscription_aggregator.flask_app.with_mysql_cursor", side_effect=mock_ctx):

            # Directly invoke the endpoint coroutine
            user_out = asyncio.run(create_user(data=create_data, identity=identity))
            self.assertEqual(user_out.username, username)

            # Assert app_users record was created
            self.assertIn((owner_id, username), self.app_users)
            app_key = self.app_users[(owner_id, username)]["app_key"]
            self.assertTrue(bool(app_key))

            # Verify subscription link returns 200, not 404
            flask_client = flask_app.app.test_client()
            with patch("api.subscription_aggregator.flask_app.list_mapped_links", return_value=[]), \
                 patch("api.subscription_aggregator.flask_app.list_user_links", return_value=[]), \
                 patch("api.subscription_aggregator.flask_app.get_agent_total_used", return_value=0), \
                 patch("api.subscription_aggregator.flask_app.get_agent", return_value={"traffic_limit_bytes": 0, "expire_at": None}):
                sub_resp = flask_client.get(f"/sub/{username}/{app_key}/links")
                self.assertEqual(sub_resp.status_code, 200)

    def test_atomic_creation_rollback_on_failure(self):
        """User creation and credential creation should be atomic within the transaction."""
        mock_ctx = self._create_mock_cursor(should_fail_on_app_user=True)
        owner_id = 777
        username = "failuser"

        with patch("bot.with_mysql_cursor", side_effect=mock_ctx):
            with self.assertRaises(RuntimeError):
                bot.upsert_local_user(owner_id, username, 10 * 1024**3, 30)

            # Verify that neither local_users, local_user_keys, nor app_users remain
            self.assertNotIn((owner_id, username), self.local_users)
            self.assertEqual(len(self.local_user_keys), 0)
            self.assertNotIn((owner_id, username), self.app_users)
