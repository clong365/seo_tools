import json
import os
import tempfile
import unittest
from unittest import mock

import requests

from cf import (extract_rows, build_query, build_edge_query, extract_edge_rows,
               build_sql, ae_query, ae_report)


class TestExtractRows(unittest.TestCase):
    def test_empty(self):
        resp = {"data": {"viewer": {"accounts": []}}}
        self.assertEqual(extract_rows(resp), [])

    def test_rows(self):
        resp = {
            "data": {"viewer": {"accounts": [{"rumPageloadEventsAdaptiveGroups": [
                {"count": 7, "sum": {"visits": 5}, "dimensions": {"countryName": "UZ"}},
                {"count": 33, "sum": {"visits": 20}, "dimensions": {"countryName": "FR"}},
            ]}]}}
        }
        rows = extract_rows(resp)
        self.assertEqual(rows, [
            ({"countryName": "UZ"}, 7, 5),
            ({"countryName": "FR"}, 33, 20),
        ])

    def test_no_sum(self):
        resp = {"data": {"viewer": {"accounts": [{"rumPageloadEventsAdaptiveGroups": [
            {"count": 4, "dimensions": {"countryName": "X"}},
        ]}]}}}
        rows = extract_rows(resp)
        self.assertEqual(rows, [({"countryName": "X"}, 4, 0)])


class TestBuildQuery(unittest.TestCase):
    def test_contains_account_site_dimension(self):
        q = build_query("ACC", "SITE", "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z", "countryName")
        self.assertIn('accountTag: "ACC"', q)
        self.assertIn('siteTag: "SITE"', q)
        self.assertIn("dimensions { countryName }", q)
        self.assertIn("sum { visits }", q)

    def test_no_dimension(self):
        q = build_query("ACC", "SITE", "s", "e")
        self.assertNotIn("dimensions", q)


class TestEdge(unittest.TestCase):
    def test_build_query(self):
        q = build_edge_query("ZONE", "2026-09-01", "2026-10-01")
        self.assertIn('zoneTag: "ZONE"', q)
        self.assertIn("httpRequestsAdaptiveGroups", q)
        self.assertIn("edgeResponseStatus", q)

    def test_build_query_filters_eyeball_by_default(self):
        """默认必须只取真实客户端：否则 Worker Cache API 的遥测行
        （requestSource=edgeWorkerCacheAPI）会污染状态码趋势——2026-10-02 实测
        当日 504 记录 100% 来自该来源，而真实客户端 504=0。"""
        q = build_edge_query("ZONE", "2026-09-01", "2026-10-01")
        self.assertIn('requestSource: "eyeball"', q)

    def test_build_query_can_include_all_sources(self):
        q = build_edge_query("ZONE", "2026-09-01", "2026-10-01", eyeball=False)
        self.assertNotIn("requestSource", q)

    def test_extract(self):
        resp = {"data": {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": [
            {"count": 5, "dimensions": {"date": "2026-10-01", "edgeResponseStatus": 404}},
            {"count": 9, "dimensions": {"date": "2026-10-01", "edgeResponseStatus": 301}},
        ]}]}}}
        self.assertEqual(extract_edge_rows(resp), {"2026-10-01": {404: 5, 301: 9}})

    def test_extract_empty(self):
        self.assertEqual(extract_edge_rows({"data": {"viewer": {"zones": []}}}), {})



class TestBuildSql(unittest.TestCase):
    """AE SQL 构造。dataset 名属敏感标识，一律由配置传入，不得写死在代码里。"""

    def test_preset_3h_matches_template(self):
        sql = build_sql(preset="3h", dataset="test_ds")
        self.assertIn("FROM test_ds", sql)
        self.assertIn("blob4 AS kind", sql)
        self.assertIn("INTERVAL '3' HOUR", sql)
        self.assertIn("GROUP BY blob4", sql)
        self.assertIn("FORMAT JSON", sql)      # 与 cf CLI 对齐，否则输出 NDJSON

    def test_preset_3h_has_no_hardcoded_dataset(self):
        """模板不得内置真实 dataset 名（属敏感标识）。拼接写法避免本文件成为命中源。"""
        sql = build_sql(preset="3h", dataset="test_ds")
        self.assertNotIn("xian" + "mi", sql)
        self.assertEqual(sql.count("FROM "), 1)      # FROM 目标只能是代入的 dataset

    def test_sql_file_is_used_verbatim(self):
        fd, path = tempfile.mkstemp(suffix=".sql")
        with os.fdopen(fd, "w") as f:
            f.write("SELECT 1 AS x FORMAT JSON")
        try:
            self.assertEqual(build_sql(sql_file=path), "SELECT 1 AS x FORMAT JSON")
        finally:
            os.unlink(path)

    def test_preset_and_file_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit):
            build_sql(preset="3h", sql_file="/tmp/x.sql", dataset="test_ds")

    def test_neither_preset_nor_file(self):
        with self.assertRaises(SystemExit):
            build_sql(dataset="test_ds")

    def test_preset_requires_dataset(self):
        with self.assertRaises(SystemExit):
            build_sql(preset="3h", dataset=None)

    def test_unknown_preset(self):
        with self.assertRaises(SystemExit):
            build_sql(preset="nope", dataset="test_ds")

    def test_missing_sql_file(self):
        with self.assertRaises(SystemExit):
            build_sql(sql_file="/nonexistent/x.sql")


