#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram bot + MySQL (local users + panels) with Admin/Agent roles

Admin:
- Manage panels (add/edit creds/template/sub url, per-panel config filter)
- Remove panel (disables all mapped users on that panel first)
- Manage agents: add/edit (name), set agent quota (bytes), renew expiry by **days**, activate/deactivate
- Assign services to agents (independent toggles)
- Manage services (group panels under a service)
Agent:
- New local user (assign a service)
- Search/list users
- Edit user (limit/reset/renew + change service)

Shared:
- Unified subscription link per user
- Remote disable/enable logic preserved

ENV:
- BOT_TOKEN
- ADMIN_IDS="11111,22222" (Telegram user IDs for admins)
- MYSQL_*  , PUBLIC_BASE_URL
"""

import os
import logging
import secrets
import re
import json
import uuid
import io
from urllib.parse import urlparse, unquote
from datetime import datetime, timedelta, timezone
import asyncio

from dotenv import load_dotenv
from mysql.connector import Error as MySQLError
import qrcode

from apis import marzneshin, marzban, rebecca, sanaei, pasarguard, guardcore

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ConversationHandler,
    MessageHandler, ContextTypes, filters,
)

from api.subscription_aggregator import (
    admin_ids,
    expand_owner_ids,
    canonical_owner_id,
)
from api.admin import get_agent_usage_by_panel as fetch_agent_usage_by_panel
from services import (
    init_mysql_pool,
    with_mysql_cursor,
    ensure_schema,
    get_agent_record,
    get_agent_token_value,
    rotate_agent_token_value,
    get_admin_token,
    rotate_admin_token,
    set_agent_quota,
    set_agent_user_limit,
    set_agent_max_user_bytes,
    renew_agent_days,
    set_agent_active,
    get_setting,
    set_setting,
    TokenEncryptionError as PanelTokenEncryptionError,
    encrypt_panel_password,
    ensure_panel_tokens,
)
from models.admins import TokenEncryptionError as AdminTokenEncryptionError

# ---------- logging ----------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("marz_bot")

# ---------- api helpers ----------
PANEL_TYPES = ("marzneshin", "marzban", "rebecca", "sanaei", "pasarguard", "guardcore")
API_MODULES = {
    "marzneshin": marzneshin,
    "marzban": marzban,
    "rebecca": rebecca,
    "sanaei": sanaei,
    "pasarguard": pasarguard,
    "guardcore": guardcore,
}

def get_api(panel_type: str):
    return API_MODULES.get(panel_type or "marzneshin", marzneshin)


def panel_username(panel_type: str, username: str) -> str:
    """Return panel-specific username representation."""

    value = str(username or "").strip()
    if (panel_type or "").lower() == "guardcore":
        return value.lower()
    return value

# ---------- proxy helpers ----------
def clone_proxy_settings(proxies: dict) -> dict:
    """Copy proxy settings and regenerate credentials.

    Ensures each created user receives unique identifiers instead of reusing
    UUIDs or passwords from the template user.
    """
    cleaned = {}
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

# ---------- roles ----------
def is_admin(tg_id: int) -> bool:
    return tg_id in admin_ids()


def get_manage_owner_id(context: ContextTypes.DEFAULT_TYPE, actor_id: int) -> int:
    owner_id = int(context.user_data.get("manage_owner_id") or actor_id)
    if owner_id != actor_id and not is_admin(actor_id):
        return actor_id
    return owner_id

# ---------- states ----------
(
    ASK_PANEL_NAME, ASK_PANEL_TYPE, ASK_PANEL_URL, ASK_PANEL_USER, ASK_PANEL_PASS,
    ASK_NEWUSER_NAME, ASK_PRESET_CHOICE, ASK_LIMIT_GB, ASK_DURATION,
    ASK_SEARCH_USER, ASK_PANEL_TEMPLATE,
    ASK_EDIT_LIMIT, ASK_RENEW_DAYS,
    ASK_EDIT_PANEL_NAME, ASK_EDIT_PANEL_USER, ASK_EDIT_PANEL_PASS,
    ASK_SELECT_SERVICE,
    ASK_PANEL_SUB_URL,
    ASK_PANEL_MULTIPLIER,
    ASK_PANEL_API_KEY,

    # agent mgmt
    ASK_AGENT_NAME, ASK_AGENT_TGID,
    ASK_AGENT_LIMIT, ASK_AGENT_RENEW_DAYS,   # changed: renew by days
    ASK_AGENT_MAX_USERS, ASK_AGENT_MAX_USER_GB,
    ASK_ASSIGN_AGENT_PANELS,
    ASK_PANEL_REMOVE_CONFIRM,

    # service mgmt
    ASK_SERVICE_NAME, ASK_EDIT_SERVICE_NAME, ASK_ASSIGN_SERVICE_PANELS,

    # preset mgmt
    ASK_PRESET_GB, ASK_PRESET_DAYS,

    # settings
    ASK_LIMIT_MSG,
    ASK_SUB_PLACEHOLDER_TEMPLATE,
    ASK_SERVICE_EMERGENCY_CFG,
    ASK_EXTRA_SUB_DOMAINS,
    ASK_NEAR_LIMIT_THRESHOLD,
    ASK_NEAR_LIMIT_SYNC_INTERVAL,
    ASK_NORMAL_SYNC_INTERVAL,
) = range(40)

# ---------- helpers ----------
UNIT = 1024
MIN_GUARDCORE_CREATE_LIMIT_BYTES = 20 * (UNIT**3)
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{2,19}$")

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
        if ch.isdigit() or ch in ".,": num += ch.replace(",", ".")
        else: unit += ch
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


def _usage_sync_threshold_text(owner_id: int) -> str:
    return (get_setting(owner_id, "usage_sync_near_limit_threshold") or "10%").strip() or "10%"


def _usage_sync_minutes(owner_id: int, key: str, default_minutes: int) -> int:
    raw = (get_setting(owner_id, key) or "").strip()
    if not raw:
        return default_minutes
    try:
        val = int(float(raw))
    except Exception:
        return default_minutes
    return max(1, val)


def _parse_sync_minutes_input(raw: str) -> int | None:
    txt = (raw or "").strip().lower().replace("minutes", "").replace("minute", "").replace("min", "")
    txt = txt.strip()
    try:
        val = int(float(txt))
    except Exception:
        return None
    return val if val > 0 else None


def _propagate_admin_setting_to_agents(key: str, value: str) -> None:
    """Mirror an admin setting to all agents so worker loops read a consistent value."""
    agent_key_map = {
        "near_limit_sync_interval": "agent_near_limit_sync_interval",
        "normal_sync_interval": "agent_normal_sync_interval",
    }
    agent_key = agent_key_map.get(key)
    with with_mysql_cursor() as cur:
        cur.execute("SELECT telegram_user_id FROM agents")
        rows = cur.fetchall()
    for row in rows:
        tg_id = row.get("telegram_user_id")
        if tg_id is None:
            continue
        set_setting(int(tg_id), key, value)
        if agent_key:
            set_setting(int(tg_id), agent_key, value)


def is_valid_local_username(username: str) -> bool:
    return bool(USERNAME_RE.fullmatch((username or "").strip()))


def service_has_guardcore_panel(service_id: int) -> bool:
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM service_panels sp
            JOIN panels p ON p.id = sp.panel_id
            WHERE sp.service_id=%s AND LOWER(COALESCE(p.panel_type, ''))='guardcore'
            LIMIT 1
            """,
            (service_id,),
        )
        return bool(cur.fetchone())

def make_panel_name(url, u):
    try:
        h = urlparse(url).hostname or url
    except Exception:
        h = url

def normalize_domain_entry(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        host = parsed.netloc or parsed.path
    else:
        host = value
    host = host.split("/", 1)[0].strip()
    return host.lower()

def parse_extra_domains(raw: str) -> list[str]:
    if not raw:
        return []
    entries = []
    seen = set()
    for part in re.split(r"[,\n]+", raw):
        host = normalize_domain_entry(part)
        if not host or host in seen:
            continue
        entries.append(host)
        seen.add(host)
    return entries


def _back_kb(callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back", callback_data=callback_data)]]
    )

def _sub_placeholder_toggle_label(owner_id: int) -> str:
    enabled = (get_setting(owner_id, "subscription_placeholder_enabled") or "0") != "0"
    return "🟢 Sub Placeholder: ON" if enabled else "🔴 Sub Placeholder: OFF"

def _agent_technical_kb(owner_id: int) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton(_sub_placeholder_toggle_label(owner_id), callback_data="toggle_sub_placeholder")],
        [InlineKeyboardButton("🧩 Sub Placeholder Template", callback_data="sub_placeholder_template")],
        [InlineKeyboardButton("⬅️ Back", callback_data="back_home")],
    ]
    return InlineKeyboardMarkup(kb)


def _admin_technical_kb(owner_id: int) -> InlineKeyboardMarkup:
    notif_enabled = (get_setting(owner_id, "limit_event_notifications_enabled") or "1") != "0"
    notif_label = "🟢 Limit Event Notifications: ON" if notif_enabled else "🔴 Limit Event Notifications: OFF"
    threshold_text = _usage_sync_threshold_text(owner_id)
    near_minutes = _usage_sync_minutes(owner_id, "near_limit_sync_interval", 5)
    normal_minutes = _usage_sync_minutes(owner_id, "normal_sync_interval", 10)
    kb = [
        [InlineKeyboardButton(notif_label, callback_data="toggle_limit_event_notifications")],
        [InlineKeyboardButton(_sub_placeholder_toggle_label(owner_id), callback_data="toggle_sub_placeholder")],
        [InlineKeyboardButton("🧩 Sub Placeholder Template", callback_data="sub_placeholder_template")],
        [InlineKeyboardButton(f"⚠️ Near-Limit Threshold: {threshold_text}", callback_data="set_near_limit_threshold")],
        [InlineKeyboardButton(f"⏱️ Near-Limit Sync: {near_minutes}m", callback_data="set_near_limit_sync_interval")],
        [InlineKeyboardButton(f"⏱️ Normal Sync: {normal_minutes}m", callback_data="set_normal_sync_interval")],
        [InlineKeyboardButton("💬 Limit Message", callback_data="limit_msg")],
        [InlineKeyboardButton("🌐 Extra Sub Domains", callback_data="extra_sub_domains")],
        [InlineKeyboardButton("🔑 Admin Token", callback_data="admin_token")],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")],
    ]
    return InlineKeyboardMarkup(kb)


def get_extra_domains(owner_id: int) -> list[str]:
    settings_owner = owner_id
    if not is_admin(owner_id):
        admins = sorted(admin_ids())
        if admins:
            settings_owner = admins[0]
    raw = get_setting(settings_owner, "extra_sub_domains") or ""
    return parse_extra_domains(raw)

def build_sub_links(owner_id: int, username: str, app_key: str) -> list[str]:
    public_base = os.getenv("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")
    parsed = urlparse(public_base)
    scheme = parsed.scheme or "https"
    base_host = (parsed.netloc or parsed.path).lower()
    links = [f"{public_base}/sub/{username}/{app_key}/links"]
    for host in get_extra_domains(owner_id):
        if host == base_host:
            continue
        links.append(f"{scheme}://{host}/sub/{username}/{app_key}/links")
    return links

def format_sub_links_html(links: list[str]) -> str:
    if not links:
        return "🔗 Sub: —"
    if len(links) == 1:
        return f"🔗 Sub: <code>{links[0]}</code>"
    lines = ["🔗 Sub Links:"]
    lines.extend([f"• <code>{link}</code>" for link in links])
    return "\n".join(lines)

def format_sub_links_text(links: list[str]) -> str:
    if not links:
        return "🔗 Sub: —"
    if len(links) == 1:
        return f"🔗 {links[0]}"
    lines = ["🔗 Links:"]
    lines.extend([f"• {link}" for link in links])
    return "\n".join(lines)
    h = str(h).replace("www.", "")
    base = f"{h}-{u}".strip("-")
    return (base[:120] if len(base) > 120 else base) or "panel"

def generate_qr_png(data: str) -> io.BytesIO:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    buf.name = "qr.png"
    return buf

# ---------- data access ----------
def list_my_panels_admin(admin_tg_id: int):
    ids = expand_owner_ids(admin_tg_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT * FROM panels WHERE telegram_user_id IN ({placeholders}) ORDER BY created_at DESC",
            tuple(ids),
        )
        rows = cur.fetchall()
    return ensure_panel_tokens(rows)

def list_panels_for_agent(agent_tg_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("""
            SELECT p.* FROM agent_panels ap
            JOIN panels p ON p.id = ap.panel_id
            WHERE ap.agent_tg_id=%s
            ORDER BY p.created_at DESC
        """, (agent_tg_id,))
        rows = cur.fetchall()
    return ensure_panel_tokens(rows)

# ----- service helpers -----
def create_service(name: str) -> int:
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute("INSERT INTO services(name) VALUES(%s)", (name,))
        return cur.lastrowid

def list_services():
    with with_mysql_cursor() as cur:
        cur.execute("SELECT * FROM services ORDER BY created_at DESC")
        return cur.fetchall()


def list_services_for_owner(owner_id: int):
    if is_admin(owner_id):
        return list_services()

    with with_mysql_cursor() as cur:
        cur.execute(
            """
            SELECT s.*
            FROM agent_services ags
            JOIN services s ON s.id = ags.service_id
            WHERE ags.agent_tg_id=%s
            ORDER BY s.created_at DESC
            """,
            (owner_id,),
        )
        return cur.fetchall()

def get_service(sid: int):
    with with_mysql_cursor() as cur:
        cur.execute("SELECT * FROM services WHERE id=%s", (sid,))
        return cur.fetchone()

def list_service_panel_ids(service_id: int) -> set[int]:
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute("SELECT panel_id FROM service_panels WHERE service_id=%s", (service_id,))
        return {int(r[0]) for r in cur.fetchall()}

def set_service_panels(service_id: int, panel_ids: set[int]):
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute("DELETE FROM service_panels WHERE service_id=%s", (service_id,))
        if panel_ids:
            cur.executemany(
                "INSERT INTO service_panels(service_id,panel_id) VALUES(%s,%s)",
                [(service_id, int(pid)) for pid in panel_ids],
            )

def list_agents_by_service(service_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("SELECT agent_tg_id FROM agent_services WHERE service_id=%s", (service_id,))
        return [int(r["agent_tg_id"]) for r in cur.fetchall()]


def list_agent_service_ids(agent_tg_id: int) -> set[int]:
    with with_mysql_cursor() as cur:
        cur.execute("SELECT service_id FROM agent_services WHERE agent_tg_id=%s", (agent_tg_id,))
        return {int(r["service_id"]) for r in cur.fetchall()}


def _service_panel_union(service_ids: set[int]) -> set[int]:
    panel_ids: set[int] = set()
    for sid in service_ids:
        panel_ids.update(list_service_panel_ids(int(sid)))
    return panel_ids


def set_agent_services(agent_tg_id: int, service_ids: set[int]):
    clean_ids = {int(sid) for sid in service_ids}
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute("DELETE FROM agent_services WHERE agent_tg_id=%s", (agent_tg_id,))
        if clean_ids:
            cur.executemany(
                "INSERT INTO agent_services(agent_tg_id,service_id) VALUES(%s,%s)",
                [(agent_tg_id, sid) for sid in sorted(clean_ids)],
            )
    set_agent_panels(agent_tg_id, _service_panel_union(clean_ids))

def list_local_users_by_service(service_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("SELECT owner_id, username FROM local_users WHERE service_id=%s", (service_id,))
        return cur.fetchall()

def set_agent_service(agent_tg_id: int, service_id: int | None):
    # Backward-compatible shim: single service assignment means replacing all assignments.
    set_agent_services(agent_tg_id, ({int(service_id)} if service_id else set()))

def resolve_local_user_owner(owner_id: int, username: str) -> int | None:
    """Return the concrete owner ID for a given local user accessible to ``owner_id``."""

    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT owner_id FROM local_users WHERE owner_id IN ({placeholders}) AND username=%s LIMIT 1",
            tuple(ids) + (username,),
        )
        row = cur.fetchone()
        return int(row["owner_id"]) if row else None


async def set_local_user_service(owner_id: int, username: str, service_id: int | None):
    real_owner = resolve_local_user_owner(owner_id, username)
    if real_owner is None:
        log.info(
            "set_local_user_service skip: owner=%s username=%s not found", owner_id, username
        )
        return

    params: list[object] = [service_id, real_owner, username]
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            "UPDATE local_users SET service_id=%s WHERE owner_id=%s AND username=%s",
            params,
        )
    pids = list_service_panel_ids(service_id) if service_id else set()
    await sync_user_panels_async(real_owner, username, pids)

async def propagate_service_panels(service_id: int):
    """After service panels change, update agents/users accordingly."""
    pids = list_service_panel_ids(service_id)
    for ag_id in list_agents_by_service(service_id):
        set_agent_panels(ag_id, pids)

    rows = list_local_users_by_service(service_id)
    total = len(rows)

    async def _sync(idx: int, row: dict):
        owner_id = row["owner_id"]
        username = row["username"]
        log.info("sync_user_panels start %d/%d: %s/%s", idx, total, owner_id, username)
        await sync_user_panels_async(owner_id, username, pids)
        log.info("sync_user_panels done %d/%d: %s/%s", idx, total, owner_id, username)

    if rows:
        await asyncio.gather(*(_sync(i + 1, r) for i, r in enumerate(rows)))
    log.info("propagate_service_panels complete for service %s", service_id)

# ----- preset helpers -----
def list_presets(owner_id: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT * FROM account_presets WHERE telegram_user_id IN ({placeholders}) ORDER BY created_at DESC",
            tuple(ids),
        )
        return cur.fetchall()

def create_preset(owner_id: int, limit_bytes: int, duration_days: int) -> int:
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            "INSERT INTO account_presets(telegram_user_id,limit_bytes,duration_days)VALUES(%s,%s,%s)",
            (canonical_owner_id(owner_id), limit_bytes, duration_days),
        )
        return cur.lastrowid

def delete_preset(owner_id: int, preset_id: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = [preset_id] + ids
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            f"DELETE FROM account_presets WHERE id=%s AND telegram_user_id IN ({placeholders})",
            tuple(params),
        )

def get_preset(owner_id: int, preset_id: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = [preset_id] + ids
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT * FROM account_presets WHERE id=%s AND telegram_user_id IN ({placeholders})",
            tuple(params),
        )
        return cur.fetchone()


def update_preset(owner_id: int, preset_id: int, limit_bytes: int, duration_days: int):
    with with_mysql_cursor(dict_=False) as cur:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        params = [limit_bytes, duration_days, preset_id] + ids
        cur.execute(
            f"UPDATE account_presets SET limit_bytes=%s, duration_days=%s WHERE id=%s AND telegram_user_id IN ({placeholders})",
            tuple(params),
        )

