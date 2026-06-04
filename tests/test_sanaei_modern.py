import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def _load_sanaei_modern():
    requests_stub = types.SimpleNamespace(Session=lambda: Mock())
    cachetools_stub = types.SimpleNamespace(
        TTLCache=lambda *args, **kwargs: {},
        cached=lambda cache=None, lock=None: (lambda func: func),
    )
    services_pkg = types.ModuleType("services")
    panel_tokens_stub = types.ModuleType("services.panel_tokens")
    panel_tokens_stub.refresh_panel_access_token_for_request = lambda *args, **kwargs: None

    originals = {name: sys.modules.get(name) for name in ("requests", "cachetools", "services", "services.panel_tokens")}
    sys.modules["requests"] = requests_stub
    sys.modules["cachetools"] = cachetools_stub
    sys.modules["services"] = services_pkg
    sys.modules["services.panel_tokens"] = panel_tokens_stub
    try:
        spec = importlib.util.spec_from_file_location(
            "sanaei_modern_under_test", Path(__file__).resolve().parents[1] / "apis" / "sanaei_modern.py"
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


sanaei_modern = _load_sanaei_modern()


class SanaeiModernResponseTests(unittest.TestCase):
    def test_panel_success_rejects_false_like_values(self):
        false_values = [False, 0, "false", "False", "0", "", " no ", "off"]
        for value in false_values:
            with self.subTest(value=value):
                self.assertFalse(sanaei_modern._panel_success({"success": value}))

    def test_create_user_does_not_treat_failed_duplicate_response_as_success(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "success": False,
            "msg": "Something went wrong (email already in use: bugtest-a7f93d2c\n)",
            "obj": None,
        }

        payload = {
            "client": {"email": "bugtest-a7f93d2c", "enable": True},
            "inboundIds": [7],
        }

        with patch.object(sanaei_modern, "_fetch_all_client_emails", return_value=(set(), None)), patch.object(
            sanaei_modern, "_request_with_reauth", return_value=response
        ):
            obj, err = sanaei_modern.create_user("https://panel.example", "token", payload)

        self.assertIsNone(obj)
        self.assertIn("email already in use", err)

    def test_create_user_rejects_duplicate_found_before_post(self):
        payload = {
            "client": {"email": "bugtest-a7f93d2c", "enable": True},
            "inboundIds": [7],
        }

        with patch.object(
            sanaei_modern, "_fetch_all_client_emails", return_value=({"bugtest-a7f93d2c"}, None)
        ), patch.object(sanaei_modern, "_request_with_reauth") as request:
            obj, err = sanaei_modern.create_user("https://panel.example", "token", payload)

        self.assertIsNone(obj)
        self.assertIn("already exists", err)
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
