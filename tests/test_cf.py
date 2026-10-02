import unittest
from cf import extract_rows, build_query, build_edge_query, extract_edge_rows


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

    def test_extract(self):
        resp = {"data": {"viewer": {"zones": [{"httpRequestsAdaptiveGroups": [
            {"count": 5, "dimensions": {"date": "2026-10-01", "edgeResponseStatus": 404}},
            {"count": 9, "dimensions": {"date": "2026-10-01", "edgeResponseStatus": 301}},
        ]}]}}}
        self.assertEqual(extract_edge_rows(resp), {"2026-10-01": {404: 5, 301: 9}})

    def test_extract_empty(self):
        self.assertEqual(extract_edge_rows({"data": {"viewer": {"zones": []}}}), {})


if __name__ == "__main__":
    unittest.main()
