"""
Comprehensive regression and unit tests for ValhallaBot traffic accounting.

Tests all 9 scenarios required by the engineering specification:
Test 1 - Normal synchronization (10 GB baseline -> 15 GB usage -> 5 GB delta)
Test 2 - Repeated synchronization (idempotency: 5 GB charged once, not twice)
Test 3 - Failure during accounting (transaction rollback, retry charges once)
Test 4 - Time expiration (75 GB consumed, subscription expires, panel stays 75 GB -> remains 75 GB)
Test 5 - Reactivation (75 GB consumed, disabled, reactivated, panel stays 75 GB -> remains 75 GB)
Test 6 - Concurrent synchronization (simultaneous workers -> charged exactly delta, not 2x)
Test 7 - Multiple panels (links reporting 40 GB and 35 GB -> total 75 GB, no duplicate)
Test 8 - Weighted traffic (multiplier preserved: local user weighted, agent/panel raw)
Test 9 - Counter reset (upstream counter resets -> no negative delta, historical traffic not recharged)
"""
from __future__ import annotations

import copy
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from scripts import usage_sync


class MockDatabaseState:
    """In-memory database state supporting transactional atomicity, rollback, and row-level locking."""

    def __init__(self):
        self.lock = threading.RLock()
        self.row_locks: dict[str, threading.Lock] = {}
        self.local_users: dict[tuple[int, str], dict] = {}
        self.links: dict[int, dict] = {}
        self.agents: dict[int, dict] = {}
        self.agent_panel_totals: dict[tuple[int, int], dict] = {}
        self.agent_usage_events: list[dict] = []
        self.next_event_id = 1

    def get_row_lock(self, key: str) -> threading.Lock:
        with self.lock:
            if key not in self.row_locks:
                self.row_locks[key] = threading.Lock()
            return self.row_locks[key]


class MockConnection:
    def __init__(self, db: MockDatabaseState):
        self.db = db
        self.in_transaction = True
        self.locked_keys: list[str] = []
        # Snapshot state for rollback support
        self._snapshot()

    def _snapshot(self):
        with self.db.lock:
            self.orig_local_users = copy.deepcopy(self.db.local_users)
            self.orig_links = copy.deepcopy(self.db.links)
            self.orig_agents = copy.deepcopy(self.db.agents)
            self.orig_panel_totals = copy.deepcopy(self.db.agent_panel_totals)
            self.orig_events = copy.deepcopy(self.db.agent_usage_events)

    def commit(self):
        self.in_transaction = False
        self._release_locks()

    def rollback(self):
        with self.db.lock:
            self.db.local_users = copy.deepcopy(self.orig_local_users)
            self.db.links = copy.deepcopy(self.orig_links)
            self.db.agents = copy.deepcopy(self.orig_agents)
            self.db.agent_panel_totals = copy.deepcopy(self.orig_panel_totals)
            self.db.agent_usage_events = copy.deepcopy(self.orig_events)
        self.in_transaction = False
        self._release_locks()

    def _release_locks(self):
        for k in self.locked_keys:
            lock = self.db.get_row_lock(k)
            if lock.locked():
                try:
                    lock.release()
                except RuntimeError:
                    pass
        self.locked_keys.clear()

    def close(self):
        self._release_locks()


