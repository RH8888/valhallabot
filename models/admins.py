"""Helpers for managing admin API tokens."""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from services.repository import get_repository

from .token_crypto import TokenEncryptionError, decrypt_token, encrypt_token, generate_token


log = logging.getLogger(__name__)


def _persist_token(admin_id: int, token: str) -> None:
    """Persist the hashed and encrypted version of the provided token."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    encrypted = encrypt_token(token)
    repository = get_repository()
    repository.persist_admin_token(admin_id, token_hash, encrypted)


def get_admin_token() -> Optional[str]:
    """Return the current administrator token, migrating legacy storage if needed."""
    repository = get_repository()
    row = repository.get_super_admin()
    if not row:
        return None

    encrypted = row.get("api_token_encrypted")
    if encrypted:
        return decrypt_token(encrypted)

    legacy_raw = row.get("api_token_raw")
    if legacy_raw:
        log.info(
            "Migrating legacy admin token stored in api_token_raw for admin %s",
            row["id"],
        )
        _persist_token(row["id"], legacy_raw)
        return legacy_raw

    plaintext = row.get("api_token")
    if plaintext:
        log.info("Migrating plaintext admin token for admin %s", row["id"])
        _persist_token(row["id"], plaintext)
        return plaintext

    return None


def rotate_admin_token() -> str:
    """Generate a new admin token, store it hashed/encrypted, and return the raw value."""
    token, token_hash = generate_token()
    encrypted = encrypt_token(token)

    repository = get_repository()
    updated = repository.update_super_admin_token(token_hash, encrypted)
    if not updated:
        repository.insert_super_admin_token(token_hash, encrypted)
    return token


def validate_admin_token(token: str) -> Optional[dict]:
    """Validate a presented admin token and return the matching row if valid."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    repository = get_repository()

    row = repository.get_admin_by_token_hash(token_hash)
    if row:
        return row

    row = repository.get_admin_by_token_raw(token)
    if row:
        log.info(
            "Migrating legacy admin token stored in api_token_raw for admin %s",
            row["id"],
        )
        _persist_token(row["id"], token)
        return row

    row = repository.get_admin_with_plaintext_token(token)
    if row:
        log.info(
            "Migrating plaintext admin token for admin %s during validation",
            row["id"],
        )
        _persist_token(row["id"], token)
        return row

    return None


__all__ = [
    "TokenEncryptionError",
    "get_admin_token",
    "rotate_admin_token",
    "validate_admin_token",
]
