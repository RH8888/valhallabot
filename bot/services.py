"""Data access and business logic helpers for the bot."""

from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from api.subscription_aggregator import canonical_owner_id, expand_owner_ids
from services import get_agent_record, rotate_agent_token_value, with_mysql_cursor

from .utils import canonicalize_name, clone_proxy_settings, get_api, is_admin, log

__all__ = [
    "list_my_panels_admin",
    "list_panels_for_agent",
    "create_service",
    "list_services",
    "get_service",
    "list_service_panel_ids",
    "set_service_panels",
    "list_agents_by_service",
    "list_local_users_by_service",
    "set_agent_service",
    "resolve_local_user_owner",
    "set_local_user_service",
    "propagate_service_panels",
    "list_presets",
    "create_preset",
    "delete_preset",
    "get_preset",
    "update_preset",
    "upsert_app_user",
    "get_app_key",
    "upsert_local_user",
    "save_link",
    "remove_link",
    "list_linked_panel_ids",
    "map_linked_remote_usernames",
    "get_local_user",
    "search_local_users",
    "list_all_local_users",
    "count_local_users",
    "list_user_links",
    "delete_local_user",
    "delete_user",
    "set_panel_sub_url",
    "get_panel",
    "get_panel_disabled_names",
    "set_panel_disabled_names",
    "get_panel_disabled_nums",
    "set_panel_disabled_nums",
    "list_panel_links",
    "delete_panel_and_cleanup",
    "upsert_agent",
    "get_agent",
    "list_agents",
    "list_agent_panel_ids",
    "set_agent_panels",
    "sync_user_panels",
    "sync_user_panels_async",
]

# ---------- data access ----------
def list_my_panels_admin(admin_tg_id: int):
    ids = expand_owner_ids(admin_tg_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT * FROM panels WHERE telegram_user_id IN ({placeholders}) ORDER BY created_at DESC",
            tuple(ids),
        )
        return cur.fetchall()

def list_panels_for_agent(agent_tg_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("""
            SELECT p.* FROM agent_panels ap
            JOIN panels p ON p.id = ap.panel_id
            WHERE ap.agent_tg_id=%s
            ORDER BY p.created_at DESC
        """, (agent_tg_id,))
        return cur.fetchall()

# ----- service helpers -----
def create_service(name: str) -> int:
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute("INSERT INTO services(name) VALUES(%s)", (name,))
        return cur.lastrowid

def list_services():
    with with_mysql_cursor() as cur:
        cur.execute("SELECT * FROM services ORDER BY created_at DESC")
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
        cur.execute("SELECT telegram_user_id FROM agents WHERE service_id=%s", (service_id,))
        return [int(r["telegram_user_id"]) for r in cur.fetchall()]

def list_local_users_by_service(service_id: int):
    with with_mysql_cursor() as cur:
        cur.execute("SELECT owner_id, username FROM local_users WHERE service_id=%s", (service_id,))
        return cur.fetchall()

def set_agent_service(agent_tg_id: int, service_id: int | None):
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute("UPDATE agents SET service_id=%s WHERE telegram_user_id=%s", (service_id, agent_tg_id))
    # sync agent panels to service
    pids = list_service_panel_ids(service_id) if service_id else set()
    set_agent_panels(agent_tg_id, pids)

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
                   disabled_pushed=0""",
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
            f"SELECT username,plan_limit_bytes,used_bytes,expire_at,disabled_pushed FROM local_users "
            f"WHERE owner_id IN ({placeholders}) AND username=%s LIMIT 1",
            tuple(ids) + (username,)
        )
        return cur.fetchone()

def search_local_users(owner_id: int, q: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT username FROM local_users WHERE owner_id IN ({placeholders}) AND username LIKE %s ORDER BY username ASC LIMIT 50",
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
    params = [int(new_limit_bytes)] + ids + [username]
    with with_mysql_cursor() as cur:
        cur.execute(
            f"UPDATE local_users SET plan_limit_bytes=%s WHERE owner_id IN ({placeholders}) AND username=%s",
            params
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
                row["panel_url"], row["access_token"], rn, data_limit=new_limit_bytes
            )
            if not ok:
                log.warning("remote limit update failed on %s: %s", row["panel_url"], err)

def reset_used(owner_id: int, username: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = ids + [username]
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT used_bytes, owner_id FROM local_users WHERE owner_id IN ({placeholders}) AND username=%s LIMIT 1",
            params,
        )
        row = cur.fetchone()
        prev_used = int(row["used_bytes"] or 0) if row else 0
        owner_real = int(row["owner_id"]) if row else None
        cur.execute(
            f"UPDATE local_users SET used_bytes=0 WHERE owner_id IN ({placeholders}) AND username=%s",
            params,
        )
        if prev_used > 0 and owner_real is not None:
            cur.execute(
                "UPDATE agents SET total_used_bytes = GREATEST(total_used_bytes - %s, 0) WHERE telegram_user_id=%s",
                (prev_used, owner_real),
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
                                    expire_at + INTERVAL %s DAY)
               WHERE owner_id IN ({placeholders}) AND username=%s""",
            params
        )
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT expire_at FROM local_users WHERE owner_id IN ({placeholders}) AND username=%s",
            tuple(ids) + (username,),
        )
        row = cur.fetchone()
    expire_ts = 0
    if row and row.get("expire_at"):
        expire_dt = row["expire_at"]
        if isinstance(expire_dt, datetime):
            expire_ts = int(expire_dt.replace(tzinfo=timezone.utc).timestamp())
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


def list_user_links(owner_id: int, local_username: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        cur.execute(
            f"""SELECT lup.panel_id, lup.remote_username,
                      p.panel_url, p.access_token, p.panel_type
                 FROM local_user_panel_links lup
                 JOIN panels p ON p.id = lup.panel_id
                 WHERE lup.owner_id IN ({placeholders}) AND lup.local_username=%s""",
            tuple(ids) + (local_username,),
        )
        return cur.fetchall()


def delete_local_user(owner_id: int, username: str):
    ids = expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    params = tuple(ids) + (username,)
    with with_mysql_cursor() as cur:
        cur.execute(
            f"SELECT used_bytes, owner_id FROM local_users WHERE owner_id IN ({placeholders}) AND username=%s LIMIT 1",
            params,
        )
        row = cur.fetchone()
        used = int(row["used_bytes"] or 0) if row else 0
        owner_real = int(row["owner_id"]) if row else None
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
        if used > 0 and owner_real is not None:
            cur.execute(
                "UPDATE agents SET total_used_bytes = GREATEST(total_used_bytes - %s, 0) WHERE telegram_user_id=%s",
                (used, owner_real),
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
            remote = links_map.get(int(pid), username)
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
        remote = links_map.get(int(pid), username)
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

