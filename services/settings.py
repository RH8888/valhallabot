"""Helpers for owner-scoped settings storage."""
from __future__ import annotations

import logging
from typing import Optional

from services.database import errorcode, mysql_errors, with_mysql_cursor

log = logging.getLogger(__name__)
_settings_table_missing_logged = False


def get_setting(owner_id: int, key: str) -> Optional[str]:
    from api.subscription_aggregator.ownership import ordered_admin_ids

    admins = ordered_admin_ids()
    # Sudo-admin settings are global defaults for every admin and agent.
    # Admin rows are checked first so their decisions are applied consistently.
    ids = admins if owner_id in admins else admins + [owner_id]
    if not ids:
        ids = [owner_id]
    in_placeholders = ",".join(["%s"] * len(ids))
    order_clauses = " ".join([f"WHEN %s THEN {idx}" for idx, _ in enumerate(ids)])
    order_by = f"CASE owner_id {order_clauses} ELSE {len(ids)} END"
    with with_mysql_cursor() as cur:
        try:
            cur.execute(
                f"""
                SELECT `value`
                FROM settings
                WHERE owner_id IN ({in_placeholders}) AND `key`=%s
                ORDER BY {order_by}
                LIMIT 1
                """,
                tuple(ids) + (key,) + tuple(ids),
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
    from api.subscription_aggregator.ownership import canonical_owner_id

    oid = canonical_owner_id(owner_id)
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            "REPLACE INTO settings (owner_id, `key`, `value`) VALUES (%s, %s, %s)",
            (oid, key, value),
        )


def delete_setting(owner_id: int, key: str) -> bool:
    from api.subscription_aggregator.ownership import canonical_owner_id

    oid = canonical_owner_id(owner_id)
    with with_mysql_cursor(dict_=False) as cur:
        cur.execute(
            "DELETE FROM settings WHERE owner_id=%s AND `key`=%s",
            (oid, key),
        )
        return cur.rowcount > 0