def upsert_app_user(tg_id: int, u: str) -> str:
    owner_ids = expand_owner_ids(tg_id)
    placeholders = ",".join(["%s"] * len(owner_ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT app_key FROM app_users WHERE telegram_user_id IN ({placeholders}) AND username=%s",
            tuple(owner_ids) + (u,),
        )
        row = cur.fetchone()
        if row:
            return row["app_key"]
        k = secrets.token_hex(16)
        cur.execute(
            "INSERT INTO app_users(telegram_user_id,username,app_key)VALUES(%s,%s,%s)",
            (canonical_owner_id(tg_id), u, k),
        )
        return k

def get_app_key(tg_id: int, u: str) -> str:
    owner_ids = expand_owner_ids(tg_id)
    placeholders = ",".join(["%s"] * len(owner_ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT app_key FROM app_users WHERE telegram_user_id IN ({placeholders}) AND username=%s",
            tuple(owner_ids) + (u,),
        )
        row = cur.fetchone()
    return row["app_key"] if row else upsert_app_user(tg_id, u)

def _generate_unique_local_user_key(cur) -> str:
    """Generate a unique access key for a local user."""

    while True:
        candidate = uuid.uuid4().hex
        cur.execute(
            "SELECT 1 FROM local_user_keys WHERE access_key=%s LIMIT 1",
            (candidate,),
        )
        if not cur.fetchone():
            return candidate


def _ensure_local_user_key(cur, local_user_id: int, expires_at: datetime | None) -> str:
    """Ensure a local user has an associated access key."""

    cur.execute(
        "SELECT access_key, expires_at FROM local_user_keys WHERE local_user_id=%s LIMIT 1",
        (local_user_id,),
    )
    row = cur.fetchone()
    if row:
        if row.get("expires_at") != expires_at:
            cur.execute(
                "UPDATE local_user_keys SET expires_at=%s WHERE local_user_id=%s",
                (expires_at, local_user_id),
            )
        return row["access_key"]

    access_key = _generate_unique_local_user_key(cur)
    cur.execute(
        "INSERT INTO local_user_keys(local_user_id, access_key, expires_at) VALUES (%s,%s,%s)",
        (local_user_id, access_key, expires_at),
    )
    return access_key


def upsert_local_user(owner_id: int, username: str, limit_bytes: int, duration_days: int):
    exp = datetime.utcnow() + timedelta(days=duration_days) if duration_days > 0 else None
    canonical_owner = canonical_owner_id(owner_id)
    with with_mysql_cursor() as cur:
        cur.execute(
            """INSERT INTO local_users(owner_id,username,plan_limit_bytes,expire_at,disabled_pushed)
               VALUES(%s,%s,%s,%s,0)
               ON DUPLICATE KEY UPDATE
                   plan_limit_bytes=VALUES(plan_limit_bytes),
                   expire_at=VALUES(expire_at),
                   usage_limit_notified=0,
                   expire_limit_notified=0""",
            (canonical_owner, username, int(limit_bytes), exp)
        )
        cur.execute(
            "SELECT id FROM local_users WHERE owner_id=%s AND username=%s LIMIT 1",
            (canonical_owner, username),
        )
        row = cur.fetchone()
        if row:
            _ensure_local_user_key(cur, int(row["id"]), exp)

def save_link(owner_id: int, local_username: str, panel_id: int, remote_username: str):
    with with_mysql_cursor() as cur:
        cur.execute(
            """INSERT INTO local_user_panel_links(owner_id,local_username,panel_id,remote_username)
               VALUES(%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE remote_username=VALUES(remote_username)""",
            (canonical_owner_id(owner_id), local_username, panel_id, remote_username)
        )

def remove_link(owner_id: int, local_username: str, panel_id: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"DELETE FROM local_user_panel_links WHERE owner_id IN ({placeholders}) AND local_username=%s AND panel_id=%s",
            tuple(ids) + (local_username, panel_id)
        )

def list_linked_panel_ids(owner_id: int, local_username: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT panel_id FROM local_user_panel_links WHERE owner_id IN ({placeholders}) AND local_username=%s",
            tuple(ids) + (local_username,)
        )
        return {int(r["panel_id"]) for r in cur.fetchall()}

def map_linked_remote_usernames(owner_id: int, local_username: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT panel_id, remote_username FROM local_user_panel_links WHERE owner_id IN ({placeholders}) AND local_username=%s",
            tuple(ids) + (local_username,)
        )
        return {int(r["panel_id"]): r["remote_username"] for r in cur.fetchall()}

def get_local_user(owner_id: int, username: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT username,plan_limit_bytes,used_bytes,expire_at,manual_disabled,disabled_pushed FROM local_users "
            f"WHERE owner_id IN ({placeholders}) AND username=%s LIMIT 1",
            tuple(ids) + (username,)
        )
        return cur.fetchone()

def search_local_users(owner_id: int, q: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT username FROM local_users WHERE owner_id IN ({placeholders}) AND LOWER(username) LIKE LOWER(%s) ORDER BY username ASC LIMIT 50",
            tuple(ids) + (f"%{q}%",)
        )
        return cur.fetchall()

def list_all_local_users(owner_id: int, offset: int = 0, limit: int = 25):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT username FROM local_users WHERE owner_id IN ({placeholders}) ORDER BY username ASC LIMIT %s OFFSET %s",
            tuple(ids) + (limit, offset)
        )
        return cur.fetchall()

def count_local_users(owner_id: int) -> int:
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) c FROM local_users WHERE owner_id IN ({placeholders})",
            tuple(ids)
        )
        return int(cur.fetchone()["c"])

def update_limit(owner_id: int, username: str, new_limit_bytes: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""SELECT plan_limit_bytes, used_bytes, expire_at, manual_disabled, disabled_pushed
                FROM local_users
                WHERE owner_id IN ({placeholders}) AND username=%s
                LIMIT 1""",
            tuple(ids) + (username,),
        )
        row = cur.fetchone()
    if not row:
        return
    current_limit = int(row.get("plan_limit_bytes") or 0)
    used = int(row.get("used_bytes") or 0)
    manual_disabled = bool(row.get("manual_disabled") or 0)
    exp = row.get("expire_at")
    expired = bool(exp and exp <= datetime.utcnow())
    effective_limit = max(0, int(new_limit_bytes))
    params = [int(effective_limit)] + ids + [username]
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""UPDATE local_users
                SET plan_limit_bytes=%s,
                    usage_limit_notified=0
                WHERE owner_id IN ({placeholders}) AND username=%s""",
            params
        )
        if not manual_disabled and not expired and (effective_limit == 0 or used < effective_limit):
            cur.execute(
                f"""UPDATE local_users
                    SET disabled_pushed=0,
                        disabled_pushed_at=NULL
                    WHERE owner_id IN ({placeholders}) AND username=%s""",
                tuple(ids) + (username,),
            )
    for row in list_user_links(owner_id, username):
        api = get_api(row.get("panel_type"))
        remotes = (
            row["remote_username"].split(",")
            if row.get("panel_type") == "sanaei"
            else [row["remote_username"]]
        )
        for rn in remotes:
            ok, err = api.update_remote_user(
                row["panel_url"], row["access_token"], rn, data_limit=effective_limit
            )
            if not ok:
                log.warning("remote limit update failed on %s: %s", row["panel_url"], err)
            if not manual_disabled and not expired and (effective_limit == 0 or used < effective_limit):
                ok_en, err_en = api.enable_remote_user(
                    row["panel_url"], row["access_token"], rn
                )
                if not ok_en:
                    log.warning("remote enable failed on %s: %s", row["panel_url"], err_en)

def set_user_disabled(owner_id: int, username: str, disabled: bool):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""SELECT plan_limit_bytes, used_bytes, expire_at
                FROM local_users
                WHERE owner_id IN ({placeholders}) AND username=%s
                LIMIT 1""",
            tuple(ids) + (username,),
        )
        row = cur.fetchone()
    if not row:
        return
    limit = int(row.get("plan_limit_bytes") or 0)
    used = int(row.get("used_bytes") or 0)
    exp = row.get("expire_at")
    expired = bool(exp and exp <= datetime.utcnow())
    over_limit = limit > 0 and used >= limit
    should_enable = not disabled and not expired and not over_limit

    if disabled:
        manual_flag = 1
        pushed_flag = 1
        pushed_at = "UTC_TIMESTAMP()"
    elif should_enable:
        manual_flag = 0
        pushed_flag = 0
        pushed_at = "NULL"
    else:
        manual_flag = 0
        pushed_flag = 1
        pushed_at = "UTC_TIMESTAMP()"

    params = [manual_flag, pushed_flag] + ids + [username]
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""UPDATE local_users
                SET manual_disabled=%s,
                    disabled_pushed=%s,
                    disabled_pushed_at={pushed_at}
                WHERE owner_id IN ({placeholders}) AND username=%s""",
            params,
        )

    for row in list_user_links(owner_id, username):
        api = get_api(row.get("panel_type"))
        remotes = (
            row["remote_username"].split(",")
            if row.get("panel_type") == "sanaei"
            else [row["remote_username"]]
        )
        for rn in remotes:
            if disabled:
                ok, err = api.disable_remote_user(
                    row["panel_url"], row["access_token"], rn
                )
                if not ok:
                    log.warning("remote disable failed on %s: %s", row["panel_url"], err)
            elif should_enable:
                ok, err = api.enable_remote_user(
                    row["panel_url"], row["access_token"], rn
                )
                if not ok:
                    log.warning("remote enable failed on %s: %s", row["panel_url"], err)
            else:
                ok, err = api.disable_remote_user(
                    row["panel_url"], row["access_token"], rn
                )
                if not ok:
                    log.warning("remote disable failed on %s: %s", row["panel_url"], err)

def reset_used(owner_id: int, username: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = ids + [username]
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT used_bytes FROM local_users WHERE owner_id IN ({placeholders}) AND username=%s LIMIT 1",
            params,
        )
        cur.fetchone()
        cur.execute(
            f"""UPDATE local_users
                SET used_bytes=0,
                    usage_limit_notified=0
                WHERE owner_id IN ({placeholders}) AND username=%s""",
            params,
        )
    for row in list_user_links(owner_id, username):
        api = get_api(row.get("panel_type"))
        remotes = (
            row["remote_username"].split(",")
            if row.get("panel_type") == "sanaei"
            else [row["remote_username"]]
        )
        for rn in remotes:
            ok, err = api.reset_remote_user_usage(
                row["panel_url"], row["access_token"], rn
            )
            if not ok:
                log.warning("remote reset failed on %s: %s", row["panel_url"], err)

def renew_user(owner_id: int, username: str, add_days: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = [add_days, add_days] + ids + [username]
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""UPDATE local_users
               SET expire_at = IF(expire_at IS NULL, UTC_TIMESTAMP() + INTERVAL %s DAY,
                                    expire_at + INTERVAL %s DAY),
                   expire_limit_notified=0
               WHERE owner_id IN ({placeholders}) AND username=%s""",
            params
        )
        cur.execute(
            f"""SELECT expire_at, plan_limit_bytes, used_bytes, manual_disabled
                FROM local_users
                WHERE owner_id IN ({placeholders}) AND username=%s""",
            tuple(ids) + (username,),
        )
        row = cur.fetchone()
    expire_ts = 0
    manual_disabled = bool(row.get("manual_disabled") or 0) if row else False
    limit = int(row.get("plan_limit_bytes") or 0) if row else 0
    used = int(row.get("used_bytes") or 0) if row else 0
    if row and row.get("expire_at"):
        expire_dt = row["expire_at"]
        if isinstance(expire_dt, datetime):
            expire_ts = int(expire_dt.replace(tzinfo=timezone.utc).timestamp())
    expired = bool(row and row.get("expire_at") and row.get("expire_at") <= datetime.utcnow())
    should_enable = bool(row) and not manual_disabled and not expired and (limit == 0 or used < limit)
    if should_enable:
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""UPDATE local_users
                    SET disabled_pushed=0,
                        disabled_pushed_at=NULL
                    WHERE owner_id IN ({placeholders}) AND username=%s""",
                tuple(ids) + (username,),
            )
    for r in list_user_links(owner_id, username):
        api = get_api(r.get("panel_type"))
        remotes = (
            r["remote_username"].split(",")
            if r.get("panel_type") == "sanaei"
            else [r["remote_username"]]
        )
        for rn in remotes:
            ok, err = api.update_remote_user(
                r["panel_url"], r["access_token"], rn, expire=expire_ts
            )
            if not ok:
                log.warning("remote renew failed on %s: %s", r["panel_url"], err)
            if should_enable:
                ok_en, err_en = api.enable_remote_user(
                    r["panel_url"], r["access_token"], rn
                )
                if not ok_en:
                    log.warning("remote enable failed on %s: %s", r["panel_url"], err_en)


