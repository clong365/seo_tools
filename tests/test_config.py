import os
import tempfile
import unittest

from config import load_sites, resolve, require


def write_conf(obj):
    """写一份 sites.json 到临时文件，返回路径。"""
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as f:
        import json
        json.dump(obj, f)
    return path


class TestLoadSites(unittest.TestCase):
    def test_missing_file_returns_empty(self):
        self.assertEqual(load_sites("/nonexistent/sites.json"), {})

    def test_reads_dict(self):
        path = write_conf({"ga_property": "12345"})
        try:
            self.assertEqual(load_sites(path), {"ga_property": "12345"})
        finally:
            os.unlink(path)

    def test_non_dict_json_returns_empty(self):
        fd, path = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write('["not", "a", "dict"]')
        try:
            self.assertEqual(load_sites(path), {})
        finally:
            os.unlink(path)


class TestResolve(unittest.TestCase):
    def setUp(self):
        self._saved = {}
        for var in ("CF_ACCOUNT", "GA_PROPERTY", "TEST_ONLY"):
            self._saved[var] = os.environ.pop(var, None)

    def tearDown(self):
        for var, val in self._saved.items():
            if val is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = val

    def test_cli_value_wins(self):
        path = write_conf({"ga_property": "from-conf"})
        os.environ["GA_PROPERTY"] = "from-env"
        try:
            self.assertEqual(
                resolve("ga_property", "GA_PROPERTY", "from-flag", conf_path=path),
                "from-flag")
        finally:
            os.unlink(path)

    def test_env_beats_conf(self):
        path = write_conf({"ga_property": "from-conf"})
        os.environ["GA_PROPERTY"] = "from-env"
        try:
            self.assertEqual(
                resolve("ga_property", "GA_PROPERTY", None, conf_path=path),
                "from-env")
        finally:
            os.unlink(path)

    def test_falls_back_to_conf(self):
        path = write_conf({"ga_property": "from-conf"})
        try:
            self.assertEqual(
                resolve("ga_property", "GA_PROPERTY", None, conf_path=path),
                "from-conf")
        finally:
            os.unlink(path)

    def test_returns_none_when_absent(self):
        self.assertIsNone(resolve("ga_property", "TEST_ONLY", None, conf_path="/nonexistent/x.json"))

    def test_none_cli_value_means_not_given(self):
        """flag 默认是 None（未传），不能当成'传了空值'去覆盖 env/conf。"""
        path = write_conf({"ga_property": "from-conf"})
        try:
            self.assertEqual(
                resolve("ga_property", "TEST_ONLY", None, conf_path=path),
                "from-conf")
        finally:
            os.unlink(path)

    def test_empty_string_conf_value_treated_as_absent(self):
        path = write_conf({"ga_property": ""})
        self.assertIsNone(resolve("ga_property", "TEST_ONLY", None, conf_path=path))


class TestRequire(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.pop("TEST_ONLY", None)

    def tearDown(self):
        if self._saved is not None:
            os.environ["TEST_ONLY"] = self._saved

    def test_returns_value_when_present(self):
        os.environ["TEST_ONLY"] = "v"
        self.assertEqual(require("ga_property", "TEST_ONLY", None, conf_path="/nonexistent/x.json"), "v")

    def test_exits_with_helpful_message(self):
        with self.assertRaises(SystemExit) as ctx:
            require("ga_property", "GA_PROPERTY", None, conf_path="/nonexistent/x.json")
        msg = str(ctx.exception)
        self.assertIn("GA_PROPERTY", msg)          # 要告诉用户设哪个环境变量
        self.assertIn("sites.json", msg)           # 要告诉用户另一个办法
        self.assertIn("ga_property", msg)          # 要说出配置键名


if __name__ == "__main__":
    unittest.main()