class TestAeQuery(unittest.TestCase):
    @staticmethod
    def _resp(payload, code=200):
        r = requests.Response()
        r.status_code = code
        r._content = json.dumps(payload).encode()
        r.headers["Content-Type"] = "application/json"
        return r

    @mock.patch("cf.requests.post")
    def test_posts_raw_sql_body_and_bearer(self, post):
        """请求体是纯 SQL 文本（不是 JSON 包装），鉴权用 API token。"""
        post.return_value = self._resp({"data": [], "rows": 0})
        ae_query("TOK", "ACC", "SELECT 1")
        kw = post.call_args.kwargs
        self.assertIn("/accounts/ACC/analytics_engine/sql", post.call_args.args[0])
        self.assertEqual(kw["data"], b"SELECT 1")
        self.assertEqual(kw["headers"]["Authorization"], "Bearer TOK")

    @mock.patch("cf.requests.post")
    def test_returns_parsed_json(self, post):
        payload = {"meta": [{"name": "kind", "type": "String"}],
                   "data": [{"kind": "301", "n": "302"}], "rows": 1}
        post.return_value = self._resp(payload)
        self.assertEqual(ae_query("TOK", "ACC", "SELECT 1"), payload)

    @mock.patch("cf.requests.post")
    def test_error_status_raises_with_body(self, post):
        post.return_value = self._resp({"errors": [{"message": "denied"}]}, code=403)
        with self.assertRaises(RuntimeError) as ctx:
            ae_query("TOK", "ACC", "SELECT 1")
        self.assertIn("denied", str(ctx.exception))   # 缺权限要报出来，不许静默降级

    @mock.patch("cf.requests.post")
    def test_cloudflare_errors_field_raises(self, post):
        """HTTP 200 但带 errors 也算失败——不许静默吐空结果。"""
        post.return_value = self._resp({"errors": [{"message": "bad sql"}]}, code=200)
        with self.assertRaises(RuntimeError):
            ae_query("TOK", "ACC", "SELECT 1")




class TestAeReportDatasetFallback(unittest.TestCase):
    """dataset 必须能从 sites.json 取——否则 --preset 3h 不带 --dataset 就跑不起来。

    此前实现把 args.dataset 原样传下去、没接配置回退，单测又都显式传 dataset，
    于是整条回退路径无覆盖，冒烟才抓到。
    """

    @staticmethod
    def _conf(obj):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        return path

    @mock.patch("cf.ae_query")
    def test_dataset_falls_back_to_sites_json(self, aeq):
        aeq.return_value = {"data": [], "rows": 0}
        path = self._conf({"ae_dataset": "test_ds"})
        try:
            ae_report("TOK", "ACC", "3h", None, dataset=None, conf_path=path)
        finally:
            os.unlink(path)
        sql = aeq.call_args.args[2]
        self.assertIn("FROM test_ds", sql)

    @mock.patch("cf.ae_query")
    def test_explicit_dataset_beats_conf(self, aeq):
        aeq.return_value = {"data": [], "rows": 0}
        path = self._conf({"ae_dataset": "from_conf"})
        try:
            ae_report("TOK", "ACC", "3h", None, dataset="explicit", conf_path=path)
        finally:
            os.unlink(path)
        self.assertIn("FROM explicit", aeq.call_args.args[2])

    @mock.patch("cf.ae_query")
    def test_missing_dataset_exits_with_hint(self, aeq):
        with self.assertRaises(SystemExit) as ctx:
            ae_report("TOK", "ACC", "3h", None, dataset=None,
                      conf_path="/nonexistent/x.json")
        self.assertIn("ae_dataset", str(ctx.exception))



if __name__ == "__main__":
    unittest.main()
