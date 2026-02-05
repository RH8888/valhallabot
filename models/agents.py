from .token_crypto import (
    TokenEncryptionError,
    decrypt_token as _base_decrypt,
    encrypt_token as _base_encrypt,
    generate_token,
)



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
    # Import here to avoid circular import with bot.py
    from services import with_mysql_cursor

    encrypted = _encrypt_token(token)

    with with_mysql_cursor() as cur:
        cur.execute(
            """
            UPDATE agents
            SET api_token=%s,
                api_token_encrypted=%s
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
            SELECT api_token_encrypted
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

        # Token missing entirely; create a new one.
        token, token_hash = generate_api_token()
        encrypted_token = _encrypt_token(token)
        cur.execute(
            """
            UPDATE agents
            SET api_token=%s,
                api_token_encrypted=%s
            WHERE id=%s
            """,
            (token_hash, encrypted_token, agent_id),
        )
        return token


def migrate_agent_tokens_to_encrypted():
    """No-op migration kept for backward compatibility.

    Agent plaintext token storage (`api_token_raw`) has been removed from the
    schema, so there is no legacy data to migrate in current deployments.
    """

    return None
