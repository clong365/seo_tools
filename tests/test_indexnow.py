import unittest
from unittest import mock

import requests

from indexnow import make_payload, push, summarize, exit_code, BATCH


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
    def test_http_non_2xx_recorded_as_failure_but_does_not_abort(self, post):
        """HTTP 非 2xx：不中断，但必须记为失败。

        ⚠️ 分清两种失败路径，别以为「500 已被保护」：
          - **HTTP 非 2xx**：requests.post 正常返回。旧实现**根本不看 status code**
            （只打印），所以 500 从来不会中断循环——这条断言原本就成立，不是本次的防护点。
          - **requests.post 抛异常**（网络错误）：旧实现**会直接中断循环**，
            才是本次要防的路径，见 test_request_exception_*。
        """
        post.return_value = self._resp(500)
        n = BATCH + 1                           # 2 批
        urls = [f"https://www.example.com/p{i}/" for i in range(n)]
        results = push("www.example.com", "a" * 32, urls, dry_run=False)
        self.assertEqual(post.call_count, 2)                    # 不吞后续批次
        self.assertEqual([r["ok"] for r in results], [False, False])
        self.assertIn("500", results[0]["detail"])

    @mock.patch("indexnow.requests.post")
    def test_request_exception_does_not_abort(self, post):
        """网络异常不得吞掉后续批次——这才是本次事故的同款形态。"""
        post.side_effect = [ConnectionError("boom"),
                            self._resp(200), self._resp(200)]
        n = BATCH * 2 + 1                       # 3 批
        urls = [f"https://www.example.com/p{i}/" for i in range(n)]
        results = push("www.example.com", "a" * 32, urls, dry_run=False)
        self.assertEqual(post.call_count, 3)                    # 3 批都尝试了
        self.assertEqual(len(results), 3)
        self.assertFalse(results[0]["ok"])
        self.assertIn("ConnectionError", results[0]["detail"])  # 记异常类型
        self.assertTrue(results[1]["ok"])
        self.assertTrue(results[2]["ok"])

    @mock.patch("indexnow.requests.post")
    def test_each_batch_records_result(self, post):
        post.side_effect = [self._resp(200), self._resp(503)]
        n = BATCH + 1
        urls = [f"https://www.example.com/p{i}/" for i in range(n)]
        results = push("www.example.com", "a" * 32, urls, dry_run=False)
        self.assertEqual([r["batch"] for r in results], [1, 2])
        self.assertEqual([r["ok"] for r in results], [True, False])
        self.assertEqual(results[0]["detail"], "HTTP 200")
        self.assertIn("503", results[1]["detail"])

    @mock.patch("indexnow.requests.post")
    def test_dry_run_returns_no_results(self, post):
        urls = [f"https://www.example.com/p{i}/" for i in range(BATCH + 5)]
        self.assertEqual(push("www.example.com", "a" * 32, urls, dry_run=True), [])


class TestSummaryAndExit(unittest.TestCase):
    """汇总与退出码：绝不允许「安静地少发」。"""

    def test_summary_reports_totals_and_failure_detail(self):
        results = [
            {"batch": 1, "ok": True, "detail": "HTTP 200"},
            {"batch": 2, "ok": False, "detail": "ConnectionError: boom"},
            {"batch": 3, "ok": False, "detail": "HTTP 503"},
        ]
        text = summarize(results)
        self.assertIn("3", text)                 # 总批数
        self.assertIn("1", text)                 # 成功数
        self.assertIn("2", text)                 # 失败数
        self.assertIn("批次 2", text)            # 失败批次号
        self.assertIn("ConnectionError", text)   # 失败原因

    def test_summary_all_ok(self):
        results = [{"batch": 1, "ok": True, "detail": "HTTP 200"}]
        text = summarize(results)
        self.assertIn("成功", text)
        self.assertNotIn("失败批次", text)

    def test_exit_zero_when_all_ok(self):
        self.assertEqual(exit_code([{"batch": 1, "ok": True, "detail": "HTTP 200"}]), 0)

    def test_exit_nonzero_when_any_failure(self):
        """任一批失败必须非零退出——否则 CI/cron 会当成成功。"""
        self.assertEqual(exit_code([
            {"batch": 1, "ok": True, "detail": "HTTP 200"},
            {"batch": 2, "ok": False, "detail": "HTTP 503"},
        ]), 1)

    def test_exit_zero_for_empty(self):
        self.assertEqual(exit_code([]), 0)       # dry-run 不该被算作失败



if __name__ == "__main__":
    unittest.main()
