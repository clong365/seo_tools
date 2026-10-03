import unittest
from unittest import mock

import requests

from indexnow import make_payload, push, BATCH


class TestPayload(unittest.TestCase):
    def test_payload_shape(self):
        p = make_payload("www.example.com", "a" * 32, ["https://www.example.com/p01/"])
        self.assertEqual(p["host"], "www.example.com")
        self.assertEqual(p["key"], "a" * 32)
        self.assertEqual(p["keyLocation"], f"https://www.example.com/{'a' * 32}.txt")
        self.assertEqual(p["urlList"], ["https://www.example.com/p01/"])

    def test_batch_constant(self):
        self.assertEqual(BATCH, 10000)  # IndexNow 协议上限，勿改



class TestPush(unittest.TestCase):
    """覆盖 push() 的真实推送分支。

    这条分支 dry-run 走不到（dry_run 直接 continue），所以此前无任何测试覆盖，
    打字错（r.status 应为 r.status_code）就这样溜到线上：第 1 批 POST 已发出、
    打印时抛 AttributeError、循环中止，25 批只推了 1 批。
    """

    @staticmethod
    def _resp(code=200):
        """真的 requests.Response——它有 status_code、没有 status。

        刻意不用 mock.Mock()：Mock 对任意属性都返回 Mock，
        用 .status 还是 .status_code 测试都过，等于什么也没验。
        """
        r = requests.Response()
        r.status_code = code
        return r

    @mock.patch("indexnow.requests.post")
    def test_reports_status_code_from_response(self, post):
        post.return_value = self._resp(200)
        urls = [f"https://www.example.com/p{i}/" for i in range(3)]
        push("www.example.com", "a" * 32, urls, dry_run=False)   # 不该抛异常
        self.assertEqual(post.call_count, 1)

    @mock.patch("indexnow.requests.post")
    def test_all_batches_are_posted(self, post):
        """每一批都要发出去——中途抛异常导致只推 1/25 批，正是本次事故形态。"""
        post.return_value = self._resp(200)
        n = BATCH * 2 + 1                       # 3 批
        urls = [f"https://www.example.com/p{i}/" for i in range(n)]
        push("www.example.com", "a" * 32, urls, dry_run=False)
        self.assertEqual(post.call_count, 3)

    @mock.patch("indexnow.requests.post")
    def test_batch_payload_carried(self, post):
        post.return_value = self._resp(200)
        push("www.example.com", "a" * 32, ["https://www.example.com/p1/"], dry_run=False)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["urlList"], ["https://www.example.com/p1/"])
        self.assertEqual(payload["host"], "www.example.com")

    @mock.patch("indexnow.requests.post")
    def test_dry_run_never_posts(self, post):
        urls = [f"https://www.example.com/p{i}/" for i in range(BATCH + 5)]
        push("www.example.com", "a" * 32, urls, dry_run=True)
        post.assert_not_called()

    @mock.patch("indexnow.requests.post")
    def test_non_200_still_reports_and_continues(self, post):
        post.return_value = self._resp(500)
        n = BATCH + 1                           # 2 批
        urls = [f"https://www.example.com/p{i}/" for i in range(n)]
        push("www.example.com", "a" * 32, urls, dry_run=False)
        self.assertEqual(post.call_count, 2)    # 单批失败不吞掉后续批次



if __name__ == "__main__":
    unittest.main()
