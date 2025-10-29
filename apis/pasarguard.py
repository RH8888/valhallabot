#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helper functions for interacting with Pasarguard panel API."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin

import base64
import os
from threading import RLock

import requests
from cachetools import TTLCache, cached

SESSION = requests.Session()
ALLOWED_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://")

FETCH_CACHE_TTL = int(os.getenv("FETCH_CACHE_TTL", "300"))
_links_cache = TTLCache(maxsize=256, ttl=FETCH_CACHE_TTL)
_links_lock = RLock()


def get_headers(token: str) -> Dict[str, str]:
    """Return authorization header for the given bearer token."""
    return {"Authorization": f"Bearer {token}"}


def _build_api_url(panel_url: str, *segments: object) -> str:
    """Return a fully-qualified Pasarguard API URL for *segments*.

    The OpenAPI specification in ``docs/pasarguard.json`` defines endpoints
    relative to the ``/api`` prefix (for example, ``DELETE /api/user/{username}``
    for removing a user).  ``requests`` does not automatically escape path
    segments, so usernames containing characters such as ``+`` or ``@`` would be
    misinterpreted by the panel when interpolated directly into an f-string.

    ``quote`` ensures every path segment is URL-safe before the join, matching
    the documented endpoints exactly.
    """

    cleaned_segments = []
    for seg in segments:
        if seg is None:
            continue
        part = str(seg).strip("/")
        if not part:
            continue
        cleaned_segments.append(quote(part, safe=""))
    cleaned = "/".join(cleaned_segments)
    return urljoin(panel_url.rstrip("/") + "/", cleaned)


def _normalise_proxy_settings(candidate: object) -> Dict[str, Any]:
    """Return a plain dict copy of Pasarguard proxy settings."""

    if not isinstance(candidate, Mapping):
        return {}

    normalised: Dict[str, Any] = {}
    for proto, settings in candidate.items():
        if isinstance(settings, Mapping):
            normalised[str(proto)] = dict(settings)
        else:
            normalised[str(proto)] = settings
    return normalised


def _prepare_user_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Translate the bot payload to Pasarguard's UserCreate/UserModify schema."""

    if not isinstance(payload, Mapping):
        return {}

    body: Dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if key == "proxies":
            body["proxy_settings"] = _normalise_proxy_settings(value)
        elif key == "proxy_settings":
            body["proxy_settings"] = _normalise_proxy_settings(value)
        elif key == "inbounds":
            # Pasarguard does not expose inbounds on the user schema; they map to
            # node-side configuration.  Ignore them for API requests.
            continue
        else:
            body[key] = value
    return body


def _normalise_user_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise Pasarguard user payloads for the bot."""

    status = (obj.get("status") or "").lower()
    obj["enabled"] = status in {"active", "limited"}
    proxies = obj.get("proxy_settings")
    if proxies:
        obj.setdefault("proxies", _normalise_proxy_settings(proxies))
    obj.setdefault("inbounds", {})
    groups = obj.get("group_ids")
    if groups is None:
        obj["group_ids"] = []
    elif isinstance(groups, Iterable) and not isinstance(groups, (str, bytes, bytearray)):
        obj["group_ids"] = list(groups)
    else:
        obj["group_ids"] = [groups]
    return obj


def fetch_user_services(
    panel_url: str, token: str, username: str
) -> Tuple[Optional[List[int]], Optional[str]]:
    """Pasarguard does not expose service IDs; return an empty list."""
    return [], None


def create_user(panel_url: str, token: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    """Create a user on the remote panel."""
    try:
        body = _prepare_user_payload(payload)
        r = SESSION.post(
            _build_api_url(panel_url, "api", "user"),
            json=body,
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code in (200, 201):
            data = r.json()
            if isinstance(data, dict):
                return _normalise_user_object(data), None
            return data, None
        return None, f"{r.status_code} {r.text[:300]}"
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]


def get_user(panel_url: str, token: str, username: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Fetch user details from the panel."""
    try:
        r = SESSION.get(
            _build_api_url(panel_url, "api", "user", username),
            headers=get_headers(token),
            timeout=15,
        )
        if r.status_code != 200:
            return None, f"{r.status_code} {r.text[:200]}"
        obj = r.json()
        if isinstance(obj, dict):
            _normalise_user_object(obj)
            sub_url = obj.get("subscription_url") or ""
            token_part = sub_url.rstrip("/").split("/")[-1]
            if token_part:
                obj.setdefault("key", token_part)
        return obj, None
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]


