#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import requests
from urllib.parse import urljoin
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from services import init_mysql_pool, with_mysql_cursor
from services.database import mysql_errors
from services.panel_tokens import ensure_panel_tokens
from services.settings import get_setting as get_owner_setting

from apis import marzneshin, marzban, rebecca, sanaei, pasarguard, guardcore

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | usage_sync | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("usage_sync")

API_MODULES = {
    "marzneshin": marzneshin,
    "marzban": marzban,
    "rebecca": rebecca,
    "sanaei": sanaei,
    "pasarguard": pasarguard,
    "guardcore": guardcore,
}

_local_users_columns = None

DEFAULT_NEAR_LIMIT_SYNC_INTERVAL_MINUTES = 5
DEFAULT_NORMAL_SYNC_INTERVAL_MINUTES = 10
DEFAULT_NEAR_LIMIT_THRESHOLD_PERCENT = 10.0
MIN_SYNC_INTERVAL_SECONDS = 60
REPORT_WINDOW_MINUTES = 10
AGENT_INTERVAL_SETTING_KEYS = {
    "near_limit_sync_interval": "agent_near_limit_sync_interval",
    "normal_sync_interval": "agent_normal_sync_interval",
}


def get_api(panel_type: str):
    """Return API module for the given panel type."""
    return API_MODULES.get(panel_type or "marzneshin", marzneshin)

# ---------------- existing per-link / per-user logic ----------------

def ensure_links_table():
    """Create local_user_panel_links table if missing."""
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS local_user_panel_links(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                owner_id BIGINT NOT NULL,
                local_username VARCHAR(64) NOT NULL,
                panel_id BIGINT NOT NULL,
                remote_username VARCHAR(128) NOT NULL,
                last_used_traffic BIGINT NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_link(owner_id, local_username, panel_id),
                FOREIGN KEY (panel_id) REFERENCES panels(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )


def ensure_agent_panel_usage_totals_table():
    """Create lifetime usage table and backfill from existing link snapshots."""
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_panel_usage_totals(
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                agent_tg_id BIGINT NOT NULL,
                panel_id BIGINT NOT NULL,
                total_used_bytes BIGINT NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY uq_agent_panel_usage(agent_tg_id, panel_id),
                FOREIGN KEY (panel_id) REFERENCES panels(id) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """
        )
        cur.execute(
            """
            INSERT INTO agent_panel_usage_totals(agent_tg_id, panel_id, total_used_bytes)
            SELECT
                lup.owner_id,
                lup.panel_id,
                COALESCE(SUM(lup.last_used_traffic), 0) AS total_used_bytes
            FROM local_user_panel_links lup
            GROUP BY lup.owner_id, lup.panel_id
            ON DUPLICATE KEY UPDATE total_used_bytes = GREATEST(
                agent_panel_usage_totals.total_used_bytes,
                VALUES(total_used_bytes)
            )
            """
        )


def fetch_all_links():
    try:
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                SELECT lup.id AS link_id,
                       lup.owner_id,
                       lup.local_username,
                       lup.panel_id,
                       lup.remote_username,
                       lup.last_used_traffic,
                       p.panel_url,
                       p.access_token,
                       p.panel_type,
                       p.usage_multiplier,
                       p.admin_username,
                       p.admin_password_encrypted,
                       p.token_refreshed_at
                FROM local_user_panel_links lup
                JOIN panels p ON p.id = lup.panel_id
                ORDER BY lup.id ASC
                """
            )
            links = cur.fetchall()
            if not links:
                return links

            # Refresh once per unique panel, then fan out refreshed token to all links.
            panel_rows = {}
            for row in links:
                panel_rows.setdefault(row["panel_id"], row)
            refreshed_panels = ensure_panel_tokens(list(panel_rows.values()))
            refreshed_by_panel = {int(p["panel_id"]): p for p in refreshed_panels if p.get("panel_id") is not None}
            for row in links:
                refreshed = refreshed_by_panel.get(int(row["panel_id"]))
                if refreshed:
                    row["access_token"] = refreshed.get("access_token") or row.get("access_token")
                    row["token_refreshed_at"] = refreshed.get("token_refreshed_at")
            return links
    except mysql_errors.ProgrammingError as e:
        if getattr(e, "errno", None) == 1146:  # table doesn't exist
            log.warning("local_user_panel_links table missing; creating")
            ensure_links_table()
            return []
        raise

def fetch_used_traffic(panel_type, panel_url, bearer, remote_username):
    """Return used traffic for a remote user via appropriate panel API."""
    try:
        api = get_api(panel_type)
        if panel_type == "sanaei" and "," in remote_username:
            total = 0
            for rn in [r.strip() for r in remote_username.split(",") if r.strip()]:
                obj, err = api.get_user(panel_url, bearer, rn)
                if not obj:
                    return None, f"{panel_url}: {err or 'user not found'}"
                total += int(obj.get("used_traffic", 0) or 0)
            return total, None
        obj, err = api.get_user(panel_url, bearer, remote_username)
        if not obj:
            return None, f"{panel_url}: {err or 'user not found'}"
        return int(obj.get("used_traffic", 0) or 0), None
    except Exception as e:  # pragma: no cover - network errors
        return None, str(e)

def add_local_usage(owner_id, local_username, delta):
    if delta <= 0:
        return
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            UPDATE local_users
            SET used_bytes = LEAST(used_bytes + %s, 18446744073709551615)
            WHERE owner_id = %s AND username = %s
        """,
            (int(delta), int(owner_id), local_username),
        )


def add_agent_usage(owner_id, delta):
    if delta <= 0:
        return
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            UPDATE agents
            SET total_used_bytes = LEAST(total_used_bytes + %s, 18446744073709551615)
            WHERE telegram_user_id = %s
        """,
            (int(delta), int(owner_id)),
        )


