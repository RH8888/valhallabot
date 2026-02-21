#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask subscription aggregator for Marzneshin/Marzban/Rebecca/Sanaei/Pasarguard/Guardcore panels
- GET /sub/<local_username>/<app_key>/links
- Returns only configs (ss://, vless://, vmess://, trojan://), one per line (text/plain)
- Enforces local quota. If user quota exceeded -> empty body + DISABLE remote (once).
- NEW: Enforces AGENT-level quota/expiry too: if agent exhausted/expired -> empty body + DISABLE ALL agent users (once).
- Supports per-panel disabled config-name filters (anything after '#' is the name).
"""

import os
import logging
import math
import re
import json
from pathlib import Path
from urllib.parse import urljoin, unquote, quote

import base64
import requests
SESSION = requests.Session()
from cachetools import TTLCache, cached
from threading import RLock
from flask import Flask, Response, abort, request, render_template_string
from types import SimpleNamespace
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from services import ensure_panel_tokens, init_mysql_pool, with_mysql_cursor
from services.database import errorcode, mysql_errors
from apis import sanaei, pasarguard, rebecca, guardcore
from .ownership import expand_owner_ids, canonical_owner_id

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | flask_agg | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("flask_agg")

ALLOWED_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://")
RATIO_NAME_SCHEMES = ("vless://", "vmess://", "ss://")
SUB_PLACEHOLDER_BASE_CONFIG = "ss://bm9uZTp2YWxoYWxsYQ%3D%3D@127.0.0.1:53#"
SUB_PLACEHOLDER_ENABLED_KEY = "subscription_placeholder_enabled"
SUB_PLACEHOLDER_TEMPLATE_KEY = "subscription_placeholder_template"

BASE_DIR = Path(__file__).resolve().parents[2]
with (BASE_DIR / "templates" / "index.html").open(encoding="utf-8") as f:
    HTML_TEMPLATE = f.read()
with (BASE_DIR / "templates" / "error.html").open(encoding="utf-8") as f:
    ERROR_TEMPLATE = f.read()
with (BASE_DIR / "templates" / "landing.html").open(encoding="utf-8") as f:
    LANDING_TEMPLATE = f.read()

# Load environment variables and initialize the MySQL pool on import so that
# the application is ready for WSGI servers like Gunicorn.
init_mysql_pool()

FETCH_CACHE_TTL = int(os.getenv("FETCH_CACHE_TTL", "300"))
_fetch_user_cache = TTLCache(maxsize=256, ttl=FETCH_CACHE_TTL)
_fetch_user_lock = RLock()
_fetch_links_cache = TTLCache(maxsize=256, ttl=FETCH_CACHE_TTL)
_fetch_links_lock = RLock()

_settings_table_missing_logged = False


def get_setting(owner_id: int, key: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        try:
            cur.execute(
                f"""
                SELECT value
                FROM settings
                WHERE owner_id IN ({placeholders}) AND `key`=%s
                LIMIT 1
                """,
                tuple(ids) + (key,),
            )
        except mysql_errors.ProgrammingError as exc:
            if getattr(exc, "errno", None) == errorcode.ER_NO_SUCH_TABLE:
                global _settings_table_missing_logged
                if not _settings_table_missing_logged:
                    log.warning(
                        "settings table missing; returning no setting values until it is created"
                    )
                    _settings_table_missing_logged = True
                return None
            raise
        row = cur.fetchone()
        return row["value"] if row else None

# ---------- queries ----------
def get_owner_id(app_username, app_key):
    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT telegram_user_id FROM app_users WHERE username=%s AND app_key=%s LIMIT 1",
            (app_username, app_key),
        )
        row = cur.fetchone()
        return int(row["telegram_user_id"]) if row else None

def get_local_user(owner_id, local_username):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT owner_id, username, plan_limit_bytes, used_bytes, expire_at, manual_disabled,
                   disabled_pushed, usage_limit_notified, expire_limit_notified, service_id
            FROM local_users
            WHERE owner_id IN ({placeholders}) AND username=%s
            LIMIT 1
        """,
            tuple(ids) + (local_username,),
        )
        return cur.fetchone()

