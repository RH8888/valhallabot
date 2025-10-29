#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helper functions for interacting with Pasarguard panel API."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

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


@cached(cache=_links_cache, lock=_links_lock)
def fetch_links_from_panel(panel_url: str, username: str, key: str) -> List[str]:
    """Return list of subscription links for a user token."""
    try:
        url = urljoin(panel_url.rstrip("/") + "/", f"sub/{key}/v2ray")
        r = SESSION.get(url, headers={"accept": "text/plain"}, timeout=20)
        if r.status_code == 200:
            txt = (r.text or "").strip()
            if txt:
                try:
                    decoded = base64.b64decode(txt + "===")
                    txt = decoded.decode(errors="ignore")
                except Exception:
                    pass
                lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
                if any(ln.lower().startswith(ALLOWED_SCHEMES) for ln in lines):
                    return lines
        url = urljoin(panel_url.rstrip("/") + "/", f"sub/{key}/")
        r = SESSION.get(
            url,
            headers={"accept": "application/json,text/plain"},
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
        if r.status_code == 200:
            return [
                ln.strip()
                for ln in (r.text or "").splitlines()
                if ln.strip() and ln.strip().lower().startswith(ALLOWED_SCHEMES)
            ]
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
        if r.headers.get("content-type", "").startswith("application/json"):
            try:
                data = r.json()
            except Exception:
                data = None
            if data is not None:
                links = _extract_links(data)
                if links:
                    return links
        return [
            ln.strip()
            for ln in (r.text or "").splitlines()
            if ln.strip() and ln.strip().lower().startswith(ALLOWED_SCHEMES)
        ]
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