class MockCursor:
    def __init__(self, conn: MockConnection):
        self.conn = conn
        self.db = conn.db
        self.last_result = None

    def execute(self, query: str, params: tuple = ()):
        q = " ".join(query.strip().split())
        q_upper = q.upper()

        if "SELECT LUP.ID AS LINK_ID" in q_upper and "FOR UPDATE" in q_upper:
            link_id = int(params[0])
            lock_key = f"link_{link_id}"
            # Row-level lock acquisition
            lock = self.db.get_row_lock(lock_key)
            lock.acquire()
            self.conn.locked_keys.append(lock_key)

            with self.db.lock:
                link = self.db.links.get(link_id)
                if not link:
                    self.last_result = None
                    return
                user_key = (link["owner_id"], link["local_username"])
                user = self.db.local_users.get(user_key, {})
                row = {
                    "link_id": link["id"],
                    "last_used_traffic": link["last_used_traffic"],
                    "owner_id": link["owner_id"],
                    "local_username": link["local_username"],
                    "panel_id": link["panel_id"],
                    "manual_disabled": user.get("manual_disabled", 0),
                    "disabled_pushed": user.get("disabled_pushed", 0),
                    "expire_at": user.get("expire_at"),
                }
                self.last_result = row
            return

        if q_upper.startswith("UPDATE LOCAL_USERS"):
            delta = int(params[0])
            owner_id = int(params[1])
            username = params[2]
            with self.db.lock:
                u = self.db.local_users.get((owner_id, username))
                if u:
                    u["used_bytes"] = min(u["used_bytes"] + delta, 18446744073709551615)
            return

        if q_upper.startswith("UPDATE AGENTS"):
            delta = int(params[0])
            tg_id = int(params[1])
            with self.db.lock:
                a = self.db.agents.get(tg_id)
                if a:
                    a["total_used_bytes"] = min(a["total_used_bytes"] + delta, 18446744073709551615)
            return

        if q_upper.startswith("INSERT INTO AGENT_PANEL_USAGE_TOTALS"):
            agent_tg_id = int(params[0])
            panel_id = int(params[1])
            delta = int(params[2])
            with self.db.lock:
                key = (agent_tg_id, panel_id)
                if key not in self.db.agent_panel_totals:
                    self.db.agent_panel_totals[key] = {
                        "agent_tg_id": agent_tg_id,
                        "panel_id": panel_id,
                        "total_used_bytes": delta,
                    }
                else:
                    self.db.agent_panel_totals[key]["total_used_bytes"] = min(
                        self.db.agent_panel_totals[key]["total_used_bytes"] + delta,
                        18446744073709551615,
                    )
            return

        if q_upper.startswith("INSERT INTO AGENT_USAGE_EVENTS"):
            agent_tg_id = int(params[0])
            panel_id = int(params[1])
            delta = int(params[2])
            with self.db.lock:
                ev_id = self.db.next_event_id
                self.db.next_event_id += 1
                self.db.agent_usage_events.append({
                    "id": ev_id,
                    "agent_tg_id": agent_tg_id,
                    "panel_id": panel_id,
                    "delta_bytes": delta,
                })
            return

        if q_upper.startswith("UPDATE LOCAL_USER_PANEL_LINKS"):
            new_val = int(params[0])
            link_id = int(params[1])
            with self.db.lock:
                l = self.db.links.get(link_id)
                if l:
                    l["last_used_traffic"] = new_val
            return

    def fetchone(self):
        return self.last_result

    def fetchall(self):
        return [self.last_result] if self.last_result else []

    def close(self):
        pass


class MockCursorContext:
    def __init__(self, db: MockDatabaseState):
        self.db = db
        self.conn = None
        self.cur = None

    def __enter__(self):
        self.conn = MockConnection(self.db)
        self.cur = MockCursor(self.conn)
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.cur.close()
            self.conn.close()
        return False