def list_mapped_links(owner_id, local_username):
    """Return panel link mappings for a local user.

    Only the data required for API-based subscription fetching is selected; any
    panel-level subscription URL configured for name filtering is ignored here.
    """
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT lup.panel_id, lup.remote_username,
                   p.panel_url, p.access_token, p.panel_type,
                   p.admin_username, p.admin_password_encrypted,
                   p.usage_multiplier, p.append_ratio_to_name
            FROM local_user_panel_links lup
            JOIN panels p ON p.id = lup.panel_id
            WHERE lup.owner_id IN ({placeholders}) AND lup.local_username=%s
            """,
            tuple(ids) + (local_username,),
        )
        rows = cur.fetchall()
    return ensure_panel_tokens(rows)

def list_all_panels(owner_id):
    """List all panels for an owner for fallback resolution.

    Subscription URLs stored for config-name filtering are intentionally not
    returned as the unified subscription now fetches configs directly via the
    panel API.
    """
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, panel_url, access_token, panel_type,
                   admin_username, admin_password_encrypted,
                   usage_multiplier, append_ratio_to_name
            FROM panels
            WHERE telegram_user_id IN ({placeholders})
            """,
            tuple(ids),
        )
        rows = cur.fetchall()
    return ensure_panel_tokens(rows)

def mark_user_disabled(owner_id, local_username):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            UPDATE local_users
            SET disabled_pushed=1, disabled_pushed_at=NOW()
            WHERE owner_id IN ({placeholders}) AND username=%s
        """,
            tuple(ids) + (local_username,),
        )


def mark_usage_limit_notified(owner_id, local_username):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            UPDATE local_users
            SET usage_limit_notified=1, usage_limit_notified_at=NOW()
            WHERE owner_id IN ({placeholders}) AND username=%s
        """,
            tuple(ids) + (local_username,),
        )


