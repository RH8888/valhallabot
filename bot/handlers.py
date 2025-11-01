#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram bot + MySQL (local users + panels) with Admin/Agent roles

Admin:
- Manage panels (add/edit creds/template/sub url, per-panel config filter)
- Remove panel (disables all mapped users on that panel first)
- Manage agents: add/edit (name), set agent quota (bytes), renew expiry by **days**, activate/deactivate
- Assign panels to agents (checkbox)
- Manage services (group panels under a service)
Agent:
- New local user (assign a service)
- Search/list users
- Edit user (limit/reset/renew + change service)

Shared:
- Unified subscription link per user
- Remote disable/enable logic preserved

ENV:
- BOT_TOKEN
- ADMIN_IDS="11111,22222" (Telegram user IDs for admins)
- MYSQL_*  , PUBLIC_BASE_URL
"""

import asyncio
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlparse

from mysql.connector import Error as MySQLError

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from api.subscription_aggregator import expand_owner_ids
from models.admins import TokenEncryptionError as AdminTokenEncryptionError
from services import (
    get_admin_token,
    get_agent_record,
    get_agent_token_value,
    renew_agent_days,
    rotate_admin_token,
    rotate_agent_token_value,
    set_agent_active,
    set_agent_max_user_bytes,
    set_agent_quota,
    set_agent_user_limit,
    with_mysql_cursor,
)

from .services import *  # noqa: F401,F403
from .utils import (
    UNIT,
    clone_proxy_settings,
    fmt_bytes_short,
    gb_to_bytes,
    get_api,
    is_admin,
    log,
    make_panel_name,
    parse_human_size,
)

# ---------- states ----------
(
    ASK_PANEL_NAME, ASK_PANEL_TYPE, ASK_PANEL_URL, ASK_PANEL_USER, ASK_PANEL_PASS,
    ASK_NEWUSER_NAME, ASK_PRESET_CHOICE, ASK_LIMIT_GB, ASK_DURATION,
    ASK_SEARCH_USER, ASK_PANEL_TEMPLATE,
    ASK_EDIT_LIMIT, ASK_RENEW_DAYS,
    ASK_EDIT_PANEL_NAME, ASK_EDIT_PANEL_USER, ASK_EDIT_PANEL_PASS,
    ASK_SELECT_SERVICE,
    ASK_PANEL_SUB_URL,

    # agent mgmt
    ASK_AGENT_NAME, ASK_AGENT_TGID,
    ASK_AGENT_LIMIT, ASK_AGENT_RENEW_DAYS,   # changed: renew by days
    ASK_AGENT_MAX_USERS, ASK_AGENT_MAX_USER_GB,
    ASK_ASSIGN_AGENT_PANELS,
    ASK_PANEL_REMOVE_CONFIRM,

    # service mgmt
    ASK_SERVICE_NAME, ASK_EDIT_SERVICE_NAME, ASK_ASSIGN_SERVICE_PANELS,

    # preset mgmt
    ASK_PRESET_GB, ASK_PRESET_DAYS,

    # settings
    ASK_LIMIT_MSG,
    ASK_SERVICE_EMERGENCY_CFG,
) = range(33)


# ---------- wiring ----------