def list_user_links(owner_id: int, local_username: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""SELECT lup.panel_id, lup.remote_username,
                      p.panel_url, p.access_token, p.panel_type,
                      p.admin_username, p.admin_password_encrypted
                 FROM local_user_panel_links lup
                 JOIN panels p ON p.id = lup.panel_id
                 WHERE lup.owner_id IN ({placeholders}) AND lup.local_username=%s""",
            tuple(ids) + (local_username,),
        )
        rows = cur.fetchall()
    return ensure_panel_tokens(rows)


def delete_local_user(owner_id: int, username: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = tuple(ids) + (username,)
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT used_bytes FROM local_users WHERE owner_id IN ({placeholders}) AND username=%s LIMIT 1",
            params,
        )
        cur.fetchone()
        cur.execute(
            f"DELETE FROM local_user_panel_links WHERE owner_id IN ({placeholders}) AND local_username=%s",
            params,
        )
        cur.execute(
            f"DELETE FROM local_users WHERE owner_id IN ({placeholders}) AND username=%s",
            params,
        )
        cur.execute(
            f"DELETE FROM app_users WHERE telegram_user_id IN ({placeholders}) AND username=%s",
            params,
        )


def delete_user(owner_id: int, username: str):
    rows = list_user_links(owner_id, username)
    for r in rows:
        try:
            api = get_api(r.get("panel_type"))
            remotes = (
                r["remote_username"].split(",")
                if r.get("panel_type") == "sanaei"
                else [r["remote_username"]]
            )
            for rn in remotes:
                ok, err = api.remove_remote_user(r["panel_url"], r["access_token"], rn)
                if not ok:
                    log.warning(
                        "remote delete failed on %s@%s: %s",
                        rn,
                        r["panel_url"],
                        err or "unknown",
                    )
        except Exception as e:
            log.warning("remote delete exception: %s", e)
    delete_local_user(owner_id, username)

# panels extra
def set_panel_sub_url(owner_id: int, panel_id: int, sub_url: str | None):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = [sub_url, int(panel_id)] + ids
    with with_mysql_cursor() as cur:
        cur.execute(
            f"UPDATE panels SET sub_url=%s WHERE id=%s AND telegram_user_id IN ({placeholders})",
            params
        )

def set_panel_api_key(owner_id: int, panel_id: int, api_key: str | None):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = [api_key, int(panel_id)] + ids
    with with_mysql_cursor() as cur:
        cur.execute(
            f"UPDATE panels SET access_token=%s WHERE id=%s AND telegram_user_id IN ({placeholders})",
            params,
        )


def set_panel_append_ratio_to_name(owner_id: int, panel_id: int, enabled: bool):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = [1 if enabled else 0, int(panel_id)] + ids
    with with_mysql_cursor() as cur:
        cur.execute(
            f"UPDATE panels SET append_ratio_to_name=%s WHERE id=%s AND telegram_user_id IN ({placeholders})",
            params,
        )

def get_panel(owner_id: int, panel_id: int):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = [int(panel_id)] + ids
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT * FROM panels WHERE id=%s AND telegram_user_id IN ({placeholders})",
            params
        )
        return cur.fetchone()

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

def get_panel_disabled_names(panel_id: int):
    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT config_name FROM panel_disabled_configs WHERE panel_id=%s",
            (int(panel_id),),
        )
        # Return normalized, unique names so callers can match reliably
        return sorted(
            {
                cn
                for r in cur.fetchall()
                for cn in [canonicalize_name(r["config_name"])]
                if (r["config_name"] or "").strip() and cn
            }
        )

def set_panel_disabled_names(owner_id: int, panel_id: int, names):
    # Normalize and dedupe names so dynamic parts don't cause mismatches
    clean = [
        c
        for c in sorted({canonicalize_name(n) for n in names if n and n.strip()})
        if c
    ]
    with with_mysql_cursor() as cur:
        cur.execute("DELETE FROM panel_disabled_configs WHERE panel_id=%s", (int(panel_id),))
        if clean:
            cur.executemany(
                """
                INSERT INTO panel_disabled_configs(telegram_user_id,panel_id,config_name)
                VALUES(%s,%s,%s)
                """,
                [(canonical_owner_id(owner_id), int(panel_id), n) for n in clean],
            )

def get_panel_disabled_nums(panel_id: int):
    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT config_index FROM panel_disabled_numbers WHERE panel_id=%s",
            (int(panel_id),),
        )
        return [int(r["config_index"]) for r in cur.fetchall() if r["config_index"]]

def set_panel_disabled_nums(owner_id: int, panel_id: int, nums):
    clean = sorted({int(n) for n in nums if str(n).isdigit() and int(n) > 0})
    with with_mysql_cursor() as cur:
        cur.execute("DELETE FROM panel_disabled_numbers WHERE panel_id=%s", (int(panel_id),))
        if clean:
            cur.executemany(
                """
                INSERT INTO panel_disabled_numbers(telegram_user_id,panel_id,config_index)
                VALUES(%s,%s,%s)
                """,
                [(canonical_owner_id(owner_id), int(panel_id), n) for n in clean],
            )

def list_panel_links(panel_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("""
            SELECT lup.owner_id, lup.local_username, lup.remote_username,
                   p.panel_url, p.access_token, p.panel_type
            FROM local_user_panel_links lup
            JOIN panels p ON p.id = lup.panel_id
            WHERE lup.panel_id=%s
        """, (int(panel_id),))
        return cur.fetchall()

def delete_panel_and_cleanup(owner_id: int, panel_id: int):
    # 1) disable all mapped remote users on that panel
    rows = list_panel_links(panel_id)
    for r in rows:
        try:
            api = get_api(r.get("panel_type"))
            remotes = (
                r["remote_username"].split(",")
                if r.get("panel_type") == "sanaei"
                else [r["remote_username"]]
            )
            for rn in remotes:
                ok, err = api.disable_remote_user(r["panel_url"], r["access_token"], rn)
                if not ok:
                    log.warning("disable before delete failed on %s: %s", r["panel_url"], err or "unknown")
        except Exception as e:
            log.warning("disable before delete exception: %s", e)
    # 2) delete mappings + panel
    with with_mysql_cursor() as cur:
        cur.execute("DELETE FROM local_user_panel_links WHERE panel_id=%s", (int(panel_id),))
        cur.execute("DELETE FROM panel_disabled_configs WHERE panel_id=%s", (int(panel_id),))
        cur.execute("DELETE FROM panel_disabled_numbers WHERE panel_id=%s", (int(panel_id),))
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        cur.execute(
            f"DELETE FROM panels WHERE id=%s AND telegram_user_id IN ({placeholders})",
            [int(panel_id)] + ids
        )

# ---------- agents ----------
def upsert_agent(tg_id: int, name: str):
    token = None
    new_agent_id = None
    with with_mysql_cursor() as cur:
        cur.execute("SELECT id FROM agents WHERE telegram_user_id=%s", (tg_id,))
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE agents SET name=%s, active=1 WHERE telegram_user_id=%s",
                (name, tg_id),
            )
        else:
            cur.execute(
                "INSERT INTO agents(telegram_user_id,name,plan_limit_bytes,expire_at,active,user_limit,max_user_bytes,api_token,api_token_encrypted) "
                "VALUES(%s,%s,0,NULL,1,0,0,NULL,NULL)",
                (tg_id, name),
            )
            new_agent_id = cur.lastrowid
    if new_agent_id:
        token = rotate_agent_token_value(new_agent_id)
    return token

def get_agent(tg_id: int):
    return get_agent_record(tg_id)

def list_agents():
    with with_mysql_cursor() as cur:
        cur.execute("SELECT * FROM agents ORDER BY created_at DESC")
        return cur.fetchall()

def list_agent_panel_ids(agent_tg_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("SELECT panel_id FROM agent_panels WHERE agent_tg_id=%s", (agent_tg_id,))
        return {int(r["panel_id"]) for r in cur.fetchall()}

def set_agent_panels(agent_tg_id: int, panel_ids: set[int]):
    with with_mysql_cursor() as cur:
        cur.execute("DELETE FROM agent_panels WHERE agent_tg_id=%s", (agent_tg_id,))
        if panel_ids:
            cur.executemany("INSERT INTO agent_panels(agent_tg_id,panel_id) VALUES(%s,%s)",
                            [(agent_tg_id, int(pid)) for pid in panel_ids])

# ---------- UI ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    is_sudo = is_admin(uid)
    ag = get_agent(uid) if not is_sudo else None

    if not is_sudo and not ag:
        return

    context.user_data["manage_owner_id"] = uid

    header = ""
    if ag:
        limit_b = int(ag.get("plan_limit_bytes") or 0)
        max_users = int(ag.get("user_limit") or 0)
        max_user_b = int(ag.get("max_user_bytes") or 0)
        user_cnt = count_local_users(uid)
        exp = ag.get("expire_at")
        parts = [f"👤 <b>{ag['name']}</b>", f"👥 Users: {user_cnt}/{('∞' if max_users==0 else max_users)}"]
        if limit_b:
            parts.append(f"📦 Quota: {fmt_bytes_short(limit_b)}")
        if max_user_b:
            parts.append(f"📛 Max/User: {fmt_bytes_short(max_user_b)}")
        if exp:
            parts.append(f"⏳ Expire: {exp.strftime('%Y-%m-%d')}")
        header = "\n".join(parts) + "\n\n"

    if is_sudo:
        kb = [
            [InlineKeyboardButton("🧬 New Local User", callback_data="new_user")],
            [InlineKeyboardButton("👥 List Users", callback_data="list_users:0")],
            [InlineKeyboardButton("🧩 Presets", callback_data="manage_presets")],
            [InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin_panel")],
        ]
    else:
        kb = [
            [InlineKeyboardButton("🧬 New Local User", callback_data="new_user")],
            [InlineKeyboardButton("👥 List Users", callback_data="list_users:0")],
            [InlineKeyboardButton("🧩 Presets", callback_data="manage_presets")],
            [InlineKeyboardButton("🔑 API Token", callback_data="agent_token")],
            [InlineKeyboardButton("🛠️ Settings", callback_data="agent_technical")],
        ]

    text = header + "Choose an option:"
    if update.message:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    else:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

def _panel_select_kb(panels, selected: set):
    rows = []
    for p in panels:
        pid = int(p["id"])
        mark = "✅" if pid in selected else "⬜"
        title = f"{mark} {p['name']} ({p.get('panel_type', 'marzneshin')})"
        rows.append([InlineKeyboardButton(title[:64], callback_data=f"ap:toggle:{pid}")])

    rows.append([
        InlineKeyboardButton("☑️ All", callback_data="ap:all"),
        InlineKeyboardButton("🔲 None", callback_data="ap:none"),
    ])
    rows.append([
        InlineKeyboardButton("✅ Apply", callback_data="ap:apply"),
        InlineKeyboardButton("❌ Cancel", callback_data="ap:cancel"),
    ])
    return InlineKeyboardMarkup(rows)

def _agent_service_select_kb(services, selected: set):
    rows = []
    for s in services:
        sid = int(s["id"])
        mark = "✅" if sid in selected else "⬜"
        rows.append([InlineKeyboardButton(f"{mark} {s['name']}"[:64], callback_data=f"as:toggle:{sid}")])
    rows.append([
        InlineKeyboardButton("☑️ All", callback_data="as:all"),
        InlineKeyboardButton("🔲 None", callback_data="as:none"),
    ])
    rows.append([
        InlineKeyboardButton("✅ Apply", callback_data="as:apply"),
        InlineKeyboardButton("❌ Cancel", callback_data="as:cancel"),
    ])
    return InlineKeyboardMarkup(rows)

def _service_panel_select_kb(panels, selected: set):
    rows = []
    for p in panels:
        pid = int(p["id"])
        mark = "✅" if pid in selected else "⬜"
        title = f"{mark} {p['name']} ({p.get('panel_type', 'marzneshin')})"
        rows.append([InlineKeyboardButton(title[:64], callback_data=f"sp:toggle:{pid}")])
    rows.append([
        InlineKeyboardButton("☑️ All", callback_data="sp:all"),
        InlineKeyboardButton("🔲 None", callback_data="sp:none"),
    ])
    rows.append([
        InlineKeyboardButton("✅ Apply", callback_data="sp:apply"),
        InlineKeyboardButton("❌ Cancel", callback_data="sp:cancel"),
    ])
    return InlineKeyboardMarkup(rows)

async def show_service_panel_select(q, context, service_id: int):
    uid = q.from_user.id
    panels = list_my_panels_admin(uid)
    if not panels:
        await q.edit_message_text("هیچ پنلی ثبت نشده.")
        return ConversationHandler.END
    selected = list_service_panel_ids(service_id)
    context.user_data["sp_panels"] = panels
    context.user_data["sp_selected"] = set(selected)
    context.user_data["service_id"] = service_id
    kb = _service_panel_select_kb(panels, set(selected))
    await q.edit_message_text("پنل‌های سرویس را انتخاب کن:", reply_markup=kb)
    return ASK_ASSIGN_SERVICE_PANELS

async def show_service_select(update_or_q, context, owner_id: int):
    services = list_services_for_owner(owner_id)
    if not services:
        msg = "❌ هیچ سرویس مجازی برای شما فعال نشده است."
        if hasattr(update_or_q, "edit_message_text"):
            await update_or_q.edit_message_text(msg)
        else:
            await update_or_q.message.reply_text(msg)
        return ConversationHandler.END
    kb = [[InlineKeyboardButton(r['name'], callback_data=f"selservice:{r['id']}")] for r in services]
    kb.append([InlineKeyboardButton("❌ Cancel", callback_data="selservice:cancel")])
    if hasattr(update_or_q, "edit_message_text"):
        await update_or_q.edit_message_text("سرویس را انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update_or_q.message.reply_text("سرویس را انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))
    return ASK_SELECT_SERVICE

async def show_preset_menu(q, context, uid: int, notice: str | None = None):
    rows = list_presets(uid)
    kb = []
    for r in rows:
        kb.append([
            InlineKeyboardButton(f"{fmt_bytes_short(r['limit_bytes'])} / {r['duration_days']}d", callback_data=f"preset_edit:{r['id']}"),
            InlineKeyboardButton("🗑️ حذف", callback_data=f"preset_del:{r['id']}")
        ])

    kb.append([InlineKeyboardButton("➕ Add", callback_data="preset_add")])
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="back_home")])
    text = "برای ویرایش پریست روی آن کلیک کنید یا برای حذف، دکمه حذف را بزنید.\n\nپریست‌ها:" if rows else "هیچ پریستی ثبت نشده."
    if notice: text = f"{notice}\n{text}"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

async def show_preset_select(update_or_q, context, uid: int, notice: str | None = None):
    rows = list_presets(uid)
    kb = [[InlineKeyboardButton(f"{fmt_bytes_short(r['limit_bytes'])} / {r['duration_days']}d", callback_data=f"preset_sel:{r['id']}")] for r in rows]
    kb.append([InlineKeyboardButton("✏️ Custom", callback_data="preset_custom")])
    text = "یک پریست را انتخاب کن:" if rows else "پریست تعریف نشده، Custom را بزن:" 
    if notice: text = f"{notice}\n{text}"
    if hasattr(update_or_q, "edit_message_text"):
        await update_or_q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    elif hasattr(update_or_q, "reply_text"):
        await update_or_q.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update_or_q.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))
    return ASK_PRESET_CHOICE

# ---------- buttons ----------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    uid = update.effective_user.id

    if data == "admin_panel":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        kb = [
            [InlineKeyboardButton("🗂️ Servers", callback_data="admin_servers")],
            [InlineKeyboardButton("👑 Manage Agents", callback_data="manage_agents")],
            [InlineKeyboardButton("🛠️ Technical", callback_data="admin_technical")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_home")],
        ]
        await q.edit_message_text("پنل ادمین:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data == "admin_servers":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        kb = [
            [InlineKeyboardButton("📦 Panels", callback_data="servers_panels")],
            [InlineKeyboardButton("🧰 Services", callback_data="servers_services")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")],
        ]
        await q.edit_message_text("Servers:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data == "servers_panels":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        kb = [
            [InlineKeyboardButton("➕ Add Panel", callback_data="add_panel")],
            [InlineKeyboardButton("🛠️ Manage Panels", callback_data="manage_panels")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_servers")],
        ]
        await q.edit_message_text("Servers → Panels:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data == "servers_services":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        kb = [
            [InlineKeyboardButton("🆕 Add Service", callback_data="add_service")],
            [InlineKeyboardButton("🧰 Manage Services", callback_data="manage_services")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_servers")],
        ]
        await q.edit_message_text("Servers → Services:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data == "admin_technical":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        await q.edit_message_text("Technical:", reply_markup=_admin_technical_kb(uid))
        return ConversationHandler.END

    if data == "agent_technical":
        if is_admin(uid) or not get_agent(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        await q.edit_message_text("Settings:", reply_markup=_agent_technical_kb(uid))
        return ConversationHandler.END

    if data == "toggle_limit_event_notifications":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        current = (get_setting(uid, "limit_event_notifications_enabled") or "1") != "0"
        set_setting(uid, "limit_event_notifications_enabled", "0" if current else "1")
        await q.edit_message_text("Technical:", reply_markup=_admin_technical_kb(uid))
        return ConversationHandler.END

    if data == "toggle_sub_placeholder":
        if not is_admin(uid) and not get_agent(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        current = (get_setting(uid, "subscription_placeholder_enabled") or "0") != "0"
        set_setting(uid, "subscription_placeholder_enabled", "0" if current else "1")
        if is_admin(uid):
            await q.edit_message_text("Technical:", reply_markup=_admin_technical_kb(uid))
        else:
            await q.edit_message_text("Settings:", reply_markup=_agent_technical_kb(uid))
        return ConversationHandler.END

    if data == "set_near_limit_threshold":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        cur = _usage_sync_threshold_text(uid)
        await q.edit_message_text(
            "مقدار فعلی Near Limit Threshold\n"
            f"{cur}\n\n"
            "مقدار جدید را بفرست. نمونه‌ها: 10% یا 500MB",
            reply_markup=_back_kb("admin_technical"),
        )
        return ASK_NEAR_LIMIT_THRESHOLD

    if data == "set_near_limit_sync_interval":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        cur = _usage_sync_minutes(uid, "near_limit_sync_interval", 5)
        await q.edit_message_text(
            f"مقدار فعلی Near-Limit Sync Interval: {cur} دقیقه\n\n"
            "عدد جدید (دقیقه) را بفرست:",
            reply_markup=_back_kb("admin_technical"),
        )
        return ASK_NEAR_LIMIT_SYNC_INTERVAL

    if data == "set_normal_sync_interval":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        cur = _usage_sync_minutes(uid, "normal_sync_interval", 10)
        await q.edit_message_text(
            f"مقدار فعلی Normal Sync Interval: {cur} دقیقه\n\n"
            "عدد جدید (دقیقه) را بفرست:",
            reply_markup=_back_kb("admin_technical"),
        )
        return ASK_NORMAL_SYNC_INTERVAL
    if data == "limit_msg":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        cur = get_setting(uid, "limit_message") or "—"
        await q.edit_message_text(f"پیام فعلی:\n{cur}\n\nپیام جدید را بفرست:", reply_markup=_back_kb("admin_technical"))
        return ASK_LIMIT_MSG

    if data == "sub_placeholder_template":
        if not is_admin(uid) and not get_agent(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        cur = get_setting(uid, "subscription_placeholder_template") or "—"
        back_target = "admin_technical" if is_admin(uid) else "agent_technical"
        await q.edit_message_text(
            "قالب فعلی:\n"
            f"{cur}\n\n"
            "قالب جدید را بفرست.\n"
            "برای حذف: clear",
            reply_markup=_back_kb(back_target),
        )
        return ASK_SUB_PLACEHOLDER_TEMPLATE

    if data == "extra_sub_domains":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        cur_domains = get_extra_domains(uid)
        cur = "\n".join(cur_domains) if cur_domains else "—"
        await q.edit_message_text(
            "دامنه‌های اضافه فعلی:\n"
            f"{cur}\n\n"
            "دامنه‌های جدید را با کاما یا خط جدید بفرست.\n"
            "برای حذف: clear",
            reply_markup=_back_kb("admin_technical")
        )
        return ASK_EXTRA_SUB_DOMAINS


    # --- admin/agent shared
    if data == "manage_presets":
        return await show_preset_menu(q, context, uid)
    if data == "preset_add":
        await q.edit_message_text("حجم در GB پریست:")
        return ASK_PRESET_GB
    if data.startswith("preset_edit:"):
        pid = int(data.split(":", 1)[1])
        context.user_data["editing_preset_id"] = pid
        await q.edit_message_text("حجم جدید در GB پریست:")
        return ASK_PRESET_GB

    if data.startswith("preset_del:"):
        pid = int(data.split(":", 1)[1])
        preset = get_preset(uid, pid)
        if not preset:
            return await show_preset_menu(q, context, uid, notice="❌ پریست یافت نشد.")

        text = f"پریست {fmt_bytes_short(preset['limit_bytes'])} / {preset['duration_days']}d حذف شود؟"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ بله، حذف کن", callback_data=f"preset_del_confirm:{pid}")],
            [InlineKeyboardButton("⬅️ انصراف", callback_data="manage_presets")],
        ])
        await q.edit_message_text(text, reply_markup=kb)
        return ConversationHandler.END

    if data.startswith("preset_del_confirm:"):
        pid = int(data.split(":", 1)[1])
        delete_preset(uid, pid)
        return await show_preset_menu(q, context, uid, notice="✅ حذف شد.")
    if data.startswith("preset_sel:"):
        pid = int(data.split(":",1)[1])
        info = get_preset(uid, pid)
        if not info:
            return await show_preset_select(q, context, uid, notice="پریست یافت نشد.")
        max_b = int(context.user_data.get("agent_max_user_bytes") or 0)
        if max_b > 0 and int(info.get("limit_bytes") or 0) > max_b:
            return await show_preset_select(q, context, uid, notice=f"❌ حداکثر حجم مجاز {fmt_bytes_short(max_b)} است.")
        context.user_data["limit_bytes"] = int(info.get("limit_bytes") or 0)
        context.user_data["duration_days"] = int(info.get("duration_days") or 0)
        class Fake:
            async def edit_message_text(self, *a, **k):
                await q.edit_message_text(*a, **k)
        return await show_service_select(Fake(), context, uid)
    if data == "preset_custom":
        await q.edit_message_text("حجم در GB (0=نامحدود):")
        return ASK_LIMIT_GB

    if data == "agent_token":
        ag = get_agent(uid)
        if not ag:
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        kb = [
            [InlineKeyboardButton("Show token", callback_data="agent_show_token")],
            [InlineKeyboardButton("Rotate token", callback_data="agent_rotate_token")],
            [InlineKeyboardButton("⬅️ Back", callback_data="back_home")],
        ]
        await q.edit_message_text("API token:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data == "agent_show_token":
        return await agent_show_token(update, context)

    if data == "agent_rotate_token":
        return await agent_rotate_token(update, context)

    if data == "admin_token":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        kb = [
            [InlineKeyboardButton("Show token", callback_data="admin_show_token")],
            [InlineKeyboardButton("Rotate token", callback_data="admin_rotate_token")],
            [InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")],
        ]
        await q.edit_message_text("Admin API token:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data == "admin_show_token":
        return await admin_show_token(update, context)

    if data == "admin_rotate_token":
        return await admin_rotate_token(update, context)

    if data == "add_panel":
        if not is_admin(uid):
            await q.edit_message_text("فقط ادمین می‌تواند پنل اضافه کند.")
            return ConversationHandler.END
        await q.edit_message_text("🧾 اسم پنل را بفرست:", reply_markup=_back_kb("servers_panels"))
        return ASK_PANEL_NAME

    if data == "add_service":
        if not is_admin(uid):
            await q.edit_message_text("فقط ادمین می‌تواند سرویس اضافه کند.")
            return ConversationHandler.END
        await q.edit_message_text("🧾 اسم سرویس را بفرست:", reply_markup=_back_kb("servers_services"))
        return ASK_SERVICE_NAME

    if data == "manage_panels":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        rows = list_my_panels_admin(uid)
        if not rows:
            await q.edit_message_text("هیچ پنلی ثبت نشده. ابتدا ➕ Add Panel.", reply_markup=_back_kb("servers_panels"))
            return ConversationHandler.END
        kb = [[InlineKeyboardButton(f"{r['name']}"[:64],
                                    callback_data=f"panel_sel:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="servers_panels")])
        await q.edit_message_text("یک پنل را انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data == "manage_services":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        rows = list_services()
        if not rows:
            await q.edit_message_text("هیچ سرویسی ثبت نشده. ابتدا ➕ Add Service.", reply_markup=_back_kb("servers_services"))
            return ConversationHandler.END
        kb = [[InlineKeyboardButton(f"{r['name']}"[:64],
                                    callback_data=f"service_sel:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="servers_services")])
        await q.edit_message_text("یک سرویس را انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data.startswith("service_sel:"):
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        sid = int(data.split(":", 1)[1])
        context.user_data["service_id"] = sid
        return await show_service_card(q, context, sid)

    if data == "service_assign_panels":
        if not is_admin(uid):
            return ConversationHandler.END
        sid = context.user_data.get("service_id")
        return await show_service_panel_select(q, context, sid)

    if data == "service_emerg_cfg":
        if not is_admin(uid):
            return ConversationHandler.END
        sid = context.user_data.get("service_id")
        cur = get_setting(uid, f"emergency_config_service_{sid}") or "—"
        await q.edit_message_text(
            f"کانفیگ فعلی:\n{cur}\n\nکانفیگ جدید را بفرست (یا off برای پاک کردن):",
            reply_markup=_back_kb(f"service_sel:{sid}")
        )
        return ASK_SERVICE_EMERGENCY_CFG

    if data == "service_rename":
        if not is_admin(uid):
            return ConversationHandler.END
        sid = context.user_data.get("service_id")
        await q.edit_message_text("اسم جدید سرویس را بفرست:", reply_markup=_back_kb(f"service_sel:{sid}"))
        return ASK_EDIT_SERVICE_NAME

    if data == "service_delete":
        if not is_admin(uid):
            return ConversationHandler.END
        sid = context.user_data.get("service_id")
        with with_mysql_cursor(dict_=False) as cur:
            cur.execute("DELETE FROM services WHERE id=%s", (sid,))
        await q.edit_message_text("سرویس حذف شد.", reply_markup=_back_kb("servers_services"))
        return ConversationHandler.END

    if data.startswith("panel_sel:"):
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        pid = int(data.split(":", 1)[1])
        context.user_data["edit_panel_id"] = pid
        return await show_panel_card(q, context, uid, pid)

    if data == "p_set_template":
        if not is_admin(uid): return ConversationHandler.END
        pid = context.user_data.get("edit_panel_id")
        info = get_panel(uid, pid) if pid else None
        prompt = (
            "ID اینباندها (با کاما جدا کن)" if info and info.get("panel_type") == "sanaei" else "نام تمپلیت"
        )
        await q.edit_message_text(f"{prompt} را بفرست (برای حذف، '-'):", reply_markup=_back_kb(f"panel_sel:{pid}")) ; return ASK_PANEL_TEMPLATE
    if data == "p_rename":
        if not is_admin(uid): return ConversationHandler.END
        await q.edit_message_text("اسم جدید پنل را بفرست:", reply_markup=_back_kb(f"panel_sel:{context.user_data.get('edit_panel_id')}")) ; return ASK_EDIT_PANEL_NAME
    if data == "p_change_creds":
        if not is_admin(uid): return ConversationHandler.END
        await q.edit_message_text("یوزرنیم ادمین جدید را بفرست:", reply_markup=_back_kb(f"panel_sel:{context.user_data.get('edit_panel_id')}")) ; return ASK_EDIT_PANEL_USER
    if data == "p_set_multiplier":
        if not is_admin(uid): return ConversationHandler.END
        await q.edit_message_text("نسبت مصرف را بفرست (مثلا 1 یا 0.5). برای ریست، '-':", reply_markup=_back_kb(f"panel_sel:{context.user_data.get('edit_panel_id')}"))
        return ASK_PANEL_MULTIPLIER
    if data == "p_toggle_ratio_name":
        if not is_admin(uid):
            return ConversationHandler.END
        pid = context.user_data.get("edit_panel_id")
        info = get_panel(uid, pid) if pid else None
        if not info:
            await q.edit_message_text("پنل پیدا نشد.")
            return ConversationHandler.END
        ratio = float(info.get("usage_multiplier") or 1.0)
        if abs(ratio - 1.0) <= 1e-9:
            return await show_panel_card(q, context, uid, pid)
        set_panel_append_ratio_to_name(uid, pid, not bool(info.get("append_ratio_to_name") or 0))
        return await show_panel_card(q, context, uid, pid)
    if data == "p_set_sub":
        if not is_admin(uid): return ConversationHandler.END
        pid = context.user_data.get("edit_panel_id")
        info = get_panel(uid, pid) if pid else None
        if info and info.get("panel_type") == "sanaei":
            await q.edit_message_text("این پنل از لینک سابسکریپشن پشتیبانی نمی‌کند.")
            return ConversationHandler.END
        await q.edit_message_text("لینک سابسکریپشن پنل را بفرست (برای حذف، '-'):", reply_markup=_back_kb(f"panel_sel:{pid}")) ; return ASK_PANEL_SUB_URL
    if data == "p_set_api_key":
        if not is_admin(uid): return ConversationHandler.END
        pid = context.user_data.get("edit_panel_id")
        info = get_panel(uid, pid) if pid else None
        if not info:
            await q.edit_message_text("پنل پیدا نشد.")
            return ConversationHandler.END
        panel_type = (info.get("panel_type") or "").lower()
        if panel_type not in ("rebecca", "guardcore"):
            await q.edit_message_text("این پنل از API Key پشتیبانی نمی‌کند.")
            return ConversationHandler.END
        await q.edit_message_text("API Key را بفرست (برای حذف، '-'):", reply_markup=_back_kb(f"panel_sel:{pid}"))
        return ASK_PANEL_API_KEY
    if data == "p_filter_cfgs":
        if not is_admin(uid): return ConversationHandler.END
        pid = context.user_data.get("edit_panel_id")
        info = get_panel(uid, pid)
        if not info:
            await q.edit_message_text("پنل پیدا نشد.")
            return ConversationHandler.END
        if info.get("panel_type") == "sanaei":
            await q.edit_message_text("این پنل از فیلتر کانفیگ‌ها پشتیبانی نمی‌کند.")
            return ConversationHandler.END
        if not info.get("sub_url"):
            await q.edit_message_text("اول لینک سابسکریپشن پنل را تنظیم کن (Set/Clear Sub URL).")
            return ConversationHandler.END
        return await show_panel_cfg_selector(q, context, uid, pid, page=0)
    if data == "p_filter_cfgnums":
        if not is_admin(uid): return ConversationHandler.END
        pid = context.user_data.get("edit_panel_id")
        info = get_panel(uid, pid)
        if not info:
            await q.edit_message_text("پنل پیدا نشد.")
            return ConversationHandler.END
        if info.get("panel_type") == "sanaei":
            await q.edit_message_text("این پنل از فیلتر کانفیگ‌ها پشتیبانی نمی‌کند.")
            return ConversationHandler.END
        if not info.get("sub_url"):
            await q.edit_message_text("اول لینک سابسکریپشن پنل را تنظیم کن (Set/Clear Sub URL).")
            return ConversationHandler.END
        return await show_panel_cfgnum_selector(q, context, uid, pid, page=0)
    if data == "p_remove":
        if not is_admin(uid): return ConversationHandler.END
        pid = context.user_data.get("edit_panel_id")
        if not pid:
            await q.edit_message_text("پنل انتخاب نشده.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ بله، حذف کن", callback_data="p_remove_yes")],
            [InlineKeyboardButton("⬅️ انصراف", callback_data=f"panel_sel:{pid}")],
        ])
        await q.edit_message_text("⚠️ قبل از حذف، تمام یوزرهای مپ‌شده روی این پنل دیزیبل می‌شوند. مطمئنی؟", reply_markup=kb)
        return ASK_PANEL_REMOVE_CONFIRM
    if data == "p_remove_yes":
        if not is_admin(uid): return ConversationHandler.END
        pid = context.user_data.get("edit_panel_id")
        delete_panel_and_cleanup(uid, pid)
        await q.edit_message_text("✅ پنل حذف شد و همهٔ کانفیگ‌های مرتبط دیزیبل شدند.", reply_markup=_back_kb("servers_panels"))
        return ConversationHandler.END

    if data == "new_user":
        await q.edit_message_text("نام یوزر جدید (local/unified) را بفرست:") ; return ASK_NEWUSER_NAME

    if data == "search_user":
        await q.edit_message_text("اسم یوزر برای جستجو (partial مجاز):") ; return ASK_SEARCH_USER

    if data.startswith("list_users:"):
        page = int(data.split(":", 1)[1])
        page = max(0, page)
        owner_id = get_manage_owner_id(context, uid)
        total = count_local_users(owner_id)
        per = 25
        off = page * per
        rows = list_all_local_users(owner_id, offset=off, limit=per) or []
        if not rows and page > 0:
            page = 0 ; off = 0
            rows = list_all_local_users(owner_id, offset=0, limit=per)
        kb = [[InlineKeyboardButton("🔍 Search Users", callback_data="search_user")]]
        kb.extend([[InlineKeyboardButton(r["username"], callback_data=f"user_sel:{r['username']}")] for r in rows])
        nav = []
        if page > 0: nav.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"list_users:{page-1}"))
        if off + per < total: nav.append(InlineKeyboardButton("بعدی ➡️", callback_data=f"list_users:{page+1}"))
        if nav: kb.append(nav)
        back_cb = "back_home" if owner_id == uid else f"agent_sel:{owner_id}"
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data=back_cb)])
        await q.edit_message_text(f"👥 کاربران (صفحه {page+1})", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data.startswith("user_sel:"):
        uname = data.split(":", 1)[1]
        context.user_data["manage_username"] = uname
        owner_id = get_manage_owner_id(context, uid)
        return await show_user_card(q, owner_id, uname)

    if data == "act_edit_limit":
        await q.edit_message_text("لیمیت جدید: 0/unlimited یا 500MB / 10GB / 1.5TB") ; return ASK_EDIT_LIMIT

    if data == "act_reset_used":
        uname = context.user_data.get("manage_username")
        if not uname:
            await q.edit_message_text("یوزر انتخاب نشده.")
            return ConversationHandler.END
        owner_id = get_manage_owner_id(context, uid)
        reset_used(owner_id, uname)
        return await show_user_card(q, owner_id, uname, notice="✅ مصرف صفر شد.")

    if data == "act_qr_code":
        uname = context.user_data.get("manage_username")
        if not uname:
            await q.edit_message_text("یوزر انتخاب نشده.")
            return ConversationHandler.END
        owner_id = get_manage_owner_id(context, uid)
        app_key = get_app_key(owner_id, uname)
        sub_links = build_sub_links(owner_id, uname, app_key)
        if not sub_links:
            await q.edit_message_text("لینک سابسکریپشن پیدا نشد.")
            return ConversationHandler.END
        await q.answer()
        for link in sub_links:
            qr_img = generate_qr_png(link)
            await context.bot.send_photo(
                chat_id=uid,
                photo=qr_img,
                caption=f"🔗 {link}",
            )
        return await show_user_card(q, owner_id, uname, notice="✅ QR codes sent.")

    if data == "act_renew":
        await q.edit_message_text("چند روز اضافه شود؟ (مثلا 30)") ; return ASK_RENEW_DAYS

    if data == "act_assign_service":
        uname = context.user_data.get("manage_username")
        owner_id = get_manage_owner_id(context, uid)
        rows = list_services()
        if not rows:
            await q.edit_message_text("هیچ سرویسی ثبت نشده.")
            return ConversationHandler.END
        if not is_admin(uid):
            allowed = list_agent_service_ids(owner_id)
            rows = [r for r in rows if int(r["id"]) in allowed]
        kb = [[InlineKeyboardButton(r['name'], callback_data=f"user_service:{r['id']}")] for r in rows]
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="user_sel_back")])
        await q.edit_message_text("یک سرویس را انتخاب کن:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data.startswith("user_service:"):
        uname = context.user_data.get("manage_username")
        owner_id = get_manage_owner_id(context, uid)
        sid = int(data.split(":",1)[1])
        await set_local_user_service(owner_id, uname, sid)
        return await show_user_card(q, owner_id, uname, notice="✅ سرویس کاربر ذخیره شد.")

    if data == "act_toggle_user":
        uname = context.user_data.get("manage_username")
        if not uname:
            await q.edit_message_text("یوزر انتخاب نشده.")
            return ConversationHandler.END
        owner_id = get_manage_owner_id(context, uid)
        row = get_local_user(owner_id, uname)
        if not row:
            await q.edit_message_text("کاربر پیدا نشد.")
            return ConversationHandler.END
        manual_disabled = bool(row.get("manual_disabled") or 0)
        set_user_disabled(owner_id, uname, not manual_disabled)
        notice = "✅ کاربر فعال شد." if manual_disabled else "🚫 کاربر غیرفعال شد."
        return await show_user_card(q, owner_id, uname, notice=notice)

    if data == "user_sel_back":
        uname = context.user_data.get("manage_username")
        owner_id = get_manage_owner_id(context, uid)
        return await show_user_card(q, owner_id, uname)

    if data == "act_del_user":
        uname = context.user_data.get("manage_username")
        if not uname:
            await q.edit_message_text("یوزر انتخاب نشده.")
            return ConversationHandler.END
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑️ بله، حذف کن", callback_data="act_del_user_yes")],
            [InlineKeyboardButton("⬅️ انصراف", callback_data=f"user_sel:{uname}")],
        ])
        await q.edit_message_text(f"کاربر {uname} حذف شود؟", reply_markup=kb)
        return ConversationHandler.END

    if data == "act_del_user_yes":
        uname = context.user_data.get("manage_username")
        if not uname:
            await q.edit_message_text("یوزر انتخاب نشده.")
            return ConversationHandler.END
        owner_id = get_manage_owner_id(context, uid)
        delete_user(owner_id, uname)
        await q.edit_message_text("✅ کاربر حذف شد.")
        return ConversationHandler.END

    # ----- agent mgmt (admin) -----
    if data == "manage_agents":
        if not is_admin(uid):
            await q.edit_message_text("دسترسی ندارید.")
            return ConversationHandler.END
        rows = list_agents()
        kb = [[InlineKeyboardButton(f"{r['name']} - {r['telegram_user_id']}", callback_data=f"agent_sel:{r['telegram_user_id']}")] for r in rows[:50]]
        kb.append([InlineKeyboardButton("➕ Add Agent", callback_data="agent_add")])
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="admin_panel")])
        await q.edit_message_text("نماینده‌ها:", reply_markup=InlineKeyboardMarkup(kb))
        return ConversationHandler.END

    if data == "agent_add":
        if not is_admin(uid): return ConversationHandler.END
        await q.edit_message_text("نام نماینده:")
        return ASK_AGENT_NAME

    if data.startswith("agent_sel:"):
        if not is_admin(uid): return ConversationHandler.END
        aid = int(data.split(":",1)[1])
        context.user_data["agent_tg_id"] = aid
        return await show_agent_card(q, context, aid)

    if data == "agent_users":
        if not is_admin(uid):
            return ConversationHandler.END
        agent_id = context.user_data.get("agent_tg_id")
        if not agent_id:
            await q.edit_message_text("نماینده انتخاب نشده.")
            return ConversationHandler.END
        context.user_data["manage_owner_id"] = int(agent_id)
        return await on_agent_users_list(q, context)


    if data == "agent_set_quota":
        if not is_admin(uid): return ConversationHandler.END
        await q.edit_message_text("حجم کل نماینده (مثلا 200GB یا 0=نامحدود):")
        return ASK_AGENT_LIMIT

    if data == "agent_set_user_limit":
        if not is_admin(uid): return ConversationHandler.END
        await q.edit_message_text("حداکثر تعداد یوزر (0=نامحدود):")
        return ASK_AGENT_MAX_USERS

    if data == "agent_set_max_user":
        if not is_admin(uid): return ConversationHandler.END
        await q.edit_message_text("حداکثر حجم هر یوزر (مثلا 50GB یا 0=نامحدود):")
        return ASK_AGENT_MAX_USER_GB

    if data == "agent_renew_days":
        if not is_admin(uid): return ConversationHandler.END
        await q.edit_message_text("چند روز به انقضا اضافه شود؟ (مثلا 30)")
        return ASK_AGENT_RENEW_DAYS

    if data == "agent_toggle_active":
        if not is_admin(uid): return ConversationHandler.END
        a = context.user_data.get("agent_tg_id")
        info = get_agent(a)
        set_agent_active(a, not bool(info and info.get("active")))
        return await show_agent_card(q, context, a)

    if data == "agent_assign_services":
        if not is_admin(uid): return ConversationHandler.END
        a = context.user_data.get("agent_tg_id")
        rows = list_services()
        if not rows:
            await q.edit_message_text("هیچ سرویسی ثبت نشده.")
            return ConversationHandler.END
        selected = set(list_agent_service_ids(a))
        context.user_data["as_selected"] = selected
        kb = _agent_service_select_kb(rows, selected)
        await q.edit_message_text("سرویس‌های این نماینده:", reply_markup=kb)
        return ConversationHandler.END

    if data == "agent_usage_panel":
        if not is_admin(uid): return ConversationHandler.END
        a = context.user_data.get("agent_tg_id")
        if not a:
            await q.edit_message_text("نماینده انتخاب نشده.")
            return ConversationHandler.END
        return await show_agent_usage_panel(q, a)

    if data == "admin_show_agent_token":
        if not is_admin(uid): return ConversationHandler.END
        return await admin_show_agent_token(update, context)

    if data == "admin_rotate_agent_token":
        if not is_admin(uid): return ConversationHandler.END
        return await admin_rotate_agent_token(update, context)

    if data.startswith("as:"):
        if not is_admin(uid): return ConversationHandler.END
        a = context.user_data.get("agent_tg_id")
        cmd = data.split(":",1)[1]
        services = list_services()
        selected = context.user_data.get("as_selected") or set(list_agent_service_ids(a))
        if cmd == "all":
            selected = {int(s["id"]) for s in services}
        elif cmd == "none":
            selected = set()
        elif cmd.startswith("toggle:"):
            sid = int(cmd.split(":",1)[1])
            if sid in selected: selected.remove(sid)
            else: selected.add(sid)
        elif cmd == "apply":
            set_agent_services(a, selected)
            return await show_agent_card(q, context, a, notice="✅ سرویس‌های نماینده ذخیره شد.")
        elif cmd == "cancel":
            return await show_agent_card(q, context, a)
        context.user_data["as_selected"] = selected
        kb = _agent_service_select_kb(services, selected)
        await q.edit_message_text("سرویس‌های این نماینده:", reply_markup=kb)
        return ConversationHandler.END

    if data == "agent_sel_back":
        a = context.user_data.get("agent_tg_id")
        return await show_agent_card(q, context, a)

    if data.startswith("ap:"):
        if not is_admin(uid): return ConversationHandler.END
        a = context.user_data.get("agent_tg_id")
        return await show_agent_card(q, context, a, notice="⚠️ تخصیص پنل برای نماینده غیرفعال شده است.")

    if data.startswith("sp:"):
        if not is_admin(uid): return ConversationHandler.END
        sid = context.user_data.get("service_id")
        cmd = data.split(":",1)[1]
        panels = context.user_data.get("sp_panels") or []
        selected = context.user_data.get("sp_selected") or set()
        if cmd == "all":
            selected = {int(p["id"]) for p in panels}
        elif cmd == "none":
            selected = set()
        elif cmd.startswith("toggle:"):
            pid = int(cmd.split(":",1)[1])
            if pid in selected: selected.remove(pid)
            else: selected.add(pid)
        elif cmd == "apply":
            set_service_panels(sid, selected)
            await propagate_service_panels(sid)
            return await show_service_card(q, context, sid, notice="✅ پنل‌های سرویس ذخیره شد.")
        elif cmd == "cancel":
            return await show_service_card(q, context, sid)
        context.user_data["sp_selected"] = selected
        kb = _service_panel_select_kb(panels, selected)
        await q.edit_message_text("پنل‌های سرویس:", reply_markup=kb)
        return ConversationHandler.END

    if data == "back_home":
        await start(update, context)
        return ConversationHandler.END

    # ---- service selection during user creation ----
    if data.startswith("selservice:"):
        cmd = data.split(":",1)[1]
        if cmd == "cancel":
            await q.edit_message_text("لغو شد.")
            return ConversationHandler.END
        sid = int(cmd)
        uid = update.effective_user.id
        if not is_admin(uid):
            allowed = list_agent_service_ids(uid)
            if sid not in allowed:
                await q.edit_message_text("❌ این سرویس برای شما فعال نیست.")
                return ConversationHandler.END
        selected_ids = list_service_panel_ids(sid)
        if not selected_ids:
            await q.edit_message_text("این سرویس هیچ پنلی ندارد.")
            return ConversationHandler.END
        limit_bytes = int(context.user_data.get("limit_bytes") or 0)
        if service_has_guardcore_panel(sid) and limit_bytes < MIN_GUARDCORE_CREATE_LIMIT_BYTES:
            await q.edit_message_text(
                "❌ برای سرویس دارای GuardCore حداقل حجم کاربر باید 20GB باشد. ساخت کاربر لغو شد."
            )
            return ConversationHandler.END
        await finalize_create_on_selected(q, context, uid, selected_ids)
        await set_local_user_service(uid, context.user_data.get("new_username"), sid)
        return ConversationHandler.END

    # ---------- panel cfg selector actions ----------
    if data.startswith("pcfg:"):
        pid = context.user_data.get("cfg_panel_id")
        if not pid:
            await q.edit_message_text("جلسه تنظیمات معتبر نیست.")
            return ConversationHandler.END

        cmd = data.split(":",1)[1]
        names = context.user_data.get("cfg_names") or []
        enabled = set(context.user_data.get("cfg_enabled") or set())
        page = int(context.user_data.get("cfg_page", 0))
        per = 20

        if cmd == "all":
            enabled = set(names)
        elif cmd == "none":
            enabled = set()
        elif cmd.startswith("toggle:"):
            idx = int(cmd.split(":",1)[1])
            if 0 <= idx < len(names):
                n = names[idx]
                if n in enabled: enabled.remove(n)
                else: enabled.add(n)
        elif cmd.startswith("page:"):
            np = int(cmd.split(":",1)[1])
            if np >= 0:
                page = np
        elif cmd == "apply":
            disabled = set(names) - set(enabled)
            set_panel_disabled_names(uid, pid, disabled)
            return await show_panel_cfg_selector(q, context, uid, pid, page=page, notice="✅ ذخیره شد.")
        elif cmd == "refresh":
            return await show_panel_cfg_selector(q, context, uid, pid, page=page)
        elif cmd == "cancel":
            return await show_panel_card(q, context, uid, pid)

        context.user_data["cfg_enabled"] = list(enabled)
        context.user_data["cfg_page"] = page
        kb, text = build_panel_cfg_kb(names, enabled, page, per)
        await q.edit_message_text(text, reply_markup=kb)
        return ConversationHandler.END

    if data.startswith("pcnum:"):
        pid = context.user_data.get("cfg_panel_id")
        if not pid:
            await q.edit_message_text("جلسه تنظیمات معتبر نیست.")
            return ConversationHandler.END

        cmd = data.split(":",1)[1]
        titles = context.user_data.get("cfgnum_titles") or []
        enabled = set(context.user_data.get("cfgnums_enabled") or set())
        page = int(context.user_data.get("cfgnum_page", 0))
        total = len(titles)
        per = 20

        if cmd == "all":
            enabled = set(range(1, total+1))
        elif cmd == "none":
            enabled = set()
        elif cmd.startswith("toggle:"):
            idx = int(cmd.split(":",1)[1])
            if 1 <= idx <= total:
                if idx in enabled: enabled.remove(idx)
                else: enabled.add(idx)
        elif cmd.startswith("page:"):
            np = int(cmd.split(":",1)[1])
            if np >= 0:
                page = np
        elif cmd == "apply":
            disabled = set(range(1, total+1)) - set(enabled)
            set_panel_disabled_nums(uid, pid, disabled)
            return await show_panel_cfgnum_selector(q, context, uid, pid, page=page, notice="✅ ذخیره شد.")
        elif cmd == "refresh":
            return await show_panel_cfgnum_selector(q, context, uid, pid, page=page)
        elif cmd == "cancel":
            return await show_panel_card(q, context, uid, pid)

        context.user_data["cfgnums_enabled"] = list(enabled)
        context.user_data["cfgnum_page"] = page
        kb, text = build_panel_cfgnum_kb(titles, enabled, page, per)
        await q.edit_message_text(text, reply_markup=kb)
        return ConversationHandler.END

    return ConversationHandler.END

# ---------- panel cfg selector UI ----------
def build_panel_cfg_kb(names, enabled_set, page: int, per: int):
    total = len(names)
    start = page * per
    end = min(start + per, total)
    page_names = names[start:end]
    rows = []
    for idx, nm in enumerate(page_names, start=start):
        mark = "✅" if nm in enabled_set else "⬜"
        title = f"{mark} {nm}"
        rows.append([InlineKeyboardButton(title[:64], callback_data=f"pcfg:toggle:{idx}")])
    controls = [
        InlineKeyboardButton("☑️ All", callback_data="pcfg:all"),
        InlineKeyboardButton("🔲 None", callback_data="pcfg:none"),
    ]
    rows.append(controls)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"pcfg:page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"pcfg:page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton("✅ Apply", callback_data="pcfg:apply"),
        InlineKeyboardButton("❌ Cancel", callback_data="pcfg:cancel"),
        InlineKeyboardButton("🔄 Refresh", callback_data="pcfg:refresh"),
    ])
    text = f"فهرست کانفیگ‌های پنل (صفحه {page+1})"
    return InlineKeyboardMarkup(rows), text

def build_panel_cfgnum_kb(titles, enabled_set, page: int, per: int):
    total = len(titles)
    start = page * per
    end = min(start + per, total)
    page_titles = titles[start:end]
    rows = []
    for idx, nm in enumerate(page_titles, start=start+1):
        mark = "✅" if idx in enabled_set else "⬜"
        title = f"{mark} {idx}. {nm}"
        rows.append([InlineKeyboardButton(title[:64], callback_data=f"pcnum:toggle:{idx}")])
    controls = [
        InlineKeyboardButton("☑️ All", callback_data="pcnum:all"),
        InlineKeyboardButton("🔲 None", callback_data="pcnum:none"),
    ]
    rows.append(controls)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️", callback_data=f"pcnum:page:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("➡️", callback_data=f"pcnum:page:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton("✅ Apply", callback_data="pcnum:apply"),
        InlineKeyboardButton("❌ Cancel", callback_data="pcnum:cancel"),
        InlineKeyboardButton("🔄 Refresh", callback_data="pcnum:refresh"),
    ])
    text = f"فهرست کانفیگ‌ها بر اساس شماره (صفحه {page+1})"
    return InlineKeyboardMarkup(rows), text

def extract_name(link: str) -> str:
    try:
        i = link.find("#")
        if i == -1:
            return ""
        nm = unquote(link[i+1:]).strip()
        return nm[:255]
    except Exception:
        return ""

async def show_panel_cfg_selector(q, context: ContextTypes.DEFAULT_TYPE, owner_id: int, panel_id: int, page: int = 0, notice: str = None):
    info = get_panel(owner_id, panel_id)
    if not info:
        await q.edit_message_text("پنل پیدا نشد.")
        return ConversationHandler.END

    api = get_api(info.get("panel_type"))
    links = []
    if info.get("template_username"):
        u, e = api.get_user(info["panel_url"], info["access_token"], info["template_username"])
        if u and u.get("key"):
            links = api.fetch_links_from_panel(info["panel_url"], info["template_username"], u["key"])
    elif info.get("sub_url"):
        links = api.fetch_subscription_links(info["sub_url"])
    if not links:
        await q.edit_message_text("ابتدا template یا لینک سابسکریپشن را تنظیم کن.")
        return ConversationHandler.END

    seen, names = set(), []
    for s in links:
        nm = extract_name(s) or "(بدون‌نام)"
        if nm not in seen:
            seen.add(nm)
            names.append(nm)

    disabled = set(get_panel_disabled_names(panel_id))
    enabled = set(names) - disabled

    context.user_data["cfg_names"] = names
    context.user_data["cfg_enabled"] = list(enabled)
    context.user_data["cfg_page"] = page
    context.user_data["cfg_panel_id"] = panel_id

    kb, txt = build_panel_cfg_kb(names, enabled, page, 20)
    if notice:
        txt = f"{notice}\n{txt}"
    await q.edit_message_text(txt, reply_markup=kb)
    return ConversationHandler.END

async def show_panel_cfgnum_selector(q, context: ContextTypes.DEFAULT_TYPE, owner_id: int, panel_id: int, page: int = 0, notice: str = None):
    info = get_panel(owner_id, panel_id)
    if not info:
        await q.edit_message_text("پنل پیدا نشد.")
        return ConversationHandler.END

    api = get_api(info.get("panel_type"))
    links = []
    if info.get("template_username"):
        u, e = api.get_user(info["panel_url"], info["access_token"], info["template_username"])
        if u and u.get("key"):
            links = api.fetch_links_from_panel(info["panel_url"], info["template_username"], u["key"])
    elif info.get("sub_url"):
        links = api.fetch_subscription_links(info["sub_url"])
    if not links:
        await q.edit_message_text("ابتدا template یا لینک سابسکریپشن را تنظیم کن.")
        return ConversationHandler.END

    titles = [extract_name(s) or f"کانفیگ {i+1}" for i, s in enumerate(links)]
    disabled = set(get_panel_disabled_nums(panel_id))
    enabled = set(range(1, len(titles)+1)) - disabled

    context.user_data["cfgnum_titles"] = titles
    context.user_data["cfgnums_enabled"] = list(enabled)
    context.user_data["cfgnum_page"] = page
    context.user_data["cfg_panel_id"] = panel_id

    kb, txt = build_panel_cfgnum_kb(titles, enabled, page, 20)
    if notice:
        txt = f"{notice}\n{txt}"
    await q.edit_message_text(txt, reply_markup=kb)
    return ConversationHandler.END

# ---------- cards ----------
async def show_panel_card(q, context: ContextTypes.DEFAULT_TYPE, owner_id: int, panel_id: int):
    p = get_panel(owner_id, panel_id)
    if not p:
        await q.edit_message_text("پنل پیدا نشد.")
        return ConversationHandler.END

    is_sanaei = p.get('panel_type') == 'sanaei'
    panel_type = (p.get("panel_type") or "").lower()
    supports_api_key = panel_type in ("rebecca", "guardcore")
    ratio = float(p.get("usage_multiplier") or 1.0)
    show_append_ratio_toggle = abs(ratio - 1.0) > 1e-9
    append_ratio_enabled = bool(p.get("append_ratio_to_name") or 0)
    label = "Inbound" if is_sanaei else "Template"
    api_key_state = None
    if supports_api_key:
        api_key_state = "set" if (p.get("access_token") or "").strip() else "unset"
    lines = [
        f"🧩 <b>{p['name']}</b>",
        f"📦 Type: <b>{p.get('panel_type', 'marzneshin')}</b>",
        f"🌐 URL: <code>{p['panel_url']}</code>",
        f"👤 Admin: <code>{p['admin_username']}</code>",
        f"🧬 {label}: <b>{p.get('template_username') or '-'}</b>",
        f"⚖️ Ratio: <b>{ratio:.2f}x</b>",
    ]
    if show_append_ratio_toggle:
        lines.append(f"🏷️ Append ratio to config name: <b>{'ON' if append_ratio_enabled else 'OFF'}</b>")
    if supports_api_key:
        lines.append(f"🔐 API Key: <b>{api_key_state}</b>")
    if not is_sanaei:
        lines.append(f"🔗 Sub URL: <code>{p.get('sub_url') or '-'}</code>")
    lines += [
        "",
        "چه کاری انجام بدهم؟",
    ]
    kb = [
        [InlineKeyboardButton(f"🧬 Set/Clear {label}", callback_data="p_set_template")],
        [InlineKeyboardButton("🔑 Change Admin Credentials", callback_data="p_change_creds")],
        [InlineKeyboardButton("✏️ Rename Panel", callback_data="p_rename")],
        [InlineKeyboardButton("⚖️ Set Usage Ratio", callback_data="p_set_multiplier")],
    ]
    if show_append_ratio_toggle:
        toggle_label = "🟢 Append ratio to config name: ON" if append_ratio_enabled else "⚪️ Append ratio to config name: OFF"
        kb.append([InlineKeyboardButton(toggle_label, callback_data="p_toggle_ratio_name")])
    if supports_api_key:
        kb.append([InlineKeyboardButton("🧾 Set/Clear API Key", callback_data="p_set_api_key")])
    if not is_sanaei:
        kb.append([InlineKeyboardButton("🔗 Set/Clear Sub URL", callback_data="p_set_sub")])
        kb.append([InlineKeyboardButton("🧷 فیلتر کانفیگ‌های پنل", callback_data="p_filter_cfgs")])
        kb.append([InlineKeyboardButton("🔢 فیلتر بر اساس شماره", callback_data="p_filter_cfgnums")])
    kb.append([InlineKeyboardButton("🗑️ Remove Panel", callback_data="p_remove")])
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="manage_panels")])
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return ConversationHandler.END

async def show_service_card(q, context: ContextTypes.DEFAULT_TYPE, service_id: int, notice: str = None):
    s = get_service(service_id)
    if not s:
        await q.edit_message_text("سرویس پیدا نشد.")
        return ConversationHandler.END
    lines = []
    if notice:
        lines.append(notice)
    lines.append(f"🧩 <b>{s['name']}</b>")
    pids = list_service_panel_ids(service_id)
    if pids:
        names = []
        panels = list_my_panels_admin(q.from_user.id)
        for p in panels:
            if int(p["id"]) in pids:
                names.append(p["name"])
        lines.append("Panels: " + ", ".join(names))
    lines.append("\nچه کاری انجام بدهم؟")
    kb = [
        [InlineKeyboardButton("🧷 Assign Panels", callback_data="service_assign_panels")],
        [InlineKeyboardButton("✏️ Rename Service", callback_data="service_rename")],
        [InlineKeyboardButton("🗑️ Remove Service", callback_data="service_delete")],
        [InlineKeyboardButton("🚨 Emergency Config", callback_data="service_emerg_cfg")],
        [InlineKeyboardButton("⬅️ Back", callback_data="manage_services")],
    ]
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return ConversationHandler.END

async def on_agent_users_list(q, context: ContextTypes.DEFAULT_TYPE):
    owner_id = int(context.user_data.get("manage_owner_id") or q.from_user.id)
    total = count_local_users(owner_id)
    per = 25
    rows = list_all_local_users(owner_id, offset=0, limit=per) or []
    kb = [[InlineKeyboardButton("🔍 Search Users", callback_data="search_user")]]
    kb.extend([[InlineKeyboardButton(r["username"], callback_data=f"user_sel:{r['username']}")] for r in rows])
    nav = []
    if per < total:
        nav.append(InlineKeyboardButton("بعدی ➡️", callback_data="list_users:1"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data=f"agent_sel:{owner_id}")])
    await q.edit_message_text("👥 کاربران نماینده (صفحه 1)", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

async def show_user_card(q, owner_id: int, uname: str, notice: str = None):
    row = get_local_user(owner_id, uname)
    if not row:
        await q.edit_message_text("کاربر پیدا نشد.")
        return ConversationHandler.END

    limit_b = int(row["plan_limit_bytes"] or 0)
    used_b  = int(row["used_bytes"] or 0)
    exp     = row["expire_at"]
    manual_disabled = bool(row.get("manual_disabled") or 0)
    pushed  = int(row.get("disabled_pushed", 0) or 0)

    app_key = get_app_key(owner_id, uname)
    sub_links = build_sub_links(owner_id, uname, app_key)

    lines = []
    if notice:
        lines.append(notice)
    lines += [
        f"👤 <b>{uname}</b>",
        format_sub_links_html(sub_links),
        f"📦 Limit: <b>{'Unlimited' if limit_b==0 else fmt_bytes_short(limit_b)}</b>",
        f"📊 Used: <b>{fmt_bytes_short(used_b)}</b>",
        f"🧮 Remaining: <b>{'Unlimited' if limit_b==0 else fmt_bytes_short(max(0, limit_b-used_b))}</b>",
        f"⏳ Expires: <b>{(exp.strftime('%Y-%m-%d %H:%M:%S UTC') if exp else '—')}</b>",
        f"🚫 Manual Disabled: <b>{'Yes' if manual_disabled else 'No'}</b>",
        f"📡 Disabled pushed: <b>{'Yes' if pushed else 'No'}</b>",
        "",
        "Choose an action:",
    ]
    toggle_label = "✅ Enable User" if manual_disabled else "🚫 Disable User"
    kb = [
        [InlineKeyboardButton("✏️ Edit Limit", callback_data="act_edit_limit")],
        [InlineKeyboardButton("🧹 Reset Used", callback_data="act_reset_used")],
        [InlineKeyboardButton("📱 QR Code", callback_data="act_qr_code")],
        [InlineKeyboardButton("🔁 Renew (add days)", callback_data="act_renew")],
        [InlineKeyboardButton("🧰 Assign Service", callback_data="act_assign_service")],
        [InlineKeyboardButton(toggle_label, callback_data="act_toggle_user")],
        [InlineKeyboardButton("🗑️ Delete User", callback_data="act_del_user")],
        [InlineKeyboardButton("⬅️ Back", callback_data="list_users:0")],
    ]
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return ConversationHandler.END

async def show_agent_card(q, context: ContextTypes.DEFAULT_TYPE, agent_tg_id: int, notice: str = None):
    a = get_agent(agent_tg_id)
    if not a:
        await q.edit_message_text("نماینده پیدا نشد.")
        return ConversationHandler.END
    context.user_data["agent_tg_id"] = agent_tg_id

    limit_b = int(a.get("plan_limit_bytes") or 0)
    exp = a.get("expire_at")
    active = bool(a.get("active", 1))
    max_users = int(a.get("user_limit") or 0)
    max_user_b = int(a.get("max_user_bytes") or 0)
    user_cnt = count_local_users(agent_tg_id)
    service_ids = sorted(list_agent_service_ids(agent_tg_id))
    lines = []
    if notice: lines.append(notice)
    lines += [
        f"👤 <b>{a['name']}</b> (TG: <code>{a['telegram_user_id']}</code>)",
        f"📦 Agent Quota: <b>{'Unlimited' if limit_b==0 else fmt_bytes_short(limit_b)}</b>",
        f"👥 Users: <b>{user_cnt}</b> / <b>{'Unlimited' if max_users==0 else max_users}</b>",
        f"📛 Max/User: <b>{'Unlimited' if max_user_b==0 else fmt_bytes_short(max_user_b)}</b>",
        f"⏳ Agent Expire: <b>{(exp.strftime('%Y-%m-%d %H:%M:%S UTC') if exp else '—')}</b>",
        f"✅ Active: <b>{'Yes' if active else 'No'}</b>",
        f"🧰 Services: <b>{len(service_ids)}</b>" + (f" — <code>{', '.join(map(str, service_ids))}</code>" if service_ids else ""),
        "",
        "Choose:",
    ]
    kb = [
        [InlineKeyboardButton("✏️ Set Quota", callback_data="agent_set_quota")],
        [InlineKeyboardButton("👥 Set User Limit", callback_data="agent_set_user_limit")],
        [InlineKeyboardButton("📛 Set Max/User", callback_data="agent_set_max_user")],
        [InlineKeyboardButton("🔁 Renew (days)", callback_data="agent_renew_days")],
        [InlineKeyboardButton("🧰 Assign Services", callback_data="agent_assign_services")],
        [InlineKeyboardButton("👥 Users", callback_data="agent_users")],
        [InlineKeyboardButton("📊 Agent Usage by Panel", callback_data="agent_usage_panel")],
        [InlineKeyboardButton("🔘 Toggle Active", callback_data="agent_toggle_active")],
        [InlineKeyboardButton("Show token", callback_data="admin_show_agent_token")],
        [InlineKeyboardButton("Rotate token", callback_data="admin_rotate_agent_token")],
        [InlineKeyboardButton("⬅️ Back", callback_data="manage_agents")],
    ]
    await q.edit_message_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
    return ConversationHandler.END

async def show_agent_usage_panel(q, agent_tg_id: int):
    usage = fetch_agent_usage_by_panel(agent_tg_id)
    lines = [
        f"📊 <b>Agent Usage by Panel</b>",
        f"Agent: <code>{agent_tg_id}</code>",
        f"Total Used: <b>{fmt_bytes_short(int(usage.total_used_bytes or 0))}</b>",
        "",
    ]

    if not usage.panels:
        lines.append("No panels assigned.")
    else:
        for idx, panel in enumerate(usage.panels, start=1):
            used = fmt_bytes_short(int(panel.used_bytes or 0))
            lines.append(
                f"{idx}. <b>{panel.panel_name}</b> ({panel.panel_type})\n"
                f"   ID: <code>{panel.panel_id}</code> — Used: <b>{used}</b>"
            )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ Back", callback_data=f"agent_sel:{agent_tg_id}")],
    ])
    await q.edit_message_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    return ConversationHandler.END

async def agent_show_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    ag = get_agent(uid)
    if not ag:
        await q.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    try:
        tok = get_agent_token_value(ag["id"])
    except ValueError:
        tok = rotate_agent_token_value(ag["id"])
        log.warning("Token missing for agent %s, generated a new one", uid)
    await context.bot.send_message(
        uid, f"Your API token:\n<code>{tok}</code>", parse_mode="HTML"
    )
    log.info("Agent %s viewed API token", uid)
    return ConversationHandler.END

async def agent_rotate_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    ag = get_agent(uid)
    if not ag:
        await q.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    tok = rotate_agent_token_value(ag["id"])
    await context.bot.send_message(uid, f"New API token:\n<code>{tok}</code>", parse_mode="HTML")
    log.info("Agent %s rotated API token", uid)
    return ConversationHandler.END

async def admin_show_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    if not is_admin(uid):
        await q.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    try:
        tok = get_admin_token()
    except AdminTokenEncryptionError as exc:
        log.error("Failed to load admin token: %s", exc)
        await context.bot.send_message(
            uid,
            "❌ Unable to decrypt the admin token. Check AGENT_TOKEN_ENCRYPTION_KEY.",
        )
        return ConversationHandler.END
    if not tok:
        await context.bot.send_message(uid, "No admin token set.")
        return ConversationHandler.END
    await context.bot.send_message(uid, f"Admin API token:\n<code>{tok}</code>", parse_mode="HTML")
    log.info("Admin %s viewed admin API token", uid)
    return ConversationHandler.END

async def admin_rotate_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    if not is_admin(uid):
        await q.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    try:
        tok = rotate_admin_token()
    except AdminTokenEncryptionError as exc:
        log.error("Failed to rotate admin token: %s", exc)
        await context.bot.send_message(
            uid,
            "❌ Unable to rotate the admin token. Check AGENT_TOKEN_ENCRYPTION_KEY.",
        )
        return ConversationHandler.END
    await context.bot.send_message(uid, f"New admin API token:\n<code>{tok}</code>", parse_mode="HTML")
    log.info("Admin %s rotated admin API token", uid)
    return ConversationHandler.END

async def admin_show_agent_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    if not is_admin(uid):
        await q.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    atg = context.user_data.get("agent_tg_id")
    a = get_agent(atg)
    if not a:
        await q.edit_message_text("نماینده پیدا نشد.")
        return ConversationHandler.END
    try:
        tok = get_agent_token_value(a["id"])
    except ValueError:
        tok = rotate_agent_token_value(a["id"])
        log.warning("Token missing for agent %s, generated a new one", atg)
    await context.bot.send_message(
        uid,
        f"Token for {a['name']}:\n<code>{tok}</code>",
        parse_mode="HTML",
    )
    log.info("Admin %s viewed token for agent %s", uid, atg)
    return await show_agent_card(q, context, atg, notice="📨 Token sent via PM.")

async def admin_rotate_agent_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = update.effective_user.id
    if not is_admin(uid):
        await q.edit_message_text("دسترسی ندارید.")
        return ConversationHandler.END
    atg = context.user_data.get("agent_tg_id")
    a = get_agent(atg)
    if not a:
        await q.edit_message_text("نماینده پیدا نشد.")
        return ConversationHandler.END
    tok = rotate_agent_token_value(a["id"])
    await context.bot.send_message(uid, f"New token for {a['name']}:\n<code>{tok}</code>", parse_mode="HTML")
    log.info("Admin %s rotated token for agent %s", uid, atg)
    return await show_agent_card(q, context, atg, notice="✅ Token rotated.")

async def show_assign_panels(q, context: ContextTypes.DEFAULT_TYPE, agent_tg_id: int):
    # Deprecated: agent panel assignment is intentionally disabled.
    await q.edit_message_text("این بخش غیرفعال شده است. از Assign Services استفاده کنید.")
    return ConversationHandler.END

# ---------- service mgmt (admin only) ----------
async def got_service_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("دسترسی ندارید.")
        return ConversationHandler.END
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("❌ اسم معتبر بفرست:")
        return ASK_SERVICE_NAME
    sid = create_service(name)
    await update.message.reply_text("✅ سرویس ایجاد شد.", reply_markup=_back_kb("servers_services"))
    return ConversationHandler.END

async def got_service_new_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("❌ اسم معتبر بفرست:")
        return ASK_EDIT_SERVICE_NAME
    sid = context.user_data.get("service_id")
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute("UPDATE services SET name=%s WHERE id=%s", (name, sid))
    await update.message.reply_text("✅ نام سرویس تغییر کرد.", reply_markup=_back_kb(f"service_sel:{sid}"))
    return ConversationHandler.END

# ---------- preset mgmt ----------
async def got_preset_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    limit_b = gb_to_bytes(update.message.text or "0")
    context.user_data["preset_limit_bytes"] = limit_b
    await update.message.reply_text("مدت استفاده به روز:")
    return ASK_PRESET_DAYS

async def got_preset_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(float((update.message.text or "0").strip()))
        assert days > 0
    except Exception:
        await update.message.reply_text("❌ یک عدد مثبت بفرست:")
        return ASK_PRESET_DAYS
    limit_b = int(context.user_data.get("preset_limit_bytes") or 0)

    editing_id = context.user_data.pop("editing_preset_id", None)
    if editing_id:
        update_preset(update.effective_user.id, editing_id, limit_b, days)
        notice = "✅ پریست ویرایش شد."
    else:
        create_preset(update.effective_user.id, limit_b, days)
        notice = "✅ پریست ذخیره شد."

    class Fake:
        async def edit_message_text(self, *a, **k):
            await update.message.reply_text(*a, **k)
    return await show_preset_menu(Fake(), context, update.effective_user.id, notice=notice)

# ---------- settings (admin) ----------
async def got_limit_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    msg = (update.message.text or "").strip()
    if not msg:
        await update.message.reply_text("❌ پیام خالیه. دوباره بفرست:")
        return ASK_LIMIT_MSG
    set_setting(update.effective_user.id, "limit_message", msg)
    await update.message.reply_text("✅ پیام ذخیره شد.", reply_markup=_back_kb("admin_technical"))
    return ConversationHandler.END

async def got_sub_placeholder_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_admin(uid) and not get_agent(uid):
        return ConversationHandler.END
    msg = (update.message.text or "").strip()
    if not msg:
        await update.message.reply_text("❌ قالب خالیه. دوباره بفرست:")
        return ASK_SUB_PLACEHOLDER_TEMPLATE
    back_target = "admin_technical" if is_admin(uid) else "agent_technical"
    if msg.lower() in {"off", "none", "clear", "delete"}:
        set_setting(uid, "subscription_placeholder_template", "")
        await update.message.reply_text("✅ قالب پاک شد.", reply_markup=_back_kb(back_target))
        return ConversationHandler.END
    set_setting(uid, "subscription_placeholder_template", msg)
    await update.message.reply_text("✅ قالب ذخیره شد.", reply_markup=_back_kb(back_target))
    return ConversationHandler.END

async def got_service_emerg_cfg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    sid = context.user_data.get("service_id")
    msg = (update.message.text or "").strip()
    key = f"emergency_config_service_{sid}"
    if msg.lower() in {"off", "none", "clear"}:
        set_setting(update.effective_user.id, key, "")
        await update.message.reply_text("✅ کانفیگ سرویس پاک شد.", reply_markup=_back_kb(f"service_sel:{sid}"))
        return ConversationHandler.END
    if not msg:
        await update.message.reply_text("❌ کانفیگ خالیه. دوباره بفرست:")
        return ASK_SERVICE_EMERGENCY_CFG
    set_setting(update.effective_user.id, key, msg)
    await update.message.reply_text("✅ کانفیگ سرویس ذخیره شد.", reply_markup=_back_kb(f"service_sel:{sid}"))
    return ConversationHandler.END

async def got_extra_sub_domains(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    msg = (update.message.text or "").strip()
    if not msg:
        await update.message.reply_text("❌ لیست خالیه. دوباره بفرست:")
        return ASK_EXTRA_SUB_DOMAINS
    if msg.lower() in {"off", "none", "clear", "delete"}:
        set_setting(update.effective_user.id, "extra_sub_domains", "")
        await update.message.reply_text("✅ دامنه‌های اضافه پاک شد.", reply_markup=_back_kb("admin_technical"))
        return ConversationHandler.END
    domains = parse_extra_domains(msg)
    if not domains:
        await update.message.reply_text("❌ دامنه معتبر پیدا نشد. دوباره بفرست:")
        return ASK_EXTRA_SUB_DOMAINS
    set_setting(update.effective_user.id, "extra_sub_domains", "\n".join(domains))
    await update.message.reply_text("✅ دامنه‌های اضافه ذخیره شد.", reply_markup=_back_kb("admin_technical"))
    return ConversationHandler.END


async def got_near_limit_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    msg = (update.message.text or "").strip().lower()
    if not msg:
        await update.message.reply_text("❌ مقدار خالیه. دوباره بفرست (مثل 10% یا 500MB):")
        return ASK_NEAR_LIMIT_THRESHOLD

    valid = False
    if msg.endswith("%"):
        try:
            val = float(msg[:-1].strip())
            valid = 0 <= val <= 100
        except Exception:
            valid = False
    elif msg.endswith("mb"):
        try:
            val = float(msg[:-2].strip())
            valid = val >= 0
        except Exception:
            valid = False

    if not valid:
        await update.message.reply_text("❌ فرمت نامعتبر است. مثل 10% یا 500MB بفرست:")
        return ASK_NEAR_LIMIT_THRESHOLD

    set_setting(update.effective_user.id, "usage_sync_near_limit_threshold", msg.upper() if msg.endswith("mb") else msg)
    await update.message.reply_text("✅ آستانه Near Limit ذخیره شد.", reply_markup=_back_kb("admin_technical"))
    return ConversationHandler.END


async def got_near_limit_sync_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    minutes = _parse_sync_minutes_input(update.message.text or "")
    if minutes is None:
        await update.message.reply_text("❌ یک عدد مثبت (دقیقه) بفرست:")
        return ASK_NEAR_LIMIT_SYNC_INTERVAL
    set_setting(update.effective_user.id, "near_limit_sync_interval", str(minutes))
    _propagate_admin_setting_to_agents("near_limit_sync_interval", str(minutes))
    await update.message.reply_text("✅ بازه Near-Limit Sync ذخیره شد.", reply_markup=_back_kb("admin_technical"))
    return ConversationHandler.END


async def got_normal_sync_interval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    minutes = _parse_sync_minutes_input(update.message.text or "")
    if minutes is None:
        await update.message.reply_text("❌ یک عدد مثبت (دقیقه) بفرست:")
        return ASK_NORMAL_SYNC_INTERVAL
    set_setting(update.effective_user.id, "normal_sync_interval", str(minutes))
    _propagate_admin_setting_to_agents("normal_sync_interval", str(minutes))
    await update.message.reply_text("✅ بازه Normal Sync ذخیره شد.", reply_markup=_back_kb("admin_technical"))
    return ConversationHandler.END

# ---------- add/edit panels (admin only) ----------
async def got_panel_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("دسترسی ندارید.")
        return ConversationHandler.END
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("❌ اسم معتبر بفرست:")
        return ASK_PANEL_NAME
    context.user_data["panel_name"] = name
    await update.message.reply_text(
        f"نوع پنل را مشخص کن ({'/'.join(PANEL_TYPES)}):",
        reply_markup=_back_kb("servers_panels")
    )
    return ASK_PANEL_TYPE

async def got_panel_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    t = (update.message.text or "").strip().lower()
    if t not in PANEL_TYPES:
        await update.message.reply_text(
            f"❌ نوع پنل نامعتبر. یکی از {'/'.join(PANEL_TYPES)} بفرست:",
            reply_markup=_back_kb("servers_panels")
        )
        return ASK_PANEL_TYPE
    context.user_data["panel_type"] = t
    await update.message.reply_text("🌐 URL پنل (مثال https://panel.example.com):", reply_markup=_back_kb("servers_panels"))
    return ASK_PANEL_URL

async def got_panel_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    url = (update.message.text or "").strip().rstrip("/")
    if not (url.startswith("http://") or url.startswith("https://")):
        await update.message.reply_text("❌ URL نامعتبر. دوباره بفرست:")
        return ASK_PANEL_URL
    context.user_data["panel_url"] = url
    await update.message.reply_text("👤 یوزرنیم ادمین:", reply_markup=_back_kb("servers_panels"))
    return ASK_PANEL_USER

async def got_panel_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    u = (update.message.text or "").strip()
    if not u:
        await update.message.reply_text("❌ خالیه. دوباره بفرست:")
        return ASK_PANEL_USER
    context.user_data["panel_user"] = u
    await update.message.reply_text("🔒 پسورد ادمین:", reply_markup=_back_kb("servers_panels"))
    return ASK_PANEL_PASS

async def got_panel_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    panel_url = context.user_data.get("panel_url")
    panel_user = context.user_data.get("panel_user")
    panel_name = context.user_data.get("panel_name") or make_panel_name(panel_url, panel_user)
    panel_type = context.user_data.get("panel_type", "marzneshin")
    password = (update.message.text or "").strip()
    try:
        api = get_api(panel_type)
        tok, err = api.get_admin_token(panel_url, panel_user, password)
        if not tok:
            await update.message.reply_text(f"❌ لاگین ناموفق: {err}")
            return ConversationHandler.END
        encrypted_password = None
        try:
            encrypted_password = encrypt_panel_password(password)
        except PanelTokenEncryptionError as exc:
            log.warning("Failed to encrypt panel password for %s: %s", panel_url, exc)
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                INSERT INTO panels(
                    telegram_user_id,
                    panel_url,
                    name,
                    panel_type,
                    admin_username,
                    access_token,
                    admin_password_encrypted
                ) VALUES(%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    update.effective_user.id,
                    panel_url,
                    panel_name,
                    panel_type,
                    panel_user,
                    tok,
                    encrypted_password,
                ),
            )
        msg = f"✅ پنل اضافه شد: {panel_name}"
        if panel_type == "sanaei":
            msg += "\nنکته: از 🛠️ Manage Panels می‌تونی Inbound ID را ست کنی."
        else:
            msg += "\nنکته: از 🛠️ Manage Panels می‌تونی Template و Sub URL را ست کنی."
        await update.message.reply_text(msg, reply_markup=_back_kb("servers_panels"))
    except MySQLError as e:
        await update.message.reply_text(f"❌ خطای DB: {e}", reply_markup=_back_kb("servers_panels"))
    except Exception as e:
        log.exception("add panel")
        await update.message.reply_text(f"❌ خطا: {e}", reply_markup=_back_kb("servers_panels"))
    finally:
        for k in ("panel_name", "panel_url", "panel_user", "panel_type"):
            context.user_data.pop(k, None)
    return ConversationHandler.END

async def got_panel_template(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    pid = context.user_data.get("edit_panel_id")
    if not pid:
        await update.message.reply_text("❌ پنل انتخاب نشده.")
        return ConversationHandler.END
    txt = (update.message.text or "").strip()
    val = None if txt == "-" else txt
    info = get_panel(update.effective_user.id, pid)
    if val and info and info.get("panel_type") == "sanaei":
        parts = [p.strip() for p in val.split(",") if p.strip().isdigit()]
        if not parts:
            await update.message.reply_text("❌ شناسه‌های اینباند نامعتبر است.")
            return ASK_PANEL_TEMPLATE
        val = ",".join(parts)
    try:
        with with_mysql_cursor() as cur:
            ids = expand_owner_ids(update.effective_user.id)
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"UPDATE panels SET template_username=%s WHERE id=%s AND telegram_user_id IN ({placeholders})",
                tuple([val, pid] + ids),
            )
        class FakeCQ:
            async def edit_message_text(self, *args, **kwargs):
                await update.message.reply_text(*args, **kwargs)
        return await show_panel_card(FakeCQ(), context, update.effective_user.id, pid)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}", reply_markup=_back_kb("servers_panels"))
        return ConversationHandler.END

async def got_edit_panel_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    pid = context.user_data.get("edit_panel_id")
    new = (update.message.text or "").strip()
    if not pid or not new:
        await update.message.reply_text("❌ ورودی نامعتبر.")
        return ConversationHandler.END
    try:
        with with_mysql_cursor() as cur:
            ids = expand_owner_ids(update.effective_user.id)
            placeholders = ",".join(["%s"] * len(ids))
            cur.execute(
                f"UPDATE panels SET name=%s WHERE id=%s AND telegram_user_id IN ({placeholders})",
                tuple([new, pid] + ids),
            )
        class FakeCQ:
            async def edit_message_text(self, *args, **kwargs):
                await update.message.reply_text(*args, **kwargs)
        return await show_panel_card(FakeCQ(), context, update.effective_user.id, pid)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}", reply_markup=_back_kb("servers_panels"))
        return ConversationHandler.END

async def got_edit_panel_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data["new_admin_user"] = (update.message.text or "").strip()
    if not context.user_data["new_admin_user"]:
        await update.message.reply_text("❌ خالیه. دوباره بفرست:")
        return ASK_EDIT_PANEL_USER
    await update.message.reply_text("پسورد ادمین جدید را بفرست:")
    return ASK_EDIT_PANEL_PASS

async def got_edit_panel_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    pid = context.user_data.get("edit_panel_id")
    new_user = context.user_data.get("new_admin_user")
    new_pass = (update.message.text or "").strip()
    if not pid or not new_user or not new_pass:
        await update.message.reply_text("❌ ورودی نامعتبر.")
        return ConversationHandler.END
    try:
        ids = expand_owner_ids(update.effective_user.id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"SELECT panel_url, panel_type FROM panels WHERE id=%s AND telegram_user_id IN ({placeholders})",
                tuple([pid] + ids),
            )
            row = cur.fetchone()
        if not row:
            raise RuntimeError("panel not found")
        api = get_api(row.get("panel_type"))
        tok, err = api.get_admin_token(row["panel_url"], new_user, new_pass)
        if not tok:
            raise RuntimeError(f"login failed: {err}")
        encrypted_password = None
        try:
            encrypted_password = encrypt_panel_password(new_pass)
        except PanelTokenEncryptionError as exc:
            log.warning("Failed to encrypt panel password for %s: %s", row["panel_url"], exc)
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""
                UPDATE panels
                SET admin_username=%s,
                    access_token=%s,
                    admin_password_encrypted=%s
                WHERE id=%s AND telegram_user_id IN ({placeholders})
                """,
                tuple([new_user, tok, encrypted_password, pid] + ids),
            )
        context.user_data.pop("new_admin_user", None)
        class FakeCQ:
            async def edit_message_text(self, *args, **kwargs):
                await update.message.reply_text(*args, **kwargs)
        return await show_panel_card(FakeCQ(), context, update.effective_user.id, pid)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا در بروزرسانی دسترسی: {e}")
        return ConversationHandler.END

