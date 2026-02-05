#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helper functions for interacting with Guardcore panel API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse

import base64
import os
import time
from threading import RLock

import requests
from cachetools import TTLCache, cached

SESSION = requests.Session()
ALLOWED_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://")

FETCH_CACHE_TTL = int(os.getenv("FETCH_CACHE_TTL", "300"))
_links_cache = TTLCache(maxsize=256, ttl=FETCH_CACHE_TTL)
_links_lock = RLock()


def get_headers(token: str) -> Dict[str, str]:
    """Return authorization headers for Guardcore requests.

    This app authenticates via OAuth2 password bearer tokens obtained from
    ``/api/admins/token``. To use an API key instead, prefix the stored token
    with ``api_key:`` so it is sent as ``X-API-Key``.
    """

    if not token:
        return {}
    token_str = str(token).strip()
    lowered = token_str.lower()
    if lowered.startswith("api_key:") or lowered.startswith("apikey:") or lowered.startswith("x-api-key:"):
        return {"X-API-Key": token_str.split(":", 1)[1].strip()}
    if lowered.startswith("bearer "):
        return {"Authorization": token_str}
    return {"Authorization": f"Bearer {token_str}"}


def _build_api_url(panel_url: str, *segments: object) -> str:
    """Return a fully-qualified Guardcore API URL for *segments*."""

    cleaned_segments: List[str] = []
    for seg in segments:
        if seg is None:
            continue
        part = str(seg).strip("/")
        if not part:
            continue
        cleaned_segments.append(quote(part, safe=""))
    cleaned = "/".join(cleaned_segments)
    return urljoin(panel_url.rstrip("/") + "/", cleaned)


def _coerce_int(value: object) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalise_service_ids(value: object) -> List[int]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [int(v) for v in value if isinstance(v, (int, float, str)) and str(v).strip().isdigit()]
    if isinstance(value, str):
        parts = [p.strip() for p in value.split(",") if p.strip()]
        return [int(p) for p in parts if p.isdigit()]
    try:
        return [int(value)]
    except (TypeError, ValueError):
        return []


def _normalise_limit_expire(value: object) -> Optional[int]:
    """Return Guardcore-compatible UNIX seconds for ``limit_expire``.

    Guardcore validates ``limit_expire`` as a future UNIX timestamp (UTC).
    Bot payloads may provide either absolute timestamps or duration seconds,
    so this helper normalises both into a valid future timestamp.
    """

    limit_expire = _coerce_int(value)
    if limit_expire is None:
        return None

    now_ts = int(time.time())

    # Accept milliseconds as input and convert to seconds.
    if limit_expire > 10_000_000_000:
        limit_expire //= 1000

    # If value is not already a future timestamp, treat it as duration seconds.
    if limit_expire <= now_ts:
        limit_expire = now_ts + limit_expire

    # Guardcore requires a timestamp strictly in the future.
    if limit_expire <= now_ts:
        limit_expire = now_ts + 1

    return limit_expire


def _prepare_subscription_payload(payload: Mapping[str, object]) -> Dict[str, object]:
    """Translate a bot payload into Guardcore's SubscriptionCreate schema."""

    body: Dict[str, object] = {}
    username = payload.get("username")
    if username:
        body["username"] = username

    limit_usage = _coerce_int(payload.get("limit_usage"))
    if limit_usage is None:
        limit_usage = _coerce_int(payload.get("data_limit"))
    if limit_usage is None:
        limit_usage = _coerce_int(payload.get("data_limit_bytes"))
    body["limit_usage"] = limit_usage if limit_usage is not None else 0

    limit_expire = _normalise_limit_expire(payload.get("limit_expire"))
    if limit_expire is None:
        limit_expire = _normalise_limit_expire(payload.get("expire"))
    body["limit_expire"] = limit_expire if limit_expire is not None else int(time.time()) + 1

    service_ids = payload.get("service_ids")
    if service_ids is None and payload.get("service_id") is not None:
        service_ids = [payload.get("service_id")]
    body["service_ids"] = _normalise_service_ids(service_ids)

    for key in (
        "access_key",
        "note",
        "telegram_id",
        "discord_webhook_url",
        "auto_delete_days",
        "auto_renewals",
    ):
        value = payload.get(key)
        if value is not None:
            body[key] = value
    return body


