"""Subscription aggregator shared components."""
from .ownership import admin_ids, expand_owner_ids, canonical_owner_id
from .flask_app import create_flask_app

__all__ = [
    "admin_ids",
    "expand_owner_ids",
    "canonical_owner_id",
    "create_flask_app",
]
