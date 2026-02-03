"""Helpers for owner-scoped settings storage."""
from __future__ import annotations

import logging
from typing import Optional

from api.subscription_aggregator.ownership import canonical_owner_id, expand_owner_ids
from services.database import errorcode, mysql_errors, with_mysql_cursor

log = logging.getLogger(__name__)
_settings_table_missing_logged = False


def get_setting(owner_id: int, key: str) -> Optional[str]:
    ids = expand_owner_ids(owner_id)
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
    oid = canonical_owner_id(owner_id)
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            "REPLACE INTO settings (owner_id, `key`, `value`) VALUES (%s, %s, %s)",
            (oid, key, value),
        )


def delete_setting(owner_id: int, key: str) -> bool:
    oid = canonical_owner_id(owner_id)
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            "DELETE FROM settings WHERE owner_id=%s AND `key`=%s",
            (oid, key),
        )
        return cur.rowcount > 0
