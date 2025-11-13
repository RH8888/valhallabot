"""Backend-neutral data access helpers for subscription workflows.

The subscription aggregator Flask app and the usage synchronisation script
previously accessed the database layer directly via raw MySQL helpers.  That
approach breaks when the application is configured to use the MongoDB backend
because those helpers are initialised only for MySQL.  This module provides a
small abstraction that exposes the handful of queries and updates required by
those components while offering concrete implementations for both supported
backends.

The goal is not to perfectly map every column to the MongoDB schema but rather
to provide a consistent view of the data that the callers expect.  Where field
types differ between the backends (for example numeric identifiers stored as
strings) the helpers normalise the values so the rest of the application can
remain oblivious to the underlying representation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from pymongo.collection import Collection

from services import (
    get_mongo_database,
    init_mysql_pool,
    load_database_settings,
    with_mysql_cursor,
)
from services.database import errorcode, mysql_errors
from api.subscription_aggregator.ownership import expand_owner_ids

log = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.utcnow()


def _normalise_owner_ids(owner_id: int) -> List[Any]:
    """Return Mongo-friendly owner id variants for queries."""

    variants: List[Any] = []
    for oid in expand_owner_ids(owner_id):
        variants.append(oid)
        if isinstance(oid, int):
            variants.append(str(oid))
        elif isinstance(oid, str) and oid.isdigit():
            variants.append(int(oid))
    # Preserve ordering but drop duplicates
    seen = set()
    uniq: List[Any] = []
    for item in variants:
        if item in seen:
            continue
        seen.add(item)
        uniq.append(item)
    return uniq


def _panel_key(value: Any) -> Any:
    """Normalise a panel identifier for dict lookups."""

    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        try:
            return int(value)
        except Exception:  # pragma: no cover - defensive
            return value
    return value


class SubscriptionStorage:
    """Common interface implemented by both backend flavours."""

    def get_setting(self, owner_id: int, key: str) -> Optional[str]:
        raise NotImplementedError

    def get_owner_id(self, app_username: str, app_key: str) -> Optional[int]:
        raise NotImplementedError

    def get_local_user(self, owner_id: int, local_username: str) -> Optional[Mapping[str, Any]]:
        raise NotImplementedError

    def list_mapped_links(self, owner_id: int, local_username: str) -> List[Mapping[str, Any]]:
        raise NotImplementedError

    def list_all_panels(self, owner_id: int) -> List[Mapping[str, Any]]:
        raise NotImplementedError

    def mark_user_disabled(self, owner_id: int, local_username: str) -> None:
        raise NotImplementedError

    def mark_user_enabled(self, owner_id: int, local_username: str) -> None:
        raise NotImplementedError

    def load_disabled_filters(
        self, panel_ids: Iterable[Any]
    ) -> Tuple[Dict[Any, set[str]], Dict[Any, set[int]]]:
        raise NotImplementedError

    def get_agent(self, owner_id: int) -> Optional[Mapping[str, Any]]:
        raise NotImplementedError

    def get_agent_total_used(self, owner_id: int) -> int:
        raise NotImplementedError

    def list_all_agent_links(self, owner_id: int) -> List[Mapping[str, Any]]:
        raise NotImplementedError

    def mark_agent_disabled(self, owner_id: int) -> None:
        raise NotImplementedError

    def mark_agent_enabled(self, owner_id: int) -> None:
        raise NotImplementedError

    def mark_all_users_disabled(self, owner_id: int) -> None:
        raise NotImplementedError

    def mark_all_users_enabled(self, owner_id: int) -> None:
        raise NotImplementedError

    def fetch_all_links(self) -> List[Mapping[str, Any]]:
        raise NotImplementedError

    def add_usage(self, owner_id: int, local_username: str, delta: int) -> None:
        raise NotImplementedError

    def update_link_last_used(self, link_id: Any, new_used: int) -> None:
        raise NotImplementedError

    def list_links_of_local_user(self, owner_id: int, local_username: str) -> List[Mapping[str, Any]]:
        raise NotImplementedError

    def list_all_local_usernames(self, owner_id: int) -> List[str]:
        raise NotImplementedError

    def list_agent_assigned_panels(self, owner_id: int) -> List[Mapping[str, Any]]:
        raise NotImplementedError

    def ensure_links_structure(self) -> None:
        raise NotImplementedError


class MySQLSubscriptionStorage(SubscriptionStorage):
    """Implementation backed by the legacy MySQL schema."""

    def __init__(self) -> None:
        self._settings_table_missing_logged = False

    def get_setting(self, owner_id: int, key: str) -> Optional[str]:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            try:
                cur.execute(
                    f"SELECT value FROM settings WHERE owner_id IN ({placeholders}) AND `key`=%s LIMIT 1",
                    tuple(ids) + (key,),
                )
            except mysql_errors.ProgrammingError as exc:
                if getattr(exc, "errno", None) == errorcode.ER_NO_SUCH_TABLE:
                    if not self._settings_table_missing_logged:
                        log.warning(
                            "settings table missing; returning no setting values until it is created"
                        )
                        self._settings_table_missing_logged = True
                    return None
                raise
            row = cur.fetchone()
            return row["value"] if row else None

    def get_owner_id(self, app_username: str, app_key: str) -> Optional[int]:
        with with_mysql_cursor() as cur:
            cur.execute(
                "SELECT telegram_user_id FROM app_users WHERE username=%s AND app_key=%s LIMIT 1",
                (app_username, app_key),
            )
            row = cur.fetchone()
            return int(row["telegram_user_id"]) if row else None

    def get_local_user(self, owner_id: int, local_username: str) -> Optional[Mapping[str, Any]]:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""
                SELECT owner_id, username, plan_limit_bytes, used_bytes, expire_at, disabled_pushed, service_id
                FROM local_users
                WHERE owner_id IN ({placeholders}) AND username=%s
                LIMIT 1
                """,
                tuple(ids) + (local_username,),
            )
            return cur.fetchone()

    def list_mapped_links(self, owner_id: int, local_username: str) -> List[Mapping[str, Any]]:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""
                SELECT lup.panel_id, lup.remote_username,
                       p.panel_url, p.access_token, p.panel_type
                FROM local_user_panel_links lup
                JOIN panels p ON p.id = lup.panel_id
                WHERE lup.owner_id IN ({placeholders}) AND lup.local_username=%s
                """,
                tuple(ids) + (local_username,),
            )
            return cur.fetchall()

    def list_all_panels(self, owner_id: int) -> List[Mapping[str, Any]]:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"SELECT id, panel_url, access_token, panel_type FROM panels WHERE telegram_user_id IN ({placeholders})",
                tuple(ids),
            )
            return cur.fetchall()

    def mark_user_disabled(self, owner_id: int, local_username: str) -> None:
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

    def mark_user_enabled(self, owner_id: int, local_username: str) -> None:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""
                UPDATE local_users
                SET disabled_pushed=0, disabled_pushed_at=NULL
                WHERE owner_id IN ({placeholders}) AND username=%s
                """,
                tuple(ids) + (local_username,),
            )

    def load_disabled_filters(
        self, panel_ids: Iterable[Any]
    ) -> Tuple[Dict[Any, set[str]], Dict[Any, set[int]]]:
        panel_list = [int(pid) for pid in panel_ids if isinstance(pid, (int, float)) or (isinstance(pid, str) and pid.isdigit())]
        if not panel_list:
            return {}, {}
        placeholders = ",".join(["%s"] * len(panel_list))
        names: Dict[Any, set[str]] = {}
        nums: Dict[Any, set[int]] = {}
        with with_mysql_cursor() as cur:
            cur.execute(
                f"SELECT panel_id, config_name FROM panel_disabled_configs WHERE panel_id IN ({placeholders})",
                tuple(panel_list),
            )
            for row in cur.fetchall():
                pid = int(row["panel_id"])
                names.setdefault(pid, set()).add(str(row.get("config_name") or "").strip())
            cur.execute(
                f"SELECT panel_id, config_index FROM panel_disabled_numbers WHERE panel_id IN ({placeholders})",
                tuple(panel_list),
            )
            for row in cur.fetchall():
                pid = int(row["panel_id"])
                idx = row.get("config_index")
                if isinstance(idx, (int,)) and int(idx) > 0:
                    nums.setdefault(pid, set()).add(int(idx))
        return names, nums

    def get_agent(self, owner_id: int) -> Optional[Mapping[str, Any]]:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""
                SELECT telegram_user_id, name, plan_limit_bytes, expire_at, active, disabled_pushed
                FROM agents
                WHERE telegram_user_id IN ({placeholders}) AND active=1
                LIMIT 1
                """,
                tuple(ids),
            )
            return cur.fetchone()

    def get_agent_total_used(self, owner_id: int) -> int:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"SELECT total_used_bytes AS su FROM agents WHERE telegram_user_id IN ({placeholders}) AND active=1 LIMIT 1",
                tuple(ids),
            )
            row = cur.fetchone()
            return int(row.get("su") or 0) if row else 0

    def list_all_agent_links(self, owner_id: int) -> List[Mapping[str, Any]]:
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

    def mark_agent_disabled(self, owner_id: int) -> None:
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

    def mark_agent_enabled(self, owner_id: int) -> None:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""
                UPDATE agents
                SET disabled_pushed=0, disabled_pushed_at=NULL
                WHERE telegram_user_id IN ({placeholders})
                """,
                tuple(ids),
            )

    def mark_all_users_disabled(self, owner_id: int) -> None:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""
                UPDATE local_users
                SET disabled_pushed=1, disabled_pushed_at=NOW()
                WHERE owner_id IN ({placeholders})
                """,
                tuple(ids),
            )

    def mark_all_users_enabled(self, owner_id: int) -> None:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""
                UPDATE local_users
                SET disabled_pushed=0, disabled_pushed_at=NULL
                WHERE owner_id IN ({placeholders})
                """,
                tuple(ids),
            )

    def fetch_all_links(self) -> List[Mapping[str, Any]]:
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
                           p.panel_type
                    FROM local_user_panel_links lup
                    JOIN panels p ON p.id = lup.panel_id
                    ORDER BY lup.id ASC
                    """,
                )
                return cur.fetchall()
        except mysql_errors.ProgrammingError as exc:
            if getattr(exc, "errno", None) == errorcode.ER_NO_SUCH_TABLE:
                log.warning("local_user_panel_links table missing; creating")
                self.ensure_links_structure()
                return []
            raise

    def add_usage(self, owner_id: int, local_username: str, delta: int) -> None:
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

    def update_link_last_used(self, link_id: Any, new_used: int) -> None:
        with with_mysql_cursor() as cur:
            cur.execute(
                "UPDATE local_user_panel_links SET last_used_traffic=%s WHERE id=%s",
                (int(new_used), int(link_id)),
            )

    def list_links_of_local_user(self, owner_id: int, local_username: str) -> List[Mapping[str, Any]]:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"""
                SELECT lup.panel_id, lup.remote_username, p.panel_url, p.access_token, p.panel_type
                FROM local_user_panel_links lup
                JOIN panels p ON p.id = lup.panel_id
                WHERE lup.owner_id IN ({placeholders}) AND lup.local_username=%s
                """,
                tuple(ids) + (local_username,),
            )
            return cur.fetchall()

    def list_all_local_usernames(self, owner_id: int) -> List[str]:
        ids = expand_owner_ids(owner_id)
        placeholders = ",".join(["%s"] * len(ids))
        with with_mysql_cursor() as cur:
            cur.execute(
                f"SELECT username FROM local_users WHERE owner_id IN ({placeholders})",
                tuple(ids),
            )
            return [row["username"] for row in cur.fetchall()]

    def list_agent_assigned_panels(self, owner_id: int) -> List[Mapping[str, Any]]:
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.panel_url, p.access_token, p.panel_type
                FROM agent_panels ap
                JOIN panels p ON p.id = ap.panel_id
                WHERE ap.agent_tg_id=%s
                """,
                (owner_id,),
            )
            return cur.fetchall()

    def ensure_links_structure(self) -> None:
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
                """,
            )


@dataclass
class MongoCollections:
    settings: Collection
    app_users: Collection
    local_users: Collection
    links: Collection
    panels: Collection
    agents: Collection
    panel_disabled_configs: Collection
    panel_disabled_numbers: Collection
    agent_panels: Collection


class MongoSubscriptionStorage(SubscriptionStorage):
    """Implementation backed by the MongoDB collections."""

    def __init__(self) -> None:
        db = get_mongo_database()
        self._collections = MongoCollections(
            settings=db["settings"],
            app_users=db["app_users"],
            local_users=db["local_users"],
            links=db["local_user_panel_links"],
            panels=db["panels"],
            agents=db["agents"],
            panel_disabled_configs=db.get_collection("panel_disabled_configs"),
            panel_disabled_numbers=db.get_collection("panel_disabled_numbers"),
            agent_panels=db["agent_panels"],
        )

    # Helper utilities -------------------------------------------------
    def _panel_map(self, owner_id: int) -> Dict[Any, Dict[str, Any]]:
        docs = list(
            self._collections.panels.find(
                {"telegram_user_id": {"$in": _normalise_owner_ids(owner_id)}}
            )
        )
        result: Dict[Any, Dict[str, Any]] = {}
        for doc in docs:
            pid = doc.get("id")
            if pid is None:
                pid = doc.get("_id")
            if pid is None:
                continue
            panel_id = pid
            if isinstance(panel_id, str) and panel_id.isdigit():
                panel_id = int(panel_id)
            panel_info = {
                "id": panel_id,
                "panel_url": doc.get("panel_url"),
                "access_token": doc.get("access_token"),
                "panel_type": doc.get("panel_type"),
            }
            result[_panel_key(panel_id)] = panel_info
            # Also store string/int variants for lookups
            result[_panel_key(str(panel_id))] = panel_info
        return result

    def _resolve_panel(self, owner_id: int, panel_id: Any) -> Optional[Dict[str, Any]]:
        panel_map = getattr(self, "_panel_cache", None)
        if panel_map is None or panel_map.get("__owner__") != owner_id:
            panel_map = self._panel_map(owner_id)
            panel_map["__owner__"] = owner_id
            self._panel_cache = panel_map
        key = _panel_key(panel_id)
        if key in panel_map:
            return panel_map[key]
        # Attempt string/int conversions lazily
        if isinstance(key, int):
            return panel_map.get(str(key))
        if isinstance(key, str) and key.isdigit():
            return panel_map.get(int(key))
        return None

    def _links_with_panels(self, owner_id: int, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        docs = list(self._collections.links.find(query))
        out: List[Dict[str, Any]] = []
        for doc in docs:
            panel = self._resolve_panel(owner_id, doc.get("panel_id"))
            if not panel:
                continue
            entry = {
                "panel_id": panel["id"],
                "remote_username": doc.get("remote_username"),
                "panel_url": panel.get("panel_url"),
                "access_token": panel.get("access_token"),
                "panel_type": panel.get("panel_type"),
            }
            if "local_username" in doc:
                entry["local_username"] = doc.get("local_username")
            if "id" in doc:
                entry["link_id"] = doc.get("id")
            if "_id" in doc and "link_id" not in entry:
                entry["link_id"] = doc.get("_id")
            if "last_used_traffic" in doc:
                entry["last_used_traffic"] = doc.get("last_used_traffic")
            out.append(entry)
        return out

    # Interface implementation ----------------------------------------
    def get_setting(self, owner_id: int, key: str) -> Optional[str]:
        doc = self._collections.settings.find_one(
            {"owner_id": {"$in": _normalise_owner_ids(owner_id)}, "key": key}
        )
        if not doc:
            return None
        return doc.get("value")

    def get_owner_id(self, app_username: str, app_key: str) -> Optional[int]:
        doc = self._collections.app_users.find_one(
            {"username": app_username, "app_key": app_key},
            {"telegram_user_id": 1},
        )
        if not doc:
            return None
        tg = doc.get("telegram_user_id")
        if isinstance(tg, str) and tg.isdigit():
            return int(tg)
        try:
            return int(tg)
        except Exception:
            return tg

    def get_local_user(self, owner_id: int, local_username: str) -> Optional[Mapping[str, Any]]:
        doc = self._collections.local_users.find_one(
            {"owner_id": {"$in": _normalise_owner_ids(owner_id)}, "username": local_username}
        )
        return doc

    def list_mapped_links(self, owner_id: int, local_username: str) -> List[Mapping[str, Any]]:
        query = {
            "owner_id": {"$in": _normalise_owner_ids(owner_id)},
            "local_username": local_username,
        }
        return self._links_with_panels(owner_id, query)

    def list_all_panels(self, owner_id: int) -> List[Mapping[str, Any]]:
        docs = list(
            self._collections.panels.find(
                {"telegram_user_id": {"$in": _normalise_owner_ids(owner_id)}}
            )
        )
        panels: List[Dict[str, Any]] = []
        for doc in docs:
            pid = doc.get("id", doc.get("_id"))
            if isinstance(pid, str) and pid.isdigit():
                pid = int(pid)
            panels.append(
                {
                    "id": pid,
                    "panel_url": doc.get("panel_url"),
                    "access_token": doc.get("access_token"),
                    "panel_type": doc.get("panel_type"),
                }
            )
        return panels

    def mark_user_disabled(self, owner_id: int, local_username: str) -> None:
        self._collections.local_users.update_many(
            {"owner_id": {"$in": _normalise_owner_ids(owner_id)}, "username": local_username},
            {
                "$set": {"disabled_pushed": 1, "disabled_pushed_at": _now_utc()},
            },
        )

    def mark_user_enabled(self, owner_id: int, local_username: str) -> None:
        self._collections.local_users.update_many(
            {"owner_id": {"$in": _normalise_owner_ids(owner_id)}, "username": local_username},
            {"$set": {"disabled_pushed": 0}, "$unset": {"disabled_pushed_at": ""}},
        )

    def load_disabled_filters(
        self, panel_ids: Iterable[Any]
    ) -> Tuple[Dict[Any, set[str]], Dict[Any, set[int]]]:
        # Mongo deployments may not use these collections; return empty maps if absent.
        configs = self._collections.panel_disabled_configs
        numbers = self._collections.panel_disabled_numbers
        if configs is None or numbers is None:
            return {}, {}

        keys = [_panel_key(pid) for pid in panel_ids]
        names: Dict[Any, set[str]] = {}
        nums: Dict[Any, set[int]] = {}

        cfg_docs = configs.find({"panel_id": {"$in": keys}})
        for doc in cfg_docs:
            pid = _panel_key(doc.get("panel_id"))
            cn = doc.get("config_name")
            if cn:
                names.setdefault(pid, set()).add(str(cn).strip())

        num_docs = numbers.find({"panel_id": {"$in": keys}})
        for doc in num_docs:
            pid = _panel_key(doc.get("panel_id"))
            idx = doc.get("config_index")
            try:
                idx_int = int(idx)
            except (TypeError, ValueError):
                continue
            if idx_int > 0:
                nums.setdefault(pid, set()).add(idx_int)

        return names, nums

    def get_agent(self, owner_id: int) -> Optional[Mapping[str, Any]]:
        doc = self._collections.agents.find_one(
            {
                "telegram_user_id": {"$in": _normalise_owner_ids(owner_id)},
                "$or": [{"active": {"$exists": False}}, {"active": True}, {"active": 1}],
            }
        )
        return doc

    def get_agent_total_used(self, owner_id: int) -> int:
        doc = self._collections.agents.find_one(
            {"telegram_user_id": {"$in": _normalise_owner_ids(owner_id)}},
            {"total_used_bytes": 1},
        )
        if not doc:
            return 0
        value = doc.get("total_used_bytes") or 0
        try:
            return int(value)
        except Exception:
            return 0

    def list_all_agent_links(self, owner_id: int) -> List[Mapping[str, Any]]:
        query = {"owner_id": {"$in": _normalise_owner_ids(owner_id)}}
        return self._links_with_panels(owner_id, query)

    def mark_agent_disabled(self, owner_id: int) -> None:
        self._collections.agents.update_many(
            {"telegram_user_id": {"$in": _normalise_owner_ids(owner_id)}},
            {"$set": {"disabled_pushed": 1, "disabled_pushed_at": _now_utc()}},
        )

    def mark_agent_enabled(self, owner_id: int) -> None:
        self._collections.agents.update_many(
            {"telegram_user_id": {"$in": _normalise_owner_ids(owner_id)}},
            {"$set": {"disabled_pushed": 0}, "$unset": {"disabled_pushed_at": ""}},
        )

    def mark_all_users_disabled(self, owner_id: int) -> None:
        self._collections.local_users.update_many(
            {"owner_id": {"$in": _normalise_owner_ids(owner_id)}},
            {"$set": {"disabled_pushed": 1, "disabled_pushed_at": _now_utc()}},
        )

    def mark_all_users_enabled(self, owner_id: int) -> None:
        self._collections.local_users.update_many(
            {"owner_id": {"$in": _normalise_owner_ids(owner_id)}},
            {"$set": {"disabled_pushed": 0}, "$unset": {"disabled_pushed_at": ""}},
        )

    def fetch_all_links(self) -> List[Mapping[str, Any]]:
        docs = list(self._collections.links.find())
        out: List[Dict[str, Any]] = []
        for doc in docs:
            owner_id = doc.get("owner_id")
            if owner_id is None:
                continue
            entry = {
                "link_id": doc.get("id", doc.get("_id")),
                "owner_id": owner_id,
                "local_username": doc.get("local_username"),
                "panel_id": doc.get("panel_id"),
                "remote_username": doc.get("remote_username"),
                "last_used_traffic": doc.get("last_used_traffic", 0),
            }
            panel = self._resolve_panel(owner_id, doc.get("panel_id"))
            if panel:
                entry.update(
                    {
                        "panel_url": panel.get("panel_url"),
                        "access_token": panel.get("access_token"),
                        "panel_type": panel.get("panel_type"),
                    }
                )
            out.append(entry)
        return out

    def add_usage(self, owner_id: int, local_username: str, delta: int) -> None:
        if delta <= 0:
            return
        self._collections.local_users.update_many(
            {"owner_id": {"$in": _normalise_owner_ids(owner_id)}, "username": local_username},
            {"$inc": {"used_bytes": int(delta)}},
        )
        self._collections.agents.update_many(
            {"telegram_user_id": {"$in": _normalise_owner_ids(owner_id)}},
            {"$inc": {"total_used_bytes": int(delta)}},
        )

    def update_link_last_used(self, link_id: Any, new_used: int) -> None:
        self._collections.links.update_many(
            {"$or": [{"id": link_id}, {"_id": link_id}]},
            {"$set": {"last_used_traffic": int(new_used)}},
        )

    def list_links_of_local_user(self, owner_id: int, local_username: str) -> List[Mapping[str, Any]]:
        query = {
            "owner_id": {"$in": _normalise_owner_ids(owner_id)},
            "local_username": local_username,
        }
        return self._links_with_panels(owner_id, query)

    def list_all_local_usernames(self, owner_id: int) -> List[str]:
        docs = self._collections.local_users.find(
            {"owner_id": {"$in": _normalise_owner_ids(owner_id)}},
            {"username": 1},
        )
        return [doc.get("username") for doc in docs if doc.get("username")]

    def list_agent_assigned_panels(self, owner_id: int) -> List[Mapping[str, Any]]:
        docs = list(self._collections.agent_panels.find({"agent_tg_id": owner_id}))
        results: List[Dict[str, Any]] = []
        for doc in docs:
            panel = self._resolve_panel(owner_id, doc.get("panel_id"))
            if not panel:
                continue
            results.append(panel)
        return results

    def ensure_links_structure(self) -> None:  # pragma: no cover - Mongo doesn't need DDL
        return


_STORAGE: SubscriptionStorage | None = None


def get_subscription_storage() -> SubscriptionStorage:
    """Return a singleton storage implementation for the configured backend."""

    global _STORAGE
    if _STORAGE is not None:
        return _STORAGE

    settings = load_database_settings(force_refresh=True)
    if settings.backend == "mysql":
        init_mysql_pool()
        _STORAGE = MySQLSubscriptionStorage()
    elif settings.backend == "mongodb":
        _STORAGE = MongoSubscriptionStorage()
    else:  # pragma: no cover - defensive guard
        raise RuntimeError(f"Unsupported database backend: {settings.backend}")
    return _STORAGE


__all__ = [
    "SubscriptionStorage",
    "MySQLSubscriptionStorage",
    "MongoSubscriptionStorage",
    "get_subscription_storage",
]
