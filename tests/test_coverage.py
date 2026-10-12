import csv
import io
import os
import sqlite3
import tempfile
import unittest
import zipfile

import coverage


CRITICAL_CSV = """Reason,Source,Validation,Pages
Page with redirect,Website,Not Started,54635
Not found (404),Website,Not Started,1191
"""

TABLE_CSV = """URL,Last crawled
https://example.com/a/,2026-10-11
https://example.com/b/,2026-10-10
"""

METADATA_CSV = """Property,Value
Sitemap,All known pages
Issue,Page with redirect
"""


def make_export_dir(root, table_csv=TABLE_CSV, issue="Page with redirect",
                    drilldown="page-with-redirect"):
    """在 root 下造一个最小 GSC Coverage 导出目录，返回路径。"""
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "Critical issues.csv"), "w") as f:
        f.write(CRITICAL_CSV)
    with open(os.path.join(root, "Non-critical issues.csv"), "w") as f:
        f.write("Reason,Source,Validation,Pages\n")
    d = os.path.join(root, drilldown)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "Table.csv"), "w") as f:
        f.write(table_csv)
    with open(os.path.join(d, "Metadata.csv"), "w") as f:
        f.write(METADATA_CSV.replace("Page with redirect", issue))
    return root


class TestParse(unittest.TestCase):
    def test_parse_issues_csv(self):
        rows = coverage.parse_issues_csv(CRITICAL_CSV)
        self.assertEqual(rows, [
            {"reason": "Page with redirect", "source": "Website",
             "validation": "Not Started", "pages": 54635},
            {"reason": "Not found (404)", "source": "Website",
             "validation": "Not Started", "pages": 1191},
        ])

    def test_parse_issues_csv_tolerates_thousands_separator_and_bom(self):
        rows = coverage.parse_issues_csv(
            "﻿Reason,Source,Validation,Pages\nPage with redirect,Website,Started,\"54,635\"\n")
        self.assertEqual(rows[0]["pages"], 54635)

    def test_parse_metadata_csv(self):
        self.assertEqual(coverage.parse_metadata_csv(METADATA_CSV).get("Issue"),
                         "Page with redirect")

    def test_parse_table_csv(self):
        self.assertEqual(coverage.parse_table_csv(TABLE_CSV), [
            ("https://example.com/a/", "2026-10-11"),
            ("https://example.com/b/", "2026-10-10"),
        ])

    def test_parse_table_csv_without_last_crawled_column(self):
        self.assertEqual(coverage.parse_table_csv("URL\nhttps://example.com/a/\n"),
                         [("https://example.com/a/", "")])


class TestImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "s.db")

    def tearDown(self):
        self.tmp.cleanup()

    def _import(self, path, date="2026-10-12"):
        conn = coverage.open_db(self.db)
        try:
            return coverage.import_export(conn, path, date)
        finally:
            conn.close()

    def test_import_dir_stores_summary_and_urls(self):
        src = make_export_dir(os.path.join(self.tmp.name, "export"))
        counts = self._import(src)
        self.assertEqual(counts["buckets_with_urls"], 1)
        conn = sqlite3.connect(self.db)
        summary = list(conn.execute(
            "SELECT bucket, pages FROM coverage_summary WHERE date='2026-10-12' ORDER BY bucket"))
        urls = list(conn.execute(
            "SELECT bucket, url, last_crawled FROM coverage_urls ORDER BY url"))
        conn.close()
        self.assertEqual(summary, [("Not found (404)", 1191), ("Page with redirect", 54635)])
        self.assertEqual(urls, [
            ("Page with redirect", "https://example.com/a/", "2026-10-11"),
            ("Page with redirect", "https://example.com/b/", "2026-10-10"),
        ])

    def test_import_same_date_replaces(self):
        src = make_export_dir(os.path.join(self.tmp.name, "export"))
        self._import(src)
        # 改一条 URL 后重导同日：旧数据应被整个换掉，不是叠加
        make_export_dir(src, table_csv="URL,Last crawled\nhttps://example.com/c/,\n")
        self._import(src)
        conn = sqlite3.connect(self.db)
        urls = [r[0] for r in conn.execute("SELECT url FROM coverage_urls")]
        conn.close()
        self.assertEqual(urls, ["https://example.com/c/"])

    def test_import_zip(self):
        src = make_export_dir(os.path.join(self.tmp.name, "export"))
        zpath = os.path.join(self.tmp.name, "export.zip")
        with zipfile.ZipFile(zpath, "w") as z:
            for base, _, files in os.walk(src):
                for name in files:
                    p = os.path.join(base, name)
                    z.write(p, os.path.relpath(p, src))
        counts = self._import(zpath)
        self.assertEqual(counts["urls"], 2)

    def test_import_rejects_path_without_exports(self):
        empty = os.path.join(self.tmp.name, "empty")
        os.makedirs(empty)
        with self.assertRaises(SystemExit):
            self._import(empty)

    def test_bucket_falls_back_to_dir_name_without_metadata(self):
        src = os.path.join(self.tmp.name, "export")
        make_export_dir(src)
        os.remove(os.path.join(src, "page-with-redirect", "Metadata.csv"))
        self._import(src)
        conn = sqlite3.connect(self.db)
        buckets = [r[0] for r in conn.execute("SELECT DISTINCT bucket FROM coverage_urls")]
        conn.close()
        self.assertEqual(buckets, ["page-with-redirect"])


class TestDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "s.db")
        conn = coverage.open_db(self.db)
        rows = [
            # (date, bucket, url)
            ("2026-10-07", "404", "https://example.com/gone/"),      # B 消失
            ("2026-10-07", "404", "https://example.com/stay/"),      # 两期同桶
            ("2026-10-07", "redirect", "https://example.com/move/"), # 迁到 404
            ("2026-10-12", "404", "https://example.com/stay/"),
            ("2026-10-12", "404", "https://example.com/move/"),
            ("2026-10-12", "404", "https://example.com/new/"),       # B 新增
        ]
        conn.executemany(
            "INSERT INTO coverage_urls (date, bucket, url) VALUES (?, ?, ?)", rows)
        conn.executemany(
            "INSERT INTO coverage_summary (date, bucket, severity, pages) VALUES (?, ?, ?, ?)",
            [("2026-10-07", "404", "critical", 100),
             ("2026-10-12", "404", "critical", 120)])
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def _diff(self, a="2026-10-07", b="2026-10-12", bucket=None):
        conn = sqlite3.connect(self.db)
        try:
            return coverage.diff_snapshots(conn, a, b, bucket=bucket)
        finally:
            conn.close()

    def test_added_removed_migrated(self):
        d = self._diff()
        self.assertEqual(d["added"], {"404": ["https://example.com/new/"]})
        self.assertEqual(d["removed"], {"404": ["https://example.com/gone/"]})
        self.assertEqual(d["migrated"],
                         [("https://example.com/move/", "redirect", "404")])

    def test_summary_change(self):
        d = self._diff()
        self.assertEqual(d["summary"].get("404"), (100, 120))

    def test_bucket_filter(self):
        d = self._diff(bucket="redirect")
        self.assertEqual(d["added"], {})
        self.assertEqual(d["removed"], {"redirect": ["https://example.com/move/"]})
        self.assertEqual(d["migrated"], [])

    def test_missing_date_rejected(self):
        with self.assertRaises(SystemExit):
            self._diff(a="2026-01-01")

    def test_same_date_is_zero_diff(self):
        d = self._diff(a="2026-10-12", b="2026-10-12")
        self.assertEqual(d["added"], {})
        self.assertEqual(d["removed"], {})
        self.assertEqual(d["migrated"], [])


class TestBucketsListing(unittest.TestCase):
    def test_list_dates(self):
        tmp = tempfile.TemporaryDirectory()
        db = os.path.join(tmp.name, "s.db")
        conn = coverage.open_db(db)
        conn.execute("INSERT INTO coverage_urls (date, bucket, url) VALUES ('2026-10-12', '404', 'u1')")
        conn.execute("INSERT INTO coverage_summary (date, bucket, severity, pages)"
                     " VALUES ('2026-10-12', '404', 'critical', 9)")
        conn.commit()
        dates = coverage.list_dates(conn)
        conn.close()
        tmp.cleanup()
        self.assertEqual(dates, [("2026-10-12", 1, 1)])


if __name__ == "__main__":
    unittest.main()
