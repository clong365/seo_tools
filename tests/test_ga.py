import unittest
from ga import format_rows


class TestFormatRows(unittest.TestCase):
    def test_empty(self):
        resp = {"dimensionHeaders": [], "metricHeaders": [], "rows": []}
        self.assertEqual(format_rows(resp), ([], [], []))

    def test_with_dimensions(self):
        resp = {
            "dimensionHeaders": [{"name": "country"}],
            "metricHeaders": [{"name": "activeUsers"}, {"name": "sessions"}],
            "rows": [
                {"dimensionValues": [{"value": "China"}], "metricValues": [{"value": "42071"}, {"value": "43436"}]},
                {"dimensionValues": [{"value": "US"}], "metricValues": [{"value": "9588"}, {"value": "9646"}]},
            ],
        }
        dims, metrics, rows = format_rows(resp)
        self.assertEqual(dims, ["country"])
        self.assertEqual(metrics, ["activeUsers", "sessions"])
        self.assertEqual(rows, [(("China",), ("42071", "43436")), (("US",), ("9588", "9646"))])

    def test_metrics_only(self):
        resp = {
            "dimensionHeaders": [],
            "metricHeaders": [{"name": "activeUsers"}],
            "rows": [{"dimensionValues": [], "metricValues": [{"value": "123"}]}],
        }
        dims, metrics, rows = format_rows(resp)
        self.assertEqual(dims, [])
        self.assertEqual(metrics, ["activeUsers"])
        self.assertEqual(rows, [((), ("123",))])


if __name__ == "__main__":
    unittest.main()
