"""Helpers for subscription link/domain generation."""
from __future__ import annotations

import os
import re
from typing import Dict, List
from urllib.parse import urlparse

from api.subscription_aggregator.ownership import admin_ids
from services.settings import get_setting


def normalize_domain_entry(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://")):
        parsed = urlparse(value)
        host = parsed.netloc or parsed.path
    else:
        host = value
    host = host.split("/", 1)[0].strip()
    return host.lower()


def parse_extra_domains(raw: str) -> List[str]:
    if not raw:
        return []
    entries: List[str] = []
    seen = set()
    for part in re.split(r"[,\n]+", raw):
        host = normalize_domain_entry(part)
        if not host or host in seen:
            continue
        entries.append(host)
        seen.add(host)
    return entries


def _settings_owner_id(owner_id: int) -> int:
    if owner_id in admin_ids():
        return owner_id
    admins = sorted(admin_ids())
    return admins[0] if admins else owner_id


def get_extra_domains(owner_id: int) -> List[str]:
    settings_owner = _settings_owner_id(owner_id)
    raw = get_setting(settings_owner, "extra_sub_domains") or ""
    return parse_extra_domains(raw)


def _public_base_url() -> str:
    return os.getenv("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")


def build_subscription_domain_groups(
    owner_id: int,
    username: str,
    app_key: str,
    public_base: str | None = None,
) -> Dict[str, List[Dict[str, str]]]:
    public_base = (public_base or _public_base_url()).rstrip("/")
    parsed = urlparse(public_base)
    scheme = parsed.scheme or "https"
    base_host = (parsed.netloc or parsed.path).lower()

    def make_entry(host: str, url: str) -> Dict[str, str]:
        return {"label": host, "url": url}

    main = []
    if base_host:
        main.append(make_entry(base_host, f"{public_base}/sub/{username}/{app_key}/links"))

    additional_domains: List[Dict[str, str]] = []
    additional_subdomains: List[Dict[str, str]] = []
    for host in get_extra_domains(owner_id):
        if not host or host == base_host:
            continue
        url = f"{scheme}://{host}/sub/{username}/{app_key}/links"
        parts = [p for p in host.split(".") if p]
        if len(parts) <= 2:
            additional_domains.append(make_entry(host, url))
        else:
            additional_subdomains.append(make_entry(host, url))

    return {
        "main": main,
        "additional_domains": additional_domains,
        "additional_subdomains": additional_subdomains,
    }


def build_sub_links(
    owner_id: int, username: str, app_key: str, public_base: str | None = None
) -> List[str]:
    groups = build_subscription_domain_groups(owner_id, username, app_key, public_base)
    links: List[str] = []
    for key in ("main", "additional_domains", "additional_subdomains"):
        links.extend([entry["url"] for entry in groups.get(key, [])])
    return links


__all__ = [
    "build_sub_links",
    "build_subscription_domain_groups",
    "get_extra_domains",
    "normalize_domain_entry",
    "parse_extra_domains",
]
