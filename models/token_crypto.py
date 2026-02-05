"""Shared helpers for encrypting and hashing API tokens."""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import secrets

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv


log = logging.getLogger(__name__)
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


class TokenEncryptionError(RuntimeError):
    """Raised when a token cannot be encrypted or decrypted."""


def _persist_key(key: str) -> None:
    try:
        if ENV_PATH.exists():
            lines = ENV_PATH.read_text().splitlines()
        else:
            lines = []
        updated = False
        for idx, line in enumerate(lines):
            if line.startswith("AGENT_TOKEN_ENCRYPTION_KEY="):
                lines[idx] = f"AGENT_TOKEN_ENCRYPTION_KEY={key}"
                updated = True
                break
        if not updated:
            lines.append(f"AGENT_TOKEN_ENCRYPTION_KEY={key}")
        ENV_PATH.write_text("\n".join(lines) + "\n")
    except OSError as exc:
        log.warning("Unable to persist AGENT_TOKEN_ENCRYPTION_KEY to .env: %s", exc)


def _normalize_key(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"\"", "'"}
    ):
        return value[1:-1].strip()
    return value


def _load_key_from_env_file() -> str:
    try:
        if not ENV_PATH.exists():
            return ""
        for line in ENV_PATH.read_text().splitlines():
            if line.startswith("AGENT_TOKEN_ENCRYPTION_KEY="):
                _, _, raw = line.partition("=")
                return _normalize_key(raw)
    except OSError as exc:
        log.warning("Unable to read AGENT_TOKEN_ENCRYPTION_KEY from .env: %s", exc)
    return ""


def _get_or_create_key() -> str:
    key = _normalize_key(os.environ.get("AGENT_TOKEN_ENCRYPTION_KEY"))
    if key:
        os.environ["AGENT_TOKEN_ENCRYPTION_KEY"] = key
        return key

    load_dotenv(dotenv_path=ENV_PATH)
    key = _normalize_key(os.environ.get("AGENT_TOKEN_ENCRYPTION_KEY"))
    if key:
        os.environ["AGENT_TOKEN_ENCRYPTION_KEY"] = key
        return key

    key = _load_key_from_env_file()
    if key:
        os.environ["AGENT_TOKEN_ENCRYPTION_KEY"] = key
        return key

    generated = Fernet.generate_key().decode()
    os.environ["AGENT_TOKEN_ENCRYPTION_KEY"] = generated
    _persist_key(generated)
    log.warning("Generated missing AGENT_TOKEN_ENCRYPTION_KEY at runtime.")
    return generated


def _get_cipher() -> Fernet:
    key = _get_or_create_key()
    try:
        return Fernet(key.encode())
    except ValueError as exc:  # pragma: no cover - invalid key format
        raise TokenEncryptionError(
            "AGENT_TOKEN_ENCRYPTION_KEY is not a valid Fernet key"
        ) from exc


def encrypt_token(token: str) -> str:
    """Encrypt a raw token using the configured Fernet key."""
    try:
        return _get_cipher().encrypt(token.encode()).decode()
    except TokenEncryptionError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise TokenEncryptionError("Failed to encrypt token") from exc


def decrypt_token(ciphertext: str) -> str:
    """Decrypt an encrypted token using the configured Fernet key."""
    try:
        return _get_cipher().decrypt(ciphertext.encode()).decode()
    except TokenEncryptionError:
        raise
    except InvalidToken as exc:
        raise TokenEncryptionError("Stored token cannot be decrypted") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise TokenEncryptionError("Failed to decrypt token") from exc


def generate_token() -> tuple[str, str]:
    """Generate a random token and return the token and its SHA-256 hash."""
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


__all__ = [
    "TokenEncryptionError",
    "encrypt_token",
    "decrypt_token",
    "generate_token",
]