async def got_panel_sub_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    pid = context.user_data.get("edit_panel_id")
    if not pid:
        await update.message.reply_text("❌ پنل انتخاب نشده.")
        return ConversationHandler.END
    txt = (update.message.text or "").strip()
    val = None if txt == "-" else txt
    if val and not (val.startswith("http://") or val.startswith("https://")):
        await update.message.reply_text("❌ لینک نامعتبر. دوباره بفرست (یا '-' برای حذف):")
        return ASK_PANEL_SUB_URL
    try:
        set_panel_sub_url(update.effective_user.id, pid, val)
        class FakeCQ:
            async def edit_message_text(self, *args, **kwargs):
                await update.message.reply_text(*args, **kwargs)
        return await show_panel_card(FakeCQ(), context, update.effective_user.id, pid)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}", reply_markup=_back_kb("servers_panels"))
        return ConversationHandler.END

async def got_panel_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    pid = context.user_data.get("edit_panel_id")
    if not pid:
        await update.message.reply_text("❌ پنل انتخاب نشده.")
        return ConversationHandler.END
    info = get_panel(update.effective_user.id, pid)
    if not info:
        await update.message.reply_text("❌ پنل انتخاب نشده.")
        return ConversationHandler.END
    panel_type = (info.get("panel_type") or "").lower()
    if panel_type not in ("rebecca", "guardcore"):
        await update.message.reply_text("❌ این پنل از API Key پشتیبانی نمی‌کند.")
        return ConversationHandler.END
    txt = (update.message.text or "").strip()
    if not txt:
        await update.message.reply_text("❌ مقدار معتبر بفرست (یا '-' برای حذف):")
        return ASK_PANEL_API_KEY
    val = None if txt == "-" else txt
    if val and panel_type == "guardcore":
        lowered = val.lower()
        if not (lowered.startswith("api_key:") or lowered.startswith("apikey:") or lowered.startswith("x-api-key:")):
            val = f"api_key:{val}"
    try:
        set_panel_api_key(update.effective_user.id, pid, val)
        class FakeCQ:
            async def edit_message_text(self, *args, **kwargs):
                await update.message.reply_text(*args, **kwargs)
        return await show_panel_card(FakeCQ(), context, update.effective_user.id, pid)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}", reply_markup=_back_kb("servers_panels"))
        return ConversationHandler.END

