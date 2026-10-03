"""守卫：源码里不得出现真实标识符。

标识符从 ~/.config/seo-tools/sites.json 读（在仓库外），测试本身不携带真实值；
项目名用拼接写法，避免测试文件自己成为命中源。
"""
import os
import unittest

from config import load_sites

SCAN_DIRS = ("." ,)
SKIP_DIRS = {".git", ".venv", "__pycache__", ".remember", ".superpowers"}
SCAN_EXT = (".py", ".md", ".json", ".txt", ".yml", ".yaml", ".toml")

# 项目名（拼接，避免本文件被 grep 命中）
PROJECT_NAMES = ["xian" + "mi", "trade" + "link"]
# 已知敏感子串
SENSITIVE_SUBSTRINGS = [
    "lyrical" + "-country",
    "googlesearch" + "console@",
]


def iter_source_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(SCAN_EXT):
                yield os.path.join(dirpath, name)


class TestNoSecretsInSource(unittest.TestCase):
    def test_no_project_names_in_repo(self):
        hits = []
        for path in iter_source_files("."):
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for name in PROJECT_NAMES:
                if name in text:
                    hits.append(f"{path}: 含项目名 {name}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_sensitive_substrings_in_repo(self):
        hits = []
        for path in iter_source_files("."):
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for s in SENSITIVE_SUBSTRINGS:
                if s in text:
                    hits.append(f"{path}: 含 {s}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_sites_json_values_in_repo(self):
        """把 sites.json 里的真实取值反查回仓库——这是最直接的泄漏检测。"""
        sites = load_sites()
        if not sites:
            self.skipTest("本机无 sites.json，跳过取值反查")
        values = [v for v in sites.values() if isinstance(v, str) and len(v) >= 4]
        hits = []
        for path in iter_source_files("."):
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for v in values:
                if v in text:
                    hits.append(f"{path}: 含 sites.json 取值")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_no_default_id_constants_in_scripts(self):
        """脚本不得再有写死的 DEFAULT_ACCOUNT / DEFAULT_SITE / DEFAULT_ZONE / DEFAULT_PROPERTY。"""
        for mod in ("cf.py", "ga.py", "crux.py", "psi.py"):
            with open(mod, encoding="utf-8") as fh:
                text = fh.read()
            for bad in ("DEFAULT_ACCOUNT", "DEFAULT_SITE", "DEFAULT_ZONE",
                        "DEFAULT_PROPERTY", "DEFAULT_ORIGIN", "DEFAULT_URL"):
                self.assertNotIn(bad, text, f"{mod} 仍含 {bad}")


if __name__ == "__main__":
    unittest.main()
