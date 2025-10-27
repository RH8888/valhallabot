#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helper functions for interacting with Pasarguard panel API."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import base64
import json
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


def _normalise_group_ids(candidate: object) -> List[int]:
    """Return a list of unique group IDs extracted from *candidate*."""

    def _to_int(value: object) -> Optional[int]:
        if isinstance(value, bool):  # pragma: no cover - guard against bool/int confusion
            return None
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    if isinstance(candidate, Iterable) and not isinstance(candidate, (str, bytes, bytearray, Mapping)):
        seen: set[int] = set()
        result: List[int] = []
        for item in candidate:
            val = _to_int(item)
            if val is None or val in seen:
                continue
            seen.add(val)
            result.append(val)
        return result

    val = _to_int(candidate)
    if val is None:
        return []
    return [val]


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
        elif key == "group_ids":
            body["group_ids"] = _normalise_group_ids(value)
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
    obj["group_ids"] = _normalise_group_ids(obj.get("group_ids"))
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
            urljoin(panel_url.rstrip("/") + "/", "api/user"),
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
            urljoin(panel_url.rstrip("/") + "/", f"api/user/{username}"),
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


def _extract_links_from_string(raw: str) -> List[str]:
    """Return subscription links encoded in *raw* string."""

    if not isinstance(raw, str):
        return []

    val = raw.strip()
    if not val:
        return []

    if val.startswith("{") or val.startswith("["):
        try:
            data = json.loads(val)
        except Exception:
            pass
        else:
            return _extract_links(data)

    if val.lower().startswith(ALLOWED_SCHEMES):
        return [val]

    try:
        decoded = base64.b64decode(val + "===")
    except Exception:
        return []

    try:
        text = decoded.decode(errors="ignore")
    except Exception:
        return []

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [ln for ln in lines if ln.lower().startswith(ALLOWED_SCHEMES)]


def _extract_links(candidate: object) -> List[str]:
    """Recursively extract subscription links from JSON structures."""

    if isinstance(candidate, str):
        return _extract_links_from_string(candidate)

    links: List[str] = []
    if isinstance(candidate, Mapping):
        for item in candidate.values():
            links.extend(_extract_links(item))
    elif isinstance(candidate, Iterable) and not isinstance(candidate, (bytes, bytearray)):
        for item in candidate:
            links.extend(_extract_links(item))
    return links


def _links_from_response(resp: requests.Response) -> List[str]:
    """Extract configuration links from an HTTP response."""

    if resp.headers.get("content-type", "").startswith("application/json"):
        try:
            data = resp.json()
        except Exception:
            data = None
        if data is not None:
            links = _extract_links(data)
            if links:
                return links
    return _extract_links_from_string(resp.text or "")


@cached(cache=_links_cache, lock=_links_lock)
def fetch_links_from_panel(panel_url: str, username: str, key: str) -> List[str]:
    """Return list of subscription links for a user token."""
    try:
        for suffix in (
            f"sub/{key}/links_base64",
            f"sub/{key}/links",
            f"sub/{key}/xray",
            f"sub/{key}/",
        ):
            url = urljoin(panel_url.rstrip("/") + "/", suffix)
            r = SESSION.get(
                url,
                headers={"accept": "application/json,text/plain"},
                timeout=20,
            )
            if r.status_code != 200:
                continue
            links = _links_from_response(r)
            if links:
                return links
        return []
    except Exception:  # pragma: no cover - network errors
        return []


def disable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Disable a user on the panel."""
    try:
        r = SESSION.put(
            urljoin(panel_url.rstrip("/") + "/", f"api/user/{username}"),
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
            urljoin(panel_url.rstrip("/") + "/", f"api/user/{username}"),
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
            urljoin(panel_url.rstrip("/") + "/", f"api/user/{username}"),
            headers=get_headers(token),
            timeout=20,
        )
        if r.status_code in (200, 204):
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def reset_remote_user_usage(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Reset traffic statistics for *username* on the panel."""
    try:
        r = SESSION.post(
            urljoin(panel_url.rstrip("/") + "/", f"api/user/{username}/reset"),
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
            urljoin(panel_url.rstrip("/") + "/", f"api/user/{username}"),
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
        if r.status_code != 200:
            return []
        return _links_from_response(r)
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
