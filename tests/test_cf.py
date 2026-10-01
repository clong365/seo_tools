import unittest
from cf import extract_rows, build_query


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


if __name__ == "__main__":
    unittest.main()