def mark_expire_limit_notified(owner_id, local_username):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            UPDATE local_users
            SET expire_limit_notified=1, expire_limit_notified_at=NOW()
            WHERE owner_id IN ({placeholders}) AND username=%s
        """,
            tuple(ids) + (local_username,),
        )


def send_owner_limit_notification(owner_id: int, message: str):
    enabled = (get_setting(owner_id, "limit_event_notifications_enabled") or "1") != "0"
    if not enabled:
        return
    token = (os.getenv("BOT_TOKEN") or "").strip()
    if not token:
        log.warning("BOT_TOKEN missing; cannot send limit event notification")
        return
    try:
        SESSION.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": int(owner_id), "text": message},
            timeout=10,
        )
    except Exception as exc:
        log.warning("failed sending limit event notification to %s: %s", owner_id, exc)


def disable_remote(panel_type, panel_url, token, remote_username):
    try:
        if panel_type == "sanaei":
            remotes = [r.strip() for r in remote_username.split(",") if r.strip()]
            all_ok, last_msg = True, None
            for rn in remotes:
                ok, msg = sanaei.disable_remote_user(panel_url, token, rn)
                if not ok:
                    all_ok = False
                    last_msg = msg
            return (200 if all_ok else None), last_msg
        if panel_type == "guardcore":
            ok, msg = guardcore.disable_remote_user(panel_url, token, remote_username)
            return (200 if ok else None), msg
        # Try Marzneshin style first
        url = urljoin(panel_url.rstrip("/") + "/", f"api/users/{remote_username}/disable")
        r = SESSION.post(url, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if r.status_code == 200:
            return r.status_code, r.text[:200]
        # Fallback to Marzban style
        url = urljoin(panel_url.rstrip("/") + "/", f"api/user/{remote_username}")
        r = SESSION.put(
            url,
            json={"status": "disabled"},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=20,
        )
        return r.status_code, r.text[:200]
    except Exception as e:
        return None, str(e)

def _username_candidates(remote_username: str):
    if not isinstance(remote_username, str):
        return [remote_username]
    lowered = remote_username.lower()
    if lowered and lowered != remote_username:
        return [remote_username, lowered]
    return [remote_username]


@cached(cache=_fetch_user_cache, lock=_fetch_user_lock)
def fetch_user(panel_url: str, token: str, remote_username: str, panel_type: str = ""):
    panel_type = (panel_type or "").lower()
    try:
        if panel_type == "guardcore":
            user, err = guardcore.get_user(panel_url, token, remote_username)
            if err:
                return None
            if isinstance(user, dict):
                sub_link = user.get("link") or user.get("subscription_url")
                if sub_link:
                    user.setdefault("subscription_url", sub_link)
                    user.setdefault("key", sub_link)
            return user
        for candidate in _username_candidates(remote_username):
            url = urljoin(panel_url.rstrip("/") + "/", f"api/users/{candidate}")
            r = SESSION.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
            if r.status_code == 200:
                return r.json()
        # Fallback to Marzban endpoint
        for candidate in _username_candidates(remote_username):
            url = urljoin(panel_url.rstrip("/") + "/", f"api/user/{candidate}")
            r = SESSION.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
            if r.status_code != 200:
                continue
            obj = r.json()
            status = obj.get("status")
            obj["enabled"] = status != "disabled"
            sub_url = obj.get("subscription_url") or ""
            token_part = sub_url.rstrip("/").split("/")[-1]
            if token_part:
                obj.setdefault("key", token_part)
            return obj
        return None
    except:
        return None

@cached(cache=_fetch_links_cache, lock=_fetch_links_lock)
def fetch_links_from_panel(
    panel_url: str,
    remote_username: str,
    key: str,
    panel_type: str = "",
):
    """Return links and an optional error message for debugging."""
    errors = []
    panel_type = (panel_type or "").lower()
    try:
        if panel_type == "guardcore":
            links = guardcore.fetch_links_from_panel(panel_url, remote_username, key)
            if links:
                return links, None
            errors.append("guardcore links empty")
            return [], "; ".join(errors)

        # Try Marzban style first (/v2ray base64)
        url = urljoin(panel_url.rstrip("/") + "/", f"sub/{key}/v2ray")
        r = SESSION.get(url, headers={"accept": "text/plain"}, timeout=20)
        if r.status_code == 200:
            txt = (r.text or "").strip()
            if txt:
                try:
                    decoded = base64.b64decode(txt + "===")
                    txt = decoded.decode(errors="ignore")
                except Exception as e:
                    errors.append(f"v2ray b64 {e}")
                lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
                if any(ln.lower().startswith(ALLOWED_SCHEMES) for ln in lines):
                    return lines, None
                errors.append("v2ray empty")
        else:
            errors.append(f"v2ray HTTP {r.status_code}")

        # Fallback to Marzneshin style (supports lowercase usernames only)
        for candidate in _username_candidates(remote_username):
            url = urljoin(panel_url.rstrip("/") + "/", f"sub/{candidate}/{key}/links")
            r = SESSION.get(url, headers={"accept": "application/json,text/plain"}, timeout=20)
            if r.status_code != 200:
                errors.append(f"links HTTP {r.status_code} ({candidate})")
                continue
            try:
                if r.headers.get("content-type", "").startswith("application/json"):
                    data = r.json()
                    if isinstance(data, list):
                        return [str(x) for x in data], None
                    if isinstance(data, dict) and "links" in data:
                        return [str(x) for x in data["links"]], None
            except Exception as e:
                errors.append(f"json {e} ({candidate})")
            lines = [
                ln.strip()
                for ln in (r.text or "").splitlines()
                if ln.strip() and ln.strip().lower().startswith(ALLOWED_SCHEMES)
            ]
            if lines:
                return lines, None
            errors.append(f"links empty ({candidate})")
        return [], "; ".join(errors)
    except Exception as e:
        errors.append(str(e))
        return [], "; ".join(errors)


def collect_links(mapped, local_username: str, want_html: bool):
    """Fetch links for multiple panel mappings concurrently.

    Using a thread pool allows resolving subscription URLs from different
    panels in parallel which significantly reduces the overall response
    time when many panels are configured.
    """
    all_links, errors = [], []
    remote_info = None

    panel_ids = [m["panel_id"] for m in mapped]
    disabled_name_map, disabled_num_map = load_disabled_filters(panel_ids)

    def worker(l, dn_map, di_map):
        disabled_names = dn_map.get(l["panel_id"], set())
        disabled_nums = di_map.get(l["panel_id"], set())
        links, errs, rinfo = [], [], None
        if l.get("panel_type") == "sanaei":
            remotes = [r.strip() for r in l["remote_username"].split(",") if r.strip()]

            def remote_worker(rn: str):
                info = None
                if want_html:
                    u, uerr = sanaei.get_user(l["panel_url"], l["access_token"], rn)
                    if not uerr:
                        info = u
                ls, err = sanaei.fetch_links_from_panel(l["panel_url"], l["access_token"], rn)
                if err:
                    err = f"{rn}@{l['panel_url']}: {err}"
                return ls, err, info

            if len(remotes) > 1:
                inner_workers = min(3, len(remotes)) or 1
                with ThreadPoolExecutor(max_workers=inner_workers) as inner_ex:
                    futures = [inner_ex.submit(remote_worker, rn) for rn in remotes]
                    for fut in as_completed(futures):
                        ls, err, info = fut.result()
                        links.extend(ls)
                        if err:
                            errs.append(err)
                        if want_html and rinfo is None and info:
                            rinfo = info
            else:
                for rn in remotes:
                    ls, err, info = remote_worker(rn)
                    links.extend(ls)
                    if err:
                        errs.append(err)
                    if want_html and rinfo is None and info:
                        rinfo = info
        else:
            panel_type = (l.get("panel_type") or "").lower()
            if panel_type == "rebecca":
                u, uerr = rebecca.get_user(l["panel_url"], l["access_token"], l["remote_username"])
                if uerr:
                    errs.append(f"{l['remote_username']}@{l['panel_url']}: {uerr}")
                if want_html and rinfo is None and u:
                    rinfo = u
                key = u.get("key") if isinstance(u, dict) else None
                if key:
                    ls = rebecca.fetch_links_from_panel(l["panel_url"], l["remote_username"], key)
                    if not ls:
                        errs.append(f"{l['remote_username']}@{l['panel_url']}: rebecca links empty")
                    links.extend(ls)
            elif panel_type == "pasarguard":
                u, uerr = pasarguard.get_user(l["panel_url"], l["access_token"], l["remote_username"])
                if uerr:
                    errs.append(f"{l['remote_username']}@{l['panel_url']}: {uerr}")
                if want_html and rinfo is None and u:
                    rinfo = u
                key = u.get("key") if isinstance(u, dict) else None
                if key:
                    ls = pasarguard.fetch_links_from_panel(l["panel_url"], l["remote_username"], key)
                    if not ls:
                        errs.append(f"{l['remote_username']}@{l['panel_url']}: pasarguard links empty")
                    links.extend(ls)
            elif panel_type == "guardcore":
                u, uerr = guardcore.get_user(l["panel_url"], l["access_token"], l["remote_username"])
                if uerr:
                    errs.append(f"{l['remote_username']}@{l['panel_url']}: {uerr}")
                if want_html and rinfo is None and u:
                    rinfo = u
                key = u.get("key") if isinstance(u, dict) else None
                if key:
                    ls = guardcore.fetch_links_from_panel(l["panel_url"], l["remote_username"], key)
                    if not ls:
                        errs.append(f"{l['remote_username']}@{l['panel_url']}: guardcore links empty")
                    links.extend(ls)
            else:
                u = fetch_user(
                    l["panel_url"],
                    l["access_token"],
                    l["remote_username"],
                    panel_type,
                )
                if want_html and rinfo is None:
                    rinfo = u
                if u and u.get("key"):
                    ls, err = fetch_links_from_panel(
                        l["panel_url"],
                        l["remote_username"],
                        u["key"],
                        panel_type,
                    )
                    if err:
                        errs.append(f"{l['remote_username']}@{l['panel_url']}: {err}")
                    links.extend(ls)
        if disabled_names:
            links = [x for x in links if (extract_name(x) or "") not in disabled_names]
        if disabled_nums:
            links = [x for idx, x in enumerate(links, 1) if idx not in disabled_nums]
        links = [
            maybe_append_ratio_to_name(
                x,
                float(l.get("usage_multiplier") or 1.0),
                bool(l.get("append_ratio_to_name") or 0),
            )
            for x in links
        ]
        return links, errs, rinfo

    max_workers_env = int(os.getenv("FETCH_MAX_WORKERS", "5"))
    max_workers = min(max_workers_env, len(mapped)) or 1
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(worker, m, disabled_name_map, disabled_num_map) for m in mapped]
        for fut in as_completed(futures):
            ls, errs, rinfo = fut.result()
            all_links.extend(ls)
            errors.extend(errs)
            if remote_info is None and rinfo:
                remote_info = rinfo

    return all_links, errors, remote_info

def maybe_append_ratio_to_name(link: str, ratio: float, enabled: bool) -> str:
    if not enabled:
        return link
    if abs(float(ratio) - 1.0) <= 1e-9:
        return link
    if not link.lower().startswith(RATIO_NAME_SCHEMES):
        return link
    ratio_text = f"{float(ratio):g}X"

    if link.lower().startswith("vmess://"):
        b64 = link[len("vmess://"):]
        if not b64:
            return link
        is_urlsafe = "-" in b64 or "_" in b64
        padded = b64 + "=" * (-len(b64) % 4)
        try:
            raw = (
                base64.urlsafe_b64decode(padded)
                if is_urlsafe
                else base64.b64decode(padded)
            )
            obj = json.loads(raw.decode("utf-8"))
            ps = obj.get("ps")
            if not isinstance(ps, str):
                return link
            if ps.rstrip().endswith(ratio_text):
                return link
            obj["ps"] = f"{ps} {ratio_text}"
            new_raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            new_b64 = (
                base64.urlsafe_b64encode(new_raw).decode("ascii")
                if is_urlsafe
                else base64.b64encode(new_raw).decode("ascii")
            )
            if "=" not in b64:
                new_b64 = new_b64.rstrip("=")
            return f"vmess://{new_b64}"
        except Exception:
            return link

    i = link.find("#")
    if i == -1:
        return link
    try:
        name = unquote(link[i + 1:])
        if name.rstrip().endswith(ratio_text):
            return link
        name = f"{name} {ratio_text}"
        return f"{link[:i+1]}{quote(name, safe='')}"
    except Exception:
        return link

def filter_dedupe(links):
    out, seen = [], set()
    for s in links:
        ss = s.strip().strip('"').strip("'")
        if not ss.lower().startswith(ALLOWED_SCHEMES):
            continue
        if ss not in seen:
            seen.add(ss)
            out.append(ss)
    return out

def canonicalize_name(name: str) -> str:
    """Normalize a config name by stripping user-specific details."""
    try:
        nm = unquote(name or "").strip()
        nm = re.sub(r"\s*\d+(?:\.\d+)?\s*[KMGT]?B/\d+(?:\.\d+)?\s*[KMGT]?B", "", nm, flags=re.I)
        nm = re.sub(r"\s*👤.*", "", nm)
        nm = re.sub(r"\s*\([a-zA-Z0-9_-]{3,}\)", "", nm)
        nm = re.sub(r"\s+", " ", nm)
        return nm.strip()[:255]
    except Exception:
        return ""

def extract_name(link: str) -> str:
    try:
        i = link.find("#")
        if i == -1:
            return ""
        nm = link[i+1:]
        return canonicalize_name(nm)
    except Exception:
        return ""

def load_disabled_filters(panel_ids: list[int]):
    """Return disabled config names and numbers for panels in bulk."""
    if not panel_ids:
        return {}, {}
    placeholders = ",".join(["%s"] * len(panel_ids))
    names: dict[int, set[str]] = {}
    nums: dict[int, set[int]] = {}
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT panel_id, config_name FROM panel_disabled_configs WHERE panel_id IN ({placeholders})",
            tuple(panel_ids),
        )
        for r in cur.fetchall():
            cn = canonicalize_name(r.get("config_name"))
            if cn:
                names.setdefault(int(r["panel_id"]), set()).add(cn)
        cur.execute(
            f"SELECT panel_id, config_index FROM panel_disabled_numbers WHERE panel_id IN ({placeholders})",
            tuple(panel_ids),
        )
        for r in cur.fetchall():
            idx = r.get("config_index")
            if isinstance(idx, (int,)) and int(idx) > 0:
                nums.setdefault(int(r["panel_id"]), set()).add(int(idx))
    return names, nums

# ---- agent-level ----
def get_agent(owner_id: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT telegram_user_id, plan_limit_bytes, expire_at, disabled_pushed
            FROM agents
            WHERE telegram_user_id IN ({placeholders}) AND active=1
            LIMIT 1
        """,
            tuple(ids),
        )
        return cur.fetchone()