async def got_panel_multiplier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    pid = context.user_data.get("edit_panel_id")
    if not pid:
        await update.message.reply_text("❌ پنل انتخاب نشده.")
        return ConversationHandler.END
    txt = (update.message.text or "").strip()
    if txt == "-":
        multiplier = 1.0
    else:
        try:
            multiplier = float(txt)
        except ValueError:
            await update.message.reply_text("❌ عدد معتبر بفرست (مثلا 1 یا 0.5) یا '-' برای ریست:")
            return ASK_PANEL_MULTIPLIER
        if multiplier < 0:
            await update.message.reply_text("❌ مقدار منفی مجاز نیست. دوباره بفرست:")
            return ASK_PANEL_MULTIPLIER
    try:
        ids = expand_owner_ids(update.effective_user.id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"UPDATE panels SET usage_multiplier=%s WHERE id=%s AND telegram_user_id IN ({placeholders})",
                tuple([multiplier, pid] + ids),
            )
        class FakeCQ:
            async def edit_message_text(self, *args, **kwargs):
                await update.message.reply_text(*args, **kwargs)
        return await show_panel_card(FakeCQ(), context, update.effective_user.id, pid)
    except Exception as e:
        await update.message.reply_text(f"❌ خطا: {e}", reply_markup=_back_kb("servers_panels"))
        return ConversationHandler.END

