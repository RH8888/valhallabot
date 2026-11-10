"""Unit and integration tests for API authorization and cross-agent isolation in api/users.py."""
from __future__ import annotations

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

from fastapi import HTTPException
import api.users as api_users
from api.users import (
    UserCreate,
    UserListRequest,
    UserUpdate,
    UsageRequest,
    create_user,
    list_users,
    edit_user,
    toggle_user,
    get_usage,
)
from api.auth import Identity


def run_coro(coro):
    """Run an async coroutine synchronously."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not finish synchronously")


class TestApiUsersAuthorization(unittest.TestCase):
    def setUp(self):
        self.agent1_identity = Identity(role="agent", agent_id=1001, agent_name="agent1")
        self.agent2_identity = Identity(role="agent", agent_id=1002, agent_name="agent2")
        self.admin_identity = Identity(role="admin")
        self.super_admin_identity = Identity(role="super_admin")

    def test_list_users_agent_cannot_access_other_owner(self):
        """Agent cannot access users belonging to another agent_id by specifying owner_id."""
        req = UserListRequest(owner_id=1002)
        with self.assertRaises(HTTPException) as ctx:
            list_users(data=req, identity=self.agent1_identity)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Agents cannot access or modify users of another owner", ctx.exception.detail)

    def test_list_users_agent_access_own_owner_id_allowed(self):
        """Agent specifying their own agent_id (or None) is allowed."""
        req_none = UserListRequest(owner_id=None)
        req_self = UserListRequest(owner_id=1001)

        with patch("api.users._list_users", return_value=([], 0)) as mock_list, \
             patch("api.users.get_total_usage_by_panel", return_value=0):
            res_none = list_users(data=req_none, identity=self.agent1_identity)
            self.assertEqual(res_none.total, 0)
            mock_list.assert_called_with(1001, None, 0, 25, None)

            res_self = list_users(data=req_self, identity=self.agent1_identity)
            self.assertEqual(res_self.total, 0)
            mock_list.assert_called_with(1001, None, 0, 25, None)

    def test_list_users_admin_requires_owner_id(self):
        """Admin must specify owner_id; missing owner_id raises 400 Bad Request."""
        req_missing = UserListRequest(owner_id=None)
        with self.assertRaises(HTTPException) as ctx:
            list_users(data=req_missing, identity=self.admin_identity)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("owner_id required", ctx.exception.detail)

    def test_list_users_admin_with_owner_id_succeeds(self):
        """Admin specifying target owner_id succeeds."""
        req = UserListRequest(owner_id=1002)
        with patch("api.users._list_users", return_value=([], 0)) as mock_list, \
             patch("api.users.get_total_usage_by_panel", return_value=0):
            res = list_users(data=req, identity=self.admin_identity)
            self.assertEqual(res.total, 0)
            mock_list.assert_called_with(1002, None, 0, 25, None)

    def test_edit_user_agent_cross_owner_rejected(self):
        """Agent cannot modify a user under another owner_id."""
        req = UserUpdate(limit_bytes=1000, owner_id=1002)
        with self.assertRaises(HTTPException) as ctx:
            run_coro(edit_user(username="victim", data=req, identity=self.agent1_identity))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Agents cannot access or modify users of another owner", ctx.exception.detail)

    def test_edit_user_admin_requires_owner_id(self):
        """Admin without owner_id is rejected with 400."""
        req = UserUpdate(limit_bytes=1000, owner_id=None)
        with self.assertRaises(HTTPException) as ctx:
            run_coro(edit_user(username="victim", data=req, identity=self.admin_identity))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("owner_id required", ctx.exception.detail)

    def test_edit_user_admin_with_owner_id_allowed(self):
        """Admin specifying owner_id can edit target owner's user."""
        req = UserUpdate(limit_bytes=1000, owner_id=1002)
        mock_user = {
            "username": "victim",
            "plan_limit_bytes": 1000,
            "used_bytes": 0,
            "expire_at": None,
            "service_id": None,
            "manual_disabled": 0,
            "disabled_pushed": 0,
            "access_key": "k",
            "key_expires_at": None,
        }
        with patch("api.users.apply_user_updates", return_value=True) as mock_apply, \
             patch("api.users._fetch_user", return_value=mock_user):
            res = run_coro(edit_user(username="victim", data=req, identity=self.admin_identity))
            self.assertEqual(res.username, "victim")
            mock_apply.assert_called_once()
            self.assertEqual(mock_apply.call_args[0][0], 1002)

    def test_toggle_user_agent_cross_owner_rejected(self):
        """Agent cannot toggle/disable user under another owner."""
        with self.assertRaises(HTTPException) as ctx:
            run_coro(toggle_user(username="victim", disable=True, owner_id=1002, identity=self.agent1_identity))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Agents cannot access or modify users of another owner", ctx.exception.detail)

    def test_toggle_user_admin_requires_owner_id(self):
        """Admin must specify owner_id to toggle user."""
        with self.assertRaises(HTTPException) as ctx:
            run_coro(toggle_user(username="victim", disable=True, owner_id=None, identity=self.admin_identity))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("owner_id required", ctx.exception.detail)

    def test_get_usage_agent_cross_owner_rejected(self):
        """Agent cannot query usage of another agent's user."""
        req = UsageRequest(owner_id=1002)
        with self.assertRaises(HTTPException) as ctx:
            get_usage(username="victim", data=req, identity=self.agent1_identity)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Agents cannot access or modify users of another owner", ctx.exception.detail)

    def test_create_user_agent_cross_owner_rejected(self):
        """Agent cannot create a user under another agent's account."""
        req = UserCreate(username="newuser", limit_bytes=100, duration_days=30, owner_id=1002)
        with self.assertRaises(HTTPException) as ctx:
            run_coro(create_user(data=req, identity=self.agent1_identity))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Agents cannot access or modify users of another owner", ctx.exception.detail)

