import hashlib
import secrets


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
    from bot import with_mysql_cursor

    with with_mysql_cursor() as cur:
        cur.execute(
            "UPDATE agents SET api_token=%s, api_token_raw=%s WHERE id=%s",
            (token_hash, token, agent_id),
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
    from bot import with_mysql_cursor

    with with_mysql_cursor() as cur:
        cur.execute("SELECT api_token_raw FROM agents WHERE id=%s", (agent_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("agent not found")
        if row["api_token_raw"] is None:
            # Token was never stored; create and persist a new one.
            token, token_hash = generate_api_token()
            cur.execute(
                "UPDATE agents SET api_token=%s, api_token_raw=%s WHERE id=%s",
                (token_hash, token, agent_id),
            )
            return token
    return row["api_token_raw"]