# ---------- agent mgmt ----------
async def got_agent_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    name = (update.message.text or "").strip()
    if not name:
        await update.message.reply_text("❌ نام معتبر بفرست:")
        return ASK_AGENT_NAME
    context.user_data["new_agent_name"] = name
    await update.message.reply_text("Telegram User ID نماینده را بفرست:")
    return ASK_AGENT_TGID

async def got_agent_tgid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    try:
        aid = int((update.message.text or "").strip())
    except:
        await update.message.reply_text("❌ عدد معتبر بفرست:")
        return ASK_AGENT_TGID
    tok = upsert_agent(aid, context.user_data.get("new_agent_name") or "agent")
    context.user_data.pop("new_agent_name", None)
    if tok:
        await update.message.reply_text(f"✅ نماینده اضافه شد.\nToken: {tok}")
    else:
        await update.message.reply_text("✅ نماینده اضافه شد.")
    class Fake:
        async def edit_message_text(self, *a, **k):
            await update.message.reply_text(*a, **k)
    return await show_agent_card(Fake(), context, aid)

async def got_agent_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    a = context.user_data.get("agent_tg_id") or 0
    limit_b = parse_human_size(update.message.text or "0")
    set_agent_quota(a, limit_b)
    class Fake:
        async def edit_message_text(self, *a, **k):
            await update.message.reply_text(*a, **k)
    return await show_agent_card(Fake(), context, a, notice="✅ حجم کل ذخیره شد.")

