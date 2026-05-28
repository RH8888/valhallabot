#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helper functions for interacting with MHSanaei/3x-ui panel API."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import json
import os
from threading import RLock

import requests
from requests import exceptions as req_exc
from cachetools import TTLCache, cached

from services.panel_tokens import refresh_panel_access_token_for_request

SESSION = requests.Session()
ALLOWED_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://")
FETCH_CACHE_TTL = int(os.getenv("FETCH_CACHE_TTL", "300"))
_links_cache = TTLCache(maxsize=256, ttl=FETCH_CACHE_TTL)
_links_lock = RLock()


def _describe_request_exception(exc: Exception) -> str:
    if isinstance(exc, req_exc.ConnectTimeout):
        return f"connection timeout: {exc}"
    if isinstance(exc, req_exc.ReadTimeout):
        return f"read timeout: {exc}"
    if isinstance(exc, req_exc.ConnectionError):
        return f"panel unreachable: {exc}"
    if isinstance(exc, req_exc.SSLError):
        return f"ssl error: {exc}"
    if isinstance(exc, req_exc.TooManyRedirects):
        return f"too many redirects: {exc}"
    if isinstance(exc, req_exc.RequestException):
        return f"http request error: {exc}"
    return str(exc)


def _format_http_error(resp, *, context: str) -> str:
    ct = (resp.headers.get("content-type") or "").lower()
    body_preview = _response_body_preview(resp)
    content_length = resp.headers.get("content-length")
    detail = ""
    if "application/json" in ct:
        try:
            payload = resp.json() or {}
            msg = payload.get("msg") or payload.get("message") or payload.get("detail")
            if msg:
                detail = f" | api_message={msg}"
        except Exception:
            pass
    length_hint = f"content_length={content_length}" if content_length else f"content_length={len(resp.content or b'')}"
    return f"{context}: status={resp.status_code}{detail} | {length_hint} | body={body_preview}"


def _response_body_preview(resp, *, limit: int = 500) -> str:
    text = (resp.text or "").replace("\n", " ").strip()
    if text:
        return text[:limit]
    raw = resp.content or b""
    if not raw:
        return "<empty>"
    try:
        decoded = raw.decode(resp.encoding or "utf-8", errors="replace").replace("\n", " ").strip()
    except Exception:
        decoded = ""
    if decoded:
        return decoded[:limit]
    return raw[: min(limit, len(raw))].hex()


def _normalize_token(token: str) -> str:
    return (token or "").strip()


def _parse_token_auth(token: str) -> Tuple[str, str]:
    """Return ``(mode, raw_token)`` where mode is ``legacy`` or ``modern``.

    Unknown/empty markers default to legacy mode for safe backward compatibility.
    """
    t = _normalize_token(token)
    if not t:
        return "legacy", ""
    low = t.lower()
    if low.startswith("bearer "):
        return "modern", t.split(" ", 1)[1].strip()
    if low.startswith("bearer:"):
        return "modern", t.split(":", 1)[1].strip()
    if low.startswith("api_token:"):
        return "modern", t.split(":", 1)[1].strip()
    # safe fallback for unknown markers
    return "legacy", t


def legacy_get_headers(token: str) -> Dict[str, str]:
    return {"Cookie": token}


def modern_get_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _request_with_reauth(
    method: str,
    panel_url: str,
    token: str,
    path: str,
    *,
    auth_mode: str = "legacy",
    **kwargs,
):
    url = urljoin(panel_url.rstrip('/') + '/', path)
    extra_headers = kwargs.pop("headers", {}) or {}
    auth_headers = modern_get_headers(token) if auth_mode == "modern" else legacy_get_headers(token)
    response = SESSION.request(method, url, headers={**auth_headers, **extra_headers}, **kwargs)
    if response.status_code not in (401, 403):
        return response
    new_token = refresh_panel_access_token_for_request(panel_url, token, panel_type="sanaei")
    if not new_token:
        return response
    new_mode, new_raw = _parse_token_auth(new_token)
    auth_headers = modern_get_headers(new_raw) if new_mode == "modern" else legacy_get_headers(new_token)
    return SESSION.request(method, url, headers={**auth_headers, **extra_headers}, **kwargs)


