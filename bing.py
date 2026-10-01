#!/usr/bin/env python3
"""Bing Webmaster 收录/表现复查 — API key 只读（共享版）。"""
import datetime as dt
import re

import requests

BASE = "https://ssl.bing.com/webmaster/api.svc/json/"
DEFAULT_KEY = "~/.config/seo-tools/bing-api-key.txt"
TIMEOUT = 30


def normalize_site(s):
    s = (s or "").strip().rstrip("/")
    s = re.sub(r"^https?://", "", s)
    return s.split("/", 1)[0]


def parse_msdate(s):
    m = re.search(r"/Date\((\d+)\)/", s or "")
    if not m:
        return s
    return dt.datetime.fromtimestamp(int(m.group(1)) / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


def call(key, method, params):
    # apikey 只能放 query string（Bing 官方鉴权，无 header 选项）。
    # 用 params= 让 requests 统一 URL 编码；异常消息已脱敏，不打印含 key 的 URL。
    try:
        r = requests.get(BASE + method, params={**params, "apikey": key}, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("d")
    except requests.HTTPError:
        raise RuntimeError(f"Bing API {method} HTTP {r.status_code}: {r.text[:200]}") from None
    except requests.RequestException as e:
        raise RuntimeError(f"Bing API {method} 网络错误: {type(e).__name__}") from None