def add_panel_lifetime_usage(owner_id, panel_id, delta):
    if delta <= 0:
        return
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            INSERT INTO agent_panel_usage_totals(agent_tg_id, panel_id, total_used_bytes)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE total_used_bytes = LEAST(total_used_bytes + VALUES(total_used_bytes), 18446744073709551615)
            """,
            (int(owner_id), int(panel_id), int(delta)),
        )

def update_last(link_id, new_used):
    with with_mysql_cursor() as cur:
        cur.execute(
            "UPDATE local_user_panel_links SET last_used_traffic=%s WHERE id=%s",
            (int(new_used), int(link_id)),
        )

def get_local_users_columns():
    global _local_users_columns
    if _local_users_columns is not None:
        return _local_users_columns
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'local_users'
            """
        )
        _local_users_columns = {row[0] for row in cur.fetchall()}
    return _local_users_columns

def get_local_user(owner_id, local_username):
    columns = get_local_users_columns()
    wanted = [
        "plan_limit_bytes",
        "used_bytes",
        "manual_disabled",
        "disabled_pushed",
        "usage_limit_notified",
    ]
    available = [col for col in wanted if col in columns]
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""
            SELECT {", ".join(available)}
            FROM local_users
            WHERE owner_id=%s AND username=%s
            LIMIT 1
            """,
            (owner_id, local_username),
        )
        row = cur.fetchone()
        if row:
            for col in wanted:
                row.setdefault(col, 0)
        return row


def get_setting(owner_id, key):
    return get_owner_setting(owner_id, key)


def _owner_is_agent(owner_id: int) -> bool:
    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM agents WHERE telegram_user_id=%s LIMIT 1",
            (int(owner_id),),
        )
        return bool(cur.fetchone())


def _usage_interval_setting(owner_id: int, key: str) -> str | None:
    agent_key = AGENT_INTERVAL_SETTING_KEYS.get(key)
    if agent_key and _owner_is_agent(owner_id):
        value = get_setting(owner_id, agent_key)
        if value is not None:
            return value
    return get_setting(owner_id, key)


def _parse_int_setting(owner_id: int, key: str, default_value: int, min_value: int = 1) -> int:
    raw = (_usage_interval_setting(owner_id, key) or "").strip()
    if not raw:
        return default_value
    try:
        parsed = int(float(raw))
    except (TypeError, ValueError):
        return default_value
    return max(min_value, parsed)


def _parse_near_limit_threshold(owner_id: int) -> tuple[str, float]:
    raw = (get_setting(owner_id, "usage_sync_near_limit_threshold") or "").strip().lower()
    if not raw:
        return "percent", DEFAULT_NEAR_LIMIT_THRESHOLD_PERCENT

    if raw.endswith("%"):
        try:
            val = float(raw[:-1].strip())
            return "percent", max(0.0, min(100.0, val))
        except (TypeError, ValueError):
            return "percent", DEFAULT_NEAR_LIMIT_THRESHOLD_PERCENT

    if raw.endswith("mb"):
        try:
            val = float(raw[:-2].strip())
            return "mb", max(0.0, val)
        except (TypeError, ValueError):
            return "percent", DEFAULT_NEAR_LIMIT_THRESHOLD_PERCENT

    try:
        val = float(raw)
        return "percent", max(0.0, min(100.0, val))
    except (TypeError, ValueError):
        return "percent", DEFAULT_NEAR_LIMIT_THRESHOLD_PERCENT


def _is_near_limit(owner_id: int, local_username: str) -> bool:
    lu = get_local_user(owner_id, local_username)
    if not lu:
        return False
    limit = int(lu.get("plan_limit_bytes") or 0)
    used = int(lu.get("used_bytes") or 0)
    if limit <= 0:
        return False

    remaining = max(0, limit - used)
    mode, threshold = _parse_near_limit_threshold(owner_id)
    if mode == "mb":
        remaining_mb = remaining / float(1024 ** 2)
        return remaining_mb <= threshold

    remaining_pct = (remaining / float(limit)) * 100.0 if limit > 0 else 100.0
    return remaining_pct <= threshold


def _sync_interval_seconds(owner_id: int, near_limit: bool) -> int:
    near_minutes = _parse_int_setting(
        owner_id,
        "near_limit_sync_interval",
        DEFAULT_NEAR_LIMIT_SYNC_INTERVAL_MINUTES,
        min_value=1,
    )
    normal_minutes = _parse_int_setting(
        owner_id,
        "normal_sync_interval",
        DEFAULT_NORMAL_SYNC_INTERVAL_MINUTES,
        min_value=1,
    )
    selected_minutes = near_minutes if near_limit else normal_minutes
    return max(MIN_SYNC_INTERVAL_SECONDS, selected_minutes * 60)


def mark_usage_limit_notified(owner_id, local_username):
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            UPDATE local_users
            SET usage_limit_notified=1, usage_limit_notified_at=NOW()
            WHERE owner_id=%s AND username=%s
            """,
            (owner_id, local_username),
        )