def _coerce_settings(settings) -> Dict:
    if isinstance(settings, dict):
        return settings
    if isinstance(settings, str):
        try:
            obj = json.loads(settings)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    return {}


def _list_inbounds(panel_url: str, token: str, auth_mode: str) -> Tuple[Optional[List[Dict]], Optional[str]]:
    try:
        r = _request_with_reauth(
            "GET", panel_url, token, 'panel/api/inbounds/list',
            auth_mode=auth_mode,
            headers={"accept": "application/json"},
            timeout=15,
        )
        if r.status_code != 200:
            return None, _format_http_error(r, context="list inbounds failed")
        data = r.json() or {}
        inbounds = data.get('obj') or data.get('inbounds') or []
        return inbounds, None
    except Exception as e:
        return None, _describe_request_exception(e)[:300]


def _find_client(inbounds: List[Dict], username: str) -> Tuple[Optional[Dict], Optional[Dict]]:
    for inbound in inbounds:
        settings_obj = _coerce_settings(inbound.get('settings') or '{}')
        clients = settings_obj.get('clients') or []
        for cl in clients:
            email = cl.get('email') or cl.get('Email') or cl.get('username')
            if email == username:
                return inbound, cl
    return None, None


def fetch_user_services(panel_url: str, token: str, username: str) -> Tuple[Optional[List[int]], Optional[str]]:
    return [], None