def get_agent_total_used(owner_id: int) -> int:
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT total_used_bytes AS su FROM agents WHERE telegram_user_id IN ({placeholders}) AND active=1 LIMIT 1",
            tuple(ids),
        )
        row = cur.fetchone()
        return int(row.get("su") or 0) if row else 0

def list_all_agent_links(owner_id: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT lup.local_username, lup.remote_username, p.panel_url, p.access_token, p.panel_type
            FROM local_user_panel_links lup
            JOIN panels p ON p.id = lup.panel_id
            WHERE lup.owner_id IN ({placeholders})
        """,
            tuple(ids),
        )
        return cur.fetchall()

def mark_agent_disabled(owner_id: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            UPDATE agents
            SET disabled_pushed=1, disabled_pushed_at=NOW()
            WHERE telegram_user_id IN ({placeholders})
        """,
            tuple(ids),
        )

# ---------- app ----------
app = Flask(__name__)


def create_flask_app() -> Flask:
    """Return the configured Flask subscription aggregator application."""
    return app


def bytesformat(num):
    try:
        num = float(num)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    for u in units:
        if abs(num) < 1024.0:
            return f"{num:.2f} {u}"
        num /= 1024.0
    return f"{num:.2f} PB"


def format_usage_value(num):
    """Format byte values for usage notifications using MB/GB/TB units."""
    try:
        value = float(num)
    except (TypeError, ValueError):
        value = 0.0

    mb = 1024.0 ** 2
    gb = 1024.0 ** 3
    tb = 1024.0 ** 4

    if abs(value) >= tb:
        scaled, unit = value / tb, "TB"
    elif abs(value) >= gb:
        scaled, unit = value / gb, "GB"
    else:
        scaled, unit = value / mb, "MB"

    precision = 1 if abs(scaled) >= 100 else 2
    return f"{scaled:.{precision}f} {unit}"


