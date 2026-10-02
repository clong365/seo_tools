import unittest
from crux import build_body, classify, density_shares, METRICS


class TestBuildBody(unittest.TestCase):
    def test_origin_default_metrics(self):
        b = build_body(origin="https://www.xianmi.co")
        self.assertEqual(b["origin"], "https://www.xianmi.co")
        self.assertEqual(b["metrics"], list(METRICS))
        self.assertNotIn("url", b)

    def test_url_mode(self):
        b = build_body(url="https://www.xianmi.co/p02/", form_factor="PHONE")
        self.assertEqual(b["url"], "https://www.xianmi.co/p02/")
        self.assertEqual(b["formFactor"], "PHONE")
        self.assertNotIn("origin", b)


class TestClassify(unittest.TestCase):
    def test_lcp_bands(self):
        self.assertEqual(classify(2500, 2500, 4000), "好")
        self.assertEqual(classify(2501, 2500, 4000), "需改进")
        self.assertEqual(classify(4001, 2500, 4000), "差")

    def test_cls_bands(self):
        self.assertEqual(classify(0.1, 0.1, 0.25), "好")
        self.assertEqual(classify(0.2, 0.1, 0.25), "需改进")


class TestDensity(unittest.TestCase):
    def test_three_buckets(self):
        hist = [{"density": 0.9}, {"density": 0.05}, {"density": 0.05}]
        self.assertEqual(density_shares(hist), (0.9, 0.05, 0.05))

    def test_short_histogram_padded(self):
        self.assertEqual(density_shares([{"density": 1.0}]), (1.0, 0, 0))


if __name__ == "__main__":
    unittest.main()
