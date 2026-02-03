"""Helpers for managing admin API tokens."""
"New Update"
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from .token_crypto import TokenEncryptionError, decrypt_token, encrypt_token, generate_token


log = logging.getLogger(__name__)


def _persist_token(cur, admin_id: int, token: str) -> None:
    """Persist the hashed and encrypted version of the provided token."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    encrypted = encrypt_token(token)
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


def get_admin_token() -> Optional[str]:
    """Return the current administrator token, migrating legacy storage if needed."""
    from services import with_mysql_cursor

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
        row = cur.fetchone()
        if not row:
            return None

        encrypted = row.get("api_token_encrypted")
        if encrypted:
            return decrypt_token(encrypted)

        legacy_raw = row.get("api_token_raw")
        if legacy_raw:
            log.info("Migrating legacy admin token stored in api_token_raw for admin %s", row["id"])
            _persist_token(cur, row["id"], legacy_raw)
            return legacy_raw

        plaintext = row.get("api_token")
        if plaintext:
            log.info("Migrating plaintext admin token for admin %s", row["id"])
            _persist_token(cur, row["id"], plaintext)
            return plaintext

    return None


def rotate_admin_token() -> str:
    """Generate a new admin token, store it hashed/encrypted, and return the raw value."""
    token, token_hash = generate_token()
    encrypted = encrypt_token(token)

    from services import with_mysql_cursor

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
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO admins (api_token, api_token_encrypted, api_token_raw, is_super)
                VALUES (%s, %s, NULL, 1)
                """,
                (token_hash, encrypted),
            )
    return token


def validate_admin_token(token: str) -> Optional[dict]:
    """Validate a presented admin token and return the matching row if valid."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    from services import with_mysql_cursor

    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT id, is_super FROM admins WHERE api_token=%s",
            (token_hash,),
        )
        row = cur.fetchone()
        if row:
            return row

        cur.execute(
            "SELECT id, is_super FROM admins WHERE api_token_raw=%s",
            (token,),
        )
        row = cur.fetchone()
        if row:
            log.info("Migrating legacy admin token stored in api_token_raw for admin %s", row["id"])
            _persist_token(cur, row["id"], token)
            return row

        cur.execute(
            "SELECT id, is_super FROM admins WHERE api_token=%s AND api_token_encrypted IS NULL",
            (token,),
        )
        row = cur.fetchone()
        if row:
            log.info("Migrating plaintext admin token for admin %s during validation", row["id"])
            _persist_token(cur, row["id"], token)
            return row

    return None


__all__ = [
    "TokenEncryptionError",
    "get_admin_token",
    "rotate_admin_token",
    "validate_admin_token",
]
