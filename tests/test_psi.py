import os
import tempfile
import unittest
from unittest import mock

import psi


class TestBuildParams(unittest.TestCase):
    def test_default_categories(self):
        p = psi.build_params("https://x/", "mobile", None, "K")
        self.assertIn(("url", "https://x/"), p)
        self.assertIn(("strategy", "mobile"), p)
        self.assertIn(("key", "K"), p)
        cats = [v for k, v in p if k == "category"]
        self.assertEqual(sorted(cats), sorted(psi.CATEGORIES))

    def test_explicit_categories(self):
        p = psi.build_params("https://x/", "desktop", ["performance"], "K")
        self.assertEqual([v for k, v in p if k == "category"], ["performance"])


class TestLoadKey(unittest.TestCase):
    def test_missing_key_exits(self):
        with self.assertRaises(SystemExit) as cm:
            psi.load_key("/tmp/definitely-missing-psi-key.txt")
        self.assertIn("PageSpeed Insights API", str(cm.exception))

    def test_existing_key_is_stripped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("  ABC123\n")
            path = f.name
        try:
            self.assertEqual(psi.load_key(path), "ABC123")
        finally:
            os.unlink(path)


class TestFetch(unittest.TestCase):
    def test_http_error_exits_with_message(self):
        resp = mock.Mock()
        resp.status_code = 400
        resp.json.return_value = {"error": {"message": "API key not valid"}}
        with mock.patch("psi.requests.get", return_value=resp):
            with self.assertRaises(SystemExit) as cm:
                psi.fetch("https://x/", "mobile", None, "bad")
        self.assertIn("API key not valid", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
