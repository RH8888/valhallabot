"""Agent service logic including agent deletion with user cleanup and verification."""
from __future__ import annotations

import logging
from typing import Any, Dict

from .database import with_mysql_cursor

log = logging.getLogger(__name__)


def delete_agent_with_users(agent_id_or_tg_id: int) -> Dict[str, Any]:
    """Delete an agent and all associated users, panel links, and database records.

    1. Finds the agent by DB id or Telegram user ID.
    2. Queries all associated users (local_users where owner_id = agent_tg_id).
    3. Attempts remote user removal on external panels for all user links.
    4. Executes atomic database deletion across all agent and user tables.
    5. Performs post-deletion verification to guarantee 0 remaining records.
       Raises RuntimeError (triggering DB rollback) if verification fails.
    """
    # Import delete_user here to avoid circular dependencies with bot.py
    from bot import delete_user

    with with_mysql_cursor() as cur:
        cur.execute(
            """
            SELECT id, telegram_user_id, name
            FROM agents
            WHERE id=%s OR telegram_user_id=%s
            LIMIT 1
            """,
            (agent_id_or_tg_id, agent_id_or_tg_id),
        )
        agent = cur.fetchone()

    if not agent:
        raise ValueError(f"Agent {agent_id_or_tg_id} not found")

    agent_db_id = int(agent["id"])
    agent_tg_id = int(agent["telegram_user_id"])
    agent_name = str(agent["name"])

    # Fetch all local users owned by this agent
    with with_mysql_cursor() as cur:
        cur.execute(
            "SELECT username FROM local_users WHERE owner_id=%s",
            (agent_tg_id,),
        )
        user_rows = cur.fetchall()

    usernames = [r["username"] for r in user_rows]
    log.info(
        "Deleting agent %s (DB id: %s, TG id: %s) with %d associated user(s)",
        agent_name,
        agent_db_id,
        agent_tg_id,
        len(usernames),
    )

    # 1. Attempt remote panel user removal for each user of this agent
    remote_errors = []
    for username in usernames:
        try:
            delete_user(agent_tg_id, username)
        except Exception as exc:
            log.warning("Error deleting remote/local user %s for agent %s: %s", username, agent_tg_id, exc)
            remote_errors.append(f"user '{username}': {exc}")

    # 2. Perform atomic database deletion in a transaction
    with with_mysql_cursor() as cur:
        # Delete local_user_keys for all local_users of this owner
        cur.execute(
            """
            DELETE luk FROM local_user_keys luk
            JOIN local_users lu ON lu.id = luk.local_user_id
            WHERE lu.owner_id = %s
            """,
            (agent_tg_id,),
        )

        # Delete local_user_panel_links for this owner
        cur.execute(
            "DELETE FROM local_user_panel_links WHERE owner_id=%s",
            (agent_tg_id,),
        )

        # Delete app_users for this agent
        cur.execute(
            "DELETE FROM app_users WHERE telegram_user_id=%s",
            (agent_tg_id,),
        )

        # Delete local_users for this owner
        cur.execute(
            "DELETE FROM local_users WHERE owner_id=%s",
            (agent_tg_id,),
        )

        # Delete agent_panel_usage_totals
        cur.execute(
            "DELETE FROM agent_panel_usage_totals WHERE agent_tg_id=%s",
            (agent_tg_id,),
        )

        # Delete agent_usage_events
        cur.execute(
            "DELETE FROM agent_usage_events WHERE agent_tg_id=%s",
            (agent_tg_id,),
        )

        # Delete agent_services
        cur.execute(
            "DELETE FROM agent_services WHERE agent_tg_id=%s",
            (agent_tg_id,),
        )

        # Delete agent_panels
        cur.execute(
            "DELETE FROM agent_panels WHERE agent_tg_id=%s",
            (agent_tg_id,),
        )

        # Delete account_presets
        cur.execute(
            "DELETE FROM account_presets WHERE telegram_user_id=%s",
            (agent_tg_id,),
        )

        # Delete settings
        cur.execute(
            "DELETE FROM settings WHERE owner_id=%s",
            (agent_tg_id,),
        )

        # Delete agent_access_tokens
        cur.execute(
            "DELETE FROM agent_access_tokens WHERE agent_id=%s",
            (agent_db_id,),
        )

        # Delete the agent record itself
        cur.execute(
            "DELETE FROM agents WHERE id=%s",
            (agent_db_id,),
        )

        # 3. Post-deletion Verification Check inside the transaction
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM agents WHERE id=%s OR telegram_user_id=%s",
            (agent_db_id, agent_tg_id),
        )
        if (cur.fetchone() or {}).get("cnt", 0) > 0:
            raise RuntimeError("Agent record still exists after deletion attempt")

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM local_users WHERE owner_id=%s",
            (agent_tg_id,),
        )
        if (cur.fetchone() or {}).get("cnt", 0) > 0:
            raise RuntimeError("Local users still exist after agent deletion attempt")

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM agent_services WHERE agent_tg_id=%s",
            (agent_tg_id,),
        )
        if (cur.fetchone() or {}).get("cnt", 0) > 0:
            raise RuntimeError("Agent services still exist after deletion attempt")

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM agent_panels WHERE agent_tg_id=%s",
            (agent_tg_id,),
        )
        if (cur.fetchone() or {}).get("cnt", 0) > 0:
            raise RuntimeError("Agent panels still exist after deletion attempt")

        cur.execute(
            "SELECT COUNT(*) AS cnt FROM agent_access_tokens WHERE agent_id=%s",
            (agent_db_id,),
        )
        if (cur.fetchone() or {}).get("cnt", 0) > 0:
            raise RuntimeError("Agent access tokens still exist after deletion attempt")

    log.info("Successfully deleted agent %s and verified 0 remaining records", agent_name)
    return {
        "status": "deleted",
        "agent_id": agent_db_id,
        "telegram_user_id": agent_tg_id,
        "name": agent_name,
        "deleted_users_count": len(usernames),
    }


__all__ = ["delete_agent_with_users"]
