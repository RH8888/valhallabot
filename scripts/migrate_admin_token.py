#!/usr/bin/env python3
import os

from dotenv import load_dotenv

from bot import ensure_schema, with_mysql_cursor


def main():
    load_dotenv()
    token = os.getenv("ADMIN_API_TOKEN")
    if not token:
        print("ADMIN_API_TOKEN not set; nothing to migrate.")
        return

    ensure_schema()
    with with_mysql_cursor() as cur:
        cur.execute("SELECT id FROM admins WHERE is_super=1")
        row = cur.fetchone()
        if row:
            print("Admin token already present; skipping.")
            return
        cur.execute("INSERT INTO admins (api_token, is_super) VALUES (%s, 1)", (token,))
        print("Admin token migrated.")


if __name__ == "__main__":
    main()