def _prepare_subscription_update(data: Mapping[str, object]) -> Dict[str, object]:
    """Translate a bot payload into Guardcore's SubscriptionUpdate schema."""

    body: Dict[str, object] = {}
    limit_usage = _coerce_int(data.get("limit_usage"))
    if limit_usage is None:
        limit_usage = _coerce_int(data.get("data_limit"))
    if limit_usage is None:
        limit_usage = _coerce_int(data.get("data_limit_bytes"))
    if limit_usage is not None:
        body["limit_usage"] = limit_usage

    limit_expire = _normalise_limit_expire(data.get("limit_expire"))
    if limit_expire is None:
        limit_expire = _normalise_limit_expire(data.get("expire"))
    if limit_expire is not None:
        body["limit_expire"] = limit_expire

    if data.get("service_ids") is not None or data.get("service_id") is not None:
        service_ids = data.get("service_ids")
        if service_ids is None:
            service_ids = [data.get("service_id")]
        body["service_ids"] = _normalise_service_ids(service_ids)

    for key in (
        "note",
        "telegram_id",
        "discord_webhook_url",
        "auto_delete_days",
        "auto_renewals",
    ):
        if key in data and data[key] is not None:
            body[key] = data[key]
    return body


def _normalise_subscription(obj: Dict[str, object]) -> Dict[str, object]:
    """Normalise Guardcore subscription objects for the bot."""

    if not isinstance(obj, dict):
        return obj
    access_key = obj.get("access_key")
    link = obj.get("link")
    if link:
        obj.setdefault("subscription_url", link)
    if access_key and not obj.get("key"):
        obj["key"] = link or access_key

    # Usage sync expects a unified "used_traffic" counter across panels.
    # Guardcore returns usage as total_usage/current_usage, so map those
    # fields explicitly to avoid silent 0-byte accounting.
    used_traffic = _coerce_int(obj.get("used_traffic"))
    if used_traffic is None:
        used_traffic = _coerce_int(obj.get("total_usage"))
    if used_traffic is None:
        used_traffic = _coerce_int(obj.get("current_usage"))
    if used_traffic is not None:
        obj["used_traffic"] = max(used_traffic, 0)

    return obj


def fetch_user_services(panel_url: str, token: str, username: str) -> Tuple[Optional[List[int]], Optional[str]]:
    """Return list of service IDs for *username* or an error message."""

    obj, err = get_user(panel_url, token, username)
    if err or not obj:
        return None, err or "subscription not found"
    service_ids = obj.get("service_ids") if isinstance(obj, dict) else None
    if service_ids is None:
        return [], None
    return _normalise_service_ids(service_ids), None


