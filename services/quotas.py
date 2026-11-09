"""Agent quota management helpers."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from scripts import usage_sync

from .database import with_mysql_cursor

log = logging.getLogger(__name__)


def calculate_renewal_expire_at(
    current_expire_at: datetime | None,
    duration: int | timedelta,
    now: datetime | None = None,
) -> datetime:
    """Calculate the new expiration datetime for a subscription renewal.

    If current_expire_at is None or has already expired (current_expire_at <= now),
    the new expiration extends from `now`.
    Otherwise, if the subscription is still active (current_expire_at > now),
    the new expiration extends from `current_expire_at`.

    In other words: max(current_expire_at, now) + purchased_duration.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    delta = duration if isinstance(duration, timedelta) else timedelta(days=duration)

    if current_expire_at is None:
        return now + delta

    # If comparing timezone-aware and naive datetimes, normalize to match current_expire_at
    if current_expire_at.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    elif current_expire_at.tzinfo is None and now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)

    base = max(current_expire_at, now)
    return base + delta


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
        cur.execute(
            """UPDATE agents
               SET expire_at = IF(expire_at IS NULL OR expire_at < UTC_TIMESTAMP(),
                                  UTC_TIMESTAMP() + INTERVAL %s DAY,
                                  expire_at + INTERVAL %s DAY)
               WHERE telegram_user_id=%s""",
            (add_days, add_days, tg_id),
        )


def set_agent_active(tg_id: int, active: bool) -> None:
    with with_mysql_cursor() as cur:
        cur.execute(
            "UPDATE agents SET active=%s WHERE telegram_user_id=%s",
            (1 if active else 0, tg_id),
        )


__all__ = [
    "calculate_renewal_expire_at",
    "set_agent_quota",
    "set_agent_user_limit",
    "set_agent_max_user_bytes",
    "renew_agent_days",
    "set_agent_active",
]
