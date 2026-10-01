import unittest
from gsc import normalize_site, pick_site, parse_sitemap_locs, is_sitemap_index, _is_public_http_url


class TestNormalizeSite(unittest.TestCase):
    def test_bare(self):
        self.assertEqual(normalize_site("xianmi.co"), "xianmi.co")
    def test_full_url(self):
        self.assertEqual(normalize_site("https://xianmi.co/"), "xianmi.co")
    def test_path_and_query(self):
        self.assertEqual(normalize_site("https://xianmi.co/en/?x=1"), "xianmi.co")
    def test_www_preserved(self):
        self.assertEqual(normalize_site("https://www.xianmi.co/"), "www.xianmi.co")


class TestPickSite(unittest.TestCase):
    SITES = ["sc-domain:tradelink-exp.com", "https://xianmi.co/", "https://www.foo.com/"]
    def test_sc_domain(self):
        self.assertEqual(pick_site(self.SITES, "tradelink-exp.com"), "sc-domain:tradelink-exp.com")
    def test_url_prefix(self):
        self.assertEqual(pick_site(self.SITES, "xianmi.co"), "https://xianmi.co/")
    def test_www(self):
        self.assertEqual(pick_site(self.SITES, "www.foo.com"), "https://www.foo.com/")
    def test_no_match(self):
        self.assertIsNone(pick_site(self.SITES, "unknown.com"))


class TestSitemap(unittest.TestCase):
    FLAT = '<urlset><url><loc>https://x.com/a</loc></url><url><loc>https://x.com/b</loc></url></urlset>'
    INDEX = '<sitemapindex><sitemap><loc>https://x.com/sitemap-0.xml</loc></sitemap></sitemapindex>'

    def test_parse_flat(self):
        self.assertEqual(parse_sitemap_locs(self.FLAT), ["https://x.com/a", "https://x.com/b"])
    def test_flat_not_index(self):
        self.assertFalse(is_sitemap_index(parse_sitemap_locs(self.FLAT)))
    def test_index_detected(self):
        self.assertTrue(is_sitemap_index(parse_sitemap_locs(self.INDEX)))



class TestIsPublicHttpUrl(unittest.TestCase):
    def test_http_ok(self):
        self.assertTrue(_is_public_http_url("https://xianmi.co/sitemap-0.xml"))
    def test_link_local_rejected(self):
        self.assertFalse(_is_public_http_url("http://169.254.169.254/latest/meta-data"))
    def test_loopback_rejected(self):
        self.assertFalse(_is_public_http_url("http://127.0.0.1:8080/x"))
    def test_private_rejected(self):
        self.assertFalse(_is_public_http_url("http://192.168.1.1/"))
    def test_bad_scheme_rejected(self):
        self.assertFalse(_is_public_http_url("file:///etc/passwd"))


if __name__ == "__main__":
    unittest.main()