def _to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + g_d_m[gm - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def _parse_expire_datetime(expire_at) -> datetime | None:
    if not expire_at:
        return None
    if isinstance(expire_at, datetime):
        return expire_at
    try:
        return datetime.fromisoformat(str(expire_at))
    except Exception:
        return None


def _format_time_left(expire_dt: datetime | None, now: datetime) -> str:
    if not expire_dt:
        return "Unlimited"
    seconds = int((expire_dt - now).total_seconds())
    if seconds <= 0:
        return "Expired"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} day" + ("s" if days != 1 else ""))
    if hours:
        parts.append(f"{hours} hour" + ("s" if hours != 1 else ""))
    if minutes and not days:
        parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
    return " ".join(parts) if parts else "Less than a minute"


def _format_days_left(expire_dt: datetime | None, now: datetime) -> str:
    if not expire_dt:
        return "Unlimited"
    seconds = (expire_dt - now).total_seconds()
    if seconds <= 0:
        return "0"
    return str(max(0, int(math.ceil(seconds / 86400))))


def _replace_placeholders(template: str, values: dict[str, str]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1).upper()
        return values.get(key, match.group(0))

    return re.sub(r"\{([A-Z0-9_]+)\}", repl, template, flags=re.IGNORECASE)


def build_sub_placeholder_config(owner_id: int, local_username: str, lu) -> str | None:
    enabled = (get_setting(owner_id, SUB_PLACEHOLDER_ENABLED_KEY) or "0") != "0"
    if not enabled:
        return None
    template = (get_setting(owner_id, SUB_PLACEHOLDER_TEMPLATE_KEY) or "").strip()
    if not template:
        return None

    limit = int(lu.get("plan_limit_bytes") or 0) if lu else 0
    used = int(lu.get("used_bytes") or 0) if lu else 0
    expire_dt = _parse_expire_datetime(lu.get("expire_at") if lu else None)
    now = datetime.utcnow()

    data_left = "Unlimited" if limit <= 0 else format_usage_value(max(0, limit - used))
    data_limit = "Unlimited" if limit <= 0 else format_usage_value(limit)
    expire_date = expire_dt.strftime("%Y-%m-%d") if expire_dt else "Unlimited"
    jalali_expire_date = "Unlimited"
    if expire_dt:
        jy, jm, jd = _to_jalali(expire_dt.year, expire_dt.month, expire_dt.day)
        jalali_expire_date = f"{jy:04d}-{jm:02d}-{jd:02d}"

    values = {
        "USERNAME": local_username,
        "DATA_USAGE": format_usage_value(used),
        "DATA_LEFT": data_left,
        "DATA_LIMIT": data_limit,
        "DAYS_LEFT": _format_days_left(expire_dt, now),
        "EXPIRE_DATE": expire_date,
        "JALALI_EXPIRE_DATE": jalali_expire_date,
        "TIME_LEFT": _format_time_left(expire_dt, now),
    }
    resolved = _replace_placeholders(template, values)
    encoded = quote(resolved, safe="")
    return f"{SUB_PLACEHOLDER_BASE_CONFIG}{encoded}"


