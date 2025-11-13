#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import logging
from urllib.parse import urljoin
from datetime import datetime, timezone

from dotenv import load_dotenv
from services.subscription_storage import get_subscription_storage

from apis import marzneshin, marzban, rebecca, sanaei, pasarguard

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
}


_storage = get_subscription_storage()


def get_api(panel_type: str):
    """Return API module for the given panel type."""
    return API_MODULES.get(panel_type or "marzneshin", marzneshin)

# ---------------- existing per-link / per-user logic ----------------
def fetch_all_links():
    return _storage.fetch_all_links()

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
    _storage.add_usage(owner_id, local_username, delta)

def update_last(link_id, new_used):
    _storage.update_link_last_used(link_id, new_used)

def get_local_user(owner_id, local_username):
    return _storage.get_local_user(owner_id, local_username)

def list_links_of_local_user(owner_id, local_username):
    return _storage.list_links_of_local_user(owner_id, local_username)

def mark_user_disabled(owner_id, local_username):
    _storage.mark_user_disabled(owner_id, local_username)

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
    _storage.mark_user_enabled(owner_id, local_username)

def try_disable_if_user_exceeded(owner_id, local_username):
    lu = get_local_user(owner_id, local_username)
    if not lu:
        return
    limit = int(lu["plan_limit_bytes"])
    used  = int(lu["used_bytes"])
    pushed = int(lu.get("disabled_pushed", 0) or 0)

    if limit > 0 and used >= limit and not pushed:
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
    return _storage.get_agent(owner_id)

def total_used_by_owner(owner_id: int) -> int:
    return _storage.get_agent_total_used(owner_id)

def list_all_local_usernames(owner_id: int):
    return _storage.list_all_local_usernames(owner_id)

def list_agent_assigned_panels(owner_id: int):
    """پنل‌هایی که به نماینده assign شده‌اند (agent_panels)."""
    return _storage.list_agent_assigned_panels(owner_id)

def mark_agent_disabled(owner_id: int):
    _storage.mark_agent_disabled(owner_id)

def mark_all_users_disabled(owner_id: int):
    _storage.mark_all_users_disabled(owner_id)

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
    _storage.mark_agent_enabled(owner_id)

def mark_all_users_enabled(owner_id: int):
    _storage.mark_all_users_enabled(owner_id)

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
        usernames = list_all_local_usernames(owner_id)
        for uname in usernames:
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
        usernames = list_all_local_usernames(owner_id)
        for uname in usernames:
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
                    add_usage(row["owner_id"], row["local_username"], delta)
                    update_last(row["link_id"], used)
                    log.info("owner=%s local=%s +%s bytes (panel_id=%s)",
                             row["owner_id"], row["local_username"], delta, row["panel_id"])

                # بعد از هر آپدیت، وضعیت کاربر را بررسی کن (disable/enable)
                try_disable_if_user_exceeded(row["owner_id"], row["local_username"])
                try_enable_if_user_ok(row["owner_id"], row["local_username"])

                # برای بهینگی، در پایان هر owner یک‌بار چک agent quota انجام می‌دهیم
                owner_key = row.get("owner_id")
                try:
                    owner_key = int(owner_key)
                except (TypeError, ValueError):
                    pass
                seen_owners.add(owner_key)

            # پس از پردازش همه لینک‌ها، وضعیت نماینده‌ها را چک کن
            for owner_id in seen_owners:
                try_disable_agent_if_exceeded(owner_id)
                try_enable_agent_if_ok(owner_id)

        except Exception as e:
            log.exception("sync loop error: %s", e)
        time.sleep(interval)

def main():
    load_dotenv()
    storage = get_subscription_storage()
    storage.ensure_links_structure()
    loop()

if __name__ == "__main__":
    main()
