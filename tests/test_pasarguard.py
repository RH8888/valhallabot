import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock


def _load_pasarguard():
    requests_stub = types.SimpleNamespace(Session=lambda: Mock())
    cachetools_stub = types.SimpleNamespace(
        TTLCache=lambda *args, **kwargs: {},
        cached=lambda cache=None, lock=None: (lambda func: func),
    )
    originals = {name: sys.modules.get(name) for name in ("requests", "cachetools")}
    sys.modules["requests"] = requests_stub
    sys.modules["cachetools"] = cachetools_stub
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
    def test_api_key_prefixes_use_api_key_header(self):
        for prefix in ("api_key", "apikey", "x-api-key"):
            with self.subTest(prefix=prefix):
                self.assertEqual(
                    pasarguard.get_headers(f"{prefix}: pg_key_secret"),
                    {"X-Api-Key": "pg_key_secret"},
                )

    def test_bearer_tokens_remain_supported(self):
        self.assertEqual(
            pasarguard.get_headers("Bearer access-token"),
            {"Authorization": "Bearer access-token"},
        )
        self.assertEqual(
            pasarguard.get_headers("access-token"),
            {"Authorization": "Bearer access-token"},
        )
