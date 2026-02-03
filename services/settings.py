"""Helpers for owner-scoped settings storage."""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional
from services.database import errorcode, mysql_errors, with_mysql_cursor

log = logging.getLogger(__name__)
_settings_table_missing_logged = False


@lru_cache()
def _admin_ids() -> set[int]:
    ids = (os.getenv("ADMIN_IDS") or "").strip()
    if not ids:
        return set()
    return {int(x.strip()) for x in ids.split(",") if x.strip().isdigit()}


def _expand_owner_ids(owner_id: int) -> list[int]:
    ids = _admin_ids()
    return list(ids) if owner_id in ids else [owner_id]


def _canonical_owner_id(owner_id: int) -> int:
    ids = _expand_owner_ids(owner_id)
    return ids[0]


def get_setting(owner_id: int, key: str) -> Optional[str]:
    ids = _expand_owner_ids(owner_id)
    placeholders = ",".join(["%s"] * len(ids))
    with with_mysql_cursor() as cur:
        try:
            cur.execute(
                f"""
                SELECT `value`
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


def set_setting(owner_id: int, key: str, value: str) -> None:
    oid = _canonical_owner_id(owner_id)
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            "REPLACE INTO settings (owner_id, `key`, `value`) VALUES (%s, %s, %s)",
            (oid, key, value),
        )


def delete_setting(owner_id: int, key: str) -> bool:
    oid = _canonical_owner_id(owner_id)
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            "DELETE FROM settings WHERE owner_id=%s AND `key`=%s",
            (oid, key),
        )
        return cur.rowcount > 0
