from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

if "qrcode" not in sys.modules:
    sys.modules["qrcode"] = MagicMock()
if "telegram" not in sys.modules:
    sys.modules["telegram"] = MagicMock()
if "telegram.ext" not in sys.modules:
    sys.modules["telegram.ext"] = MagicMock()

import services
services.init_mysql_pool = MagicMock()

from fastapi import HTTPException

from api.web_auth import (
    create_web_session_cookie,
    get_web_identity,
    get_web_session_secret,
    web_session_serializer,
)


def run_coro(coro):
    """Run an async coroutine synchronously without Windows event loop blocking."""
    try:
        coro.send(None)
    except StopIteration as e:
        return e.value
    raise RuntimeError("Coroutine did not finish synchronously")


class TestMultiWorkerWebAuth(unittest.TestCase):
    def test_multi_worker_shared_secret_session_validation(self):
        """Worker 2 validates session created by Worker 1 when sharing WEB_SESSION_SECRET."""
        shared_secret = "test-cluster-shared-secret-key-12345"

        # Worker 1 signs the session cookie
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": shared_secret}, clear=False):
            token = create_web_session_cookie(username="alice", role="web_admin", owner_id=42)

        # Worker 2 validates the session cookie in a separate worker context
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": shared_secret}, clear=False):
            req = SimpleNamespace(state=SimpleNamespace())
            identity = run_coro(get_web_identity(request=req, web_session=token))

            self.assertEqual(identity.username, "alice")
            self.assertEqual(identity.role, "web_admin")
            self.assertEqual(identity.owner_id, 42)

    def test_multi_worker_mismatched_secret_rejection(self):
        """Worker 2 rejects session created by Worker 1 if secrets differ (multi-worker bug simulation)."""
        worker1_secret = "worker-1-unique-secret"
        worker2_secret = "worker-2-unique-secret"

        # Worker 1 creates cookie with secret 1
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": worker1_secret}, clear=False):
            token = create_web_session_cookie(username="bob", role="web_agent", owner_id=10)

        # Worker 2 attempts to validate with secret 2 -> should raise 401 Unauthorized
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": worker2_secret}, clear=False):
            req = SimpleNamespace(state=SimpleNamespace())
            with self.assertRaises(HTTPException) as cm:
                run_coro(get_web_identity(request=req, web_session=token))
            self.assertEqual(cm.exception.status_code, 401)

    def test_startup_fails_clearly_when_secret_missing(self):
        """Startup fails clearly with RuntimeError if required secret is missing rather than generating random fallback."""
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": "", "BOT_TOKEN": "", "SECRET_KEY": ""}, clear=False), \
             patch("api.web_auth.load_dotenv"):
            with self.assertRaises(RuntimeError) as cm:
                get_web_session_secret()
            self.assertIn("WEB_SESSION_SECRET is required", str(cm.exception))

            with self.assertRaises(RuntimeError) as cm_ser:
                web_session_serializer()
            self.assertIn("WEB_SESSION_SECRET is required", str(cm_ser.exception))

    def test_existing_session_fallback_secrets_preserved(self):
        """Preserves BOT_TOKEN and SECRET_KEY as backward-compatible fallbacks."""
        # Test BOT_TOKEN fallback
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": "", "BOT_TOKEN": "bot-token-fallback", "SECRET_KEY": ""}, clear=False):
            self.assertEqual(get_web_session_secret(), "bot-token-fallback")
            token = create_web_session_cookie(username="legacy_user", role="web_admin")
            req = SimpleNamespace(state=SimpleNamespace())
            identity = run_coro(get_web_identity(request=req, web_session=token))
            self.assertEqual(identity.username, "legacy_user")

        # Test SECRET_KEY fallback
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": "", "BOT_TOKEN": "", "SECRET_KEY": "secret-key-fallback"}, clear=False):
            self.assertEqual(get_web_session_secret(), "secret-key-fallback")

        # Test WEB_SESSION_SECRET takes precedence over both
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": "preferred-secret", "BOT_TOKEN": "bot-token", "SECRET_KEY": "secret-key"}, clear=False):
            self.assertEqual(get_web_session_secret(), "preferred-secret")

    def test_expired_session_rejected_across_workers(self):
        """Worker rejects expired sessions with 401 Unauthorized."""
        shared_secret = "test-shared-secret"
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": shared_secret}, clear=False):
            token = create_web_session_cookie(username="carol", role="web_admin")

        # Validate with negative TTL to simulate expired session
        with patch.dict(os.environ, {"WEB_SESSION_SECRET": shared_secret}, clear=False), \
             patch("api.web_auth.WEB_SESSION_TTL_SECONDS", -1):
            req = SimpleNamespace(state=SimpleNamespace())
            with self.assertRaises(HTTPException) as cm:
                run_coro(get_web_identity(request=req, web_session=token))
            self.assertEqual(cm.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