app.jinja_env.filters["bytesformat"] = bytesformat


def build_user(local_username, app_key, lu, remote=None):
    limit = int(lu.get("plan_limit_bytes") or 0) if lu else 0
    used = int(lu.get("used_bytes") or 0) if lu else 0
    expire_raw = ""
    enabled = True
    manual_disabled = bool(lu.get("manual_disabled")) if lu else False
    if remote:
        enabled = remote.get("enabled", True)
        expire_raw = (
            remote.get("expire_date")
            or remote.get("expire")
            or remote.get("expiryTime")
            or remote.get("expiry_time")
            or remote.get("expire_at")
            or ""
        )
    if not expire_raw and lu:
        exp_l = lu.get("expire_at")
        if exp_l:
            try:
                if isinstance(exp_l, datetime):
                    expire_raw = str(int(exp_l.timestamp()))
                else:
                    expire_raw = str(int(datetime.fromisoformat(str(exp_l)).timestamp()))
            except Exception:
                expire_raw = ""
    data_limit_reached = bool(limit > 0 and used >= limit)
    expired = False
    if manual_disabled:
        enabled = False
    try:
        if expire_raw:
            if isinstance(expire_raw, str) and not expire_raw.isdigit():
                exp_str = expire_raw.replace("Z", "+00:00")
                exp_ts = datetime.fromisoformat(exp_str).timestamp()
            else:
                exp_ts = float(expire_raw)
            if exp_ts > 1e12:
                exp_ts /= 1000.0
            if exp_ts > 0:
                expired = exp_ts <= datetime.utcnow().timestamp()
                expire_raw = str(int(exp_ts))
            else:
                expire_raw = ""
    except Exception:
        expired = False
        expire_raw = ""
    user = {
        "username": local_username,
        "subscription_url": f"/sub/{local_username}/{app_key}/links",
        "used_traffic": used,
        "data_limit": limit or None,
        "expire_date": expire_raw,
        "data_limit_reset_strategy": SimpleNamespace(value="no_reset"),
        "enabled": enabled,
        "manual_disabled": manual_disabled,
        "expired": expired,
        "data_limit_reached": data_limit_reached,
    }
    user["is_active"] = user["enabled"] and not user["expired"] and not user["data_limit_reached"]
    return user