def create_user(panel_url: str, token: str, payload: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    mode, raw = _parse_token_auth(token)
    try:
        r = _request_with_reauth("POST", panel_url, raw, 'panel/api/inbounds/addClient', auth_mode=mode, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        if r.status_code == 200:
            return r.json(), None
        return None, f"{r.status_code} {r.text[:300]}"
    except Exception as e:
        return None, _describe_request_exception(e)[:300]


def get_user(panel_url: str, token: str, username: str) -> Tuple[Optional[Dict], Optional[str]]:
    mode, raw = _parse_token_auth(token)
    inbounds, err = _list_inbounds(panel_url, raw, mode)
    if err:
        return None, err
    inbound, client = _find_client(inbounds, username)
    if not client or not inbound:
        return None, 'not found'
    uuid = client.get('id') or client.get('uuid')
    try:
        r = _request_with_reauth("GET", panel_url, raw, f"panel/api/inbounds/getClientTraffics/{username}", auth_mode=mode, headers={"accept": "application/json"}, timeout=15)
        if r.status_code != 200:
            return None, _format_http_error(r, context="list inbounds failed")
        data = r.json() or {}
        obj = data.get('obj') or data
        up = int(obj.get('up', 0) or 0)
        down = int(obj.get('down', 0) or 0)
        enabled = bool(obj.get('enable', True))
        used = up + down
        exp = obj.get('expiryTime') or obj.get('expiry_time') or client.get('expiryTime') or client.get('expiry_time')
    except Exception as e:
        return None, _describe_request_exception(e)[:300]
    return {
        'uuid': uuid, 'enabled': enabled, 'used_traffic': used,
        'expiryTime': exp, 'expiry_time': exp,
        'protocol': inbound.get('protocol'), 'port': inbound.get('port'),
        'listen': inbound.get('listen'), 'remark': inbound.get('remark'),
    }, None


@cached(cache=_links_cache, lock=_links_lock)
def fetch_links_from_panel(panel_url: str, token: str, username: str) -> Tuple[List[str], Optional[str]]:
    user, err = get_user(panel_url, token, username)
    if err or not user:
        return [], err
    host = user.get('listen') or urlparse(panel_url).hostname or ''
    port = user.get('port')
    protocol = user.get('protocol') or 'vless'
    uuid = user.get('uuid') or ''
    name = user.get('remark') or username
    if not (host and port and uuid):
        return [], 'incomplete config'
    link = f"{protocol}://{uuid}@{host}:{port}?security=none#{name}"
    if not any(link.lower().startswith(s) for s in ALLOWED_SCHEMES):
        link = f"vless://{uuid}@{host}:{port}?security=none#{name}"
    return [link], None


def _toggle_user(panel_url: str, token: str, username: str, enabled: bool):
    mode, raw = _parse_token_auth(token)
    inbounds, err = _list_inbounds(panel_url, raw, mode)
    if err:
        return False, err
    inbound, client = _find_client(inbounds, username)
    if not client or not inbound:
        return False, 'not found'
    client['enable'] = enabled
    settings_obj = _coerce_settings(inbound.get('settings') or '{}')
    clients = settings_obj.get('clients') or []
    for idx, cl in enumerate(clients):
        email = cl.get('email') or cl.get('Email') or cl.get('username')
        if email == username:
            clients[idx] = client
            break
    settings_obj['clients'] = clients
    inbound['settings'] = json.dumps(settings_obj, separators=(',', ':'))
    r = _request_with_reauth("POST", panel_url, raw, f"panel/api/inbound/update/{inbound.get('id')}", auth_mode=mode, json=inbound, headers={'Content-Type': 'application/json'}, timeout=20)
    return r.status_code == 200, (None if r.status_code == 200 else f"{r.status_code} {r.text[:200]}")


def disable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    try:
        return _toggle_user(panel_url, token, username, False)
    except Exception as e:
        return False, _describe_request_exception(e)[:300]


def enable_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    try:
        return _toggle_user(panel_url, token, username, True)
    except Exception as e:
        return False, _describe_request_exception(e)[:300]


def remove_remote_user(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    mode, raw = _parse_token_auth(token)
    try:
        inbounds, err = _list_inbounds(panel_url, raw, mode)
        if err:
            return False, err
        inbound, client = _find_client(inbounds, username)
        if not client or not inbound:
            return False, 'not found'
        uuid = client.get('id') or client.get('uuid')
        r = _request_with_reauth("POST", panel_url, raw, f"panel/api/inbounds/{inbound.get('id')}/delClient/{uuid}", auth_mode=mode, timeout=20)
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:
        return False, _describe_request_exception(e)[:300]


def reset_remote_user_usage(panel_url: str, token: str, username: str) -> Tuple[bool, Optional[str]]:
    mode, raw = _parse_token_auth(token)
    try:
        inbounds, err = _list_inbounds(panel_url, raw, mode)
        if err:
            return False, err
        inbound, client = _find_client(inbounds, username)
        if not inbound or not client:
            return False, 'not found'
        r = _request_with_reauth("POST", panel_url, raw, f"panel/api/inbounds/{inbound.get('id')}/resetClientTraffic/{username}", auth_mode=mode, timeout=20)
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:
        return False, _describe_request_exception(e)[:300]


def update_remote_user(panel_url: str, token: str, username: str, data_limit: Optional[int] = None, expire: Optional[int] = None) -> Tuple[bool, Optional[str]]:
    mode, raw = _parse_token_auth(token)
    try:
        inbounds, err = _list_inbounds(panel_url, raw, mode)
        if err:
            return False, err
        inbound, client = _find_client(inbounds, username)
        if not inbound or not client:
            return False, 'not found'
        if data_limit is not None:
            client['totalGB'] = int(data_limit)
        if expire is not None:
            client['expiryTime'] = int(expire) * 1000
        payload = {'id': inbound.get('id'), 'settings': json.dumps({'clients': [client]}, separators=(',', ':'))}
        r = _request_with_reauth("POST", panel_url, raw, f"panel/api/inbounds/updateClient/{client.get('id')}", auth_mode=mode, json=payload, headers={'Content-Type': 'application/json'}, timeout=20)
        if r.status_code == 200:
            return True, None
        return False, f"{r.status_code} {r.text[:200]}"
    except Exception as e:
        return False, _describe_request_exception(e)[:300]


def fetch_subscription_links(sub_url: str) -> List[str]:
    try:
        r = SESSION.get(sub_url, headers={"accept": "text/plain"}, timeout=20)
        if r.status_code != 200:
            return []
        return [ln.strip() for ln in (r.text or '').splitlines() if ln.strip() and ln.strip().lower().startswith(ALLOWED_SCHEMES)]
    except Exception:
        return []


def _is_modern_version(panel_version: str | None) -> bool:
    text = (panel_version or "").strip()
    if not text:
        return False
    major_text = text.split(".", 1)[0].strip()
    try:
        major = int(major_text)
    except (TypeError, ValueError):
        return False
    return major >= 3


def get_admin_token(
    panel_url: str,
    username: str,
    password: str,
    *,
    panel_version: str | None = None,
) -> Tuple[Optional[str], Optional[str]]:
    login_url = urljoin(panel_url.rstrip('/') + '/', 'login')
    try:
        # 3x-ui modern API expects JSON payload on /login. Some older deployments
        # still accept (or only accept) form-encoded data, so we fallback to form
        # only when JSON login fails with auth/content related status codes.
        payload = {"username": username, "password": password}
        payload_with_2fa = {"username": username, "password": password, "twoFactorCode": ""}
        resp = SESSION.post(
            login_url,
            json=payload,
            headers={"accept": "application/json"},
            timeout=15,
        )
        if resp.status_code == 403:
            # Some modern 3x-ui builds validate the request schema strictly and
            # require the twoFactorCode field to exist (empty when 2FA disabled).
            resp_2fa = SESSION.post(
                login_url,
                json=payload_with_2fa,
                headers={"accept": "application/json"},
                timeout=15,
            )
            if resp_2fa.status_code == 200:
                resp = resp_2fa
        if resp.status_code in (400, 401, 403, 415, 422):
            legacy_resp = SESSION.post(login_url, data=payload, timeout=15)
            if legacy_resp.status_code != 200 and resp.status_code == 403:
                # keep parity with JSON fallback by trying form payload with
                # explicit empty twoFactorCode.
                legacy_resp = SESSION.post(login_url, data=payload_with_2fa, timeout=15)
            if legacy_resp.status_code == 200:
                resp = legacy_resp
        if resp.status_code != 200:
            return None, _format_http_error(resp, context="login request failed")
        if _is_modern_version(panel_version):
            data = resp.json() if "application/json" in (resp.headers.get("content-type", "").lower()) else {}
            token = (
                (data or {}).get("access_token")
                or (data or {}).get("token")
                or ((data or {}).get("obj") or {}).get("token")
            )
            if token:
                return f"api_token:{token}", None
            # Some mixed deployments still issue cookie sessions even when modern mode is selected.
            jar = resp.cookies.get_dict()
            if jar:
                cookie_name, cookie_val = next(iter(jar.items()))
                return f"{cookie_name}={cookie_val}", None
            body_preview = _response_body_preview(resp, limit=200)
            return None, f"modern login selected but no access token in response (status={resp.status_code}, body={body_preview})"
        jar = resp.cookies.get_dict()
        cookie_name = None
        cookie_val = None
        if '3x-ui' in jar:
            cookie_name, cookie_val = '3x-ui', jar['3x-ui']
        elif 'session' in jar:
            cookie_name, cookie_val = 'session', jar['session']
        elif jar:
            cookie_name, cookie_val = next(iter(jar.items()))
        if not cookie_name or not cookie_val:
            return None, 'no session cookie'
        return f"{cookie_name}={cookie_val}", None
    except Exception as e:
        return None, _describe_request_exception(e)[:300]
