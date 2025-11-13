"""Agent quota management helpers."""
from __future__ import annotations

import logging

from scripts import usage_sync

from .repository import get_repository

log = logging.getLogger(__name__)


def set_agent_quota(tg_id: int, limit_bytes: int) -> None:
    repository = get_repository()
    repository.set_agent_quota(tg_id, limit_bytes)
    try:
        usage_sync.sync_agent_now(tg_id)
    except Exception as exc:  # pragma: no cover - defensive logging
        log.warning("sync_agent_now failed for %s: %s", tg_id, exc)


def set_agent_user_limit(tg_id: int, max_users: int) -> None:
    repository = get_repository()
    repository.set_agent_user_limit(tg_id, max_users)


def set_agent_max_user_bytes(tg_id: int, max_bytes: int) -> None:
    repository = get_repository()
    repository.set_agent_max_user_bytes(tg_id, max_bytes)


def renew_agent_days(tg_id: int, add_days: int) -> None:
    repository = get_repository()
    repository.renew_agent_days(tg_id, add_days)


def set_agent_active(tg_id: int, active: bool) -> None:
    repository = get_repository()
    repository.set_agent_active(tg_id, active)


__all__ = [
    "set_agent_quota",
    "set_agent_user_limit",
    "set_agent_max_user_bytes",
    "renew_agent_days",
    "set_agent_active",
]
