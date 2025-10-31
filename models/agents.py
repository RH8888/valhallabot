import hashlib
import logging
import os
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken


log = logging.getLogger(__name__)


class AgentTokenEncryptionError(RuntimeError):
    """Raised when the agent token cannot be encrypted or decrypted."""


@lru_cache()
def _get_cipher() -> Fernet:
    key = os.environ.get("AGENT_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise AgentTokenEncryptionError(
            "AGENT_TOKEN_ENCRYPTION_KEY must be configured to encrypt agent tokens"
        )
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise AgentTokenEncryptionError(
            "AGENT_TOKEN_ENCRYPTION_KEY is not a valid Fernet key"
        ) from exc


def _encrypt_token(token: str) -> str:
    try:
        return _get_cipher().encrypt(token.encode()).decode()
    except AgentTokenEncryptionError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise AgentTokenEncryptionError("Failed to encrypt agent token") from exc


def _decrypt_token(ciphertext: str) -> str:
    try:
        return _get_cipher().decrypt(ciphertext.encode()).decode()
    except AgentTokenEncryptionError:
        raise
    except InvalidToken as exc:
        raise AgentTokenEncryptionError("Stored agent token cannot be decrypted") from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise AgentTokenEncryptionError("Failed to decrypt agent token") from exc


def generate_api_token() -> tuple[str, str]:
    """Generate a random API token and its hash."""
    token = secrets.token_hex(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    return token, token_hash


def rotate_api_token(agent_id: int) -> str:
    """Generate and store a new API token for the agent.

    Returns the raw token so it can be shown once to the caller.
    Raises ValueError if the agent does not exist.
    """
    token, token_hash = generate_api_token()
    # Import here to avoid circular import with bot.py
    from services import with_mysql_cursor

    encrypted = _encrypt_token(token)

    with with_mysql_cursor() as cur:
        cur.execute(
            """
            UPDATE agents
            SET api_token=%s,
                api_token_encrypted=%s,
                api_token_raw=NULL
            WHERE id=%s
            """,
            (token_hash, encrypted, agent_id),
        )
        if cur.rowcount == 0:
            raise ValueError("agent not found")
    return token


def get_api_token(agent_id: int) -> str:
    """Retrieve the raw API token for an agent.

    If the token is missing, a new one is generated and stored so the
    caller always receives a valid token.

    Raises ValueError if the agent does not exist.
    """
    from services import with_mysql_cursor

    with with_mysql_cursor() as cur:
        cur.execute(
            """
            SELECT api_token_encrypted, api_token_raw
            FROM agents
            WHERE id=%s
            """,
            (agent_id,),
        )
        row = cur.fetchone()
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
            cur.execute(
                """
                UPDATE agents
                SET api_token=%s,
                    api_token_encrypted=%s,
                    api_token_raw=NULL
                WHERE id=%s
                """,
                (token_hash, encrypted_token, agent_id),
            )
            return legacy_token

        # Token missing entirely; create a new one.
        token, token_hash = generate_api_token()
        encrypted_token = _encrypt_token(token)
        cur.execute(
            """
            UPDATE agents
            SET api_token=%s,
                api_token_encrypted=%s,
                api_token_raw=NULL
            WHERE id=%s
            """,
            (token_hash, encrypted_token, agent_id),
        )
        return token


def migrate_agent_tokens_to_encrypted():
    """Encrypt legacy plaintext agent tokens stored in the database."""

    from services import with_mysql_cursor

    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT id, api_token_raw FROM agents WHERE api_token_raw IS NOT NULL"
        )
        rows = cur.fetchall()

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

    with with_mysql_cursor() as cur:
        cur.executemany(
            """
            UPDATE agents
            SET api_token=%s,
                api_token_encrypted=%s,
                api_token_raw=NULL
            WHERE id=%s
            """,
            updates,
        )
