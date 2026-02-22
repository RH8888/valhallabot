"""Ownership helper utilities shared between Flask and FastAPI layers."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Set


@lru_cache()
def ordered_admin_ids() -> List[int]:
    """Return configured administrator IDs in declared env order."""
    ids = (os.getenv("ADMIN_IDS") or "").strip()
    if not ids:
        return []
    ordered: List[int] = []
    seen: Set[int] = set()
    for raw in ids.split(","):
        raw = raw.strip()
        if not raw.isdigit():
            continue
        value = int(raw)
        if value in seen:
            continue
        ordered.append(value)
        seen.add(value)
    return ordered


@lru_cache()
def admin_ids() -> Set[int]:
    """Return the configured set of administrator Telegram IDs."""
    return set(ordered_admin_ids())


def expand_owner_ids(owner_id: int) -> List[int]:
    """Return the list of owner IDs that should be queried for shared data."""
    admins = ordered_admin_ids()
    return admins if owner_id in set(admins) else [owner_id]


def canonical_owner_id(owner_id: int) -> int:
    """Return the canonical owner id for inserts and updates."""
    ids = expand_owner_ids(owner_id)
    return ids[0]


__all__ = ["admin_ids", "ordered_admin_ids", "expand_owner_ids", "canonical_owner_id"]
