#!/usr/bin/env python3
"""Backfill hashed/encrypted storage for existing admin API tokens."""
from __future__ import annotations

import hashlib
import logging
import os

from dotenv import load_dotenv
from mysql.connector import pooling, errors as mysql_errors

from models.token_crypto import encrypt_token, TokenEncryptionError


logging.basicConfig(
    format="%(asctime)s | %(levelname)s | migrate_admin_tokens | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("migrate_admin_tokens")

POOL: pooling.MySQLConnectionPool | None = None


def init_pool() -> None:
    """Initialise a small MySQL connection pool for the migration."""
    global POOL
    if POOL is not None:
        return
    load_dotenv()
    POOL = pooling.MySQLConnectionPool(
        pool_name="migrate_admin_tokens",
        pool_size=2,
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "botdb"),
        charset="utf8mb4",
        use_pure=True,
    )


class CursorCtx:
    """Context manager that returns a cursor and commits on success."""

    def __init__(self, dict_: bool = True) -> None:
        self.dict_ = dict_
        self.conn = None
        self.cur = None

    def __enter__(self):
        global POOL
        if POOL is None:
            init_pool()
        self.conn = POOL.get_connection()
        self.cur = self.conn.cursor(dictionary=self.dict_)
        return self.cur

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.cur.close()
            self.conn.close()
        return False


def ensure_columns() -> None:
    """Add the encrypted/raw columns when they are missing."""
    with CursorCtx(dict_=False) as cur:
        try:
            cur.execute("ALTER TABLE admins ADD COLUMN api_token_encrypted TEXT")
        except mysql_errors.ProgrammingError as exc:
            if getattr(exc, "errno", None) != 1060:  # duplicate column
                raise
        try:
            cur.execute("ALTER TABLE admins ADD COLUMN api_token_raw VARCHAR(128) NULL")
        except mysql_errors.ProgrammingError as exc:
            if getattr(exc, "errno", None) != 1060:
                raise


def fetch_candidates():
    """Return admin rows that still need to be migrated."""
    with CursorCtx() as cur:
        cur.execute(
            """
            SELECT id, api_token, api_token_raw, api_token_encrypted
            FROM admins
            WHERE api_token IS NOT NULL
              AND (api_token_encrypted IS NULL OR api_token_encrypted = '')
            """
        )
        return cur.fetchall()


def migrate() -> None:
    rows = fetch_candidates()
    if not rows:
        log.info("No admin tokens require migration.")
        return

    updates: list[tuple[str, str, int]] = []
    for row in rows:
        admin_id = row["id"]
        raw_token = row.get("api_token_raw") or row.get("api_token")
        if not raw_token:
            log.warning("Skipping admin %s: no plaintext token available", admin_id)
            continue
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        try:
            encrypted = encrypt_token(raw_token)
        except TokenEncryptionError as exc:
            log.error("Failed to encrypt token for admin %s: %s", admin_id, exc)
            raise
        updates.append((token_hash, encrypted, admin_id))

    if not updates:
        log.info("No updates generated; nothing to do.")
        return

    with CursorCtx(dict_=False) as cur:
        cur.executemany(
            """
            UPDATE admins
            SET api_token=%s,
                api_token_encrypted=%s,
                api_token_raw=NULL
            WHERE id=%s
            """,
            updates,
        )
    log.info("Migrated %s admin token(s) to hashed/encrypted storage.", len(updates))


def main() -> None:
    init_pool()
    ensure_columns()
    migrate()


if __name__ == "__main__":
    main()
