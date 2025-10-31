"""Ownership helper utilities shared between Flask and FastAPI layers."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Set


@lru_cache()
def admin_ids() -> Set[int]:
    """Return the configured set of administrator Telegram IDs."""
    ids = (os.getenv("ADMIN_IDS") or "").strip()
    if not ids:
        return set()
    return {int(x.strip()) for x in ids.split(",") if x.strip().isdigit()}


def expand_owner_ids(owner_id: int) -> List[int]:
    """Return the list of owner IDs that should be queried for shared data."""
    ids = admin_ids()
    return list(ids) if owner_id in ids else [owner_id]


def canonical_owner_id(owner_id: int) -> int:
    """Return the canonical owner id for inserts and updates."""
    ids = expand_owner_ids(owner_id)
    return ids[0]


__all__ = ["admin_ids", "expand_owner_ids", "canonical_owner_id"]
