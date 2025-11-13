"""Database repository abstractions with MySQL and MongoDB implementations."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Protocol, Sequence, Tuple

from pymongo.collection import Collection

from .database import (
    get_mongo_database,
    load_database_settings,
    with_mysql_cursor,
)

log = logging.getLogger(__name__)


class Repository(Protocol):
    """Interface describing the data access operations required by services."""

    # Agent operations
    def get_agent_by_telegram_id(self, tg_id: int) -> Optional[dict]:
        ...

    def set_agent_quota(self, tg_id: int, limit_bytes: int) -> None:
        ...

    def set_agent_user_limit(self, tg_id: int, max_users: int) -> None:
        ...

    def set_agent_max_user_bytes(self, tg_id: int, max_bytes: int) -> None:
        ...

    def renew_agent_days(self, tg_id: int, add_days: int) -> None:
        ...

    def set_agent_active(self, tg_id: int, active: bool) -> None:
        ...

    def get_agent_token_fields(self, agent_id: int) -> Optional[dict]:
        ...

    def update_agent_token_fields(
        self, agent_id: int, token_hash: str, encrypted_token: str
    ) -> bool:
        ...

    def bulk_update_agent_tokens(
        self, updates: Sequence[Tuple[str, str, int]]
    ) -> None:
        ...

    def get_agents_with_legacy_tokens(self) -> Sequence[dict]:
        ...

    # Admin operations
    def get_super_admin(self) -> Optional[dict]:
        ...

    def update_super_admin_token(self, token_hash: str, encrypted: str) -> bool:
        ...

    def insert_super_admin_token(self, token_hash: str, encrypted: str) -> None:
        ...

    def persist_admin_token(self, admin_id: int, token_hash: str, encrypted: str) -> None:
        ...

    def get_admin_by_token_hash(self, token_hash: str) -> Optional[dict]:
        ...

    def get_admin_by_token_raw(self, token: str) -> Optional[dict]:
        ...

    def get_admin_with_plaintext_token(self, token: str) -> Optional[dict]:
        ...


class MySQLRepository:
    """Repository implementation backed by the existing MySQL schema."""

    def get_agent_by_telegram_id(self, tg_id: int) -> Optional[dict]:
        with with_mysql_cursor() as cur:
            cur.execute("SELECT * FROM agents WHERE telegram_user_id=%s", (tg_id,))
            return cur.fetchone()

    def set_agent_quota(self, tg_id: int, limit_bytes: int) -> None:
        with with_mysql_cursor() as cur:
            cur.execute(
                "UPDATE agents SET plan_limit_bytes=%s WHERE telegram_user_id=%s",
                (int(limit_bytes), tg_id),
            )

    def set_agent_user_limit(self, tg_id: int, max_users: int) -> None:
        with with_mysql_cursor() as cur:
            cur.execute(
                "UPDATE agents SET user_limit=%s WHERE telegram_user_id=%s",
                (int(max_users), tg_id),
            )

    def set_agent_max_user_bytes(self, tg_id: int, max_bytes: int) -> None:
        with with_mysql_cursor() as cur:
            cur.execute(
                "UPDATE agents SET max_user_bytes=%s WHERE telegram_user_id=%s",
                (int(max_bytes), tg_id),
            )

    def renew_agent_days(self, tg_id: int, add_days: int) -> None:
        with with_mysql_cursor() as cur:
            cur.execute("SELECT expire_at FROM agents WHERE telegram_user_id=%s", (tg_id,))
            row = cur.fetchone()
            if row and row.get("expire_at"):
                cur.execute(
                    """
                    UPDATE agents
                    SET expire_at = expire_at + INTERVAL %s DAY
                    WHERE telegram_user_id=%s
                    """,
                    (add_days, tg_id),
                )
            else:
                cur.execute(
                    """
                    UPDATE agents
                    SET expire_at = UTC_TIMESTAMP() + INTERVAL %s DAY
                    WHERE telegram_user_id=%s
                    """,
                    (add_days, tg_id),
                )

    def set_agent_active(self, tg_id: int, active: bool) -> None:
        with with_mysql_cursor() as cur:
            cur.execute(
                "UPDATE agents SET active=%s WHERE telegram_user_id=%s",
                (1 if active else 0, tg_id),
            )

    def get_agent_token_fields(self, agent_id: int) -> Optional[dict]:
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                SELECT id, api_token, api_token_encrypted, api_token_raw
                FROM agents
                WHERE id=%s
                """,
                (agent_id,),
            )
            return cur.fetchone()

    def update_agent_token_fields(
        self, agent_id: int, token_hash: str, encrypted_token: str
    ) -> bool:
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                UPDATE agents
                SET api_token=%s,
                    api_token_encrypted=%s,
                    api_token_raw=NULL
                WHERE id=%s
                """,
                (token_hash, encrypted_token, agent_id),
            )
            return cur.rowcount > 0

    def bulk_update_agent_tokens(
        self, updates: Sequence[Tuple[str, str, int]]
    ) -> None:
        if not updates:
            return
        with with_mysql_cursor() as cur:
            cur.executemany(
                """
                UPDATE agents
                SET api_token=%s,
                    api_token_encrypted=%s,
                    api_token_raw=NULL
                WHERE id=%s
                """,
                updates,
            )

    def get_agents_with_legacy_tokens(self) -> Sequence[dict]:
        with with_mysql_cursor() as cur:
            cur.execute(
                "SELECT id, api_token_raw FROM agents WHERE api_token_raw IS NOT NULL"
            )
            return cur.fetchall()

    def get_super_admin(self) -> Optional[dict]:
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                SELECT id, api_token, api_token_encrypted, api_token_raw
                FROM admins
                WHERE is_super=1
                ORDER BY id ASC
                LIMIT 1
                """,
            )
            return cur.fetchone()

    def update_super_admin_token(self, token_hash: str, encrypted: str) -> bool:
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                UPDATE admins
                SET api_token=%s,
                    api_token_encrypted=%s,
                    api_token_raw=NULL
                WHERE is_super=1
                """,
                (token_hash, encrypted),
            )
            return cur.rowcount > 0

    def insert_super_admin_token(self, token_hash: str, encrypted: str) -> None:
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                INSERT INTO admins (api_token, api_token_encrypted, api_token_raw, is_super)
                VALUES (%s, %s, NULL, 1)
                """,
                (token_hash, encrypted),
            )

    def persist_admin_token(self, admin_id: int, token_hash: str, encrypted: str) -> None:
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                UPDATE admins
                SET api_token=%s,
                    api_token_encrypted=%s,
                    api_token_raw=NULL
                WHERE id=%s
                """,
                (token_hash, encrypted, admin_id),
            )

    def get_admin_by_token_hash(self, token_hash: str) -> Optional[dict]:
        with with_mysql_cursor() as cur:
            cur.execute(
                "SELECT id, is_super FROM admins WHERE api_token=%s",
                (token_hash,),
            )
            return cur.fetchone()

    def get_admin_by_token_raw(self, token: str) -> Optional[dict]:
        with with_mysql_cursor() as cur:
            cur.execute(
                "SELECT id, is_super FROM admins WHERE api_token_raw=%s",
                (token,),
            )
            return cur.fetchone()

    def get_admin_with_plaintext_token(self, token: str) -> Optional[dict]:
        with with_mysql_cursor() as cur:
            cur.execute(
                """
                SELECT id, is_super
                FROM admins
                WHERE api_token=%s AND api_token_encrypted IS NULL
                """,
                (token,),
            )
            return cur.fetchone()


class MongoRepository:
    """Repository implementation backed by MongoDB collections."""

    def __init__(self) -> None:
        self._db = get_mongo_database()

    # Helper utilities -------------------------------------------------
    def _agents(self) -> Collection:
        return self._db["agents"]

    def _admins(self) -> Collection:
        return self._db["admins"]

    @staticmethod
    def _normalize(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if doc is None:
            return None
        normalised = dict(doc)
        if "id" not in normalised and "_id" in normalised:
            normalised["id"] = normalised["_id"]
        return normalised

    # Agent operations -------------------------------------------------
    def get_agent_by_telegram_id(self, tg_id: int) -> Optional[dict]:
        doc = self._agents().find_one({"telegram_user_id": tg_id})
        return self._normalize(doc)

    def set_agent_quota(self, tg_id: int, limit_bytes: int) -> None:
        self._agents().update_one(
            {"telegram_user_id": tg_id},
            {"$set": {"plan_limit_bytes": int(limit_bytes)}},
            upsert=False,
        )

    def set_agent_user_limit(self, tg_id: int, max_users: int) -> None:
        self._agents().update_one(
            {"telegram_user_id": tg_id},
            {"$set": {"user_limit": int(max_users)}},
            upsert=False,
        )

    def set_agent_max_user_bytes(self, tg_id: int, max_bytes: int) -> None:
        self._agents().update_one(
            {"telegram_user_id": tg_id},
            {"$set": {"max_user_bytes": int(max_bytes)}},
            upsert=False,
        )

    def renew_agent_days(self, tg_id: int, add_days: int) -> None:
        collection = self._agents()
        doc = collection.find_one({"telegram_user_id": tg_id}, {"expire_at": 1})
        now = datetime.now(timezone.utc)
        if doc and doc.get("expire_at"):
            expire_at = doc["expire_at"]
            if not isinstance(expire_at, datetime):
                log.warning("Agent %s has non-datetime expire_at=%r", tg_id, expire_at)
                expire_at = now
            new_expire = expire_at + timedelta(days=add_days)
        else:
            new_expire = now + timedelta(days=add_days)
        collection.update_one(
            {"telegram_user_id": tg_id},
            {"$set": {"expire_at": new_expire}},
            upsert=False,
        )

    def set_agent_active(self, tg_id: int, active: bool) -> None:
        self._agents().update_one(
            {"telegram_user_id": tg_id},
            {"$set": {"active": bool(active)}},
            upsert=False,
        )

    def get_agent_token_fields(self, agent_id: int) -> Optional[dict]:
        query = {"id": agent_id}
        doc = self._agents().find_one(query, {"api_token": 1, "api_token_encrypted": 1, "api_token_raw": 1, "id": 1})
        if not doc:
            doc = self._agents().find_one({"_id": agent_id}, {"api_token": 1, "api_token_encrypted": 1, "api_token_raw": 1, "_id": 1})
        return self._normalize(doc)

    def update_agent_token_fields(
        self, agent_id: int, token_hash: str, encrypted_token: str
    ) -> bool:
        result = self._agents().update_one(
            {"$or": [{"id": agent_id}, {"_id": agent_id}]},
            {
                "$set": {
                    "api_token": token_hash,
                    "api_token_encrypted": encrypted_token,
                },
                "$unset": {"api_token_raw": ""},
            },
            upsert=False,
        )
        return result.matched_count > 0

    def bulk_update_agent_tokens(
        self, updates: Sequence[Tuple[str, str, int]]
    ) -> None:
        collection = self._agents()
        for token_hash, encrypted, agent_id in updates:
            collection.update_one(
                {"$or": [{"id": agent_id}, {"_id": agent_id}]},
                {
                    "$set": {
                        "api_token": token_hash,
                        "api_token_encrypted": encrypted,
                    },
                    "$unset": {"api_token_raw": ""},
                },
                upsert=False,
            )

    def get_agents_with_legacy_tokens(self) -> Sequence[dict]:
        docs = list(self._agents().find({"api_token_raw": {"$ne": None}}))
        return [self._normalize(doc) for doc in docs]

    # Admin operations -------------------------------------------------
    def get_super_admin(self) -> Optional[dict]:
        doc = self._admins().find_one({"is_super": True}, sort=[("id", 1)])
        if not doc:
            doc = self._admins().find_one({"is_super": True}, sort=[("_id", 1)])
        return self._normalize(doc)

    def update_super_admin_token(self, token_hash: str, encrypted: str) -> bool:
        result = self._admins().update_one(
            {"is_super": True},
            {
                "$set": {
                    "api_token": token_hash,
                    "api_token_encrypted": encrypted,
                    "is_super": True,
                },
                "$unset": {"api_token_raw": ""},
            },
            upsert=False,
        )
        return result.matched_count > 0

    def insert_super_admin_token(self, token_hash: str, encrypted: str) -> None:
        self._admins().update_one(
            {"is_super": True},
            {
                "$set": {
                    "api_token": token_hash,
                    "api_token_encrypted": encrypted,
                    "is_super": True,
                },
                "$unset": {"api_token_raw": ""},
            },
            upsert=True,
        )

    def persist_admin_token(self, admin_id: int, token_hash: str, encrypted: str) -> None:
        self._admins().update_one(
            {"$or": [{"id": admin_id}, {"_id": admin_id}]},
            {
                "$set": {
                    "api_token": token_hash,
                    "api_token_encrypted": encrypted,
                },
                "$unset": {"api_token_raw": ""},
            },
            upsert=False,
        )

    def get_admin_by_token_hash(self, token_hash: str) -> Optional[dict]:
        doc = self._admins().find_one({"api_token": token_hash}, {"id": 1, "is_super": 1})
        return self._normalize(doc)

    def get_admin_by_token_raw(self, token: str) -> Optional[dict]:
        doc = self._admins().find_one({"api_token_raw": token}, {"id": 1, "is_super": 1})
        return self._normalize(doc)

    def get_admin_with_plaintext_token(self, token: str) -> Optional[dict]:
        doc = self._admins().find_one(
            {"api_token": token, "api_token_encrypted": {"$exists": False}},
            {"id": 1, "is_super": 1},
        )
        return self._normalize(doc)


_REPOSITORY: Repository | None = None


def get_repository() -> Repository:
    """Return the configured repository instance, creating it on demand."""

    global _REPOSITORY
    if _REPOSITORY is not None:
        return _REPOSITORY

    settings = load_database_settings()
    if settings.backend == "mysql":
        _REPOSITORY = MySQLRepository()
    elif settings.backend == "mongodb":
        _REPOSITORY = MongoRepository()
    else:  # pragma: no cover - defensive fallback
        raise RuntimeError(f"Unsupported database backend: {settings.backend}")
    return _REPOSITORY


def reset_repository() -> None:
    """Reset the cached repository (useful for tests)."""

    global _REPOSITORY
    _REPOSITORY = None


__all__ = [
    "Repository",
    "MySQLRepository",
    "MongoRepository",
    "get_repository",
    "reset_repository",
]
