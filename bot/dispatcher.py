"""Dispatcher wiring for the Telegram bot application."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from services import ensure_schema, init_mysql_pool

from . import handlers

log = logging.getLogger(__name__)


class BotDispatcher:
    """Builds and wires the Telegram ``Application`` instance."""

    def __init__(self, token: str | None = None) -> None:
        load_dotenv()
        self._token = (token or os.getenv("BOT_TOKEN", "")).strip()
        if not self._token:
            raise RuntimeError("BOT_TOKEN missing in .env")

        logging.basicConfig(
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            level=logging.INFO,
        )

        init_mysql_pool()
        ensure_schema()

    def build_application(self) -> Application:
        application = Application.builder().token(self._token).build()
        application.add_handler(self._build_conversation())
        return application

    def _build_conversation(self) -> ConversationHandler:
        return ConversationHandler(
            entry_points=[
                CommandHandler("start", handlers.start),
                CallbackQueryHandler(handlers.on_button),
            ],
            states={
                handlers.ASK_PANEL_NAME: [self._text_handler(handlers.got_panel_name)],
                handlers.ASK_PANEL_TYPE: [self._text_handler(handlers.got_panel_type)],
                handlers.ASK_PANEL_URL: [self._text_handler(handlers.got_panel_url)],
                handlers.ASK_PANEL_USER: [self._text_handler(handlers.got_panel_user)],
                handlers.ASK_PANEL_PASS: [self._text_handler(handlers.got_panel_pass)],

                handlers.ASK_PANEL_TEMPLATE: [self._text_handler(handlers.got_panel_template)],
                handlers.ASK_EDIT_PANEL_NAME: [self._text_handler(handlers.got_edit_panel_name)],
                handlers.ASK_EDIT_PANEL_USER: [self._text_handler(handlers.got_edit_panel_user)],
                handlers.ASK_EDIT_PANEL_PASS: [self._text_handler(handlers.got_edit_panel_pass)],
                handlers.ASK_PANEL_SUB_URL: [self._text_handler(handlers.got_panel_sub_url)],
                handlers.ASK_PANEL_REMOVE_CONFIRM: [CallbackQueryHandler(handlers.on_button)],

                handlers.ASK_AGENT_NAME: [self._text_handler(handlers.got_agent_name)],
                handlers.ASK_AGENT_TGID: [self._text_handler(handlers.got_agent_tgid)],
                handlers.ASK_AGENT_LIMIT: [self._text_handler(handlers.got_agent_limit)],
                handlers.ASK_AGENT_RENEW_DAYS: [self._text_handler(handlers.got_agent_renew_days)],
                handlers.ASK_AGENT_MAX_USERS: [self._text_handler(handlers.got_agent_user_limit)],
                handlers.ASK_AGENT_MAX_USER_GB: [self._text_handler(handlers.got_agent_max_user_gb)],

                handlers.ASK_SERVICE_NAME: [self._text_handler(handlers.got_service_name)],
                handlers.ASK_EDIT_SERVICE_NAME: [self._text_handler(handlers.got_service_new_name)],
                handlers.ASK_ASSIGN_SERVICE_PANELS: [CallbackQueryHandler(handlers.on_button)],

                handlers.ASK_LIMIT_MSG: [self._text_handler(handlers.got_limit_msg)],
                handlers.ASK_SERVICE_EMERGENCY_CFG: [self._text_handler(handlers.got_service_emerg_cfg)],

                handlers.ASK_PRESET_GB: [self._text_handler(handlers.got_preset_gb)],
                handlers.ASK_PRESET_DAYS: [self._text_handler(handlers.got_preset_days)],

                handlers.ASK_NEWUSER_NAME: [self._text_handler(handlers.got_newuser_name)],
                handlers.ASK_PRESET_CHOICE: [CallbackQueryHandler(handlers.on_button)],
                handlers.ASK_LIMIT_GB: [self._text_handler(handlers.got_limit)],
                handlers.ASK_DURATION: [self._text_handler(handlers.got_duration)],

                handlers.ASK_SELECT_SERVICE: [CallbackQueryHandler(handlers.on_button)],

                handlers.ASK_SEARCH_USER: [self._text_handler(handlers.got_search)],
                handlers.ASK_EDIT_LIMIT: [self._text_handler(handlers.handle_edit_limit)],
                handlers.ASK_RENEW_DAYS: [self._text_handler(handlers.handle_renew_days)],
            },
            fallbacks=[CommandHandler("cancel", handlers.cancel)],
            name="bot_flow",
            allow_reentry=True,
        )

    @staticmethod
    def _text_handler(callback):
        return MessageHandler(filters.TEXT & ~filters.COMMAND, callback)