@app.route("/sub/<local_username>/<app_key>/links", methods=["GET"])
def unified_links(local_username, app_key):
    owner_id = get_owner_id(local_username, app_key)
    if not owner_id:
        want_html = "text/html" in request.headers.get("Accept", "")
        if want_html:
            return (
                render_template_string(
                    ERROR_TEMPLATE,
                    title="لینک نامعتبر",
                    message="کلید اپلیکیشن یا لینک اشتباه است.",
                    detail="لطفاً لینک اشتراک را بررسی کنید یا از پشتیبانی بخواهید لینک صحیح را ارسال کند.",
                ),
                404,
            )
        abort(404)

    want_html = "text/html" in request.headers.get("Accept", "")

    lu = get_local_user(owner_id, local_username)
    if not lu:
        if want_html:
            return (
                render_template_string(
                    ERROR_TEMPLATE,
                    title="کاربر یافت نشد",
                    message="این نام کاربری در سیستم ثبت نشده است.",
                    detail="اگر تازه حساب ساخته‌اید، چند دقیقه بعد دوباره تلاش کنید یا با پشتیبانی تماس بگیرید.",
                ),
                404,
            )
        return Response("", mimetype="text/plain")

    # ---- Agent-level quota/expiry enforcement (global gate) ----
    ag = get_agent(owner_id)
    agent_blocked = False
    if ag:
        limit_b = int(ag.get("plan_limit_bytes") or 0)
        exp = ag.get("expire_at")
        pushed_a = int(ag.get("disabled_pushed", 0) or 0)
        expired = bool(exp and exp <= datetime.utcnow())
        exceeded = False
        if limit_b > 0:
            used_total = get_agent_total_used(owner_id)
            exceeded = used_total >= limit_b
        if expired or exceeded:
            agent_blocked = True
            if not pushed_a:
                for l in list_all_agent_links(owner_id):
                    code, msg = disable_remote(l["panel_type"], l["panel_url"], l["access_token"], l["remote_username"])
                    if code and code != 200:
                        log.warning("AGENT disable on %s@%s -> %s %s",
                                    l["remote_username"], l["panel_url"], code, msg)
                mark_agent_disabled(owner_id)
            if not want_html:
                return Response("", mimetype="text/plain")

    # ---- User-level expiry/usage enforcement ----
    limit = int(lu["plan_limit_bytes"])
    used = int(lu["used_bytes"])
    pushed = int(lu.get("disabled_pushed", 0) or 0)
    manual_disabled = int(lu.get("manual_disabled", 0) or 0)
    usage_notified = int(lu.get("usage_limit_notified", 0) or 0)
    expire_notified = int(lu.get("expire_limit_notified", 0) or 0)

    manual_blocked = False
    if manual_disabled:
        manual_blocked = True
        if not pushed:
            links = list_mapped_links(owner_id, local_username)
            if not links:
                panels = list_all_panels(owner_id)
                links = [{"panel_id": p["id"], "remote_username": local_username,
                          "panel_url": p["panel_url"], "access_token": p["access_token"],
                          "panel_type": p["panel_type"]} for p in panels]
            for l in links:
                code, msg = disable_remote(
                    l["panel_type"], l["panel_url"], l["access_token"], l["remote_username"]
                )
                if code and code != 200:
                    log.warning("disable on %s@%s -> %s %s", l["remote_username"], l["panel_url"], code, msg)
            mark_user_disabled(owner_id, local_username)
        if not want_html:
            return Response("", mimetype="text/plain")

    if not manual_disabled:
        exp = lu.get("expire_at")
        expired = bool(exp and exp <= datetime.utcnow())
        if expired:
            if not expire_notified:
                send_owner_limit_notification(
                    owner_id,
                    f"⏰ User {local_username} reached expiration limit.",
                )
                mark_expire_limit_notified(owner_id, local_username)
            if not pushed:
                links = list_mapped_links(owner_id, local_username)
                if not links:
                    panels = list_all_panels(owner_id)
                    links = [{"panel_id": p["id"], "remote_username": local_username,
                              "panel_url": p["panel_url"], "access_token": p["access_token"],
                              "panel_type": p["panel_type"]} for p in panels]
                for l in links:
                    code, msg = disable_remote(l["panel_type"], l["panel_url"], l["access_token"], l["remote_username"])
                    if code and code != 200:
                        log.warning("disable on %s@%s -> %s %s", l["remote_username"], l["panel_url"], code, msg)
                mark_user_disabled(owner_id, local_username)
            if not want_html:
                return Response("", mimetype="text/plain")

    limit_reached = False
    if not manual_disabled:
        if limit > 0 and used >= limit:
            limit_reached = True
            if not usage_notified:
                send_owner_limit_notification(
                    owner_id,
                    f"📊 User {local_username} exceeded usage limit ({format_usage_value(used)} / {format_usage_value(limit)}).",
                )
                mark_usage_limit_notified(owner_id, local_username)
            if not pushed:
                links = list_mapped_links(owner_id, local_username)
                if not links:
                    panels = list_all_panels(owner_id)
                    links = [{"panel_id": p["id"], "remote_username": local_username,
                              "panel_url": p["panel_url"], "access_token": p["access_token"],
                              "panel_type": p["panel_type"]} for p in panels]
                for l in links:
                    code, msg = disable_remote(l["panel_type"], l["panel_url"], l["access_token"], l["remote_username"])
                    if code and code != 200:
                        log.warning("disable on %s@%s -> %s %s", l["remote_username"], l["panel_url"], code, msg)
                mark_user_disabled(owner_id, local_username)
            if not want_html:
                limit_config = os.getenv(
                    "USER_LIMIT_REACHED_CONFIG",
                    "vless://limitreached@info.info:80?encryption=none&security=none&type=tcp&headerType=none",
                )
                msg_template = get_setting(owner_id, "limit_message") or os.getenv(
                    "USER_LIMIT_REACHED_MESSAGE",
                    "User {username} has reached data limit ({used} / {limit})",
                )
                msg = msg_template.replace("{username}", local_username)
                msg = msg.replace("{limit}", format_usage_value(limit))
                msg = msg.replace("{used}", format_usage_value(used))
                body = limit_config + "#" + quote(msg)
                resp = Response(body, mimetype="text/plain")

                resp.headers["X-Plan-Limit-Bytes"] = str(limit)
                resp.headers["X-Used-Bytes"] = str(used)
                resp.headers["X-Remaining-Bytes"] = "0"
                resp.headers["X-Disabled-Pushed"] = "1"
                return resp

    # ---- Aggregate & filter links (per-panel config-name filters) ----
    mapped = list_mapped_links(owner_id, local_username)
    all_links, errors, remote_info = [], [], None
    if not agent_blocked and not limit_reached and not manual_blocked:
        if mapped:
            all_links, errors, remote_info = collect_links(mapped, local_username, want_html)
        else:
            panels = list_all_panels(owner_id)
            mappings = [
                {
                    "panel_id": p["id"],
                    "remote_username": local_username,
                    "panel_url": p["panel_url"],
                    "access_token": p["access_token"],
                    "panel_type": p["panel_type"],
                }
                for p in panels
            ]
            all_links, errors, remote_info = collect_links(mappings, local_username, want_html)

    uniq = filter_dedupe(all_links)
    sid = lu.get("service_id") if lu else None
    emerg = None
    if sid:
        emerg = get_setting(owner_id, f"emergency_config_service_{sid}")
    if not emerg:
        emerg = get_setting(owner_id, "emergency_config")
    if emerg:
        uniq.append(emerg.strip())
        uniq = filter_dedupe(uniq)
    placeholder_config = build_sub_placeholder_config(owner_id, local_username, lu)
    if placeholder_config and uniq:
        uniq.insert(0, placeholder_config)
        uniq = filter_dedupe(uniq)
    if uniq:
        body = "\n".join(uniq) + "\n"
    elif errors:
        body = "\n".join(f"# {e}" for e in errors) + "\n"
    else:
        body = ""

    remaining = (limit - used) if limit > 0 else -1
    if want_html:
        user = build_user(local_username, app_key, lu, remote_info)
        return render_template_string(HTML_TEMPLATE, user=user)
    resp = Response(body, mimetype="text/plain")
    resp.headers["X-Plan-Limit-Bytes"] = str(limit)
    resp.headers["X-Used-Bytes"] = str(used)
    resp.headers["X-Remaining-Bytes"] = str(max(0, remaining)) if remaining >= 0 else "unlimited"
    resp.headers["X-Disabled-Pushed"] = str(pushed)
    return resp


@app.route("/", methods=["GET"])
def landing_page():
    return render_template_string(LANDING_TEMPLATE)


@app.errorhandler(404)
def not_found(_error):
    want_html = "text/html" in request.headers.get("Accept", "")
    if want_html:
        return (
            render_template_string(
                ERROR_TEMPLATE,
                title="یافت نشد",
                message="صفحه مورد نظر وجود ندارد.",
                detail="آدرس را بررسی کنید یا به صفحه اصلی بازگردید.",
            ),
            404,
        )
    return Response("Not found", status=404)

def main():
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    cert = os.getenv("SSL_CERT_PATH")
    key = os.getenv("SSL_KEY_PATH")
    ssl_context = (cert, key) if cert and key else None
    app.run(host=host, port=port, debug=False, ssl_context=ssl_context)

if __name__ == "__main__":
    main()