def send_owner_limit_notification(owner_id: int, message: str):
    enabled = (get_setting(owner_id, "limit_event_notifications_enabled") or "1") != "0"
    if not enabled:
        return
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        log.warning("BOT_TOKEN missing; cannot send limit event notification")
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        requests.post(
            url,
            data={"chat_id": int(owner_id), "text": message},
            timeout=8,
        )
    except Exception as exc:  # pragma: no cover - network errors
        log.warning("failed sending limit event notification to %s: %s", owner_id, exc)


def _send_telegram_message(chat_id: int, message: str):
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        log.warning("BOT_TOKEN missing; cannot send telegram notification")
        return False
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        resp = requests.post(
            url,
            data={"chat_id": int(chat_id), "text": message},
            timeout=8,
        )
        return resp.ok
    except Exception as exc:  # pragma: no cover - network errors
        log.warning("failed sending telegram notification to %s: %s", chat_id, exc)
        return False


def _split_message_chunks(text: str, limit: int = 3500) -> list[str]:
    if len(text) <= limit:
        return [text]
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
            continue
        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))
    return chunks


def _get_sudo_admin_id() -> int | None:
    ids = (os.getenv("ADMIN_IDS") or "").strip()
    if not ids:
        return None
    for raw in ids.split(","):
        raw = raw.strip()
        if raw.isdigit():
            return int(raw)
    return None


