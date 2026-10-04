import os
import socket
import tempfile
import unittest
from unittest import mock

import requests

import gsc
from gsc import (
    normalize_site, pick_site, parse_sitemap_locs, is_sitemap_index,
    _is_public_http_url, _fetch_guarded, fetch_sitemap_urls,
)


def write_conf(obj):
    """写一份 sites.json 到临时文件，返回路径。"""
    import json
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    return path


class TestNormalizeSite(unittest.TestCase):
    def test_bare(self):
        self.assertEqual(normalize_site("example.com"), "example.com")
    def test_full_url(self):
        self.assertEqual(normalize_site("https://example.com/"), "example.com")
    def test_path_and_query(self):
        self.assertEqual(normalize_site("https://example.com/en/?x=1"), "example.com")
    def test_www_preserved(self):
        self.assertEqual(normalize_site("https://www.example.com/"), "www.example.com")


    def test_sc_domain_prefix_stripped(self):
        """sc-domain: 是 GSC 资源名前缀，不是域名的一部分。

        normalize_site 的职责是「规整为裸域名」，必须去掉它——
        否则 pick_site 用 _bare_host()（已去前缀）比对时永远匹配不上。
        """
        self.assertEqual(normalize_site("sc-domain:example.org"), "example.org")

    def test_sc_domain_with_trailing_slash(self):
        self.assertEqual(normalize_site("sc-domain:example.org/"), "example.org")

    def test_sc_domain_inside_url(self):
        self.assertEqual(normalize_site("https://sc-domain:example.org/"), "example.org")


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
    def test_sc_domain_prefixed_input_matches(self):
        """用户照 GSC 控制台原样粘 sc-domain:xxx 也必须能匹配。"""
        self.assertEqual(pick_site(self.SITES, "sc-domain:example.org"), "sc-domain:example.org")

    def test_sc_domain_prefixed_input_matches_url_site(self):
        self.assertEqual(pick_site(self.SITES, "sc-domain:example.com"), "https://example.com/")

    def test_sc_domain_prefixed_www_variant(self):
        self.assertEqual(pick_site(self.SITES, "sc-domain:foo.com"), "https://www.foo.com/")

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



class TestPeriodRanges(unittest.TestCase):
    def test_current_window_ends_three_days_ago(self):
        """GSC 最近几天数据不全，当前期必须截止 3 天前。"""
        from datetime import date
        cur_start, cur_end, base_start, base_end = gsc.period_ranges(28, today=date(2026, 10, 3))
        self.assertEqual(cur_end, date(2026, 9, 30))
        self.assertEqual(cur_start, date(2026, 9, 3))

    def test_baseline_is_adjacent_equal_length(self):
        from datetime import date
        cur_start, cur_end, base_start, base_end = gsc.period_ranges(28, today=date(2026, 10, 3))
        # 基线期紧邻当前期之前，长度相同
        self.assertEqual(base_end, date(2026, 9, 2))
        self.assertEqual(base_start, date(2026, 8, 6))
        self.assertEqual((cur_end - cur_start).days, (base_end - base_start).days)
        self.assertEqual((cur_start - base_end).days, 1)

    def test_returns_dates(self):
        import datetime
        out = gsc.period_ranges(7)
        self.assertEqual(len(out), 4)
        for d in out:
            self.assertIsInstance(d, datetime.date)


class TestDiffRows(unittest.TestCase):
    def setUp(self):
        self.cur = [
            {"keys": ["/a/"], "clicks": 20, "impressions": 200, "ctr": 0.1, "position": 4.0},
            {"keys": ["/b/"], "clicks": 5, "impressions": 50, "ctr": 0.1, "position": 9.0},
        ]
        self.base = [
            {"keys": ["/a/"], "clicks": 10, "impressions": 150, "ctr": 0.066, "position": 6.0},
            {"keys": ["/b/"], "clicks": 8, "impressions": 80, "ctr": 0.1, "position": 7.0},
        ]

    def test_deltas_computed(self):
        rows = gsc.diff_rows(self.cur, self.base)
        by = {r["key"]: r for r in rows}
        self.assertEqual(by["/a/"]["d_clicks"], 10)
        self.assertEqual(by["/a/"]["d_impressions"], 50)
        self.assertAlmostEqual(by["/a/"]["d_position"], -2.0)

    def test_sorted_by_click_delta_desc(self):
        rows = gsc.diff_rows(self.cur, self.base)
        self.assertEqual([r["key"] for r in rows], ["/a/", "/b/"])

    def test_new_page_only_in_current(self):
        rows = gsc.diff_rows(self.cur, [])
        by = {r["key"]: r for r in rows}
        self.assertEqual(by["/a/"]["d_clicks"], 20)
        self.assertIsNone(by["/a/"]["base"])

    def test_disappeared_page_only_in_baseline(self):
        rows = gsc.diff_rows([], self.base)
        by = {r["key"]: r for r in rows}
        self.assertEqual(by["/a/"]["d_clicks"], -10)
        self.assertIsNone(by["/a/"]["cur"])

    def test_keeps_both_periods_metrics(self):
        rows = gsc.diff_rows(self.cur, self.base)
        by = {r["key"]: r for r in rows}
        self.assertEqual(by["/a/"]["cur"]["clicks"], 20)
        self.assertEqual(by["/a/"]["base"]["clicks"], 10)


