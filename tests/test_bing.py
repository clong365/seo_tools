import unittest
from unittest import mock
import requests
import bing


class TestParseMsdate(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(bing.parse_msdate("/Date(1789689600000)/"), "2026-09-18")


class TestNormalizeSite(unittest.TestCase):
    def test_url(self):
        self.assertEqual(bing.normalize_site("https://example.com/"), "example.com")


class TestCallSanitization(unittest.TestCase):
    def test_no_key_in_http_error(self):
        key = "SECRETKEY123"
        resp = mock.MagicMock()
        resp.status_code = 400
        resp.text = '{"ErrorCode":3,"Message":"InvalidApiKey"}'
        resp.raise_for_status.side_effect = requests.HTTPError("400", response=resp)
        with mock.patch("requests.get", return_value=resp):
            with self.assertRaises(RuntimeError) as cm:
                bing.call(key, "SubmitUrl", {"siteUrl": "https://x.com/"})
        self.assertNotIn(key, str(cm.exception))
        self.assertNotIn("apikey=", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