def _collect_all_agents_usage_rows():
    with with_mysql_cursor() as cur:
        cur.execute(
            """
            SELECT a.telegram_user_id AS agent_tg_id,
                   COALESCE(a.name, CONCAT('agent-', a.telegram_user_id)) AS agent_name,
                   p.id AS panel_id,
                   p.name AS panel_name,
                   p.panel_type,
                   COALESCE(apt.total_used_bytes, 0) AS used_bytes
            FROM agents a
            JOIN (
                SELECT ags.agent_tg_id, sp.panel_id
                FROM agent_services ags
                JOIN service_panels sp ON sp.service_id = ags.service_id

                UNION

                SELECT apt2.agent_tg_id, apt2.panel_id
                FROM agent_panel_usage_totals apt2
            ) ap ON ap.agent_tg_id = a.telegram_user_id
            JOIN panels p ON p.id = ap.panel_id
            LEFT JOIN agent_panel_usage_totals apt
              ON apt.agent_tg_id = ap.agent_tg_id AND apt.panel_id = ap.panel_id
            ORDER BY a.telegram_user_id ASC, p.id ASC
            """
        )
        return cur.fetchall()


def send_nightly_panel_usage_report_if_due(now_utc: datetime, last_sent_local_day: str | None):
    tehran_tz = timezone(timedelta(hours=3, minutes=30))
    local_now = now_utc.astimezone(tehran_tz)
    local_day = local_now.strftime("%Y-%m-%d")

    if local_now.hour != 0 or local_now.minute >= REPORT_WINDOW_MINUTES:
        return last_sent_local_day
    if last_sent_local_day == local_day:
        return last_sent_local_day

    sudo_admin_id = _get_sudo_admin_id()
    if not sudo_admin_id:
        log.warning("ADMIN_IDS missing; skipping nightly panel usage report")
        return last_sent_local_day

    rows = _collect_all_agents_usage_rows()
    if not rows:
        message = "📊 Nightly panel usage report\nNo agent/panel usage data found."
        _send_telegram_message(sudo_admin_id, message)
        return local_day

    report_lines = [
        "📊 Nightly panel usage report (all agents)",
        "Timezone: UTC+03:30 midnight snapshot",
        "",
    ]
    current_agent = None
    agent_total = 0
    overall_total = 0

    for row in rows:
        agent_key = int(row["agent_tg_id"])
        if agent_key != current_agent:
            if current_agent is not None:
                report_lines.append(f"  ↳ Agent total: {agent_total} bytes")
                report_lines.append("")
            current_agent = agent_key
            agent_total = 0
            report_lines.append(f"👤 {row['agent_name']} ({agent_key})")

        used = int(row.get("used_bytes") or 0)
        agent_total += used
        overall_total += used
        report_lines.append(
            f"  • [{row['panel_id']}] {row['panel_name']} ({row['panel_type']}): {used} bytes"
        )

    if current_agent is not None:
        report_lines.append(f"  ↳ Agent total: {agent_total} bytes")
        report_lines.append("")
    report_lines.append(f"🌐 Overall total usage: {overall_total} bytes")

    report_text = "\n".join(report_lines)
    chunks = _split_message_chunks(report_text)
    for idx, chunk in enumerate(chunks, start=1):
        title = f"(part {idx}/{len(chunks)})\n" if len(chunks) > 1 else ""
        _send_telegram_message(sudo_admin_id, f"{title}{chunk}")

    log.info("nightly panel usage report sent to sudo admin=%s for day=%s", sudo_admin_id, local_day)
    return local_day

