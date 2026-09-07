import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock


def _load_pasarguard():
    requests_stub = types.SimpleNamespace(
        Session=lambda: Mock(),
        Response=type("Response", (), {}),
    )
    cachetools_stub = types.SimpleNamespace(
        TTLCache=lambda *args, **kwargs: {},
        cached=lambda cache=None, lock=None: (lambda func: func),
    )
    panel_tokens_stub = types.SimpleNamespace(
        refresh_panel_access_token_for_request=lambda *args, **kwargs: None,
    )
    services_stub = types.ModuleType("services")
    services_stub.panel_tokens = panel_tokens_stub

    originals = {
        name: sys.modules.get(name)
        for name in ("requests", "cachetools", "services", "services.panel_tokens")
    }
    sys.modules["requests"] = requests_stub
    sys.modules["cachetools"] = cachetools_stub
    sys.modules["services"] = services_stub
    sys.modules["services.panel_tokens"] = panel_tokens_stub
    try:
        spec = importlib.util.spec_from_file_location(
            "pasarguard_under_test", Path(__file__).resolve().parents[1] / "apis" / "pasarguard.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in originals.items():
            if original is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


pasarguard = _load_pasarguard()


class PasarguardAuthenticationTests(unittest.TestCase):
    def test_bearer_header_produced(self):
        self.assertEqual(
            pasarguard.get_headers("access-token"),
            {"Authorization": "Bearer access-token"},
        )

    def test_empty_token_returns_empty_dict(self):
        self.assertEqual(pasarguard.get_headers(""), {})
        self.assertEqual(pasarguard.get_headers(None), {})


class PasarguardGetUserTests(unittest.TestCase):
    """Tests for the filtered /api/users?username=X lookup."""

    def _mock_response(self, status_code=200, json_data=None):
        resp = MagicMock()
        resp.status_code = status_code
        resp.json.return_value = json_data
        resp.text = ""
        return resp

    def test_get_user_uses_filtered_query(self):
        resp = self._mock_response(200, {
            "users": [{
                "id": 42,
                "username": "testuser",
                "status": "active",
                "subscription_url": "/link/abc123",
            }]
        })
        with patch.object(pasarguard, "_request_with_reauth", return_value=resp) as mock_req:
            obj, err = pasarguard.get_user("https://panel.example", "jwt-token", "testuser")
            self.assertIsNone(err)
            self.assertEqual(obj["username"], "testuser")
            self.assertEqual(obj["key"], "/link/abc123")
            self.assertTrue(obj["enabled"])
            # Verify it calls /api/users with the right params
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            self.assertEqual(call_args[0][2], "jwt-token")
            self.assertEqual(call_args[0][3], "api/users")
            self.assertEqual(call_args[1]["params"]["username"], "testuser")
            self.assertEqual(call_args[1]["params"]["limit"], 1)

    def test_get_user_not_found(self):
        resp = self._mock_response(200, {"users": []})
        with patch.object(pasarguard, "_request_with_reauth", return_value=resp):
            obj, err = pasarguard.get_user("https://panel.example", "tok", "nouser")
            self.assertIsNone(obj)
            self.assertIn("not found", err)

    def test_get_user_multiple_results(self):
        resp = self._mock_response(200, {"users": [
            {"username": "a", "status": "active"},
            {"username": "b", "status": "active"},
        ]})
        with patch.object(pasarguard, "_request_with_reauth", return_value=resp):
            obj, err = pasarguard.get_user("https://panel.example", "tok", "a")
            self.assertIsNone(obj)
            self.assertIn("multiple", err)

    def test_get_user_handles_list_response(self):
        resp = self._mock_response(200, [{
            "username": "alice",
            "status": "active",
            "subscription_url": "/link/xyz",
        }])
        with patch.object(pasarguard, "_request_with_reauth", return_value=resp):
            obj, err = pasarguard.get_user("https://panel.example", "tok", "alice")
            self.assertIsNone(err)
            self.assertEqual(obj["key"], "/link/xyz")


class PasarguardParsePlainLinksTests(unittest.TestCase):
    """Tests for _parse_plain_links — no base64 decoding."""

    def _mock_response(self, text, content_type="text/plain"):
        resp = MagicMock()
        resp.headers = {"content-type": content_type}
        resp.text = text
        return resp

    def test_plain_text_links(self):
        text = "vless://abc@host:443#name1\ntrojan://def@host:443#name2\n"
        links = pasarguard._parse_plain_links(self._mock_response(text))
        self.assertEqual(len(links), 2)
        self.assertTrue(links[0].startswith("vless://"))
        self.assertTrue(links[1].startswith("trojan://"))

    def test_no_base64_decoding(self):
        """Raw base64-encoded text should NOT be decoded — return empty."""
        import base64
        raw = "vless://test@host:443#name\n"
        encoded = base64.b64encode(raw.encode()).decode()
        links = pasarguard._parse_plain_links(self._mock_response(encoded))
        # The base64 string itself does not start with vless://, so no links
        self.assertEqual(links, [])
