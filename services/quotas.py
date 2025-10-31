"""Agent quota management helpers."""
from __future__ import annotations

import logging

from scripts import usage_sync

from .database import with_mysql_cursor

log = logging.getLogger(__name__)


def set_agent_quota(tg_id: int, limit_bytes: int) -> None:
    with with_mysql_cursor() as cur:
        cur.execute(
            "UPDATE agents SET plan_limit_bytes=%s WHERE telegram_user_id=%s",
            (int(limit_bytes), tg_id),
        )
    try:
        usage_sync.sync_agent_now(tg_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        log.warning("sync_agent_now failed for %s: %s", tg_id, exc)


def set_agent_user_limit(tg_id: int, max_users: int) -> None:
    with with_mysql_cursor() as cur:
        cur.execute(
            "UPDATE agents SET user_limit=%s WHERE telegram_user_id=%s",
            (int(max_users), tg_id),
        )


def set_agent_max_user_bytes(tg_id: int, max_bytes: int) -> None:
    with with_mysql_cursor() as cur:
        cur.execute(
            "UPDATE agents SET max_user_bytes=%s WHERE telegram_user_id=%s",
            (int(max_bytes), tg_id),
        )


def renew_agent_days(tg_id: int, add_days: int) -> None:
    with with_mysql_cursor() as cur:
        cur.execute("SELECT expire_at FROM agents WHERE telegram_user_id=%s", (tg_id,))
        row = cur.fetchone()
        if row and row.get("expire_at"):
            cur.execute(
                "UPDATE agents SET expire_at = expire_at + INTERVAL %s DAY WHERE telegram_user_id=%s",
                (add_days, tg_id),
            )
        else:
            cur.execute(
                "UPDATE agents SET expire_at = UTC_TIMESTAMP() + INTERVAL %s DAY WHERE telegram_user_id=%s",
                (add_days, tg_id),
            )


def set_agent_active(tg_id: int, active: bool) -> None:
    with with_mysql_cursor() as cur:
        cur.execute(
            "UPDATE agents SET active=%s WHERE telegram_user_id=%s",
            (1 if active else 0, tg_id),
        )


__all__ = [
    "set_agent_quota",
    "set_agent_user_limit",
    "set_agent_max_user_bytes",
    "renew_agent_days",
    "set_agent_active",
]