def list_links_of_local_user(owner_id, local_username):
    with with_mysql_cursor() as cur:
        cur.execute("""
            SELECT lup.panel_id, lup.remote_username, p.panel_url, p.access_token, p.panel_type
            FROM local_user_panel_links lup
            JOIN panels p ON p.id = lup.panel_id
            WHERE lup.owner_id=%s AND lup.local_username=%s
        """, (owner_id, local_username))
        return cur.fetchall()

def mark_user_disabled(owner_id, local_username):
    with with_mysql_cursor() as cur:
        cur.execute("""
            UPDATE local_users
            SET disabled_pushed=1, disabled_pushed_at=NOW()
            WHERE owner_id=%s AND username=%s
        """, (owner_id, local_username))

def disable_remote(panel_type, panel_url, token, remote_username):
    api = get_api(panel_type)
    remotes = remote_username.split(",") if panel_type == "sanaei" else [remote_username]
    all_ok, last_msg = True, None
    for rn in remotes:
        ok, msg = api.disable_remote_user(panel_url, token, rn)
        if not ok:
            all_ok = False
            last_msg = msg
    return (200 if all_ok else None), last_msg


def enable_remote(panel_type, panel_url, token, remote_username):
    api = get_api(panel_type)
    remotes = remote_username.split(",") if panel_type == "sanaei" else [remote_username]
    all_ok, last_msg = True, None
    for rn in remotes:
        ok, msg = api.enable_remote_user(panel_url, token, rn)
        if not ok:
            all_ok = False
            last_msg = msg
    return (200 if all_ok else None), last_msg

def mark_user_enabled(owner_id, local_username):
    with with_mysql_cursor() as cur:
        cur.execute("""
            UPDATE local_users
            SET disabled_pushed=0, disabled_pushed_at=NULL
            WHERE owner_id=%s AND username=%s
        """, (owner_id, local_username))

def try_disable_if_user_exceeded(owner_id, local_username):
    lu = get_local_user(owner_id, local_username)
    if not lu:
        return
    limit = int(lu["plan_limit_bytes"])
    used  = int(lu["used_bytes"])
    pushed = int(lu.get("disabled_pushed", 0) or 0)
    usage_notified = int(lu.get("usage_limit_notified", 0) or 0)
    manual_disabled = int(lu.get("manual_disabled", 0) or 0)

    if manual_disabled:
        return

    if limit > 0 and used >= limit:
        if not usage_notified:
            send_owner_limit_notification(
                owner_id,
                f"📊 User {local_username} exceeded usage limit ({used} / {limit} bytes).",
            )
            mark_usage_limit_notified(owner_id, local_username)
        if not pushed:
            links = list_links_of_local_user(owner_id, local_username)
            for l in links:
                code, msg = disable_remote(l["panel_type"], l["panel_url"], l["access_token"], l["remote_username"])
                if code and code != 200:
                    log.warning("disable on %s@%s -> %s %s", l["remote_username"], l["panel_url"], code, msg)
                else:
                    log.info("disabled %s on %s", l["remote_username"], l["panel_url"])
            mark_user_disabled(owner_id, local_username)

def try_enable_if_user_ok(owner_id, local_username):
    lu = get_local_user(owner_id, local_username)
    if not lu:
        return
    limit = int(lu["plan_limit_bytes"])
    used = int(lu["used_bytes"])
    pushed = int(lu.get("disabled_pushed", 0) or 0)
    manual_disabled = int(lu.get("manual_disabled", 0) or 0)

    if manual_disabled:
        return
    if pushed and (limit == 0 or used < limit):
        links = list_links_of_local_user(owner_id, local_username)
        for l in links:
            code, msg = enable_remote(l["panel_type"], l["panel_url"], l["access_token"], l["remote_username"])
            if code and code != 200:
                log.warning("enable on %s@%s -> %s %s", l["remote_username"], l["panel_url"], code, msg)
            else:
                log.info("enabled %s on %s", l["remote_username"], l["panel_url"])
        mark_user_enabled(owner_id, local_username)

