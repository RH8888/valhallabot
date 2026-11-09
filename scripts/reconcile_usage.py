#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Historical traffic reconciliation utility for ValhallaBot.

Identifies users affected by historical duplicate accounting / baseline resets
and provides a safe, inspectable, and non-destructive (dry-run by default)
procedure to reconcile usage totals.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

# Ensure project root is in sys.path when invoked directly as a script
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from dotenv import load_dotenv

from services.database import ensure_schema, init_mysql_pool, with_mysql_cursor

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | reconcile_usage | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("reconcile_usage")


def format_bytes_human(num: int | float) -> str:
    val = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(val) < 1024.0 or unit == "TB":
            return f"{val:.2f} {unit}"
        val /= 1024.0
    return f"{val:.2f} TB"


def scan_affected_users(owner_id: int | None = None, username: str | None = None) -> list[dict[str, Any]]:
    """Scan local users and compare local_users.used_bytes with panel link baselines."""
    where_clauses = []
    params: list[Any] = []
    if owner_id is not None:
        where_clauses.append("lu.owner_id = %s")
        params.append(owner_id)
    if username is not None:
        where_clauses.append("lu.username = %s")
        params.append(username)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    query = f"""
        SELECT lu.id AS user_id,
               lu.owner_id,
               lu.username,
               lu.plan_limit_bytes,
               lu.used_bytes AS current_used_bytes,
               lu.expire_at,
               lu.manual_disabled,
               lu.disabled_pushed,
               COALESCE(SUM(ROUND(lup.last_used_traffic * COALESCE(p.usage_multiplier, 1.0))), 0) AS expected_used_bytes,
               COUNT(lup.id) AS link_count
        FROM local_users lu
        LEFT JOIN local_user_panel_links lup ON lup.owner_id = lu.owner_id AND lup.local_username = lu.username
        LEFT JOIN panels p ON p.id = lup.panel_id
        {where_sql}
        GROUP BY lu.id, lu.owner_id, lu.username, lu.plan_limit_bytes, lu.used_bytes, lu.expire_at, lu.manual_disabled, lu.disabled_pushed
        ORDER BY lu.owner_id ASC, lu.username ASC
    """

    with with_mysql_cursor(dict_=True) as cur:
        cur.execute(query, tuple(params))
        rows = cur.fetchall()

    results = []
    for r in rows:
        current = int(r["current_used_bytes"] or 0)
        expected = int(r["expected_used_bytes"] or 0)
        excess = current - expected
        ratio = (current / expected) if expected > 0 else (float("inf") if current > 0 else 1.0)

        status = "OK"
        if excess > 0:
            if 1.90 <= ratio <= 2.10:
                status = "DOUBLED"
            else:
                status = "EXCESS"
        elif excess < 0:
            status = "UNDER_COUNTED"

        results.append({
            "user_id": r["user_id"],
            "owner_id": r["owner_id"],
            "username": r["username"],
            "plan_limit_bytes": int(r["plan_limit_bytes"] or 0),
            "current_used_bytes": current,
            "expected_used_bytes": expected,
            "excess_bytes": excess,
            "ratio": ratio,
            "link_count": int(r["link_count"] or 0),
            "status": status,
        })
    return results


def apply_reconciliation(
    affected_users: list[dict[str, Any]],
    only_doubled: bool = True,
) -> int:
    """Safely reconcile local_users.used_bytes back to expected_used_bytes."""
    fixed_count = 0
    updated_owners = set()

    for item in affected_users:
        if only_doubled and item["status"] != "DOUBLED":
            continue
        if item["status"] not in ("DOUBLED", "EXCESS"):
            continue

        owner_id = item["owner_id"]
        uname = item["username"]
        new_used = item["expected_used_bytes"]
        old_used = item["current_used_bytes"]

        with with_mysql_cursor(dict_=True) as cur:
            cur.execute(
                """
                UPDATE local_users
                SET used_bytes = %s
                WHERE owner_id = %s AND username = %s
                """,
                (new_used, owner_id, uname),
            )

        log.info(
            "Reconciled user %s (owner=%s): %s -> %s (excess: -%s)",
            uname, owner_id,
            format_bytes_human(old_used),
            format_bytes_human(new_used),
            format_bytes_human(item["excess_bytes"]),
        )
        fixed_count += 1
        updated_owners.add(owner_id)

    # Recalculate agent total_used_bytes for affected owners
    for oid in updated_owners:
        with with_mysql_cursor(dict_=True) as cur:
            cur.execute(
                """
                UPDATE agents
                SET total_used_bytes = (
                    SELECT COALESCE(SUM(used_bytes), 0)
                    FROM local_users
                    WHERE owner_id = %s
                )
                WHERE telegram_user_id = %s
                """,
                (oid, oid),
            )
        log.info("Recalculated agents.total_used_bytes for agent/owner=%s", oid)

    return fixed_count


def main():
    parser = argparse.ArgumentParser(description="Reconcile ValhallaBot traffic double-counting")
    parser.add_argument("--owner-id", type=int, default=None, help="Filter by owner/agent ID")
    parser.add_argument("--user", type=str, default=None, help="Filter by specific username")
    parser.add_argument("--fix", action="store_true", help="Apply reconciliation (default: dry run)")
    parser.add_argument("--all-excess", action="store_true", help="Fix all excess usage, not just ~2x doubled users")
    args = parser.parse_args()

    load_dotenv()
    init_mysql_pool()
    ensure_schema()

    records = scan_affected_users(owner_id=args.owner_id, username=args.user)
    affected = [r for r in records if r["status"] in ("DOUBLED", "EXCESS")]

    print("\n" + "=" * 80)
    print("VALHALLABOT TRAFFIC AUDIT REPORT")
    print("=" * 80)
    print(f"Total users inspected: {len(records)}")
    print(f"Users with suspected duplicate accounting: {len(affected)}")
    print("-" * 80)

    if not affected:
        print("No affected users found. All usage baselines match expected totals.")
        print("=" * 80 + "\n")
        return

    for a in affected:
        print(
            f"• User: {a['username']:<20} Owner: {a['owner_id']:<10} "
            f"Status: {a['status']:<10} "
            f"Current: {format_bytes_human(a['current_used_bytes']):<12} "
            f"Expected: {format_bytes_human(a['expected_used_bytes']):<12} "
            f"Excess: +{format_bytes_human(a['excess_bytes']):<12} "
            f"Ratio: {a['ratio']:.2f}x"
        )
    print("=" * 80)

    if not args.fix:
        print("\n[DRY RUN MODE] No changes were made to the database.")
        print("To reconcile affected users safely, re-run with --fix (or --fix --user <username>).\n")
    else:
        print("\nApplying reconciliation...")
        fixed = apply_reconciliation(affected, only_doubled=not args.all_excess)
        print(f"Successfully reconciled {fixed} users.\n")


if __name__ == "__main__":
    main()