def _extract_links(candidate: object) -> List[str]:
    """Recursively extract subscription links from JSON structures."""
    links: List[str] = []
    if isinstance(candidate, str):
        val = candidate.strip()
        if val and val.lower().startswith(ALLOWED_SCHEMES):
            links.append(val)
    elif isinstance(candidate, Mapping):
        for item in candidate.values():
            links.extend(_extract_links(item))
    elif isinstance(candidate, Iterable) and not isinstance(candidate, (bytes, bytearray)):
        for item in candidate:
            links.extend(_extract_links(item))
    return links


def _extract_links_from_text(text: str) -> List[str]:
    """Return subscription links from newline-separated or base64 payloads."""

    lines = [
        ln.strip()
        for ln in (text or "").splitlines()
        if ln.strip() and ln.strip().lower().startswith(ALLOWED_SCHEMES)
    ]
    if lines:
        return lines

    if not text:
        return []

    stripped = text.strip()
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


@cached(cache=_links_cache, lock=_links_lock)
def fetch_links_from_panel(panel_url: str, _username: str, key: str) -> List[str]:
    """Return list of subscription links for a user token."""
    def _parse_response(resp: requests.Response) -> List[str]:
        if resp.status_code != 200:
            return []
        if resp.headers.get("content-type", "").startswith("application/json"):
            try:
                data = resp.json()
            except Exception:
                data = None
            if data is not None:
                links = _extract_links(data)
                if links:
                    return links
        return _extract_links_from_text(resp.text or "")

    key = (key or "").strip()
    if not key:
        return []

    try:
        paths = [
            ("sub", key, "links", False),
            ("sub", key, "links_base64", False),
            ("sub", key, None, True),
            ("sub", key, "info", False),
            ("sub", key, "apps", False),
        ]

        for *segments, needs_trailing_slash in paths:
            url = _build_api_url(panel_url, *segments)
            if needs_trailing_slash:
                url = url.rstrip("/") + "/"
            try:
                resp = SESSION.get(
                    url,
                    headers={"accept": "application/json,text/plain"},
                    timeout=20,
                )
            except Exception:
                continue
            links = _parse_response(resp)
            if links:
                return links
        return []
    except Exception:  # pragma: no cover - network errors
        return []


def disable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Disable a user on the panel."""
    try:
        r = SESSION.put(
            _build_api_url(panel_url, "api", "user", username),
            json={"status": "disabled"},
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def enable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Enable a user on the panel."""
    try:
        r = SESSION.put(
            _build_api_url(panel_url, "api", "user", username),
            json={"status": "active"},
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def remove_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Delete a user on the panel."""
    try:
        r = SESSION.delete(
            _build_api_url(panel_url, "api", "user", username),
            headers={**get_headers(token), "Accept": "application/json"},
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
            _build_api_url(panel_url, "api", "user", username, "reset"),
            headers=get_headers(token),
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
        payload["data_limit_reset_strategy"] = "no_reset"
    if expire is not None:
        payload["expire"] = int(expire)
    if not payload:
        return True, None
    try:
        body = _prepare_user_payload(payload)
        r = SESSION.put(
            _build_api_url(panel_url, "api", "user", username),
            json=body,
            headers={**get_headers(token), "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def fetch_subscription_links(sub_url: str) -> List[str]:
    """Return links from a subscription URL."""
    try:
        r = SESSION.get(
            sub_url,
            headers={"accept": "text/plain,application/json"},
            timeout=20,
        )
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                data = r.json()
            except Exception:
                data = None
            if data is not None:
                links = _extract_links(data)
                if links:
                    return links
        return _extract_links_from_text(r.text or "")
    except Exception:  # pragma: no cover - network errors
        return []


def get_admin_token(panel_url: str, username: str, password: str) -> Tuple[Optional[str], Optional[str]]:
    """Authenticate against the panel and return an access token."""
    token_url = urljoin(panel_url.rstrip("/") + "/", "api/admin/token")
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
