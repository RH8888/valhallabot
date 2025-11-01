#!/usr/bin/env python3
"""Entry point for the Telegram bot application."""

from bot import BotDispatcher


def main() -> None:
    application = BotDispatcher().build_application()
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
