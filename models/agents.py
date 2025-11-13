import hashlib
import logging

from services.repository import get_repository

from .token_crypto import (
    TokenEncryptionError,
    decrypt_token as _base_decrypt,
    encrypt_token as _base_encrypt,
    generate_token,
)


log = logging.getLogger(__name__)


class AgentTokenEncryptionError(TokenEncryptionError):
    """Backward-compatible alias for agent token encryption failures."""


def _encrypt_token(token: str) -> str:
    try:
        return _base_encrypt(token)
    except TokenEncryptionError as exc:
        raise AgentTokenEncryptionError(str(exc)) from exc


def _decrypt_token(ciphertext: str) -> str:
    try:
        return _base_decrypt(ciphertext)
    except TokenEncryptionError as exc:
        raise AgentTokenEncryptionError(str(exc)) from exc


def generate_api_token() -> tuple[str, str]:
    """Generate a random API token and its hash."""
    return generate_token()


def rotate_api_token(agent_id: int) -> str:
    """Generate and store a new API token for the agent.

    Returns the raw token so it can be shown once to the caller.
    Raises ValueError if the agent does not exist.
    """
    token, token_hash = generate_api_token()
    encrypted = _encrypt_token(token)

    repository = get_repository()
    updated = repository.update_agent_token_fields(agent_id, token_hash, encrypted)
    if not updated:
        raise ValueError("agent not found")
    return token


def get_api_token(agent_id: int) -> str:
    """Retrieve the raw API token for an agent.

    If the token is missing, a new one is generated and stored so the
    caller always receives a valid token.

    Raises ValueError if the agent does not exist.
    """
    repository = get_repository()
    row = repository.get_agent_token_fields(agent_id)
    if not row:
        raise ValueError("agent not found")

    encrypted = row.get("api_token_encrypted")
    if encrypted:
        return _decrypt_token(encrypted)

    legacy_token = row.get("api_token_raw")
    if legacy_token:
        log.info("Migrating legacy plaintext token for agent %s", agent_id)
        token_hash = hashlib.sha256(legacy_token.encode()).hexdigest()
        encrypted_token = _encrypt_token(legacy_token)
        repository.update_agent_token_fields(agent_id, token_hash, encrypted_token)
        return legacy_token

    # Token missing entirely; create a new one.
    token, token_hash = generate_api_token()
    encrypted_token = _encrypt_token(token)
    repository.update_agent_token_fields(agent_id, token_hash, encrypted_token)
    return token


def migrate_agent_tokens_to_encrypted():
    """Encrypt legacy plaintext agent tokens stored in the database."""

    repository = get_repository()
    rows = repository.get_agents_with_legacy_tokens()

    if not rows:
        return

    updates = []
    for row in rows:
        agent_id = row["id"]
        legacy_token = row["api_token_raw"]
        try:
            encrypted = _encrypt_token(legacy_token)
        except AgentTokenEncryptionError as exc:
            log.error("Unable to encrypt token for agent %s: %s", agent_id, exc)
            raise
        token_hash = hashlib.sha256(legacy_token.encode()).hexdigest()
        updates.append((token_hash, encrypted, agent_id))

    if not updates:
        return

    repository.bulk_update_agent_tokens(updates)
