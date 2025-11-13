"""Token management helpers extracted from the bot layer."""
from __future__ import annotations

from typing import Optional

from models.admins import get_admin_token as _get_admin_token, rotate_admin_token as _rotate_admin_token
from models.agents import get_api_token, rotate_api_token

from .repository import get_repository


def get_agent_record(tg_id: int) -> Optional[dict]:
    """Return the agent database record by Telegram ID."""
    repository = get_repository()
    return repository.get_agent_by_telegram_id(tg_id)


def get_agent_token_value(agent_db_id: int) -> str:
    """Return the decrypted token for the agent, minting one if missing."""
    return get_api_token(agent_db_id)


def rotate_agent_token_value(agent_db_id: int) -> str:
    """Rotate and return a new token for the agent."""
    return rotate_api_token(agent_db_id)


def get_admin_token() -> Optional[str]:
    """Return the current administrator API token if configured."""
    return _get_admin_token()


def rotate_admin_token() -> str:
    """Generate and persist a new administrator API token."""
    return _rotate_admin_token()


__all__ = [
    "get_agent_record",
    "get_agent_token_value",
    "rotate_agent_token_value",
    "get_admin_token",
    "rotate_admin_token",
]
