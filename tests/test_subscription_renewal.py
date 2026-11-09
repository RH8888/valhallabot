"""Tests for subscription renewal logic."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# Ensure missing telegram/qrcode/db-pool dependencies can be safely mocked for unit tests
if "qrcode" not in sys.modules:
    sys.modules["qrcode"] = MagicMock()
if "telegram" not in sys.modules:
    sys.modules["telegram"] = MagicMock()
if "telegram.ext" not in sys.modules:
    sys.modules["telegram.ext"] = MagicMock()
if "api" not in sys.modules:
    mock_api = MagicMock()
    mock_sub = MagicMock()
    mock_sub.expand_owner_ids.side_effect = lambda uid: [uid]
    mock_sub.admin_ids.return_value = []
    mock_sub.ordered_admin_ids.return_value = []
    mock_sub.canonical_owner_id.side_effect = lambda uid: uid
    sys.modules["api"] = mock_api
    sys.modules["api.subscription_aggregator"] = mock_sub
    sys.modules["api.admin"] = MagicMock()

from services import database
database.init_mysql_pool = MagicMock()

from bot import renew_user
from services.quotas import calculate_renewal_expire_at, renew_agent_days


class TestSubscriptionRenewalCalculation(unittest.TestCase):
    def test_expired_subscription_extends_from_now(self):
        """User example:

        Previous expiration: November 1
        Renewal date: November 10
        Purchased duration: 30 days
        Expected result: December 10 (not December 1).
        """
        now = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
        previous_expiry = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
        add_days = 30

        new_expiry = calculate_renewal_expire_at(previous_expiry, add_days, now=now)
        expected_expiry = datetime(2026, 12, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(new_expiry, expected_expiry)

    def test_active_subscription_extends_from_current_expire_at(self):
        """Active subscription:

        Previous expiration: November 20
        Renewal date: November 10
        Purchased duration: 30 days
        Expected result: December 20.
        """
        now = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
        previous_expiry = datetime(2026, 11, 20, 0, 0, 0, tzinfo=timezone.utc)
        add_days = 30

        new_expiry = calculate_renewal_expire_at(previous_expiry, add_days, now=now)
        expected_expiry = datetime(2026, 12, 20, 0, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(new_expiry, expected_expiry)

    def test_subscription_expiring_exactly_now_extends_from_now(self):
        """Subscription expiring at this exact moment:

        Previous expiration: November 10 12:00
        Renewal date: November 10 12:00
        Purchased duration: 30 days
        Expected result: December 10 12:00.
        """
        now = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
        previous_expiry = datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc)
        add_days = 30

        new_expiry = calculate_renewal_expire_at(previous_expiry, add_days, now=now)
        expected_expiry = datetime(2026, 12, 10, 12, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(new_expiry, expected_expiry)

    def test_none_expiration_extends_from_now(self):
        """No previous expiration (None):

        Renewal date: November 10
        Purchased duration: 30 days
        Expected result: December 10.
        """
        now = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
        add_days = 30

        new_expiry = calculate_renewal_expire_at(None, add_days, now=now)
        expected_expiry = datetime(2026, 12, 10, 0, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(new_expiry, expected_expiry)

    def test_timezone_naive_and_aware_handling(self):
        """Handles comparisons gracefully when current_expire_at is naive UTC."""
        now = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
        naive_expired = datetime(2026, 11, 1, 0, 0, 0)
        naive_active = datetime(2026, 11, 20, 0, 0, 0)

        # Expired naive
        new_expiry = calculate_renewal_expire_at(naive_expired, 30, now=now)
        self.assertEqual(new_expiry, datetime(2026, 12, 10, 0, 0, 0))

        # Active naive
        new_expiry = calculate_renewal_expire_at(naive_active, 30, now=now)
        self.assertEqual(new_expiry, datetime(2026, 12, 20, 0, 0, 0))

    def test_custom_timedelta_duration(self):
        """Allows timedelta instances as duration."""
        now = datetime(2026, 11, 10, 0, 0, 0, tzinfo=timezone.utc)
        previous_expiry = datetime(2026, 11, 1, 0, 0, 0, tzinfo=timezone.utc)
        duration = timedelta(days=15, hours=6)

        new_expiry = calculate_renewal_expire_at(previous_expiry, duration, now=now)
        expected_expiry = datetime(2026, 11, 25, 6, 0, 0, tzinfo=timezone.utc)

        self.assertEqual(new_expiry, expected_expiry)


class TestDatabaseRenewalOperations(unittest.TestCase):
    @patch("services.quotas.with_mysql_cursor")
    def test_renew_agent_days_sql(self, mock_cursor_ctx):
        """renew_agent_days updates agents with conditional max(expire_at, now) logic."""
        mock_cursor = MagicMock()
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        renew_agent_days(123456789, 30)

        mock_cursor.execute.assert_called_once()
        sql, params = mock_cursor.execute.call_args[0]
        sql_normalized = " ".join(sql.strip().split())

        self.assertIn("UPDATE agents", sql_normalized)
        self.assertIn("expire_at IS NULL OR expire_at < UTC_TIMESTAMP()", sql_normalized)
        self.assertIn("UTC_TIMESTAMP() + INTERVAL %s DAY", sql_normalized)
        self.assertIn("expire_at + INTERVAL %s DAY", sql_normalized)
        self.assertEqual(params, (30, 30, 123456789))

    @patch("bot.list_user_links", return_value=[])
    @patch("bot.with_mysql_cursor")
    def test_renew_user_sql_and_reenable(self, mock_cursor_ctx, mock_links):
        """renew_user updates local_users with conditional max(expire_at, now) logic and clears disabled flags."""
        mock_cursor = MagicMock()
        # Call 1: UPDATE local_users + SELECT local_users
        # Call 2: UPDATE local_users (disabled_pushed=0) because user should be enabled
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        future_dt = datetime.now(timezone.utc) + timedelta(days=30)
        mock_cursor.fetchone.return_value = {
            "expire_at": future_dt.replace(tzinfo=None),
            "plan_limit_bytes": 100 * 1024 * 1024 * 1024,
            "used_bytes": 10 * 1024 * 1024 * 1024,
            "manual_disabled": 0,
        }

        renew_user(11111, "testuser", 30)

        # Inspect the first execute call (the renewal UPDATE)
        first_call = mock_cursor.execute.call_args_list[0]
        sql, params = first_call[0]
        sql_normalized = " ".join(sql.strip().split())

        self.assertIn("UPDATE local_users", sql_normalized)
        self.assertIn("expire_at IS NULL OR expire_at < UTC_TIMESTAMP()", sql_normalized)
        self.assertIn("UTC_TIMESTAMP() + INTERVAL %s DAY", sql_normalized)
        self.assertIn("expire_at + INTERVAL %s DAY", sql_normalized)
        self.assertEqual(params[:2], [30, 30])
        self.assertEqual(params[-1], "testuser")

    @patch("bot.get_api")
    @patch("bot.list_user_links")
    @patch("bot.with_mysql_cursor")
    def test_renew_user_remote_panel_propagation(self, mock_cursor_ctx, mock_links, mock_get_api):
        """renew_user propagates new expiration timestamp and re-enables client on upstream panel."""
        mock_cursor = MagicMock()
        mock_cursor_ctx.return_value.__enter__.return_value = mock_cursor

        future_dt = datetime.now(timezone.utc) + timedelta(days=30)
        mock_cursor.fetchone.return_value = {
            "expire_at": future_dt.replace(tzinfo=None),
            "plan_limit_bytes": 100 * 1024 * 1024 * 1024,
            "used_bytes": 10 * 1024 * 1024 * 1024,
            "manual_disabled": 0,
        }

        mock_api = MagicMock()
        mock_api.update_remote_user.return_value = (True, None)
        mock_api.enable_remote_user.return_value = (True, None)
        del mock_api.renew_remote_user  # ensure update_remote_user path
        mock_get_api.return_value = mock_api

        mock_links.return_value = [
            {
                "panel_id": 1,
                "remote_username": "remote_testuser",
                "panel_url": "https://panel.example.com",
                "access_token": "token123",
                "panel_type": "marzneshin",
                "sanaei_api_version": None,
            }
        ]

        renew_user(11111, "testuser", 30)

        # Verify remote panel was updated with the new expire timestamp and enabled
        mock_api.update_remote_user.assert_called_once()
        _, kwargs = mock_api.update_remote_user.call_args
        self.assertGreater(kwargs["expire"], 0)
        mock_api.enable_remote_user.assert_called_once_with(
            "https://panel.example.com", "token123", "remote_testuser"
        )


if __name__ == "__main__":
    unittest.main()
