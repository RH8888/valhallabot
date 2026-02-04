"""Shared helpers for encrypting and hashing API tokens."""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


log = logging.getLogger(__name__)


class TokenEncryptionError(RuntimeError):
    """Raised when a token cannot be encrypted or decrypted."""


def _persist_key(key: str) -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    try:
        if env_path.exists():
            lines = env_path.read_text().splitlines()
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
        env_path.write_text("\n".join(lines) + "\n")
    except OSError as exc:
        log.warning("Unable to persist AGENT_TOKEN_ENCRYPTION_KEY to .env: %s", exc)


def _get_or_create_key() -> str:
    key = os.environ.get("AGENT_TOKEN_ENCRYPTION_KEY")
    if key:
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
