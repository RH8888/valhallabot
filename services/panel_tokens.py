"""Helpers for panel access token refreshes."""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Iterable

from apis import rebecca
from models.token_crypto import TokenEncryptionError, decrypt_token, encrypt_token

from .database import with_mysql_cursor


log = logging.getLogger(__name__)


def encrypt_panel_password(password: str) -> str:
    """Encrypt a panel admin password for storage."""

    return encrypt_token(password)


def decrypt_panel_password(ciphertext: str) -> str:
    """Decrypt a stored panel admin password."""

    return decrypt_token(ciphertext)


def _decode_jwt_payload(token: str) -> dict | None:
    parts = (token or "").split(".")
    if len(parts) < 2:
        return None
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload + padding)
        return json.loads(decoded.decode("utf-8"))
    except Exception:
        return None


def _token_expired(token: str, leeway_seconds: int = 60) -> bool:
    payload = _decode_jwt_payload(token)
    if not payload:
        return False
    exp = payload.get("exp")
    if not exp:
        return False
    try:
        exp_val = int(exp)
    except (TypeError, ValueError):
        return False
    return exp_val <= int(time.time()) + leeway_seconds


def ensure_panel_access_token(panel_row: dict) -> dict:
    """Refresh Rebecca panel access tokens if expired and credentials are stored."""

    if (panel_row.get("panel_type") or "").lower() != "rebecca":
        return panel_row

    token = panel_row.get("access_token") or ""
    if token and not _token_expired(token):
        return panel_row

    encrypted = panel_row.get("admin_password_encrypted")
    if not encrypted:
        return panel_row

    panel_id = panel_row.get("id") or panel_row.get("panel_id")
    panel_url = panel_row.get("panel_url")
    admin_username = panel_row.get("admin_username")

    if not panel_url or not admin_username:
        return panel_row

    try:
        password = decrypt_panel_password(encrypted)
    except TokenEncryptionError as exc:
        log.warning("Failed to decrypt panel password for panel %s: %s", panel_id, exc)
        return panel_row

    new_token, err = rebecca.get_admin_token(panel_url, admin_username, password)
    if not new_token:
        log.warning("Failed to refresh Rebecca token for panel %s: %s", panel_id, err)
        return panel_row

    if panel_id:
        with with_mysql_cursor() as cur:
            cur.execute(
                "UPDATE panels SET access_token=%s WHERE id=%s",
                (new_token, int(panel_id)),
            )

    panel_row["access_token"] = new_token
    return panel_row


def ensure_panel_tokens(rows: Iterable[dict]) -> list[dict]:
    """Ensure access tokens are refreshed for a list of panels."""

    refreshed = []
    for row in rows:
        refreshed.append(ensure_panel_access_token(row))
    return refreshed


__all__ = [
    "TokenEncryptionError",
    "decrypt_panel_password",
    "encrypt_panel_password",
    "ensure_panel_access_token",
    "ensure_panel_tokens",
]
