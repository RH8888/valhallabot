"""Focused tests for background agent bulk disabling in flask_app.py.

Verifies:
1. Subscriber GET request returns promptly without waiting for bulk remote operations.
2. Bulk remote disabling runs in background processing.
3. Operation is idempotent (already pushed or in-progress tasks are deduplicated).
4. Remote accounts on panels are deduplicated.
5. Failures are retried, and failure prevents marking agent as disabled_pushed=1.
"""
from __future__ import annotations

import sys
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, call

# Ensure mock dependencies if not installed in current environment
if "qrcode" not in sys.modules:
    sys.modules["qrcode"] = MagicMock()
if "telegram" not in sys.modules:
    sys.modules["telegram"] = MagicMock()
if "telegram.ext" not in sys.modules:
    sys.modules["telegram.ext"] = MagicMock()

import services
services.init_mysql_pool = MagicMock()

from api.subscription_aggregator import flask_app


class TestAgentBulkDisable(unittest.TestCase):
    def setUp(self):
        with flask_app._agent_disable_lock:
            flask_app._pending_agent_disables.clear()
        self.app = flask_app.app
        self.client = self.app.test_client()

    def tearDown(self):
        with flask_app._agent_disable_lock:
            flask_app._pending_agent_disables.clear()

    @patch("api.subscription_aggregator.flask_app.get_owner_id")
    @patch("api.subscription_aggregator.flask_app.get_local_user")
    @patch("api.subscription_aggregator.flask_app.get_agent")
    @patch("api.subscription_aggregator.flask_app.get_agent_total_used")
    @patch("api.subscription_aggregator.flask_app.trigger_agent_disable_background")
    def test_subscriber_get_request_prompt_return(
        self,
        mock_trigger_bg,
        mock_get_agent_total_used,
        mock_get_agent,
        mock_get_local_user,
        mock_get_owner_id,
    ):
        """Subscriber GET request must return promptly with empty body when agent exceeded quota."""
        owner_id = 999
        mock_get_owner_id.return_value = owner_id
        mock_get_local_user.return_value = {
            "owner_id": owner_id,
            "username": "sub_user",
            "plan_limit_bytes": 1000,
            "used_bytes": 100,
            "disabled_pushed": 0,
        }
        mock_get_agent.return_value = {
            "telegram_user_id": owner_id,
            "plan_limit_bytes": 5000,
            "disabled_pushed": 0,
            "expire_at": None,
        }
        mock_get_agent_total_used.return_value = 6000  # Quota exceeded

        start = time.perf_counter()
        resp = self.client.get("/sub/sub_user/valid_app_key/links")
        elapsed = time.perf_counter() - start

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, b"")
        self.assertLess(elapsed, 0.5, "HTTP GET request blocked instead of returning promptly")
        mock_trigger_bg.assert_called_once_with(owner_id)

    @patch("api.subscription_aggregator.flask_app.get_agent")
    @patch("api.subscription_aggregator.flask_app.list_all_agent_links")
    @patch("api.subscription_aggregator.flask_app.disable_remote")
    @patch("api.subscription_aggregator.flask_app.mark_agent_disabled")
    def test_bulk_disable_remote_operations_and_deduplication(
        self,
        mock_mark_disabled,
        mock_disable_remote,
        mock_list_links,
        mock_get_agent,
    ):
        """Bulk disabling should deduplicate targets, call disable_remote, and mark agent disabled."""
        owner_id = 12345
        mock_get_agent.return_value = {
            "telegram_user_id": owner_id,
            "disabled_pushed": 0,
        }
        # Two users sharing a panel remote account, plus a distinct account
        mock_list_links.return_value = [
            {
                "local_username": "user1",
                "remote_username": "rem1",
                "panel_url": "https://p1.example.com",
                "access_token": "tok1",
                "panel_type": "marzneshin",
                "sanaei_api_version": None,
            },
            {
                "local_username": "user2",
                "remote_username": "rem1",  # Same panel & remote user
                "panel_url": "https://p1.example.com",
                "access_token": "tok1",
                "panel_type": "marzneshin",
                "sanaei_api_version": None,
            },
            {
                "local_username": "user3",
                "remote_username": "rem2",
                "panel_url": "https://p2.example.com",
                "access_token": "tok2",
                "panel_type": "sanaei",
                "sanaei_api_version": "modern",
            },
        ]
        mock_disable_remote.return_value = (200, "disabled")

        success = flask_app.disable_agent_bulk(owner_id, max_retries=1, retry_delay=0)

        self.assertTrue(success)
        # Should be called exactly twice because rem1@p1 was deduplicated
        self.assertEqual(mock_disable_remote.call_count, 2)
        mock_mark_disabled.assert_called_once_with(owner_id)

    @patch("api.subscription_aggregator.flask_app.get_agent")
    @patch("api.subscription_aggregator.flask_app.disable_remote")
    @patch("api.subscription_aggregator.flask_app.mark_agent_disabled")
    def test_idempotency_already_pushed(
        self,
        mock_mark_disabled,
        mock_disable_remote,
        mock_get_agent,
    ):
        """If disabled_pushed is already 1, bulk disable is a no-op."""
        owner_id = 12345
        mock_get_agent.return_value = {
            "telegram_user_id": owner_id,
            "disabled_pushed": 1,
        }

        success = flask_app.disable_agent_bulk(owner_id, max_retries=1, retry_delay=0)

        self.assertTrue(success)
        mock_disable_remote.assert_not_called()
        mock_mark_disabled.assert_not_called()

    @patch("api.subscription_aggregator.flask_app.get_agent_disable_executor")
    def test_idempotency_in_progress_deduplication(
        self,
        mock_get_executor,
    ):
        """Concurrent triggers for the same agent should be deduplicated while in-progress."""
        owner_id = 555
        mock_executor = MagicMock()
        mock_get_executor.return_value = mock_executor

        # Manually add to pending set to simulate active in-flight task
        flask_app._pending_agent_disables.add(owner_id)

        # Triggering again should return None and not submit any new task
        result = flask_app.trigger_agent_disable_background(owner_id)

        self.assertIsNone(result)
        mock_executor.submit.assert_not_called()

    @patch("api.subscription_aggregator.flask_app.get_agent")
    @patch("api.subscription_aggregator.flask_app.list_all_agent_links")
    @patch("api.subscription_aggregator.flask_app.disable_remote")
    @patch("api.subscription_aggregator.flask_app.mark_agent_disabled")
    def test_retry_on_transient_failure_then_succeed(
        self,
        mock_mark_disabled,
        mock_disable_remote,
        mock_list_links,
        mock_get_agent,
    ):
        """Transient errors should be retried, and succeed when retry passes."""
        owner_id = 777
        mock_get_agent.return_value = {"telegram_user_id": owner_id, "disabled_pushed": 0}
        mock_list_links.return_value = [
            {
                "local_username": "u1",
                "remote_username": "rem1",
                "panel_url": "https://p1.example.com",
                "access_token": "tok1",
                "panel_type": "marzneshin",
                "sanaei_api_version": None,
            }
        ]
        # First call fails, second call succeeds
        mock_disable_remote.side_effect = [(500, "temporary server error"), (200, "ok")]

        success = flask_app.disable_agent_bulk(owner_id, max_retries=2, retry_delay=0)

        self.assertTrue(success)
        self.assertEqual(mock_disable_remote.call_count, 2)
        mock_mark_disabled.assert_called_once_with(owner_id)

    @patch("api.subscription_aggregator.flask_app.get_agent")
    @patch("api.subscription_aggregator.flask_app.list_all_agent_links")
    @patch("api.subscription_aggregator.flask_app.disable_remote")
    @patch("api.subscription_aggregator.flask_app.mark_agent_disabled")
    def test_failure_after_retries_preserves_disabled_pushed_zero(
        self,
        mock_mark_disabled,
        mock_disable_remote,
        mock_list_links,
        mock_get_agent,
    ):
        """Permanent failure across retries must NOT mark agent disabled so it can be retried later."""
        owner_id = 888
        mock_get_agent.return_value = {"telegram_user_id": owner_id, "disabled_pushed": 0}
        mock_list_links.return_value = [
            {
                "local_username": "u1",
                "remote_username": "rem1",
                "panel_url": "https://p1.example.com",
                "access_token": "tok1",
                "panel_type": "marzneshin",
                "sanaei_api_version": None,
            }
        ]
        mock_disable_remote.return_value = (500, "persistent error")

        success = flask_app.disable_agent_bulk(owner_id, max_retries=2, retry_delay=0)

        self.assertFalse(success)
        # Tried initial attempt + 2 retries = 3 calls
        self.assertEqual(mock_disable_remote.call_count, 3)
        # Crucial: mark_agent_disabled must NOT be called on failure
        mock_mark_disabled.assert_not_called()


if __name__ == "__main__":
    unittest.main()

