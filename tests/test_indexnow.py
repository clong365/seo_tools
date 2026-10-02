import unittest
from indexnow import make_payload, BATCH


class TestPayload(unittest.TestCase):
    def test_payload_shape(self):
        p = make_payload("www.xianmi.co", "a" * 32, ["https://www.xianmi.co/p01/"])
        self.assertEqual(p["host"], "www.xianmi.co")
        self.assertEqual(p["key"], "a" * 32)
        self.assertEqual(p["keyLocation"], f"https://www.xianmi.co/{'a' * 32}.txt")
        self.assertEqual(p["urlList"], ["https://www.xianmi.co/p01/"])

    def test_batch_constant(self):
        self.assertEqual(BATCH, 10000)  # IndexNow 协议上限，勿改


if __name__ == "__main__":
    unittest.main()
