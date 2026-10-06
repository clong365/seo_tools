import json
import unittest
from unittest import mock

import requests

from baidu import push, summarize, BATCH


def _resp(body, code=200):
    """真的 requests.Response——Mock 对任意属性都返回 Mock，等于没验。"""
    r = requests.Response()
    r.status_code = code
    r._content = json.dumps(body).encode("utf-8")
    return r


SITE = "https://www.example.com"
TOKEN = "t" * 32


class TestBatchConstant(unittest.TestCase):
    def test_batch_constant(self):
        self.assertEqual(BATCH, 2000)  # 百度单次 POST 上限（官方文档口径），勿改


class TestPush(unittest.TestCase):
    @mock.patch("baidu.SESSION.post")
    def test_all_batches_are_posted(self, post):
        post.return_value = _resp({"success": BATCH, "remain": 99999})
        urls = [f"{SITE}/p{i}/" for i in range(BATCH * 2 + 1)]  # 3 批
        push(SITE, TOKEN, urls, dry_run=False)
        self.assertEqual(post.call_count, 3)

    @mock.patch("baidu.SESSION.post")
    def test_payload_is_plaintext_lines(self, post):
        post.return_value = _resp({"success": 2, "remain": 10})
        push(SITE, TOKEN, [f"{SITE}/a/", f"{SITE}/b/"], dry_run=False)
        _, kwargs = post.call_args
        self.assertEqual(kwargs["data"], f"{SITE}/a/\n{SITE}/b/".encode("utf-8"))
        self.assertIn("token=" + TOKEN, post.call_args[0][0])

    @mock.patch("baidu.SESSION.post")
    def test_remain_zero_stops_early(self, post):
        """额度用尽（remain=0）后续批次不应再发。"""
        post.return_value = _resp({"success": 1, "remain": 0})
        urls = [f"{SITE}/p{i}/" for i in range(BATCH + 1)]  # 2 批
        results = push(SITE, TOKEN, urls, dry_run=False)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(len(results), 1)

    @mock.patch("baidu.SESSION.post")
    def test_error_body_is_failure_and_config_errors_stop(self, post):
        post.return_value = _resp({"error": "not_same_site", "message": "site mismatch"})
        urls = [f"{SITE}/p{i}/" for i in range(BATCH + 1)]  # 2 批
        results = push(SITE, TOKEN, urls, dry_run=False)
        self.assertEqual(post.call_count, 1)  # 配置类错误不再继续
        self.assertFalse(results[0]["ok"])

    @mock.patch("baidu.SESSION.post")
    def test_network_exception_continues(self, post):
        post.side_effect = [requests.ConnectionError("boom"), _resp({"success": 1, "remain": 5})]
        urls = [f"{SITE}/p{i}/" for i in range(BATCH + 1)]  # 2 批
        results = push(SITE, TOKEN, urls, dry_run=False)
        self.assertEqual(post.call_count, 2)
        self.assertFalse(results[0]["ok"])
        self.assertTrue(results[1]["ok"])

    def test_summarize_reports_remain(self):
        results = [{"batch": 1, "ok": True, "detail": "success=10", "remain": 90}]
        self.assertIn("90", summarize(results))


if __name__ == "__main__":
    unittest.main()