class TestTrafficAccounting(unittest.TestCase):
    def setUp(self):
        self.db = MockDatabaseState()
        # Seed test agent
        self.owner_id = 1001
        self.db.agents[self.owner_id] = {
            "telegram_user_id": self.owner_id,
            "total_used_bytes": 0,
        }

    def _make_context(self, *args, **kwargs):
        return MockCursorContext(self.db)

    def test_1_normal_synchronization(self):
        """Test 1: Baseline 10 GB, panel usage 15 GB -> Expected new usage: 5 GB."""
        GB = 1024 ** 3
        username = "alice"
        link_id = 1
        panel_id = 10

        self.db.local_users[(self.owner_id, username)] = {
            "owner_id": self.owner_id,
            "username": username,
            "plan_limit_bytes": 50 * GB,
            "used_bytes": 10 * GB,
            "expire_at": None,
            "manual_disabled": 0,
            "disabled_pushed": 0,
        }
        self.db.links[link_id] = {
            "id": link_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel_id,
            "remote_username": "alice_rem",
            "last_used_traffic": 10 * GB,
        }

        with patch("scripts.usage_sync.with_mysql_cursor", side_effect=self._make_context):
            delta, weighted = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link_id,
                panel_id=panel_id,
                used=15 * GB,
                multiplier=1.0,
            )

        self.assertEqual(delta, 5 * GB)
        self.assertEqual(weighted, 5 * GB)
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 15 * GB)
        self.assertEqual(self.db.links[link_id]["last_used_traffic"], 15 * GB)
        self.assertEqual(self.db.agents[self.owner_id]["total_used_bytes"], 5 * GB)
        self.assertEqual(self.db.agent_panel_totals[(self.owner_id, panel_id)]["total_used_bytes"], 5 * GB)
        self.assertEqual(len(self.db.agent_usage_events), 1)
        self.assertEqual(self.db.agent_usage_events[0]["delta_bytes"], 5 * GB)

    def test_2_repeated_synchronization(self):
        """Test 2: Run the same synchronization twice -> Expected total charge 5 GB, not 10 GB (idempotency)."""
        GB = 1024 ** 3
        username = "bob"
        link_id = 2
        panel_id = 10

        self.db.local_users[(self.owner_id, username)] = {
            "owner_id": self.owner_id,
            "username": username,
            "plan_limit_bytes": 50 * GB,
            "used_bytes": 10 * GB,
            "expire_at": None,
            "manual_disabled": 0,
            "disabled_pushed": 0,
        }
        self.db.links[link_id] = {
            "id": link_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel_id,
            "remote_username": "bob_rem",
            "last_used_traffic": 10 * GB,
        }

        with patch("scripts.usage_sync.with_mysql_cursor", side_effect=self._make_context):
            # First sync
            delta1, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link_id,
                panel_id=panel_id,
                used=15 * GB,
                multiplier=1.0,
            )
            # Repeated sync with same upstream traffic
            delta2, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link_id,
                panel_id=panel_id,
                used=15 * GB,
                multiplier=1.0,
            )

        self.assertEqual(delta1, 5 * GB)
        self.assertEqual(delta2, 0)
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 15 * GB)
        self.assertEqual(self.db.links[link_id]["last_used_traffic"], 15 * GB)

    def test_3_failure_during_accounting(self):
        """Test 3: Failure during accounting rolls back transaction; retry charges only 5 GB."""
        GB = 1024 ** 3
        username = "carol"
        link_id = 3
        panel_id = 10

        self.db.local_users[(self.owner_id, username)] = {
            "owner_id": self.owner_id,
            "username": username,
            "plan_limit_bytes": 50 * GB,
            "used_bytes": 10 * GB,
            "expire_at": None,
            "manual_disabled": 0,
            "disabled_pushed": 0,
        }
        self.db.links[link_id] = {
            "id": link_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel_id,
            "remote_username": "carol_rem",
            "last_used_traffic": 10 * GB,
        }

        call_count = 0

        class FailingCursor(MockCursor):
            def execute(self, query: str, params: tuple = ()):
                nonlocal call_count
                q_upper = query.upper()
                # Simulate failure right after local_users update but before baseline update
                if "UPDATE LOCAL_USER_PANEL_LINKS" in q_upper and call_count == 0:
                    call_count += 1
                    raise RuntimeError("Simulated database connection drop before baseline update")
                super().execute(query, params)

        class FailingContext(MockCursorContext):
            def __enter__(self):
                self.conn = MockConnection(self.db)
                self.cur = FailingCursor(self.conn)
                return self.cur

        with patch("scripts.usage_sync.with_mysql_cursor", side_effect=lambda *a, **k: FailingContext(self.db)):
            with self.assertRaises(RuntimeError):
                usage_sync.record_traffic_delta(
                    owner_id=self.owner_id,
                    local_username=username,
                    link_id=link_id,
                    panel_id=panel_id,
                    used=15 * GB,
                    multiplier=1.0,
                )

        # Verify transaction completely rolled back: local_users and links are unchanged
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 10 * GB)
        self.assertEqual(self.db.links[link_id]["last_used_traffic"], 10 * GB)

        # Retry sync with working connection
        with patch("scripts.usage_sync.with_mysql_cursor", side_effect=self._make_context):
            delta, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link_id,
                panel_id=panel_id,
                used=15 * GB,
                multiplier=1.0,
            )

        self.assertEqual(delta, 5 * GB)
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 15 * GB)
        self.assertEqual(self.db.links[link_id]["last_used_traffic"], 15 * GB)

    def test_4_time_expiration(self):
        """Test 4: User consumes 75 GB, subscription expires, panel reports 75 GB -> Expected local usage remains 75 GB across cycles."""
        GB = 1024 ** 3
        username = "dave"
        link_id = 4
        panel_id = 10

        expired_time = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)

        self.db.local_users[(self.owner_id, username)] = {
            "owner_id": self.owner_id,
            "username": username,
            "plan_limit_bytes": 100 * GB,
            "used_bytes": 75 * GB,
            "expire_at": expired_time,
            "manual_disabled": 0,
            "disabled_pushed": 1,  # Expired & pushed disable to panel
        }
        self.db.links[link_id] = {
            "id": link_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel_id,
            "remote_username": "dave_rem",
            "last_used_traffic": 75 * GB,
        }

        with patch("scripts.usage_sync.with_mysql_cursor", side_effect=self._make_context):
            # Run several synchronization cycles while expired
            for _ in range(5):
                # Even if upstream panel momentarily returned 0 due to disabled status
                delta_zero, _ = usage_sync.record_traffic_delta(
                    owner_id=self.owner_id,
                    local_username=username,
                    link_id=link_id,
                    panel_id=panel_id,
                    used=0,
                    multiplier=1.0,
                )
                self.assertEqual(delta_zero, 0)
                # Baseline must NOT be corrupted to 0!
                self.assertEqual(self.db.links[link_id]["last_used_traffic"], 75 * GB)

                # Upstream reports 75 GB
                delta_normal, _ = usage_sync.record_traffic_delta(
                    owner_id=self.owner_id,
                    local_username=username,
                    link_id=link_id,
                    panel_id=panel_id,
                    used=75 * GB,
                    multiplier=1.0,
                )
                self.assertEqual(delta_normal, 0)

        # Final local usage remains exactly 75 GB, never doubled to 150 GB
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 75 * GB)
        self.assertEqual(self.db.links[link_id]["last_used_traffic"], 75 * GB)

    def test_5_reactivation(self):
        """Test 5: User consumes 75 GB, disabled, extended/reactivated, panel still reports 75 GB -> local usage remains 75 GB."""
        GB = 1024 ** 3
        username = "eve"
        link_id = 5
        panel_id = 10

        self.db.local_users[(self.owner_id, username)] = {
            "owner_id": self.owner_id,
            "username": username,
            "plan_limit_bytes": 100 * GB,
            "used_bytes": 75 * GB,
            "expire_at": None,
            "manual_disabled": 1,
            "disabled_pushed": 1,
        }
        self.db.links[link_id] = {
            "id": link_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel_id,
            "remote_username": "eve_rem",
            "last_used_traffic": 75 * GB,
        }

        with patch("scripts.usage_sync.with_mysql_cursor", side_effect=self._make_context):
            # Sync while disabled
            usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link_id,
                panel_id=panel_id,
                used=75 * GB,
                multiplier=1.0,
            )

            # Reactivate account
            future_time = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)
            self.db.local_users[(self.owner_id, username)]["manual_disabled"] = 0
            self.db.local_users[(self.owner_id, username)]["disabled_pushed"] = 0
            self.db.local_users[(self.owner_id, username)]["expire_at"] = future_time

            # Sync after reactivation
            delta, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link_id,
                panel_id=panel_id,
                used=75 * GB,
                multiplier=1.0,
            )

        self.assertEqual(delta, 0)
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 75 * GB)
        self.assertEqual(self.db.links[link_id]["last_used_traffic"], 75 * GB)

    def test_6_concurrent_synchronization(self):
        """Test 6: Two workers attempt to process the same panel-user link simultaneously -> delta charged exactly once."""
        GB = 1024 ** 3
        username = "frank"
        link_id = 6
        panel_id = 10

        self.db.local_users[(self.owner_id, username)] = {
            "owner_id": self.owner_id,
            "username": username,
            "plan_limit_bytes": 100 * GB,
            "used_bytes": 50 * GB,
            "expire_at": None,
            "manual_disabled": 0,
            "disabled_pushed": 0,
        }
        self.db.links[link_id] = {
            "id": link_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel_id,
            "remote_username": "frank_rem",
            "last_used_traffic": 50 * GB,
        }

        results = []

        def worker_task():
            with patch("scripts.usage_sync.with_mysql_cursor", side_effect=self._make_context):
                d, _ = usage_sync.record_traffic_delta(
                    owner_id=self.owner_id,
                    local_username=username,
                    link_id=link_id,
                    panel_id=panel_id,
                    used=75 * GB,
                    multiplier=1.0,
                )
                results.append(d)

        t1 = threading.Thread(target=worker_task)
        t2 = threading.Thread(target=worker_task)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # One worker should charge 25 GB, the other should charge 0 GB
        self.assertEqual(sorted(results), [0, 25 * GB])
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 75 * GB)
        self.assertEqual(self.db.links[link_id]["last_used_traffic"], 75 * GB)

    def test_7_multiple_panels(self):
        """Test 7: User has two panel links reporting 40 GB and 35 GB -> Expected total: 75 GB, repeated sync does not increase."""
        GB = 1024 ** 3
        username = "grace"
        link1_id = 71
        link2_id = 72
        panel1_id = 11
        panel2_id = 12

        self.db.local_users[(self.owner_id, username)] = {
            "owner_id": self.owner_id,
            "username": username,
            "plan_limit_bytes": 100 * GB,
            "used_bytes": 0,
            "expire_at": None,
            "manual_disabled": 0,
            "disabled_pushed": 0,
        }
        self.db.links[link1_id] = {
            "id": link1_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel1_id,
            "remote_username": "grace_rem1",
            "last_used_traffic": 0,
        }
        self.db.links[link2_id] = {
            "id": link2_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel2_id,
            "remote_username": "grace_rem2",
            "last_used_traffic": 0,
        }

        with patch("scripts.usage_sync.with_mysql_cursor", side_effect=self._make_context):
            # Sync link 1: 40 GB
            d1, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link1_id,
                panel_id=panel1_id,
                used=40 * GB,
                multiplier=1.0,
            )
            # Sync link 2: 35 GB
            d2, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link2_id,
                panel_id=panel2_id,
                used=35 * GB,
                multiplier=1.0,
            )

            # Repeated sync
            d1_rep, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link1_id,
                panel_id=panel1_id,
                used=40 * GB,
                multiplier=1.0,
            )
            d2_rep, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link2_id,
                panel_id=panel2_id,
                used=35 * GB,
                multiplier=1.0,
            )

        self.assertEqual(d1, 40 * GB)
        self.assertEqual(d2, 35 * GB)
        self.assertEqual(d1_rep, 0)
        self.assertEqual(d2_rep, 0)
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 75 * GB)
        self.assertEqual(self.db.links[link1_id]["last_used_traffic"], 40 * GB)
        self.assertEqual(self.db.links[link2_id]["last_used_traffic"], 35 * GB)

    def test_8_weighted_traffic(self):
        """Test 8: Verify multiplier behavior is preserved across local user, agent, and panel stats."""
        GB = 1024 ** 3
        username = "heidi"
        link_id = 8
        panel_id = 15
        multiplier = 1.5

        self.db.local_users[(self.owner_id, username)] = {
            "owner_id": self.owner_id,
            "username": username,
            "plan_limit_bytes": 100 * GB,
            "used_bytes": 0,
            "expire_at": None,
            "manual_disabled": 0,
            "disabled_pushed": 0,
        }
        self.db.links[link_id] = {
            "id": link_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel_id,
            "remote_username": "heidi_rem",
            "last_used_traffic": 0,
        }

        with patch("scripts.usage_sync.with_mysql_cursor", side_effect=self._make_context):
            delta, weighted_delta = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link_id,
                panel_id=panel_id,
                used=10 * GB,
                multiplier=multiplier,
            )

        # Raw delta is 10 GB; weighted delta is 15 GB
        self.assertEqual(delta, 10 * GB)
        self.assertEqual(weighted_delta, 15 * GB)

        # Local user gets weighted delta
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 15 * GB)
        # Agent gets raw delta
        self.assertEqual(self.db.agents[self.owner_id]["total_used_bytes"], 10 * GB)
        # Panel lifetime gets raw delta
        self.assertEqual(self.db.agent_panel_totals[(self.owner_id, panel_id)]["total_used_bytes"], 10 * GB)
        # Event gets raw delta
        self.assertEqual(self.db.agent_usage_events[0]["delta_bytes"], 10 * GB)

    def test_9_counter_reset(self):
        """Test 9: Upstream panel counter reset is not interpreted as negative usage, and historical traffic is not recharged."""
        GB = 1024 ** 3
        username = "ivan"
        link_id = 9
        panel_id = 10

        self.db.local_users[(self.owner_id, username)] = {
            "owner_id": self.owner_id,
            "username": username,
            "plan_limit_bytes": 100 * GB,
            "used_bytes": 75 * GB,
            "expire_at": None,
            "manual_disabled": 0,
            "disabled_pushed": 0,
        }
        self.db.links[link_id] = {
            "id": link_id,
            "owner_id": self.owner_id,
            "local_username": username,
            "panel_id": panel_id,
            "remote_username": "ivan_rem",
            "last_used_traffic": 75 * GB,
        }

        with patch("scripts.usage_sync.with_mysql_cursor", side_effect=self._make_context):
            # Panel counter reset to 0
            delta_reset, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link_id,
                panel_id=panel_id,
                used=0,
                multiplier=1.0,
            )
            # Must not be negative!
            self.assertEqual(delta_reset, 0)
            self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 75 * GB)

            # Panel starts accumulating new usage on new cycle (e.g. 5 GB)
            delta_new, _ = usage_sync.record_traffic_delta(
                owner_id=self.owner_id,
                local_username=username,
                link_id=link_id,
                panel_id=panel_id,
                used=5 * GB,
                multiplier=1.0,
            )

        # Only the new 5 GB is charged; historical 75 GB is NOT recharged!
        self.assertEqual(delta_new, 5 * GB)
        self.assertEqual(self.db.local_users[(self.owner_id, username)]["used_bytes"], 80 * GB)
        self.assertEqual(self.db.links[link_id]["last_used_traffic"], 5 * GB)

    def test_10_reconcile_historical_double_counting(self):
        """Test 10: Reconciliation tool identifies ~2x doubled users and safely restores correct usage."""
        from scripts import reconcile_usage

        GB = 1024 ** 3
        # User 1: Affected by 75 GB -> 150 GB doubling
        user1 = "affected_user"
        # User 2: Normal user (75 GB used, 75 GB expected)
        user2 = "normal_user"

        affected_records = [
            {
                "user_id": 1,
                "owner_id": self.owner_id,
                "username": user1,
                "plan_limit_bytes": 100 * GB,
                "current_used_bytes": 150 * GB,
                "expected_used_bytes": 75 * GB,
                "excess_bytes": 75 * GB,
                "ratio": 2.0,
                "link_count": 1,
                "status": "DOUBLED",
            },
            {
                "user_id": 2,
                "owner_id": self.owner_id,
                "username": user2,
                "plan_limit_bytes": 100 * GB,
                "current_used_bytes": 75 * GB,
                "expected_used_bytes": 75 * GB,
                "excess_bytes": 0,
                "ratio": 1.0,
                "link_count": 1,
                "status": "OK",
            },
        ]

        self.db.local_users[(self.owner_id, user1)] = {
            "owner_id": self.owner_id,
            "username": user1,
            "plan_limit_bytes": 100 * GB,
            "used_bytes": 150 * GB,
        }
        self.db.local_users[(self.owner_id, user2)] = {
            "owner_id": self.owner_id,
            "username": user2,
            "plan_limit_bytes": 100 * GB,
            "used_bytes": 75 * GB,
        }

        class ReconcileCursor(MockCursor):
            def execute(self, query: str, params: tuple = ()):
                q_upper = query.upper()
                if "UPDATE LOCAL_USERS" in q_upper and "SET USED_BYTES = %S" in q_upper:
                    new_used = int(params[0])
                    owner_id = int(params[1])
                    uname = params[2]
                    self.db.local_users[(owner_id, uname)]["used_bytes"] = new_used
                    return
                if "UPDATE AGENTS" in q_upper and "SET TOTAL_USED_BYTES = (" in q_upper:
                    oid = int(params[1])
                    tot = sum(u["used_bytes"] for (o, _), u in self.db.local_users.items() if o == oid)
                    self.db.agents[oid]["total_used_bytes"] = tot
                    return
                super().execute(query, params)

        class ReconcileContext(MockCursorContext):
            def __enter__(self):
                self.conn = MockConnection(self.db)
                self.cur = ReconcileCursor(self.conn)
                return self.cur

        with patch("scripts.reconcile_usage.with_mysql_cursor", side_effect=lambda *a, **k: ReconcileContext(self.db)):
            fixed = reconcile_usage.apply_reconciliation(affected_records, only_doubled=True)

        self.assertEqual(fixed, 1)
        # affected_user reconciled to 75 GB
        self.assertEqual(self.db.local_users[(self.owner_id, user1)]["used_bytes"], 75 * GB)
        # normal_user remains 75 GB
        self.assertEqual(self.db.local_users[(self.owner_id, user2)]["used_bytes"], 75 * GB)
        # Agent total updated to sum (75 + 75 = 150 GB)
        self.assertEqual(self.db.agents[self.owner_id]["total_used_bytes"], 150 * GB)


if __name__ == "__main__":
    unittest.main()
