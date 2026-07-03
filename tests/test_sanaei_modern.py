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

    def test_normalise_user_object_parses_string_false_enable(self):
        user = sanaei_modern._normalise_user_object({"email": "alice", "enable": "false"})

        self.assertFalse(user["enabled"])
        self.assertFalse(user["enable"])

    def test_update_remote_user_uses_modern_update_endpoint_and_client_payload(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True, "msg": "Client updated"}
        current = {
            "email": "alice@example.com",
            "id": 12,
            "uuid": "uuid-1",
            "totalGB": 1024,
            "expiryTime": 0,
            "enable": True,
            "inboundIds": [7],
            "used_traffic": 100,
            "up": 40,
            "down": 60,
            "links": ["vless://example"],
        }

        with patch.object(sanaei_modern, "_fetch_client", return_value=(current, None)), patch.object(
            sanaei_modern, "_request_with_reauth", return_value=response
        ) as request:
            ok, err = sanaei_modern.update_remote_user(
                "https://panel.example", "token", "alice@example.com", data_limit=2048
            )

        self.assertTrue(ok)
        self.assertIsNone(err)
        request.assert_called_once()
        args = request.call_args.args
        self.assertEqual(args[:7], ("POST", "https://panel.example", "token", "panel", "api", "clients", "update"))
        self.assertEqual(args[7], "alice@example.com")
        sent_json = request.call_args.kwargs["json"]
        self.assertEqual(sent_json["email"], "alice@example.com")
        self.assertEqual(sent_json["totalGB"], 2048)
        self.assertNotIn("id", sent_json)
        self.assertNotIn("uuid", sent_json)
        self.assertNotIn("inboundIds", sent_json)
        self.assertNotIn("used_traffic", sent_json)
        self.assertNotIn("up", sent_json)
        self.assertNotIn("down", sent_json)
        self.assertNotIn("links", sent_json)

    def test_update_payload_drops_identifier_fields_from_modern_request(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        current = {
            "email": "alice",
            "id": "550e8400-e29b-41d4-a716-446655440000",
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "totalGB": 1024,
            "expiryTime": 0,
            "enable": True,
        }

        with patch.object(sanaei_modern, "_fetch_client", return_value=(current, None)), patch.object(
            sanaei_modern, "_request_with_reauth", return_value=response
        ) as request:
            ok, err = sanaei_modern.update_remote_user("https://panel.example", "token", "alice", data_limit=2048)

        self.assertTrue(ok)
        self.assertIsNone(err)
        sent_json = request.call_args.kwargs["json"]
        self.assertNotIn("id", sent_json)
        self.assertNotIn("uuid", sent_json)

    def test_update_allows_expiry_renewal_without_uuid_and_sends_milliseconds(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        current = {
            "email": "alice",
            "id": 12,
            "totalGB": 1024,
            "expiryTime": 0,
            "enable": True,
        }

        with patch.object(sanaei_modern, "_fetch_client", return_value=(current, None)), patch.object(
            sanaei_modern, "_request_with_reauth", return_value=response
        ) as request:
            ok, err = sanaei_modern.update_remote_user("https://panel.example", "token", "alice", expire=1767225600)

        self.assertTrue(ok)
        self.assertIsNone(err)
        sent_json = request.call_args.kwargs["json"]
        self.assertEqual(sent_json["expiryTime"], 1767225600000)
        self.assertEqual(sent_json["email"], "alice")
        self.assertNotIn("id", sent_json)
        self.assertNotIn("uuid", sent_json)

    def test_disable_and_enable_drop_current_uuid_from_payload(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        current = {
            "email": "alice",
            "id": 12,
            "uuid": "550e8400-e29b-41d4-a716-446655440000",
            "totalGB": 1024,
            "expiryTime": 0,
            "enable": True,
        }

        with patch.object(sanaei_modern, "_fetch_client", return_value=(current, None)), patch.object(
            sanaei_modern, "_request_with_reauth", return_value=response
        ) as request:
            ok, err = sanaei_modern.disable_remote_user("https://panel.example", "token", "alice")

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertNotIn("id", request.call_args.kwargs["json"])

        with patch.object(sanaei_modern, "_fetch_client", return_value=(current, None)), patch.object(
            sanaei_modern, "_request_with_reauth", return_value=response
        ) as request:
            ok, err = sanaei_modern.enable_remote_user("https://panel.example", "token", "alice")

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertNotIn("id", request.call_args.kwargs["json"])

    def test_disable_and_enable_use_update_payload_enable_field_only(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"success": True}
        current = {
            "client": {
                "email": "alice",
                "uuid": "550e8400-e29b-41d4-a716-446655440000",
                "totalGB": 1024,
                "enabled": "false",
                "inboundIds": [1],
            }
        }

        with patch.object(sanaei_modern, "_fetch_client", return_value=(current, None)), patch.object(
            sanaei_modern, "_request_with_reauth", return_value=response
        ) as request:
            ok, err = sanaei_modern.disable_remote_user("https://panel.example", "token", "alice")

        self.assertTrue(ok)
        self.assertIsNone(err)
        sent_json = request.call_args.kwargs["json"]
        self.assertEqual(sent_json["enable"], False)
        self.assertNotIn("enabled", sent_json)
        self.assertNotIn("inboundIds", sent_json)
        self.assertNotIn("id", sent_json)

        with patch.object(sanaei_modern, "_fetch_client", return_value=(current, None)), patch.object(
            sanaei_modern, "_request_with_reauth", return_value=response
        ) as request:
            ok, err = sanaei_modern.enable_remote_user("https://panel.example", "token", "alice")

        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(request.call_args.kwargs["json"]["enable"], True)


if __name__ == "__main__":
    unittest.main()
