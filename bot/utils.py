"""Utility helpers for the Telegram bot flows."""

from __future__ import annotations

import json
import logging
import re
import secrets
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import unquote, urlparse

from apis import marzban, marzneshin, pasarguard, rebecca, sanaei
from api.subscription_aggregator import admin_ids

log = logging.getLogger("marz_bot")

API_MODULES = {
    "marzneshin": marzneshin,
    "marzban": marzban,
    "rebecca": rebecca,
    "sanaei": sanaei,
    "pasarguard": pasarguard,
}

UNIT = 1024


def get_api(panel_type: str):
    """Return the API module for a given panel type."""

    return API_MODULES.get(panel_type or "marzneshin", marzneshin)


def clone_proxy_settings(proxies: dict) -> dict:
    """Copy proxy settings and regenerate credentials."""

    cleaned: dict[str, Any] = {}
    for ptype, settings in (proxies or {}).items():
        if not isinstance(settings, dict):
            cleaned[ptype] = settings
            continue
        s = settings.copy()
        if "id" in s:
            s["id"] = str(uuid.uuid4())
        if "uuid" in s:
            s["uuid"] = str(uuid.uuid4())
        if "password" in s:
            s["password"] = secrets.token_hex(12)
        if "pass" in s:
            s["pass"] = secrets.token_hex(12)
        cleaned[ptype] = s
    return cleaned


def is_admin(tg_id: int) -> bool:
    return tg_id in admin_ids()


def fmt_bytes_short(n: int) -> str:
    if n <= 0:
        return "0 MB"
    tb = n / (UNIT**4)
    gb = n / (UNIT**3)
    mb = n / (UNIT**2)
    if tb >= 1:
        return f"{tb:.2f} TB"
    if gb >= 1:
        return f"{gb:.2f} GB"
    return f"{mb:.2f} MB"


def parse_human_size(s: str) -> int:
    if not s:
        return 0
    s = s.strip().lower()
    if s in ("0", "unlimited", "∞", "no limit", "nolimit"):
        return 0
    num, unit = "", ""
    for ch in s:
        if ch.isdigit() or ch in ".,":
            num += ch.replace(",", ".")
        else:
            unit += ch
    try:
        val = float(num) if num else 0.0
    except Exception:
        val = 0.0
    unit = unit.strip()
    if unit in ("", "g", "gb"):
        mul = UNIT**3
    elif unit in ("m", "mb"):
        mul = UNIT**2
    elif unit in ("t", "tb"):
        mul = UNIT**4
    else:
        mul = UNIT**3
    return int(max(0.0, val) * mul)


def gb_to_bytes(txt: str) -> int:
    try:
        gb = float((txt or "0").strip())
        gb = max(0.0, gb)
    except Exception:
        gb = 0.0
    return int(gb * (UNIT**3))


def make_panel_name(url: str, username: str) -> str:
    try:
        hostname = urlparse(url).hostname or url
    except Exception:
        hostname = url
    hostname = str(hostname).replace("www.", "")
    base = f"{hostname}-{username}".strip("-")
    return (base[:120] if len(base) > 120 else base) or "panel"


def canonicalize_name(name: str) -> str:
    """Normalize a config name by removing user-specific fragments."""

    try:
        nm = unquote(name or "").strip()
        nm = re.sub(r"\s*\d+(?:\.\d+)?\s*[KMGT]?B/\d+(?:\.\d+)?\s*[KMGT]?B", "", nm, flags=re.I)
        nm = re.sub(r"\s*👤.*", "", nm)
        nm = re.sub(r"\s*\([a-zA-Z0-9_-]{3,}\)", "", nm)
        nm = re.sub(r"\s+", " ", nm)
        return nm.strip()[:255]
    except Exception:
        return ""


def dumps_compact(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"))


def utcnow() -> datetime:
    return datetime.utcnow()
