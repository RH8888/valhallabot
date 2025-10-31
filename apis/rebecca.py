#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebecca panel API helpers mirroring :mod:`apis.marzban`."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import marzban as _marzban

SESSION = _marzban.SESSION
ALLOWED_SCHEMES = _marzban.ALLOWED_SCHEMES
FETCH_CACHE_TTL = _marzban.FETCH_CACHE_TTL


def get_headers(token: str) -> Dict[str, str]:
    """Return authorization headers for the given bearer token."""

    return _marzban.get_headers(token)


def fetch_user_services(panel_url: str, token: str, username: str) -> Tuple[Optional[List[int]], Optional[str]]:
    """Return services for *username*.

    Rebecca panels behave like Marzban panels and do not expose service IDs,
    so the function returns an empty list.
    """

    return _marzban.fetch_user_services(panel_url, token, username)


def create_user(panel_url: str, token: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    """Create a user on the Rebecca panel."""

    return _marzban.create_user(panel_url, token, payload)


def get_user(panel_url: str, token: str, username: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Fetch user details from the Rebecca panel."""

    return _marzban.get_user(panel_url, token, username)


@_marzban.cached(cache=_marzban._links_cache, lock=_marzban._links_lock)
def fetch_links_from_panel(panel_url: str, username: str, key: str) -> List[str]:
    """Return subscription links for the given user key."""

    return _marzban.fetch_links_from_panel(panel_url, username, key)


def disable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Disable a Rebecca user on the panel."""

    return _marzban.disable_remote_user(panel_url, token, username)


def enable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Enable a Rebecca user on the panel."""

    return _marzban.enable_remote_user(panel_url, token, username)


def remove_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Remove a Rebecca user from the panel."""

    return _marzban.remove_remote_user(panel_url, token, username)


def reset_remote_user_usage(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Reset usage counters for a Rebecca user."""

    return _marzban.reset_remote_user_usage(panel_url, token, username)


def update_remote_user(
    panel_url: str,
    token: str,
    username: str,
    data_limit: Optional[int] = None,
    expire: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """Update quota or expiry for a Rebecca user."""

    return _marzban.update_remote_user(panel_url, token, username, data_limit, expire)


def fetch_subscription_links(sub_url: str) -> List[str]:
    """Return subscription links for a Rebecca user."""

    return _marzban.fetch_subscription_links(sub_url)


def get_admin_token(panel_url: str, username: str, password: str) -> Tuple[Optional[str], Optional[str]]:
    """Return an API token for a Rebecca administrator."""

    return _marzban.get_admin_token(panel_url, username, password)


__all__ = [
    "SESSION",
    "ALLOWED_SCHEMES",
    "FETCH_CACHE_TTL",
    "get_headers",
    "fetch_user_services",
    "create_user",
    "get_user",
    "fetch_links_from_panel",
    "disable_remote_user",
    "enable_remote_user",
    "remove_remote_user",
    "reset_remote_user_usage",
    "update_remote_user",
    "fetch_subscription_links",
    "get_admin_token",
]