def create_user(panel_url: str, token: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    """Create a subscription on the remote panel."""

    try:
        body = _prepare_subscription_payload(payload)
        if not body.get("username"):
            return None, "missing username"
        # Guardcore expects an array of SubscriptionCreate objects, even for
        # single-user creation.
        r = SESSION.post(
            _build_api_url(panel_url, "api", "subscriptions"),
            json=[body],
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code in (200, 201):
            data = r.json()
            if isinstance(data, list):
                if not data:
                    return None, "empty response from panel"
                first = data[0]
                if isinstance(first, dict):
                    return _normalise_subscription(first), None
                return {"result": first}, None
            if isinstance(data, dict):
                return _normalise_subscription(data), None
            return data, None
        return None, f"{r.status_code} {r.text[:300]}"
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]


def get_user(panel_url: str, token: str, username: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Fetch subscription details from the panel."""

    try:
        r = SESSION.get(
            _build_api_url(panel_url, "api", "subscriptions", username),
            headers=get_headers(token),
            timeout=15,
        )
        if r.status_code != 200:
            return None, f"{r.status_code} {r.text[:200]}"
        obj = r.json()
        if isinstance(obj, dict):
            _normalise_subscription(obj)
        return obj, None
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]


def _extract_links_from_text(text: str) -> List[str]:
    lines = [
        ln.strip()
        for ln in (text or "").splitlines()
        if ln.strip() and ln.strip().lower().startswith(ALLOWED_SCHEMES)
    ]
    if lines:
        return lines
    stripped = (text or "").strip()
    if not stripped:
        return []
    padding = "=" * (-len(stripped) % 4)
    try:
        decoded = base64.b64decode(stripped + padding)
    except Exception:
        return []
    try:
        decoded_text = decoded.decode()
    except Exception:
        decoded_text = decoded.decode(errors="ignore")
    return [
        ln.strip()
        for ln in decoded_text.splitlines()
        if ln.strip() and ln.strip().lower().startswith(ALLOWED_SCHEMES)
    ]


def fetch_subscription_links(sub_url: str) -> List[str]:
    """Return links from a subscription URL."""

    try:
        r = SESSION.get(sub_url, headers={"accept": "text/plain,application/json"}, timeout=20)
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                data = r.json()
            except Exception:
                data = None
            if isinstance(data, list):
                return [str(x) for x in data]
            if isinstance(data, dict) and "links" in data:
                return [str(x) for x in data["links"]]
        return _extract_links_from_text(r.text or "")
    except Exception:  # pragma: no cover - network errors
        return []


@cached(cache=_links_cache, lock=_links_lock)
def fetch_links_from_panel(panel_url: str, username: str, key: str) -> List[str]:
    """Return subscription links for a Guardcore user."""

    sub_url = None
    if isinstance(key, str) and key.strip():
        candidate = key.strip()
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"}:
            sub_url = candidate
        elif candidate.startswith("/"):
            sub_url = urljoin(panel_url.rstrip("/") + "/", candidate.lstrip("/"))
    if not sub_url:
        return []
    return fetch_subscription_links(sub_url)


def disable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Disable a subscription on the panel."""

    try:
        r = SESSION.post(
            _build_api_url(panel_url, "api", "subscriptions", "disable"),
            json={"usernames": [username]},
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def enable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Enable a subscription on the panel."""

    try:
        r = SESSION.post(
            _build_api_url(panel_url, "api", "subscriptions", "enable"),
            json={"usernames": [username]},
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def remove_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Delete a subscription on the panel."""

    try:
        r = SESSION.delete(
            _build_api_url(panel_url, "api", "subscriptions"),
            json={"usernames": [username]},
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code in (200, 204, 404):
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def reset_remote_user_usage(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Reset traffic statistics for *username* on the panel."""

    try:
        r = SESSION.post(
            _build_api_url(panel_url, "api", "subscriptions", "reset"),
            json={"usernames": [username]},
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def update_remote_user(
    panel_url: str,
    token: str,
    username: str,
    data_limit: Optional[int] = None,
    expire: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """Update quota or expiry for *username* on the panel."""

    payload: Dict[str, object] = {}
    if data_limit is not None:
        payload["data_limit"] = int(data_limit)
    if expire is not None:
        payload["expire"] = int(expire)
    body = _prepare_subscription_update(payload)
    if not body:
        return True, None
    try:
        r = SESSION.put(
            _build_api_url(panel_url, "api", "subscriptions", username),
            json=body,
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def get_admin_token(panel_url: str, username: str, password: str) -> Tuple[Optional[str], Optional[str]]:
    """Authenticate against the panel and return an access token."""

    token_url = _build_api_url(panel_url, "api", "admins", "token")
    try:
        resp = SESSION.post(
            token_url,
            data={"username": username, "password": password, "grant_type": "password"},
            timeout=15,
        )
        if resp.status_code != 200:
            return None, f"{resp.status_code} {resp.text[:200]}"
        tok = (resp.json() or {}).get("access_token")
        if not tok:
            return None, "no access_token"
        return tok, None
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]


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
