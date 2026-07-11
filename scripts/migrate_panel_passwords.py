#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Idempotent script to migrate legacy plaintext panel passwords to Fernet-encrypted format."""

import logging
from dotenv import load_dotenv

from services import init_mysql_pool, with_mysql_cursor
from services.panel_tokens import encrypt_panel_password, decrypt_panel_password
from models.token_crypto import TokenEncryptionError

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | migrate_panel_passwords | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("migrate_panel_passwords")


def migrate() -> None:
    """Read legacy plaintext passwords, encrypt them, and update the database."""
    log.info("Starting panel admin password migration...")
    
    with with_mysql_cursor(dict_=True) as cur:
        cur.execute(
            "SELECT id, admin_password_encrypted FROM panels "
            "WHERE admin_password_encrypted IS NOT NULL AND admin_password_encrypted != ''"
        )
        rows = cur.fetchall()

    migrated_count = 0
    skipped_count = 0

    for row in rows:
        panel_id = row["id"]
        pwd = row["admin_password_encrypted"]

        try:
            # Check if already encrypted by attempting decryption
            decrypt_panel_password(pwd)
            skipped_count += 1
        except TokenEncryptionError:
            # Decryption failed; it must be legacy plaintext. Encrypt and update.
            log.info("Migrating panel ID %d (found legacy plaintext password)", panel_id)
            encrypted = encrypt_panel_password(pwd)
            
            with with_mysql_cursor(dict_=False) as update_cur:
                update_cur.execute(
                    "UPDATE panels SET admin_password_encrypted = %s WHERE id = %s",
                    (encrypted, panel_id)
                )
            migrated_count += 1

    log.info(
        "Migration process completed. Migrated: %d, Skipped: %d, Total scanned: %d",
        migrated_count,
        skipped_count,
        len(rows),
    )


def main() -> None:
    load_dotenv()
    init_mysql_pool()
    migrate()


if __name__ == "__main__":
    main()
