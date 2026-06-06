#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modern 3x-ui client adapter.

This module intentionally does not replace :mod:`apis.sanaei`.  The legacy
module targets the older inbound/client endpoints, while this adapter targets
3x-ui's first-class ``/panel/api/clients`` endpoints documented in
``docs/sanaei-new-version.json``.  Its public function names and return shapes
mirror the legacy helper so bot and sync code can switch adapters without
changing their call sites.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin
import base64

import json
import os
from threading import RLock

import requests
from cachetools import TTLCache, cached

from services.panel_tokens import refresh_panel_access_token_for_request

SESSION = requests.Session()
ALLOWED_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://", "hysteria://", "hy2://")

FETCH_CACHE_TTL = int(os.getenv("FETCH_CACHE_TTL", "300"))
_links_cache = TTLCache(maxsize=256, ttl=FETCH_CACHE_TTL)
_links_lock = RLock()


def get_headers(token: str) -> Dict[str, str]:
    """Return auth headers for modern 3x-ui bearer or cookie auth.

    Supported stored token formats:

    * ``Bearer <token>`` or a raw API token -> ``Authorization: Bearer <token>``
    * ``3x-ui=<value>`` or any stored cookie string -> ``Cookie: <string>``
    * ``cookie:<value>`` -> ``Cookie: 3x-ui=<value>`` unless ``value`` already
      looks like a full cookie string
    """

    if not token:
        return {}
    token_str = str(token).strip()
    lowered = token_str.lower()
    if lowered.startswith("cookie:"):
        cookie = token_str.split(":", 1)[1].strip()
        return {"Cookie": cookie if "=" in cookie else f"3x-ui={cookie}"}
    if lowered.startswith("bearer "):
        return {"Authorization": token_str}
    if "=" in token_str or ";" in token_str:
        return {"Cookie": token_str}
    return {"Authorization": f"Bearer {token_str}"}


def _build_api_url(panel_url: str, *segments: object) -> str:
    cleaned_segments: List[str] = []
    for seg in segments:
        if seg is None:
            continue
        part = str(seg).strip("/")
        if part:
            cleaned_segments.append(quote(part, safe=""))
    return urljoin(panel_url.rstrip("/") + "/", "/".join(cleaned_segments))


def _request_with_reauth(method: str, panel_url: str, token: str, *segments: object, **kwargs: Any):
    extra_headers = kwargs.pop("headers", {}) or {}
    headers = {**get_headers(token), **extra_headers}
    response = SESSION.request(method, _build_api_url(panel_url, *segments), headers=headers, **kwargs)
    if response.status_code not in (401, 403):
        return response
    new_token = refresh_panel_access_token_for_request(panel_url, token, panel_type="sanaei")
    if not new_token:
        return response
    return SESSION.request(
        method,
        _build_api_url(panel_url, *segments),
        headers={**get_headers(new_token), **extra_headers},
        **kwargs,
    )


def _response_error(response: requests.Response, limit: int = 300) -> str:
    return f"{response.status_code} {(response.text or '')[:limit]}"


def _unwrap_panel_response(data: Any) -> Any:
    if isinstance(data, Mapping) and "success" in data:
        return data.get("obj")
    return data


def _panel_success(data: Any) -> bool:
    """Return whether a wrapped 3x-ui response is successful.

    Some panel forks encode ``success`` as strings or integers instead of a
    JSON boolean.  Treat every explicit false-like value as a failure so
    ``{"success": false, ...}`` responses, including duplicate-email
    errors from ``/panel/api/clients/add``, never get normalised into a
    successful client object.
    """

    if not isinstance(data, Mapping) or "success" not in data:
        return True
    success = data.get("success")
    if isinstance(success, str):
        return success.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(success)


