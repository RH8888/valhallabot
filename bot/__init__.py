"""Public interface for the Telegram bot package."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from ._exports import SERVICES_EXPORTS

if TYPE_CHECKING:  # pragma: no cover - only evaluated by type checkers
    from .dispatcher import BotDispatcher as BotDispatcher

__all__ = ["BotDispatcher", "get_api", *SERVICES_EXPORTS]


def __getattr__(name: str):
    """Lazily resolve package attributes to avoid circular imports."""

    if name == "BotDispatcher":
        dispatcher = import_module(".dispatcher", __name__)
        value = getattr(dispatcher, name)
        globals()[name] = value
        return value

    if name == "get_api":
        from .utils import get_api as _get_api

        globals()[name] = _get_api
        return _get_api

    if name in SERVICES_EXPORTS:
        services = import_module(".services", __name__)
        value = getattr(services, name)
        globals()[name] = value
        return value

    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(__all__))
