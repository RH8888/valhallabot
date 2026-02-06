#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
import requests
from urllib.parse import urljoin
from datetime import datetime, timezone

from dotenv import load_dotenv
from services import init_mysql_pool, with_mysql_cursor
from services.database import mysql_errors
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
                       p.usage_multiplier
                FROM local_user_panel_links lup
                JOIN panels p ON p.id = lup.panel_id
                ORDER BY lup.id ASC
                """
            )
            return cur.fetchall()
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

def add_usage(owner_id, local_username, delta):
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
        cur.execute(
            """
            UPDATE agents
            SET total_used_bytes = LEAST(total_used_bytes + %s, 18446744073709551615)
            WHERE telegram_user_id = %s
        """,
            (int(delta), int(owner_id)),
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
    interval = int(os.getenv("USAGE_SYNC_INTERVAL", "60"))  # seconds
    while True:
        try:
            links = fetch_all_links()
            seen_owners = set()
            for row in links:
                used, err = fetch_used_traffic(row["panel_type"], row["panel_url"], row["access_token"], row["remote_username"])
                if used is None:
                    log.warning("fetch_used_traffic failed for %s@%s: %s",
                                row["remote_username"], row["panel_url"], err)
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
                    add_usage(row["owner_id"], row["local_username"], weighted_delta)
                    update_last(row["link_id"], used)
                    log.info("owner=%s local=%s +%s bytes (panel_id=%s)",
                             row["owner_id"], row["local_username"], weighted_delta, row["panel_id"])

                # بعد از هر آپدیت، وضعیت کاربر را بررسی کن (disable/enable)
                try_disable_if_user_exceeded(row["owner_id"], row["local_username"])
                try_enable_if_user_ok(row["owner_id"], row["local_username"])

                # برای بهینگی، در پایان هر owner یک‌بار چک agent quota انجام می‌دهیم
                seen_owners.add(int(row["owner_id"]))

            # پس از پردازش همه لینک‌ها، وضعیت نماینده‌ها را چک کن
            for owner_id in seen_owners:
                try_disable_agent_if_exceeded(owner_id)
                try_enable_agent_if_ok(owner_id)

        except Exception as e:
            log.exception("sync loop error: %s", e)
        time.sleep(interval)

def main():
    load_dotenv()
    init_mysql_pool()
    loop()

if __name__ == "__main__":
    main()