async def got_agent_renew_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    a = context.user_data.get("agent_tg_id") or 0
    try:
        days = int(float((update.message.text or "0").strip()))
        assert days > 0
    except Exception:
        await update.message.reply_text("❌ یک عدد مثبت بفرست (مثلا 30).")
        return ASK_AGENT_RENEW_DAYS
    renew_agent_days(a, days)
    class Fake:
        async def edit_message_text(self, *a, **k):
            await update.message.reply_text(*a, **k)
    return await show_agent_card(Fake(), context, a, notice=f"✅ {days} روز به انقضا اضافه شد.")

async def got_agent_user_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    a = context.user_data.get("agent_tg_id") or 0
    try:
        num = int((update.message.text or "0").strip())
        assert num >= 0
    except Exception:
        await update.message.reply_text("❌ یک عدد صحیح بفرست (مثلا 100 یا 0).")
        return ASK_AGENT_MAX_USERS
    set_agent_user_limit(a, num)
    class Fake:
        async def edit_message_text(self, *a, **k):
            await update.message.reply_text(*a, **k)
    return await show_agent_card(Fake(), context, a, notice="✅ محدودیت تعداد ذخیره شد.")

async def got_agent_max_user_gb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    a = context.user_data.get("agent_tg_id") or 0
    limit_b = parse_human_size(update.message.text or "0")
    set_agent_max_user_bytes(a, limit_b)
    class Fake:
        async def edit_message_text(self, *a, **k):
            await update.message.reply_text(*a, **k)
    return await show_agent_card(Fake(), context, a, notice="✅ حداکثر حجم هر یوزر ذخیره شد.")

# ---------- new user flow ----------
async def got_newuser_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_username"] = (update.message.text or "").strip()
    if not context.user_data["new_username"]:
        await update.message.reply_text("❌ خالیه. دوباره بفرست:")
        return ASK_NEWUSER_NAME
    if not is_valid_local_username(context.user_data["new_username"]):
        await update.message.reply_text(
            "❌ نام کاربر نامعتبر است. فقط حروف/اعداد انگلیسی مجاز است، باید با حرف انگلیسی شروع شود و طول آن 3 تا 20 کاراکتر باشد."
        )
        return ASK_NEWUSER_NAME
    uid = update.effective_user.id
    if not is_admin(uid):
        ag = get_agent(uid) or {}
        limit = int(ag.get("user_limit") or 0)
        max_user_bytes = int(ag.get("max_user_bytes") or 0)
        context.user_data["agent_max_user_bytes"] = max_user_bytes
        if limit > 0:
            total = count_local_users(uid)
            exists = get_local_user(uid, context.user_data["new_username"])
            if not exists and total >= limit:
                await update.message.reply_text("❌ به حد مجاز تعداد کاربران رسیده‌اید.")
                return ConversationHandler.END
    else:
        context.user_data["agent_max_user_bytes"] = 0
    return await show_preset_select(update, context, uid)

async def got_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    limit_b = gb_to_bytes(update.message.text or "0")
    max_b = int(context.user_data.get("agent_max_user_bytes") or 0)
    if max_b > 0 and limit_b > max_b:
        await update.message.reply_text(
            f"❌ حداکثر حجم مجاز {fmt_bytes_short(max_b)} است. دوباره بفرست:")
        return ASK_LIMIT_GB
    context.user_data["limit_bytes"] = limit_b
    await update.message.reply_text("مدت استفاده به روز (مثلا 30):")
    return ASK_DURATION

async def got_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        days = int(float((update.message.text or "0").strip()))
        assert days > 0
    except Exception:
        await update.message.reply_text("❌ یک عدد مثبت بفرست (مثلا 30).")
        return ASK_DURATION
    context.user_data["duration_days"] = days

    uid = update.effective_user.id
    panels = list_panels_for_agent(uid) if not is_admin(uid) else list_my_panels_admin(uid)
    if not panels:
        await update.message.reply_text("❌ هیچ پنلی برای شما ثبت نشده. لطفا به ادمین اطلاع دهید.")
        return ConversationHandler.END

    class FakeMsg:
        async def edit_message_text(self, *args, **kwargs):
            await update.message.reply_text(*args, **kwargs)
    return await show_service_select(FakeMsg(), context, update.effective_user.id)

async def got_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = (update.message.text or "").strip()
    uid = update.effective_user.id
    owner_id = get_manage_owner_id(context, uid)
    rows = search_local_users(owner_id, q)
    if not rows:
        await update.message.reply_text("کاربری یافت نشد.")
        return ConversationHandler.END
    kb = [[InlineKeyboardButton(r["username"], callback_data=f"user_sel:{r['username']}")] for r in rows[:25]]
    kb.append([InlineKeyboardButton("⬅️ Back", callback_data="list_users:0")])
    await update.message.reply_text("نتایج:", reply_markup=InlineKeyboardMarkup(kb))
    return ConversationHandler.END

async def handle_edit_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = context.user_data.get("manage_username")
    if not uname:
        await update.message.reply_text("یوزر انتخاب نشده.")
        return ConversationHandler.END
    new_bytes = parse_human_size(update.message.text or "")
    owner_id = get_manage_owner_id(context, update.effective_user.id)
    update_limit(owner_id, uname, new_bytes)
    class FakeCQ:
        async def edit_message_text(self, *args, **kwargs):
            await update.message.reply_text(*args, **kwargs)
    return await show_user_card(FakeCQ(), owner_id, uname, notice="✅ لیمیت بروزرسانی شد.")

