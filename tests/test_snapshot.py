import datetime as dt
import os
import sqlite3
import tempfile
import unittest

import snapshot


class TestSchema(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "sub", "snapshots.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_db_creates_parent_dir_and_is_idempotent(self):
        conn = snapshot.open_db(self.db)
        conn.close()
        conn = snapshot.open_db(self.db)  # 第二次不应报错
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("ga4_daily", tables)
        self.assertIn("gsc_daily", tables)
        self.assertIn("cf_edge_daily", tables)
        self.assertIn("cf_md429_daily", tables)
        conn.close()


class TestGa4Body(unittest.TestCase):
    def test_tw_uses_pagepath_begins_with_filter(self):
        body = snapshot.build_ga4_body("2026-10-11", "tw")
        self.assertEqual(body["dateRanges"],
                         [{"startDate": "2026-10-11", "endDate": "2026-10-11"}])
        names = [m["name"] for m in body["metrics"]]
        self.assertIn("screenPageViews", names)
        self.assertIn("engagedSessions", names)
        f = body["dimensionFilter"]["filter"]
        self.assertEqual(f["fieldName"], "pagePath")
        self.assertEqual(f["stringFilter"]["matchType"], "BEGINS_WITH")
        self.assertEqual(f["stringFilter"]["value"], "/zh-tw/")

    def test_cn_is_negation_of_tw(self):
        body = snapshot.build_ga4_body("2026-10-11", "cn")
        inner = body["dimensionFilter"]["notExpression"]["filter"]
        self.assertEqual(inner["stringFilter"]["value"], "/zh-tw/")

    def test_unknown_section_rejected(self):
        with self.assertRaises(ValueError):
            snapshot.build_ga4_body("2026-10-11", "hk")


class TestGa4Values(unittest.TestCase):
    def test_extracts_ints_from_report_response(self):
        resp = {
            "dimensionHeaders": [],
            "metricHeaders": [{"name": n} for n in
                              ["screenPageViews", "engagedSessions", "sessions", "activeUsers"]],
            "rows": [{"dimensionValues": [],
                      "metricValues": [{"value": v} for v in ["120", "98", "110", "80"]]}],
        }
        self.assertEqual(snapshot.ga4_section_values(resp),
                         {"screenPageViews": 120, "engagedSessions": 98,
                          "sessions": 110, "activeUsers": 80})

    def test_empty_rows_gives_zeros(self):
        resp = {"dimensionHeaders": [], "metricHeaders": [], "rows": []}
        vals = snapshot.ga4_section_values(resp)
        self.assertEqual(vals["engagedSessions"], 0)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = snapshot.open_db(os.path.join(self.tmp.name, "s.db"))

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_store_gsc_upsert_overwrites_same_date(self):
        row = {"clicks": 3, "impressions": 100, "ctr": 0.03, "position": 12.5}
        snapshot.store_gsc(self.conn, "2026-10-11", "sc-domain:example.com", row)
        snapshot.store_gsc(self.conn, "2026-10-11", "sc-domain:example.com",
                           {"clicks": 5, "impressions": 120, "ctr": 0.04, "position": 11.0})
        rows = list(self.conn.execute(
            "SELECT clicks, impressions FROM gsc_daily WHERE date='2026-10-11'"))
        self.assertEqual(rows, [(5, 120)])

    def test_fetch_gsc_backfills_lagged_window(self):
        """GSC 数据滞后 2-3 天：fetch 要查 [date-3, date] 窗口并按行自带日期入库。"""
        from unittest import mock
        resp = {"rows": [
            {"keys": ["2026-10-09"], "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5},
            {"keys": ["2026-10-10"], "clicks": 2, "impressions": 20, "ctr": 0.1, "position": 6},
        ]}
        with mock.patch.object(snapshot.gsc, "query_analytics",
                               return_value=resp) as q:
            snapshot.fetch_gsc(self.conn, "2026-10-11", "tok", "site")
        self.assertEqual(q.call_args.args[2:4], ("2026-10-08", "2026-10-11"))
        dates = [r[0] for r in self.conn.execute(
            "SELECT date FROM gsc_daily ORDER BY date")]
        self.assertEqual(dates, ["2026-10-09", "2026-10-10"])

    def test_store_ga4_upsert_overwrites_same_date_section(self):
        vals = {"screenPageViews": 10, "engagedSessions": 8, "sessions": 9, "activeUsers": 7}
        snapshot.store_ga4(self.conn, "2026-10-11", "cn", vals)
        vals["engagedSessions"] = 9
        snapshot.store_ga4(self.conn, "2026-10-11", "cn", vals)
        rows = list(self.conn.execute(
            "SELECT engaged_sessions FROM ga4_daily WHERE date='2026-10-11' AND section='cn'"))
        self.assertEqual(rows, [(9,)])

    def test_store_cf_edge_upsert_per_status(self):
        snapshot.store_cf_edge(self.conn, "2026-10-11", {200: 1000, 404: 30})
        snapshot.store_cf_edge(self.conn, "2026-10-11", {200: 1200, 301: 50})
        rows = dict(self.conn.execute(
            "SELECT status, count FROM cf_edge_daily WHERE date='2026-10-11'"))
        self.assertEqual(rows, {200: 1200, 301: 50, 404: 30})

    def test_store_cf_md429_upsert_per_host(self):
        snapshot.store_cf_md429(self.conn, "2026-10-11", {"a.example.com": 3})
        snapshot.store_cf_md429(self.conn, "2026-10-11",
                                {"a.example.com": 5, "b.example.com": 2})
        rows = dict(self.conn.execute(
            "SELECT host, count FROM cf_md429_daily WHERE date='2026-10-11'"))
        self.assertEqual(rows, {"a.example.com": 5, "b.example.com": 2})


class TestRunSnapshot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "s.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_partial_failure_returns_failures_and_keeps_successes(self):
        def ok_gsc(conn, date):
            snapshot.store_gsc(conn, date, "example.com",
                               {"clicks": 1, "impressions": 2, "ctr": 0.5, "position": 3})

        def bad_ga4(conn, date):
            raise RuntimeError("boom")

        failures = snapshot.run_snapshot(
            "2026-10-11", self.db, {"gsc": ok_gsc, "ga4": bad_ga4})
        self.assertEqual([name for name, _ in failures], ["ga4"])
        conn = sqlite3.connect(self.db)
        rows = list(conn.execute("SELECT clicks FROM gsc_daily WHERE date='2026-10-11'"))
        conn.close()
        self.assertEqual(rows, [(1,)])

    def test_default_date_is_yesterday(self):
        self.assertEqual(snapshot.resolve_date(None),
                         (dt.date.today() - dt.timedelta(days=1)).isoformat())
        self.assertEqual(snapshot.resolve_date("2026-10-01"), "2026-10-01")
        with self.assertRaises(ValueError):
            snapshot.resolve_date("10/01")


if __name__ == "__main__":
    unittest.main()
