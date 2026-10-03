import socket
import unittest
from unittest import mock

import requests

import gsc
from gsc import (
    normalize_site, pick_site, parse_sitemap_locs, is_sitemap_index,
    _is_public_http_url, _fetch_guarded, fetch_sitemap_urls,
)


class TestNormalizeSite(unittest.TestCase):
    def test_bare(self):
        self.assertEqual(normalize_site("example.com"), "example.com")
    def test_full_url(self):
        self.assertEqual(normalize_site("https://example.com/"), "example.com")
    def test_path_and_query(self):
        self.assertEqual(normalize_site("https://example.com/en/?x=1"), "example.com")
    def test_www_preserved(self):
        self.assertEqual(normalize_site("https://www.example.com/"), "www.example.com")


class TestPickSite(unittest.TestCase):
    SITES = ["sc-domain:example.org", "https://example.com/", "https://www.foo.com/"]
    def test_sc_domain(self):
        self.assertEqual(pick_site(self.SITES, "example.org"), "sc-domain:example.org")
    def test_url_prefix(self):
        self.assertEqual(pick_site(self.SITES, "example.com"), "https://example.com/")
    def test_www_exact(self):
        self.assertEqual(pick_site(self.SITES, "www.foo.com"), "https://www.foo.com/")
    def test_www_variant(self):
        self.assertEqual(pick_site(self.SITES, "foo.com"), "https://www.foo.com/")
    def test_no_match(self):
        self.assertIsNone(pick_site(self.SITES, "unknown.com"))
    def test_substring_not_matched(self):
        self.assertIsNone(pick_site(["sc-domain:notfoo.com"], "foo.com"))
    def test_suffix_not_matched(self):
        self.assertIsNone(pick_site(["https://foo.com.cn/"], "foo.com"))


class TestSitemap(unittest.TestCase):
    FLAT = '<urlset><url><loc>https://x.com/a</loc></url><url><loc>https://x.com/b</loc></url></urlset>'
    INDEX = '<sitemapindex><sitemap><loc>https://x.com/sitemap-0.xml</loc></sitemap></sitemapindex>'

    def test_parse_flat(self):
        self.assertEqual(parse_sitemap_locs(self.FLAT), ["https://x.com/a", "https://x.com/b"])
    def test_flat_not_index(self):
        self.assertFalse(is_sitemap_index(parse_sitemap_locs(self.FLAT)))
    def test_index_detected(self):
        self.assertTrue(is_sitemap_index(parse_sitemap_locs(self.INDEX)))

    @mock.patch("gsc.requests.get", side_effect=requests.RequestException("404"))
    def test_fetch_empty_on_404(self, get):
        self.assertEqual(fetch_sitemap_urls("https://example.com/"), [])


class TestIsPublicHttpUrl(unittest.TestCase):
    def test_link_local_rejected(self):
        self.assertFalse(_is_public_http_url("http://169.254.169.254/latest/meta-data"))
    def test_loopback_rejected(self):
        self.assertFalse(_is_public_http_url("http://127.0.0.1:8080/x"))
    def test_private_rejected(self):
        self.assertFalse(_is_public_http_url("http://192.168.1.1/"))
    def test_bad_scheme_rejected(self):
        self.assertFalse(_is_public_http_url("file:///etc/passwd"))

    @mock.patch("socket.getaddrinfo")
    def test_domain_public_ok(self, dns):
        dns.return_value = [(2, 1, 6, "", ("1.2.3.4", 0))]
        self.assertTrue(_is_public_http_url("https://example.com/sitemap-0.xml"))

    @mock.patch("socket.getaddrinfo")
    def test_domain_private_rejected(self, dns):
        dns.return_value = [(2, 1, 6, "", ("10.0.0.1", 0))]
        self.assertFalse(_is_public_http_url("http://evil.internal/x"))

    @mock.patch("socket.getaddrinfo")
    def test_domain_dns_fail_rejected(self, dns):
        dns.side_effect = socket.gaierror
        self.assertFalse(_is_public_http_url("http://nope.invalid/x"))


class TestFetchGuarded(unittest.TestCase):
    @mock.patch("gsc.requests.get")
    def test_redirect_to_internal_rejected(self, get):
        r = mock.MagicMock()
        r.status_code = 302
        r.headers = {"Location": "http://127.0.0.1/x"}
        get.return_value = r
        self.assertIsNone(_fetch_guarded("https://x.com/sitemap-0.xml"))

    @mock.patch("gsc._is_public_http_url", return_value=True)
    @mock.patch("gsc.requests.get", side_effect=requests.RequestException("timeout"))
    def test_network_error_returns_none(self, get, _):
        self.assertIsNone(_fetch_guarded("https://x.com/sitemap-0.xml"))


class TestMainErrorHandling(unittest.TestCase):
    @mock.patch("gsc.get_token", side_effect=RuntimeError("boom"))
    @mock.patch("gsc.os.path.exists", return_value=True)
    def test_auth_failure_actionable(self, exists, get_token):
        with mock.patch("gsc.sys.argv", ["gsc.py"]), mock.patch("gsc.sys.exit") as ex:
            gsc.main()
        self.assertIn("client_email", str(ex.call_args[0][0]))


if __name__ == "__main__":
    unittest.main()