def _json_or_empty(response: requests.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return {}


def _coerce_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_present(obj: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in obj and obj.get(key) is not None:
            return obj.get(key)
    return None


def _extract_client(obj: Any) -> Dict[str, Any]:
    if not isinstance(obj, Mapping):
        return {}
    for key in ("client", "user"):
        value = obj.get(key)
        if isinstance(value, Mapping):
            return dict(value)
    return dict(obj)


def _extract_inbound_ids(obj: Any) -> List[int]:
    if not isinstance(obj, Mapping):
        return []
    value = obj.get("inboundIds") or obj.get("inbound_ids") or obj.get("inbounds") or obj.get("inbound_ids")
    if value is None:
        return []
    if isinstance(value, Mapping):
        value = value.keys()
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        out = []
        for item in value:
            coerced = _coerce_int(item)
            if coerced is not None:
                out.append(coerced)
        return out
    coerced = _coerce_int(value)
    return [coerced] if coerced is not None else []


def _normalise_links(value: Any) -> List[str]:
    if value is None:
        return []
    candidates: List[str] = []
    if isinstance(value, str):
        candidates = value.splitlines()
    elif isinstance(value, Mapping):
        for key in ("links", "urls", "subscription_url", "subscriptionUrl", "subUrl"):
            candidates.extend(_normalise_links(value.get(key)))
    elif isinstance(value, Iterable):
        for item in value:
            candidates.extend(_normalise_links(item))
    return [ln.strip() for ln in candidates if isinstance(ln, str) and ln.strip().lower().startswith(ALLOWED_SCHEMES)]


def _normalise_user_object(client_obj: Any, traffic_obj: Any = None, links: Optional[List[str]] = None) -> Dict[str, Any]:
    raw_client = client_obj if isinstance(client_obj, Mapping) else {}
    client = _extract_client(client_obj)
    traffic = _extract_client(traffic_obj) if isinstance(traffic_obj, Mapping) else {}

    up = _coerce_int(_first_present(traffic, "up", "upload", "uplink")) or 0
    down = _coerce_int(_first_present(traffic, "down", "download", "downlink")) or 0
    used = _coerce_int(_first_present(traffic, "used_traffic", "usedTraffic", "used"))
    if used is None:
        used = up + down

    data_limit = _coerce_int(_first_present(client, "totalGB", "total", "data_limit", "dataLimit"))
    if data_limit is None:
        data_limit = _coerce_int(_first_present(traffic, "totalGB", "total", "data_limit", "dataLimit"))

    expiry = _first_present(client, "expiryTime", "expiry_time", "expire", "expireTime")
    if expiry is None:
        expiry = _first_present(traffic, "expiryTime", "expiry_time", "expire", "expireTime")

    enabled_value = _first_present(client, "enable", "enabled", "isEnabled")
    if enabled_value is None:
        status = str(client.get("status") or "").lower()
        enabled = status not in {"disabled", "limited", "expired", "depleted"}
    else:
        enabled = bool(enabled_value)

    normalised = dict(client)
    normalised.update(
        {
            "uuid": _first_present(client, "id", "uuid"),
            "email": _first_present(client, "email", "username"),
            "username": _first_present(client, "username", "email"),
            "enabled": enabled,
            "enable": enabled,
            "used_traffic": used,
            "up": up,
            "down": down,
            "data_limit": data_limit,
            "totalGB": data_limit,
            "expiryTime": expiry,
            "expiry_time": expiry,
            "inboundIds": _extract_inbound_ids(raw_client),
        }
    )

    all_links = _normalise_links(links) or _normalise_links(client)
    if all_links:
        normalised["links"] = all_links
        normalised["subscription_url"] = normalised.get("subscription_url") or all_links[0]
    else:
        sub_url = _first_present(client, "subscription_url", "subscriptionUrl", "subUrl")
        if sub_url:
            normalised["subscription_url"] = sub_url
    return normalised


def _extract_legacy_create_payload(payload: Mapping[str, Any]) -> Tuple[Dict[str, Any], List[int]]:
    client: Dict[str, Any] = {}
    inbound_ids: List[int] = []

    if isinstance(payload.get("client"), Mapping):
        client.update(payload["client"])
    if isinstance(payload.get("settings"), str):
        try:
            settings = json.loads(payload.get("settings") or "{}")
        except Exception:
            settings = {}
    elif isinstance(payload.get("settings"), Mapping):
        settings = payload.get("settings") or {}
    else:
        settings = {}
    clients = settings.get("clients") if isinstance(settings, Mapping) else None
    if isinstance(clients, list) and clients and isinstance(clients[0], Mapping):
        client.update(clients[0])

    for key in ("inboundIds", "inbound_ids"):
        inbound_ids.extend(_extract_inbound_ids({key: payload.get(key)}))
    inbound_id = _coerce_int(payload.get("id") or payload.get("inbound_id") or payload.get("inboundId"))
    if inbound_id is not None:
        inbound_ids.append(inbound_id)

    for source, target in (("username", "email"), ("data_limit", "totalGB"), ("expire", "expiryTime")):
        if payload.get(source) is not None and client.get(target) is None:
            client[target] = payload[source]
    if "email" not in client and payload.get("email"):
        client["email"] = payload["email"]
    if "enable" not in client and "enabled" in payload:
        client["enable"] = bool(payload.get("enabled"))

    return client, list(dict.fromkeys(inbound_ids))


def _prepare_create_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    client, inbound_ids = _extract_legacy_create_payload(payload)
    body = {"client": client, "inboundIds": inbound_ids}
    if not inbound_ids and isinstance(payload.get("inboundIds"), list):
        body["inboundIds"] = payload["inboundIds"]
    return body


def _iter_inbound_clients(inbound: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    settings = inbound.get("settings") or {}
    if isinstance(settings, str):
        try:
            settings = json.loads(settings or "{}")
        except Exception:
            settings = {}
    clients = settings.get("clients") if isinstance(settings, Mapping) else None
    if isinstance(clients, Iterable) and not isinstance(clients, (str, bytes, bytearray)):
        for client in clients:
            if isinstance(client, Mapping):
                yield client


def _client_email(client: Mapping[str, Any]) -> Optional[str]:
    value = _first_present(client, "email", "Email", "username")
    if value is None:
        return None
    email = str(value).strip()
    return email or None


def _normalise_client_email(email: Any) -> str:
    return str(email or "").strip().casefold()


def _list_inbounds(panel_url: str, token: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        r = _request_with_reauth(
            "GET",
            panel_url,
            token,
            "panel",
            "api",
            "inbounds",
            "list",
            headers={"accept": "application/json"},
            timeout=20,
        )
        if r.status_code != 200:
            return None, _response_error(r, 200)
        data = _json_or_empty(r)
        if not _panel_success(data):
            return None, str(data.get("msg") or "request failed")[:200]
        obj = _unwrap_panel_response(data)
        if isinstance(obj, list):
            return [dict(item) for item in obj if isinstance(item, Mapping)], None
        if isinstance(obj, Mapping):
            inbounds = obj.get("inbounds") or obj.get("list") or obj.get("items")
            if isinstance(inbounds, list):
                return [dict(item) for item in inbounds if isinstance(item, Mapping)], None
        return [], None
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]


def _fetch_all_client_emails(panel_url: str, token: str) -> Tuple[Optional[set[str]], Optional[str]]:
    inbounds, err = _list_inbounds(panel_url, token)
    if err:
        return None, err
    emails: set[str] = set()
    for inbound in inbounds or []:
        for client in _iter_inbound_clients(inbound):
            email = _client_email(client)
            if email:
                emails.add(_normalise_client_email(email))
        stats = inbound.get("clientStats")
        if isinstance(stats, Iterable) and not isinstance(stats, (str, bytes, bytearray)):
            for stat in stats:
                if isinstance(stat, Mapping):
                    email = _client_email(stat)
                    if email:
                        emails.add(_normalise_client_email(email))
    return emails, None


def _validate_new_client_email(panel_url: str, token: str, email: Any) -> Optional[str]:
    normalised = _normalise_client_email(email)
    if not normalised:
        return "client email is required"
    emails, err = _fetch_all_client_emails(panel_url, token)
    if err:
        return f"could not verify unique client email: {err}"
    if normalised in (emails or set()):
        return f"client email '{str(email).strip()}' already exists on this panel"
    return None


def _fetch_client(panel_url: str, token: str, username: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        r = _request_with_reauth("GET", panel_url, token, "panel", "api", "clients", "get", username, timeout=15)
        if r.status_code != 200:
            return None, _response_error(r, 200)
        data = _json_or_empty(r)
        if not _panel_success(data):
            return None, str(data.get("msg") or "request failed")[:200]
        return _unwrap_panel_response(data), None
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]


def _fetch_traffic(panel_url: str, token: str, username: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        r = _request_with_reauth("GET", panel_url, token, "panel", "api", "clients", "traffic", username, timeout=15)
        if r.status_code != 200:
            return None, _response_error(r, 200)
        data = _json_or_empty(r)
        if not _panel_success(data):
            return None, str(data.get("msg") or "request failed")[:200]
        return _unwrap_panel_response(data), None
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]


def fetch_user_services(panel_url: str, token: str, username: str) -> Tuple[Optional[List[int]], Optional[str]]:
    """Return inbound IDs attached to *username* when the modern API exposes them."""

    obj, err = _fetch_client(panel_url, token, username)
    if err:
        return None, err
    return _extract_inbound_ids(obj), None


def create_user(panel_url: str, token: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    """Create a client via ``POST /panel/api/clients/add``."""

    try:
        body = _prepare_create_payload(payload or {})
        client = _extract_client(body.get("client"))
        duplicate_err = _validate_new_client_email(panel_url, token, _first_present(client, "email", "username"))
        if duplicate_err:
            return None, duplicate_err
        r = _request_with_reauth(
            "POST",
            panel_url,
            token,
            "panel",
            "api",
            "clients",
            "add",
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code != 200:
            return None, _response_error(r)
        data = _json_or_empty(r)
        if not _panel_success(data):
            return None, str(data.get("msg") or "request failed")[:300]
        created = _unwrap_panel_response(data) or {"client": body.get("client"), "inboundIds": body.get("inboundIds")}
        return _normalise_user_object(created), None
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]


def get_user(panel_url: str, token: str, username: str) -> Tuple[Optional[Dict], Optional[str]]:
    """Fetch and normalise client details via modern client endpoints."""

    client, err = _fetch_client(panel_url, token, username)
    if err:
        return None, err
    traffic, traffic_err = _fetch_traffic(panel_url, token, username)
    if traffic_err:
        traffic = None
    links, _ = fetch_links_from_panel(panel_url, token, username)
    return _normalise_user_object(client, traffic, links), None


@cached(cache=_links_cache, lock=_links_lock)
def fetch_links_from_panel(panel_url: str, token: str, username: str) -> Tuple[List[str], Optional[str]]:
    """Return generated client links from ``GET /panel/api/clients/links/{email}``."""

    try:
        r = _request_with_reauth("GET", panel_url, token, "panel", "api", "clients", "links", username, timeout=20)
        if r.status_code != 200:
            return [], _response_error(r, 200)
        data = _json_or_empty(r)
        if not _panel_success(data):
            return [], str(data.get("msg") or "request failed")[:200]
        return _normalise_links(_unwrap_panel_response(data)), None
    except Exception as e:  # pragma: no cover - network errors
        return [], str(e)[:200]


def fetch_subscription_links(sub_url: str) -> List[str]:
    """Return links from a sample subscription URL for config filtering.

    Modern 3x-ui user subscriptions are normally fetched through the client
    links API, but admins can still provide any representative subscription URL
    so the bot can list config names/order and save per-panel disabled filters.
    """

    try:
        r = SESSION.get(sub_url, headers={"accept": "text/plain,application/json"}, timeout=20)
        if r.status_code != 200:
            return []
        if r.headers.get("content-type", "").startswith("application/json"):
            return _normalise_links(_json_or_empty(r))
        txt = r.text or ""
        lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
        if not any(ln.lower().startswith(ALLOWED_SCHEMES) for ln in lines):
            try:
                decoded = base64.b64decode(txt.strip() + "===")
                lines = [ln.strip() for ln in decoded.decode(errors="ignore").splitlines() if ln.strip()]
            except Exception:
                pass
        return [ln for ln in lines if ln.lower().startswith(ALLOWED_SCHEMES)]
    except Exception:  # pragma: no cover - network errors
        return []

def _update_client(panel_url: str, token: str, username: str, changes: Mapping[str, Any]) -> Tuple[bool, Optional[str]]:
    current, err = _fetch_client(panel_url, token, username)
    if err:
        return False, err
    client = _extract_client(current)
    if not client:
        return False, "not found"
    client.update({key: value for key, value in changes.items() if value is not None})
    client.setdefault("email", username)

    # Prune read-only or nested fields that might cause the panel to reject the
    # update when sent back in a flat client payload.
    for key in ("traffic", "id", "inboundIds", "createdAt", "updatedAt", "up", "down"):
        client.pop(key, None)

    try:
        r = _request_with_reauth(
            "POST",
            panel_url,
            token,
            "panel",
            "api",
            "clients",
            "update",
            username,
            json=client,
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code != 200:
            return False, _response_error(r, 200)
        data = _json_or_empty(r)
        if not _panel_success(data):
            return False, str(data.get("msg") or "request failed")[:200]
        _links_cache.pop((panel_url, token, username), None)
        return True, None
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def disable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Disable a client via ``POST /panel/api/clients/update/{email}``."""

    return _update_client(panel_url, token, username, {"enable": False, "enabled": False})


def enable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Enable a client via ``POST /panel/api/clients/update/{email}``."""

    return _update_client(panel_url, token, username, {"enable": True, "enabled": True})


def remove_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Delete a client via ``POST /panel/api/clients/del/{email}``."""

    try:
        r = _request_with_reauth(
            "POST",
            panel_url,
            token,
            "panel",
            "api",
            "clients",
            "del",
            username,
            params={"keepTraffic": 0},
            timeout=20,
        )
        if r.status_code != 200:
            return False, _response_error(r, 200)
        data = _json_or_empty(r)
        if not _panel_success(data):
            return False, str(data.get("msg") or "request failed")[:200]
        _links_cache.pop((panel_url, token, username), None)
        return True, None
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def reset_remote_user_usage(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    """Reset traffic via ``POST /panel/api/clients/resetTraffic/{email}``."""

    try:
        r = _request_with_reauth("POST", panel_url, token, "panel", "api", "clients", "resetTraffic", username, timeout=20)
        if r.status_code != 200:
            return False, _response_error(r, 200)
        data = _json_or_empty(r)
        if not _panel_success(data):
            return False, str(data.get("msg") or "request failed")[:200]
        return True, None
    except Exception as e:  # pragma: no cover - network errors
        return False, str(e)[:200]


def update_remote_user(
    panel_url: str,
    token: str,
    username: str,
    data_limit: Optional[int] = None,
    expire: Optional[int] = None,
) -> Tuple[bool, Optional[str]]:
    """Update quota or expiry for *username* on the modern client endpoint."""

    changes: Dict[str, Any] = {}
    if data_limit is not None:
        changes["totalGB"] = int(data_limit)
        changes["total"] = int(data_limit)
    if expire is not None:
        changes["expiryTime"] = int(expire) * 1000
        changes["expiry_time"] = int(expire) * 1000
    if not changes:
        return True, None
    return _update_client(panel_url, token, username, changes)


def get_admin_token(panel_url: str, username: str, password: str) -> Tuple[Optional[str], Optional[str]]:
    """Log in and return a cookie string for modern cookie auth.

    Bearer tokens are created in the panel UI and can be stored directly; this
    helper mirrors the legacy surface by returning a login session cookie.
    """

    login_url = urljoin(panel_url.rstrip("/") + "/", "login")
    try:
        resp = SESSION.post(
            login_url,
            json={"username": username, "password": password, "twoFactorCode": ""},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            resp = SESSION.post(login_url, data={"username": username, "password": password}, timeout=15)
        if resp.status_code not in (200, 201):
            return None, _response_error(resp, 200)
        jar = resp.cookies.get_dict()
        if "3x-ui" in jar:
            return f"3x-ui={jar['3x-ui']}", None
        if jar:
            return "; ".join(f"{name}={value}" for name, value in jar.items()), None
        return None, "no session cookie"
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)[:200]