async def handle_renew_days(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uname = context.user_data.get("manage_username")
    if not uname:
        await update.message.reply_text("یوزر انتخاب نشده.")
        return ConversationHandler.END
    try:
        days = int(float((update.message.text or "0").strip()))
        assert days > 0
    except Exception:
        await update.message.reply_text("❌ یک عدد مثبت بفرست (مثلا 30).")
        return ASK_RENEW_DAYS
    owner_id = get_manage_owner_id(context, update.effective_user.id)
    renew_user(owner_id, uname, days)
    class FakeCQ:
        async def edit_message_text(self, *args, **kwargs):
            await update.message.reply_text(*args, **kwargs)
    return await show_user_card(FakeCQ(), owner_id, uname, notice=f"✅ {days} روز تمدید شد.")

# ---------- cancel ----------
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("لغو شد.")
    return ConversationHandler.END

# ---------- finalize create / apply edit ----------
async def finalize_create_on_selected(q, context, owner_id: int, selected_ids: set):
    app_username = context.user_data["new_username"]
    limit_bytes = context.user_data["limit_bytes"]
    days = context.user_data["duration_days"]
    usage_sec = days * 86400

    app_key = upsert_app_user(owner_id, app_username)
    upsert_local_user(owner_id, app_username, limit_bytes, days)

    panels = list_panels_for_agent(owner_id) if not is_admin(owner_id) else list_my_panels_admin(owner_id)
    rows = [p for p in panels if int(p["id"]) in selected_ids]
    missing = [
        f"{r['name']}"
        for r in rows
        if (r.get("panel_type") in ("marzneshin", "sanaei", "guardcore")) and not r.get("template_username")
    ]
    if missing:
        await q.edit_message_text(
            "⚠️ این پنل‌ها template/inbound ندارند:\n" + "\n".join(f"• {m}" for m in missing)
        )
        return

    per_panel, errs = {}, []
    for r in rows:
        api = get_api(r.get("panel_type"))
        if r.get("panel_type") in ("marzneshin", "guardcore"):
            svc, e = api.fetch_user_services(
                r["panel_url"], r["access_token"], r.get("template_username")
            )
            if e:
                errs.append(
                    f"{r['panel_url']} (template '{r['template_username']}'): {e}"
                )
            per_panel[r["id"]] = {"service_ids": svc or []}
        elif r.get("panel_type") == "sanaei":
            ids = [x.strip() for x in (r.get("template_username") or "").split(",") if x.strip().isdigit()]
            per_panel[r["id"]] = {"inbound_ids": ids}
        else:
            tmpl = r.get("template_username")
            if not tmpl:
                errs.append(f"{r['panel_url']}: template missing")
                per_panel[r["id"]] = {"proxies": {}, "inbounds": {}}
                continue
            obj, e = api.get_user(r["panel_url"], r["access_token"], tmpl)
            if not obj:
                errs.append(
                    f"{r['panel_url']} (template '{tmpl}'): {e or 'not found'}"
                )
                per_panel[r["id"]] = {"proxies": {}, "inbounds": {}}
                continue
            tmpl_info = {
                "proxies": obj.get("proxies") or {},
                "inbounds": obj.get("inbounds") or {},
            }
            if r.get("panel_type") == "rebecca":
                tmpl_info["service_id"] = obj.get("service_id")
            if r.get("panel_type") == "pasarguard":
                groups = obj.get("group_ids")
                if groups is not None:
                    tmpl_info["group_ids"] = list(groups)
            per_panel[r["id"]] = tmpl_info
    if errs:
        await q.edit_message_text(
            "❌ خطا در خواندن سرویس بعضی پنل‌ها:\n" +
            "\n".join(f"• {e}" for e in errs[:10])
        )
        return

    ok, failed = 0, []
    for r in rows:
        api = get_api(r.get("panel_type"))
        remote_name = panel_username(r.get("panel_type"), app_username)
        if r.get("panel_type") == "marzneshin":
            payload = {
                "username": remote_name,
                "expire_strategy": "start_on_first_use",
                "usage_duration": usage_sec,
                "data_limit": limit_bytes,
                "data_limit_reset_strategy": "no_reset",
                "note": "created_by_bot",
                "service_ids": per_panel.get(r["id"], {}).get("service_ids", []),
            }
        elif r.get("panel_type") == "guardcore":
            payload = {
                "username": remote_name,
                "limit_usage": limit_bytes,
                "limit_expire": usage_sec,
                "note": "created_by_bot",
                "service_ids": per_panel.get(r["id"], {}).get("service_ids", []),
            }
        elif r.get("panel_type") == "sanaei":
            expire_ts = 0 if usage_sec <= 0 else int(datetime.now(timezone.utc).timestamp()) + usage_sec
            inbound_ids = per_panel.get(r["id"], {}).get("inbound_ids", [])
            remote_names = []
            for inb in inbound_ids:
                rn = f"{app_username}_{secrets.token_hex(3)}"
                client = {
                    "id": str(uuid.uuid4()),
                    "email": rn,
                    "enable": True,
                }
                if limit_bytes > 0:
                    client["totalGB"] = limit_bytes
                if expire_ts > 0:
                    client["expiryTime"] = expire_ts * 1000
                payload = {
                    "id": int(inb),
                    "settings": json.dumps({"clients": [client]}, separators=(",", ":")),
                }
                obj, e = api.create_user(r["panel_url"], r["access_token"], payload)
                if not obj:
                    obj, g = api.get_user(r["panel_url"], r["access_token"], rn)
                    if not obj:
                        failed.append(f"{r['panel_url']} (inb {inb}): {e or g or 'unknown error'}")
                        continue
                if not obj.get("enabled", True):
                    ok_en, err_en = api.enable_remote_user(r["panel_url"], r["access_token"], rn)
                    if not ok_en:
                        failed.append(f"{r['panel_url']} (inb {inb}): enable failed - {err_en or 'unknown'}")
                        continue
                remote_names.append(rn)
            if remote_names:
                remote_name = ",".join(remote_names)
                save_link(owner_id, app_username, r["id"], remote_name)
                ok += 1
            continue
        else:
            expire_ts = 0 if usage_sec <= 0 else int(datetime.now(timezone.utc).timestamp()) + usage_sec
            tmpl_info = per_panel.get(r["id"], {})
            payload = {
                "username": remote_name,
                "expire": expire_ts,
                "data_limit": limit_bytes,
                "data_limit_reset_strategy": "no_reset",
                "note": "created_by_bot",
                "proxies": clone_proxy_settings(tmpl_info.get("proxies", {})),
                "inbounds": tmpl_info.get("inbounds", {}),
            }
            if r.get("panel_type") == "rebecca":
                service_id = tmpl_info.get("service_id")
                if service_id is not None:
                    payload["service_id"] = service_id
            if r.get("panel_type") == "pasarguard":
                groups = tmpl_info.get("group_ids")
                if groups is not None:
                    payload["group_ids"] = list(groups)
        obj, e = api.create_user(r["panel_url"], r["access_token"], payload)
        if not obj:
            obj, g = api.get_user(r["panel_url"], r["access_token"], remote_name)
            if not obj:
                failed.append(f"{r['panel_url']}: {e or g or 'unknown error'}")
                continue
        if not obj.get("enabled", True):
            ok_en, err_en = api.enable_remote_user(r["panel_url"], r["access_token"], remote_name)
            if not ok_en:
                failed.append(f"{r['panel_url']}: enable failed - {err_en or 'unknown'}")
        save_link(owner_id, app_username, r["id"], remote_name)
        ok += 1

    links = build_sub_links(owner_id, app_username, app_key)
    txt = (
        f"✅ یوزر '{app_username}' روی {ok}/{len(rows)} پنل انتخابی ساخته/فعال شد.\n"
        f"{format_sub_links_text(links)}"
    )
    if failed:
        txt += "\n⚠️ خطاها:\n" + "\n".join(f"• {e}" for e in failed[:8])
    await q.edit_message_text(txt)

def sync_user_panels(owner_id: int, username: str, selected_ids: set):
    lu = get_local_user(owner_id, username)
    if not lu:
        links_map = map_linked_remote_usernames(owner_id, username)
        if links_map:
            log.info(
                "sync_user_panels removing stale links for missing user %s/%s", owner_id, username
            )
            panels = (
                list_panels_for_agent(owner_id)
                if not is_admin(owner_id)
                else list_my_panels_admin(owner_id)
            )
            panels_map = {int(p["id"]): p for p in panels}
            for pid, remote in list(links_map.items()):
                remove_link(owner_id, username, int(pid))
                panel = panels_map.get(int(pid))
                if not panel:
                    continue
                api = get_api(panel.get("panel_type"))
                remotes = (
                    remote.split(",")
                    if panel.get("panel_type") == "sanaei"
                    else [remote]
                )
                for rn in remotes:
                    ok, err = api.remove_remote_user(
                        panel["panel_url"], panel["access_token"], rn
                    )
                    if not ok:
                        log.warning(
                            "sync_user_panels failed removing remote %s from panel %s: %s",
                            rn,
                            panel.get("panel_url"),
                            err or "unknown error",
                        )
        log.info("sync_user_panels skip missing local user %s/%s", owner_id, username)
        return

    links_map = map_linked_remote_usernames(owner_id, username)
    current = set(links_map.keys())
    to_add = selected_ids - current
    to_remove = current - selected_ids

    added_errs = []
    removed = 0
    added_ok = 0
    enabled_ok = 0

    panels = list_panels_for_agent(owner_id) if not is_admin(owner_id) else list_my_panels_admin(owner_id)
    panels_map = {int(p["id"]): p for p in panels}

    limit_bytes_default = int(lu["plan_limit_bytes"] or 0)
    exp = lu["expire_at"]
    usage_duration_default = (
        max(86400, int((exp - datetime.utcnow()).total_seconds())) if exp else 3650 * 86400
    )
    is_disabled = bool(lu.get("disabled_pushed"))

    if to_add:
        expire_ts_default = (
            0 if usage_duration_default <= 0 else int(datetime.now(timezone.utc).timestamp()) + usage_duration_default
        )
        for pid in to_add:
            if is_disabled:
                log.info(
                    "skip add panel %s for disabled user %s/%s",
                    pid,
                    owner_id,
                    username,
                )
                continue
            p = panels_map.get(int(pid))
            if not p:
                continue
            api = get_api(p.get("panel_type"))
            tmpl = p.get("template_username")
            if p.get("panel_type") == "marzneshin":
                if not tmpl:
                    obj, g = api.get_user(p["panel_url"], p["access_token"], username)
                    if obj:
                        if not obj.get("enabled", True):
                            ok_en, err_en = api.enable_remote_user(p["panel_url"], p["access_token"], username)
                            if not ok_en:
                                added_errs.append(f"{p['panel_url']}: enable failed - {err_en or 'unknown'}")
                        save_link(owner_id, username, int(pid), username)
                        links_map[int(pid)] = username
                        added_ok += 1
                    else:
                        added_errs.append(f"{p['panel_url']}: no template & user not found")
                    continue

                svc, e = api.fetch_user_services(p["panel_url"], p["access_token"], tmpl)
                if e:
                    obj, g = api.get_user(p["panel_url"], p["access_token"], username)
                    if obj:
                        if not obj.get("enabled", True):
                            ok_en, err_en = api.enable_remote_user(p["panel_url"], p["access_token"], username)
                            if not ok_en:
                                added_errs.append(f"{p['panel_url']}: enable failed - {err_en or 'unknown'}")
                        save_link(owner_id, username, int(pid), username)
                        links_map[int(pid)] = username
                        added_ok += 1
                    else:
                        added_errs.append(f"{p['panel_url']}: {e}")
                    continue

                payload = {
                    "username": username,
                    "expire_strategy": "start_on_first_use",
                    "usage_duration": usage_duration_default,
                    "data_limit": limit_bytes_default,
                    "data_limit_reset_strategy": "no_reset",
                    "note": "user_edit_add_panel",
                    "service_ids": svc or [],
                }
                obj, e2 = api.create_user(p["panel_url"], p["access_token"], payload)
                if not obj:
                    obj, g = api.get_user(p["panel_url"], p["access_token"], username)
                    if not obj:
                        added_errs.append(f"{p['panel_url']}: {e2 or g or 'unknown error'}")
                        continue

                if not obj.get("enabled", True):
                    ok_en, err_en = api.enable_remote_user(p["panel_url"], p["access_token"], username)
                    if not ok_en:
                        added_errs.append(f"{p['panel_url']}: enable failed - {err_en or 'unknown'}")

                save_link(owner_id, username, int(pid), username)
                links_map[int(pid)] = username
                added_ok += 1
            elif p.get("panel_type") == "guardcore":
                remote_username = panel_username(p.get("panel_type"), username)
                if not tmpl:
                    obj, g = api.get_user(p["panel_url"], p["access_token"], remote_username)
                    if obj:
                        if not obj.get("enabled", True):
                            ok_en, err_en = api.enable_remote_user(p["panel_url"], p["access_token"], remote_username)
                            if not ok_en:
                                added_errs.append(f"{p['panel_url']}: enable failed - {err_en or 'unknown'}")
                        save_link(owner_id, username, int(pid), remote_username)
                        links_map[int(pid)] = remote_username
                        added_ok += 1
                    else:
                        added_errs.append(f"{p['panel_url']}: no template & user not found")
                    continue

                svc, e = api.fetch_user_services(p["panel_url"], p["access_token"], tmpl)
                if e:
                    obj, g = api.get_user(p["panel_url"], p["access_token"], remote_username)
                    if obj:
                        if not obj.get("enabled", True):
                            ok_en, err_en = api.enable_remote_user(p["panel_url"], p["access_token"], remote_username)
                            if not ok_en:
                                added_errs.append(f"{p['panel_url']}: enable failed - {err_en or 'unknown'}")
                        save_link(owner_id, username, int(pid), remote_username)
                        links_map[int(pid)] = remote_username
                        added_ok += 1
                    else:
                        added_errs.append(f"{p['panel_url']}: {e}")
                    continue

                payload = {
                    "username": remote_username,
                    "limit_usage": limit_bytes_default,
                    "limit_expire": usage_duration_default,
                    "note": "user_edit_add_panel",
                    "service_ids": svc or [],
                }
                obj, e2 = api.create_user(p["panel_url"], p["access_token"], payload)
                if not obj:
                    obj, g = api.get_user(p["panel_url"], p["access_token"], remote_username)
                    if not obj:
                        added_errs.append(f"{p['panel_url']}: {e2 or g or 'unknown error'}")
                        continue

                if not obj.get("enabled", True):
                    ok_en, err_en = api.enable_remote_user(p["panel_url"], p["access_token"], remote_username)
                    if not ok_en:
                        added_errs.append(f"{p['panel_url']}: enable failed - {err_en or 'unknown'}")

                save_link(owner_id, username, int(pid), remote_username)
                links_map[int(pid)] = remote_username
                added_ok += 1
            elif p.get("panel_type") == "sanaei":
                if not tmpl:
                    added_errs.append(f"{p['panel_url']}: inbound missing")
                    continue
                inb_ids = [x.strip() for x in tmpl.split(",") if x.strip().isdigit()]
                if not inb_ids:
                    added_errs.append(f"{p['panel_url']}: inbound missing")
                    continue
                remote_names = []
                for inb in inb_ids:
                    remote_name = f"{username}_{secrets.token_hex(3)}"
                    client = {
                        "id": str(uuid.uuid4()),
                        "email": remote_name,
                        "enable": True,
                    }
                    if limit_bytes_default > 0:
                        client["totalGB"] = limit_bytes_default
                    if expire_ts_default > 0:
                        client["expiryTime"] = expire_ts_default * 1000
                    payload = {
                        "id": int(inb),
                        "settings": json.dumps({"clients": [client]}, separators=(",", ":")),
                    }
                    obj, e2 = api.create_user(p["panel_url"], p["access_token"], payload)
                    if not obj:
                        added_errs.append(f"{p['panel_url']} (inb {inb}): {e2 or 'unknown error'}")
                        continue
                    if not obj.get("enabled", True):
                        ok_en, err_en = api.enable_remote_user(p["panel_url"], p["access_token"], remote_name)
                        if not ok_en:
                            added_errs.append(f"{p['panel_url']} (inb {inb}): enable failed - {err_en or 'unknown'}")
                            continue
                    remote_names.append(remote_name)
                if remote_names:
                    joined = ",".join(remote_names)
                    save_link(owner_id, username, int(pid), joined)
                    links_map[int(pid)] = joined
                    added_ok += 1
                continue
            else:
                obj, g = api.get_user(p["panel_url"], p["access_token"], username)
                if not obj:
                    if tmpl:
                        tmpl_obj, t_err = api.get_user(
                            p["panel_url"], p["access_token"], tmpl
                        )
                        if not tmpl_obj:
                            added_errs.append(
                                f"{p['panel_url']} (template '{tmpl}'): {t_err or 'not found'}"
                            )
                            continue
                        payload = {
                            "username": username,
                            "expire": expire_ts_default,
                            "data_limit": limit_bytes_default,
                            "data_limit_reset_strategy": "no_reset",
                            "note": "user_edit_add_panel",
                            "proxies": clone_proxy_settings(tmpl_obj.get("proxies") or {}),
                            "inbounds": tmpl_obj.get("inbounds") or {},
                        }
                        if p.get("panel_type") == "rebecca":
                            service_id = tmpl_obj.get("service_id")
                            if service_id is not None:
                                payload["service_id"] = service_id
                        if p.get("panel_type") == "pasarguard":
                            groups = tmpl_obj.get("group_ids")
                            if groups is not None:
                                payload["group_ids"] = list(groups)
                        obj, e2 = api.create_user(
                            p["panel_url"], p["access_token"], payload
                        )
                        if not obj:
                            added_errs.append(
                                f"{p['panel_url']}: {e2 or 'unknown error'}"
                            )
                            continue
                    else:
                        added_errs.append(
                            f"{p['panel_url']}: no template & user not found"
                        )
                        continue
                if not obj.get("enabled", True):
                    ok_en, err_en = api.enable_remote_user(
                        p["panel_url"], p["access_token"], username
                    )
                    if not ok_en:
                        added_errs.append(
                            f"{p['panel_url']}: enable failed - {err_en or 'unknown'}"
                        )
                save_link(owner_id, username, int(pid), username)
                links_map[int(pid)] = username
                added_ok += 1

    if to_remove:
        for pid in to_remove:
            p = panels_map.get(int(pid))
            remote = links_map.get(int(pid), panel_username(p.get("panel_type"), username) if p else username)
            remove_link(owner_id, username, int(pid))
            links_map.pop(int(pid), None)
            removed += 1
            if p:
                api = get_api(p.get("panel_type"))
                remotes = remote.split(",") if p.get("panel_type") == "sanaei" else [remote]
                for rn in remotes:
                    ok, err = api.remove_remote_user(p["panel_url"], p["access_token"], rn)
                    if not ok:
                        added_errs.append(f"remove on {p['panel_url']}: {err or 'unknown error'}")

    for pid in selected_ids:
        if is_disabled:
            continue
        p = panels_map.get(int(pid))
        if not p:
            continue
        api = get_api(p.get("panel_type"))
        remote = links_map.get(int(pid), panel_username(p.get("panel_type"), username))
        remotes = remote.split(",") if p.get("panel_type") == "sanaei" else [remote]
        for rn in remotes:
            obj, g = api.get_user(p["panel_url"], p["access_token"], rn)
            if obj and not obj.get("enabled", True):
                ok_en, err_en = api.enable_remote_user(p["panel_url"], p["access_token"], rn)
                if ok_en:
                    enabled_ok += 1
                else:
                    added_errs.append(f"{p['panel_url']}: enable failed - {err_en or 'unknown'}")
        if int(pid) not in links_map:
            save_link(owner_id, username, int(pid), remote)
            links_map[int(pid)] = remote

    log.info(
        "sync_user_panels %s/%s -> add:%d remove:%d enable:%d",
        owner_id,
        username,
        added_ok,
        removed,
        enabled_ok,
    )
    if added_errs:
        log.warning("sync_user_panels errors: %s", "; ".join(added_errs[:10]))

async def sync_user_panels_async(owner_id: int, username: str, selected_ids: set):
    """Run sync_user_panels in a thread to avoid blocking the event loop."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sync_user_panels, owner_id, username, selected_ids)

# ---------- wiring ----------
def build_app():
    load_dotenv()
    tok = os.getenv("BOT_TOKEN", "").strip()
    if not tok:
        raise RuntimeError("BOT_TOKEN missing in .env")
    init_mysql_pool()
    ensure_schema()
    app = Application.builder().token(tok).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start), CallbackQueryHandler(on_button)],
        states={
            # add panel (admin)
            ASK_PANEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_panel_name)],
            ASK_PANEL_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_panel_type)],
            ASK_PANEL_URL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, got_panel_url)],
            ASK_PANEL_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_panel_user)],
            ASK_PANEL_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_panel_pass)],

            # panel edits (admin)
            ASK_PANEL_TEMPLATE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, got_panel_template)],
            ASK_EDIT_PANEL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_edit_panel_name)],
            ASK_EDIT_PANEL_USER: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_edit_panel_user)],
            ASK_EDIT_PANEL_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_edit_panel_pass)],
            ASK_PANEL_SUB_URL:  [MessageHandler(filters.TEXT & ~filters.COMMAND, got_panel_sub_url)],
            ASK_PANEL_API_KEY:  [MessageHandler(filters.TEXT & ~filters.COMMAND, got_panel_api_key)],
            ASK_PANEL_MULTIPLIER: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_panel_multiplier)],
            ASK_PANEL_REMOVE_CONFIRM: [CallbackQueryHandler(on_button)],

            # agent mgmt (admin)
            ASK_AGENT_NAME:        [MessageHandler(filters.TEXT & ~filters.COMMAND, got_agent_name)],
            ASK_AGENT_TGID:        [MessageHandler(filters.TEXT & ~filters.COMMAND, got_agent_tgid)],
            ASK_AGENT_LIMIT:       [MessageHandler(filters.TEXT & ~filters.COMMAND, got_agent_limit)],
            ASK_AGENT_RENEW_DAYS:  [MessageHandler(filters.TEXT & ~filters.COMMAND, got_agent_renew_days)],
            ASK_AGENT_MAX_USERS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_agent_user_limit)],
            ASK_AGENT_MAX_USER_GB: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_agent_max_user_gb)],

            # service mgmt (admin)
            ASK_SERVICE_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, got_service_name)],
            ASK_EDIT_SERVICE_NAME:[MessageHandler(filters.TEXT & ~filters.COMMAND, got_service_new_name)],
            ASK_ASSIGN_SERVICE_PANELS: [CallbackQueryHandler(on_button)],

            # settings
            ASK_LIMIT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_limit_msg)],
            ASK_SUB_PLACEHOLDER_TEMPLATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, got_sub_placeholder_template)
            ],
            ASK_SERVICE_EMERGENCY_CFG: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_service_emerg_cfg)],
            ASK_EXTRA_SUB_DOMAINS: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_extra_sub_domains)],
            ASK_NEAR_LIMIT_THRESHOLD: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_near_limit_threshold)],
            ASK_NEAR_LIMIT_SYNC_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_near_limit_sync_interval)],
            ASK_NORMAL_SYNC_INTERVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_normal_sync_interval)],

            # preset mgmt
            ASK_PRESET_GB:   [MessageHandler(filters.TEXT & ~filters.COMMAND, got_preset_gb)],
            ASK_PRESET_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_preset_days)],

            # user creation
            ASK_NEWUSER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, got_newuser_name)],
            ASK_PRESET_CHOICE: [CallbackQueryHandler(on_button)],
            ASK_LIMIT_GB:     [MessageHandler(filters.TEXT & ~filters.COMMAND, got_limit)],
            ASK_DURATION:     [MessageHandler(filters.TEXT & ~filters.COMMAND, got_duration)],

            # service selection for new user
            ASK_SELECT_SERVICE: [CallbackQueryHandler(on_button)],

            # search/manage
            ASK_SEARCH_USER:  [MessageHandler(filters.TEXT & ~filters.COMMAND, got_search)],
            ASK_EDIT_LIMIT:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_limit)],
            ASK_RENEW_DAYS:   [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_renew_days)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="bot_flow",
        allow_reentry=True,
    )
    app.add_handler(conv)
    return app

if __name__ == "__main__":
    build_app().run_polling(drop_pending_updates=True)