# ---------------- NEW: Agent quota/expiry logic ----------------

def get_agent(owner_id: int):
    """owner_id همان Telegram User ID نماینده/ادمین است."""
    with with_mysql_cursor() as cur:
        cur.execute("""
            SELECT telegram_user_id, name, plan_limit_bytes, expire_at, active, disabled_pushed
            FROM agents
            WHERE telegram_user_id=%s
            LIMIT 1
        """, (owner_id,))
        return cur.fetchone()

def total_used_by_owner(owner_id: int) -> int:
    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT total_used_bytes AS tot FROM agents WHERE telegram_user_id=%s", (owner_id,)
        )
        row = cur.fetchone()
        return int(row.get("tot") or 0) if row else 0

def list_all_local_users(owner_id: int):
    columns = get_local_users_columns()
    include_manual = "manual_disabled" in columns
    select_cols = "username, manual_disabled" if include_manual else "username"
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT {select_cols} FROM local_users WHERE owner_id=%s",
            (owner_id,),
        )
        rows = cur.fetchall()
        if not include_manual:
            for row in rows:
                row["manual_disabled"] = 0
        return rows

def list_agent_assigned_panels(owner_id: int):
    """پنل‌هایی که به نماینده assign شده‌اند (agent_panels)."""
    with with_mysql_cursor() as cur:
        cur.execute("""
            SELECT p.id, p.panel_url, p.access_token, p.panel_type
            FROM agent_panels ap
            JOIN panels p ON p.id = ap.panel_id
            WHERE ap.agent_tg_id=%s
        """, (owner_id,))
        return cur.fetchall()

