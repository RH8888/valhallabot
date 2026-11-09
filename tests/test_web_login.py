from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock

if "qrcode" not in sys.modules:
    sys.modules["qrcode"] = MagicMock()
if "telegram" not in sys.modules:
    sys.modules["telegram"] = MagicMock()
if "telegram.ext" not in sys.modules:
    sys.modules["telegram.ext"] = MagicMock()

import services
services.init_mysql_pool = MagicMock()

from api.subscription_aggregator import flask_app


class TestWebLoginRoute(unittest.TestCase):
    def setUp(self):
        self.app = flask_app.app
        self.client = self.app.test_client()

    def test_web_login_page_renders_login_form(self):
        resp = self.client.get("/web/login")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        # Verify page title and login interface elements
        self.assertIn("Valhalla Web Login", html)
        self.assertIn('id="login-form"', html)
        self.assertIn('id="username"', html)
        self.assertIn('id="password"', html)
        self.assertIn('id="submit"', html)
        self.assertIn('id="error"', html)
        self.assertIn("Sign in", html)

        # Verify it does NOT render the React admin dashboard template
        self.assertNotIn('<div id="root"></div>', html)
        self.assertNotIn("/static/web-ui.tsx", html)


if __name__ == "__main__":
    unittest.main()
