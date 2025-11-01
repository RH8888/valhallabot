"""Public package interface for the Telegram bot components.

Historically many modules imported helpers directly from :mod:`bot`.
When the ``__init__`` file only re-exported :class:`BotDispatcher` those
imports started to fail (for example ``from bot import get_app_key``)
once the project structure changed.  The API application still relies on
those helpers being available, so we expose them again by re-exporting
the service-layer utilities here.
"""

from .dispatcher import BotDispatcher
from .services import *  # noqa: F401,F403 - re-export public helpers
from .services import __all__ as _service_all
from .utils import get_api

__all__ = ["BotDispatcher", "get_api", *_service_all]