class TestFindCannibalization(unittest.TestCase):
    def test_single_page_excluded(self):
        rows = [{"keys": ["kw1", "/a/"], "clicks": 10, "impressions": 100, "position": 3.0}]
        self.assertEqual(gsc.find_cannibalization(rows), [])

    def test_two_pages_included(self):
        rows = [
            {"keys": ["kw1", "/a/"], "clicks": 10, "impressions": 100, "position": 3.0},
            {"keys": ["kw1", "/b/"], "clicks": 4, "impressions": 60, "position": 8.0},
        ]
        out = gsc.find_cannibalization(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["query"], "kw1")
        self.assertEqual(len(out[0]["pages"]), 2)

    def test_min_impressions_threshold(self):
        rows = [
            {"keys": ["kw1", "/a/"], "clicks": 10, "impressions": 100, "position": 3.0},
            {"keys": ["kw1", "/b/"], "clicks": 0, "impressions": 5, "position": 40.0},
        ]
        self.assertEqual(gsc.find_cannibalization(rows, min_impressions=10), [])
        self.assertEqual(len(gsc.find_cannibalization(rows, min_impressions=1)), 1)

    def test_leading_page_is_most_clicks(self):
        rows = [
            {"keys": ["kw1", "/a/"], "clicks": 2, "impressions": 100, "position": 3.0},
            {"keys": ["kw1", "/b/"], "clicks": 15, "impressions": 60, "position": 8.0},
        ]
        out = gsc.find_cannibalization(rows)
        # leading 与 pages[].page 同为规范化身份（去尾斜杠）
        self.assertEqual(out[0]["leading"], "/b")

    def test_trailing_slash_variants_are_same_page(self):
        """尾斜杠变体是同一页（规范化问题），不得报成关键词竞争。"""
        rows = [
            {"keys": ["kw1", "/a/18077"], "clicks": 5, "impressions": 50, "position": 5.0},
            {"keys": ["kw1", "/a/18077/"], "clicks": 3, "impressions": 30, "position": 6.0},
        ]
        self.assertEqual(gsc.find_cannibalization(rows), [])

    def test_variants_merged_into_one_page_entry(self):
        rows = [
            {"keys": ["kw1", "/a/18077"], "clicks": 5, "impressions": 50, "position": 5.0},
            {"keys": ["kw1", "/a/18077/"], "clicks": 3, "impressions": 30, "position": 6.0},
            {"keys": ["kw1", "/b/"], "clicks": 2, "impressions": 40, "position": 9.0},
        ]
        out = gsc.find_cannibalization(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["pages"]), 2)          # 两个不同页，不是三个
        merged = [p for p in out[0]["pages"] if p["page"] == "/a/18077"][0]
        self.assertEqual(len(merged["variants"]), 2)        # 变体要看得见
        self.assertEqual(merged["impressions"], 80)         # 合计

    def test_language_variant_is_distinct_page(self):
        """/zh-tw/ 前缀是另一篇内容，属真竞争，不能被合并。"""
        rows = [
            {"keys": ["kw1", "/p03/a/673/11539/"], "clicks": 1, "impressions": 50, "position": 5.0},
            {"keys": ["kw1", "/zh-tw/p03/a/673/48223/"], "clicks": 1, "impressions": 60, "position": 6.0},
        ]
        out = gsc.find_cannibalization(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["pages"]), 2)

    def test_page_entry_shape(self):
        rows = [
            {"keys": ["kw1", "/a/"], "clicks": 1, "impressions": 50, "position": 5.0},
            {"keys": ["kw1", "/b/"], "clicks": 2, "impressions": 50, "position": 6.0},
        ]
        page = gsc.find_cannibalization(rows)[0]["pages"][0]
        for field in ("page", "variants", "clicks", "impressions", "position"):
            self.assertIn(field, page)


    def test_groups_multiple_queries_separately(self):
        rows = [
            {"keys": ["kw1", "/a/"], "clicks": 1, "impressions": 50, "position": 3.0},
            {"keys": ["kw1", "/b/"], "clicks": 1, "impressions": 50, "position": 8.0},
            {"keys": ["kw2", "/c/"], "clicks": 9, "impressions": 50, "position": 1.0},
        ]
        out = gsc.find_cannibalization(rows)
        self.assertEqual([o["query"] for o in out], ["kw1"])


class TestChooseSite(unittest.TestCase):
    """不带 --site 时应从 sites.json 取默认站点，否则每日命令只列站点拿不到报告。"""

    SITES = ["sc-domain:example.org", "https://example.com/"]

    def test_cli_wins(self):
        self.assertEqual(gsc.choose_site(self.SITES, "example.com"), "https://example.com/")

    def test_falls_back_to_sites_json(self):
        path = write_conf({"gsc_site": "example.org"})
        try:
            self.assertEqual(gsc.choose_site(self.SITES, None, conf_path=path),
                             "sc-domain:example.org")
        finally:
            os.unlink(path)

    def test_cli_beats_conf(self):
        path = write_conf({"gsc_site": "example.org"})
        try:
            self.assertEqual(gsc.choose_site(self.SITES, "example.com", conf_path=path),
                             "https://example.com/")
        finally:
            os.unlink(path)

    def test_none_when_neither_given(self):
        self.assertIsNone(gsc.choose_site(self.SITES, None, conf_path="/nonexistent/x.json"))

    def test_conf_value_may_carry_sc_domain_prefix(self):
        """sites.json 里的取值若带 sc-domain: 前缀也要能用。"""
        path = write_conf({"gsc_site": "sc-domain:example.org"})
        try:
            self.assertEqual(gsc.choose_site(self.SITES, None, conf_path=path),
                             "sc-domain:example.org")
        finally:
            os.unlink(path)



if __name__ == "__main__":
    unittest.main()