def mark_agent_disabled(owner_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("""
            UPDATE agents
            SET disabled_pushed=1, disabled_pushed_at=NOW()
            WHERE telegram_user_id=%s
        """, (owner_id,))

def mark_all_users_disabled(owner_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("""
            UPDATE local_users
            SET disabled_pushed=1, disabled_pushed_at=NOW()
            WHERE owner_id=%s
        """, (owner_id,))

def disable_user_on_assigned_panels(owner_id: int, username: str):
    """اگر مپ مستقیمی نبود، روی پنل‌های assign‌شده هم با همان username دیزیبل کن."""
    panels = list_agent_assigned_panels(owner_id)
    for p in panels:
        code, msg = disable_remote(p["panel_type"], p["panel_url"], p["access_token"], username)
        if code and code != 200:
            log.warning("disable (assigned) on %s@%s -> %s %s", username, p["panel_url"], code, msg)
        else:
            log.info("(assigned) disabled %s on %s", username, p["panel_url"])

def enable_user_on_assigned_panels(owner_id: int, username: str):
    """اگر مپ مستقیمی نبود، روی پنل‌های assign‌شده هم با همان username فعال کن."""
    panels = list_agent_assigned_panels(owner_id)
    for p in panels:
        code, msg = enable_remote(p["panel_type"], p["panel_url"], p["access_token"], username)
        if code and code != 200:
            log.warning("enable (assigned) on %s@%s -> %s %s", username, p["panel_url"], code, msg)
        else:
            log.info("(assigned) enabled %s on %s", username, p["panel_url"])

def mark_agent_enabled(owner_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("""
            UPDATE agents
            SET disabled_pushed=0, disabled_pushed_at=NULL
            WHERE telegram_user_id=%s
        """, (owner_id,))

def mark_all_users_enabled(owner_id: int):
    columns = get_local_users_columns()
    with with_mysql_cursor() as cur:
        if "manual_disabled" in columns:
            cur.execute(
                """
                UPDATE local_users
                SET disabled_pushed=0, disabled_pushed_at=NULL
                WHERE owner_id=%s AND manual_disabled=0
                """,
                (owner_id,),
            )
        else:
            cur.execute(
                """
                UPDATE local_users
                SET disabled_pushed=0, disabled_pushed_at=NULL
                WHERE owner_id=%s
                """,
                (owner_id,),
            )

def try_disable_agent_if_exceeded(owner_id: int):
    """
    اگر نماینده limit داشته و از سقف گذشته یا expire_at گذشته و هنوز push نشده:
    - تمام کاربران owner را در همه‌ی پنل‌های لینک‌شده و نیز پنل‌های assign‌شده disable کن
    - روی کاربران owner disabled_pushed=1 بزن
    - روی agent هم disabled_pushed=1 بزن
    """
    ag = get_agent(owner_id)
    if not ag:
        return  # این owner نماینده ثبت‌شده نیست (ممکن است ادمین باشد)

    if int(ag.get("active", 1)) == 0:
        return  # غیرفعال است؛ کار اضافه نکنیم

    already_pushed = int(ag.get("disabled_pushed", 0) or 0)
    limit_b = int(ag.get("plan_limit_bytes") or 0)
    expire_at = ag.get("expire_at")  # naive or aware? ذخیره MySQL معمولا naive UTC است

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)  # با naive UTC مقایسه می‌کنیم
    expired = False
    if expire_at:
        try:
            expired = (expire_at <= now_utc)
        except Exception:
            # اگر timezone mismatch شد، fallback
            expired = False

    over_limit = False
    if limit_b > 0:
        tot = total_used_by_owner(owner_id)
        over_limit = (tot >= limit_b)

    if (expired or over_limit) and not already_pushed:
        users = list_all_local_users(owner_id)
        for user in users:
            uname = user["username"]
            # 1) disable روی مپ‌های مستقیم کاربر
            links = list_links_of_local_user(owner_id, uname)
            for l in links:
                code, msg = disable_remote(l["panel_type"], l["panel_url"], l["access_token"], l["remote_username"])
                if code and code != 200:
                    log.warning("[AGENT] disable on %s@%s -> %s %s", l["remote_username"], l["panel_url"], code, msg)
                else:
                    log.info("[AGENT] disabled %s on %s", l["remote_username"], l["panel_url"])
            # 2) روی پنل‌های assign‌شده به نماینده، با همان username هم تلاش برای disable
            disable_user_on_assigned_panels(owner_id, uname)

        # users & agent flags
        mark_all_users_disabled(owner_id)
        mark_agent_disabled(owner_id)
        log.info("[AGENT] owner_id=%s disabled_pushed set for agent and all local users.", owner_id)

def try_enable_agent_if_ok(owner_id: int):
    ag = get_agent(owner_id)
    if not ag:
        return
    if int(ag.get("active", 1)) == 0:
        return
    pushed = int(ag.get("disabled_pushed", 0) or 0)
    if not pushed:
        return

    limit_b = int(ag.get("plan_limit_bytes") or 0)
    expire_at = ag.get("expire_at")
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    expired = False
    if expire_at:
        try:
            expired = (expire_at <= now_utc)
        except Exception:
            expired = False

    over_limit = False
    if limit_b > 0:
        tot = total_used_by_owner(owner_id)
        over_limit = (tot >= limit_b)

    if not expired and not over_limit:
        users = list_all_local_users(owner_id)
        for user in users:
            uname = user["username"]
            if int(user.get("manual_disabled", 0) or 0):
                continue
            links = list_links_of_local_user(owner_id, uname)
            for l in links:
                code, msg = enable_remote(l["panel_type"], l["panel_url"], l["access_token"], l["remote_username"])
                if code and code != 200:
                    log.warning("[AGENT] enable on %s@%s -> %s %s", l["remote_username"], l["panel_url"], code, msg)
                else:
                    log.info("[AGENT] enabled %s on %s", l["remote_username"], l["panel_url"])
            enable_user_on_assigned_panels(owner_id, uname)
        mark_all_users_enabled(owner_id)
        mark_agent_enabled(owner_id)
        log.info("[AGENT] owner_id=%s disabled_pushed cleared for agent and all local users.", owner_id)


def sync_agent_now(owner_id: int):
    """Public helper for bot to immediately re-check agent status."""
    init_mysql_pool()
    try:
        try_disable_agent_if_exceeded(owner_id)
        try_enable_agent_if_ok(owner_id)
    except Exception as e:
        log.warning("sync_agent_now failed for %s: %s", owner_id, e)

# ---------------- main loop ----------------

def loop():
    interval = int(os.getenv("USAGE_SYNC_INTERVAL", "60"))  # scheduler tick (seconds)
    next_sync_at = {}
    last_sent_local_day = None

    while True:
        try:
            links = fetch_all_links()
            seen_owners = set()
            links_by_user = {}
            for row in links:
                key = (int(row["owner_id"]), row["local_username"])
                links_by_user.setdefault(key, []).append(row)

            now_ts = time.time()
            retry_after_seconds = max(MIN_SYNC_INTERVAL_SECONDS, interval)

            for (owner_id, local_username), user_links in links_by_user.items():
                due_at = float(next_sync_at.get((owner_id, local_username), 0.0) or 0.0)
                if due_at > now_ts:
                    continue

                user_failed = False
                for row in user_links:
                    used, err = fetch_used_traffic(row["panel_type"], row["panel_url"], row["access_token"], row["remote_username"])
                    if used is None:
                        log.warning("fetch_used_traffic failed for %s@%s: %s",
                                    row["remote_username"], row["panel_url"], err)
                        user_failed = True
                        continue

                    last = int(row["last_used_traffic"] or 0)
                    if used < last:
                        # احتمالا پنل ریست شده
                        log.info("used dropped (%s -> %s) for link %s; reset baseline",
                                 last, used, row["link_id"])
                        update_last(row["link_id"], used)
                        continue

                    delta = used - last
                    if delta > 0:
                        try:
                            multiplier = float(row.get("usage_multiplier") or 1.0)
                        except (TypeError, ValueError):
                            multiplier = 1.0
                        if multiplier < 0:
                            multiplier = 1.0
                        weighted_delta = int(round(delta * multiplier))
                        add_local_usage(owner_id, local_username, weighted_delta)
                        add_agent_usage(owner_id, delta)
                        add_panel_lifetime_usage(owner_id, row["panel_id"], delta)
                        update_last(row["link_id"], used)
                        log.info("owner=%s local=%s +%s bytes (panel_id=%s)",
                                 owner_id, local_username, weighted_delta, row["panel_id"])

                # بعد از هر آپدیت، وضعیت کاربر را بررسی کن (disable/enable)
                try_disable_if_user_exceeded(owner_id, local_username)
                try_enable_if_user_ok(owner_id, local_username)
                seen_owners.add(owner_id)

                if user_failed:
                    next_sync_at[(owner_id, local_username)] = now_ts + retry_after_seconds
                else:
                    near_limit = _is_near_limit(owner_id, local_username)
                    next_sync_at[(owner_id, local_username)] = now_ts + _sync_interval_seconds(owner_id, near_limit)

            # پس از پردازش همه لینک‌ها، وضعیت نماینده‌ها را چک کن
            for owner_id in seen_owners:
                try_disable_agent_if_exceeded(owner_id)
                try_enable_agent_if_ok(owner_id)

            last_sent_local_day = send_nightly_panel_usage_report_if_due(
                datetime.now(timezone.utc),
                last_sent_local_day,
            )

        except Exception as e:
            log.exception("sync loop error: %s", e)
        time.sleep(interval)

def main():
    load_dotenv()
    init_mysql_pool()
    ensure_agent_panel_usage_totals_table()
    loop()

if __name__ == "__main__":
    main()
