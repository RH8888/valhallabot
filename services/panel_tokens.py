"""Helpers for panel access token refreshes."""
from __future__ import annotations

import base64
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable

from models.token_crypto import TokenEncryptionError, decrypt_token, encrypt_token

from .database import with_mysql_cursor


log = logging.getLogger(__name__)
FORCE_REFRESH_INTERVAL = timedelta(hours=24)


def _authenticator_for_panel_type(panel_type: str):
    panel_type = (panel_type or "").lower()
    if panel_type == "marzneshin":
        from apis import marzneshin

        return marzneshin.get_admin_token
    if panel_type == "marzban":
        from apis import marzban

        return marzban.get_admin_token
    if panel_type == "rebecca":
        from apis import rebecca

        return rebecca.get_admin_token
    if panel_type == "sanaei":
        from apis import sanaei

        return sanaei.get_admin_token
    return None


def _parse_refresh_timestamp(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _should_force_refresh(panel_row: dict) -> bool:
    refreshed_at = _parse_refresh_timestamp(panel_row.get("token_refreshed_at"))
    if not refreshed_at:
        return True
    return refreshed_at <= datetime.now(timezone.utc) - FORCE_REFRESH_INTERVAL


def _is_auth_error(error: str | None) -> bool:
    if not error:
        return False
    txt = str(error).lower()
    return "401" in txt or "403" in txt or "unauthorized" in txt or "forbidden" in txt


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
    """Refresh a panel access token when required and credentials are stored."""

    panel_type = (panel_row.get("panel_type") or "").lower()
    auth_fn = _authenticator_for_panel_type(panel_type)
    if not auth_fn:
        return panel_row

    token = panel_row.get("access_token") or ""
    if token and not _token_expired(token) and not _should_force_refresh(panel_row):
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

    new_token, err = auth_fn(panel_url, admin_username, password)
    if not new_token:
        log.warning("Failed to refresh panel token for panel %s (%s): %s", panel_id, panel_type, err)
        return panel_row

    if panel_id:
        with with_mysql_cursor() as cur:
            cur.execute(
                "UPDATE panels SET access_token=%s, token_refreshed_at=NOW() WHERE id=%s",
                (new_token, int(panel_id)),
            )

    panel_row["access_token"] = new_token
    panel_row["token_refreshed_at"] = datetime.now(timezone.utc)
    return panel_row




def refresh_panel_access_token_for_request(panel_url: str, current_token: str, panel_type: str | None = None) -> str | None:
    """Lookup panel credentials and refresh token for an API request retry."""

    if not panel_url:
        return None

    with with_mysql_cursor(dict_=True) as cur:
        if panel_type:
            cur.execute(
                """
                SELECT id, panel_url, panel_type, access_token, admin_username,
                       admin_password_encrypted, token_refreshed_at
                FROM panels
                WHERE panel_url=%s AND panel_type=%s
                ORDER BY id DESC
                LIMIT 1
                """,
                (panel_url, panel_type),
            )
            row = cur.fetchone()
            if not row:
                # Some APIs share request wrappers across compatible panel
                # implementations (e.g. Rebecca uses Marzban-style calls).
                # Fallback to URL lookup so auth-refresh still works.
                cur.execute(
                    """
                    SELECT id, panel_url, panel_type, access_token, admin_username,
                           admin_password_encrypted, token_refreshed_at
                    FROM panels
                    WHERE panel_url=%s
                    ORDER BY (access_token=%s) DESC, id DESC
                    LIMIT 1
                    """,
                    (panel_url, current_token or ""),
                )
                row = cur.fetchone()
        else:
            cur.execute(
                """
                SELECT id, panel_url, panel_type, access_token, admin_username,
                       admin_password_encrypted, token_refreshed_at
                FROM panels
                WHERE panel_url=%s
                ORDER BY (access_token=%s) DESC, id DESC
                LIMIT 1
                """,
                (panel_url, current_token or ""),
            )
            row = cur.fetchone()

    if not row:
        return None

    refreshed = ensure_panel_access_token({**row, "token_refreshed_at": None})
    new_token = refreshed.get("access_token")
    if new_token and new_token != current_token:
        return new_token
    return None

def refresh_panel_access_token_on_auth_error(panel_row: dict, error: str | None) -> dict:
    """Refresh token immediately when an auth error happens."""

    if not _is_auth_error(error):
        return panel_row
    return ensure_panel_access_token({**panel_row, "token_refreshed_at": None})


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
    "refresh_panel_access_token_for_request",
    "refresh_panel_access_token_on_auth_error",
]
