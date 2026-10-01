#!/usr/bin/env python3
"""Bing Webmaster 收录/表现复查 — API key 只读（共享版）。

用法:
    .venv/bin/python bing.py --site tradelink-exp.com
"""
import argparse
import datetime as dt
import os
import re
import sys

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


def site_roles(key, site):
    print("=== 站点角色 ===")
    try:
        d = call(key, "GetSiteRoles", {"siteUrl": site})
        if not d:
            print("  (无记录，站点可能未在 Bing 验证)")
            return
        for r in d:
            print(f"  site={r.get('Site')} role={r.get('Role')} email={r.get('Email')} "
                  f"delegator={r.get('DelegatorEmail')}")
    except Exception as ex:
        print(f"  失败: {ex}")


def quota(key, site):
    print("\n=== URL 提交配额 ===")
    try:
        d = call(key, "GetUrlSubmissionQuota", {"siteUrl": site})
        if d:
            print(f"  每日 {d.get('DailyQuota')} | 每月 {d.get('MonthlyQuota')}")
    except Exception as ex:
        print(f"  失败: {ex}")


def rank_traffic(key, site, days):
    print(f"\n=== Rank & Traffic（近 {days} 天）===")
    try:
        d = call(key, "GetRankAndTrafficStats", {"siteUrl": site})
        if not d:
            print("  (无数据)")
            return
        rows = [(parse_msdate(x.get("Date")), x.get("Impressions", 0), x.get("Clicks", 0)) for x in d]
        rows = rows[-days:]
        imp = sum(r[1] for r in rows)
        clk = sum(r[2] for r in rows)
        print(f"  合计：印象 {imp} | 点击 {clk}")
        for date, i, c in rows:
            bar = "█" * min(int(i), 40) if i else ""
            print(f"  {date}  {i:>5} imp  {c:>3} clk  {bar}")
    except Exception as ex:
        print(f"  失败: {ex}")


def keyword_stats(key, site):
    print("\n=== 关键词表现（Top 查询）===")
    try:
        d = call(key, "GetKeywordStats", {"siteUrl": site, "q": "", "country": "", "language": ""})
        if not d:
            print("  (暂无关键词数据，属早期正常)")
            return
        for row in d[:20]:
            q = row.get("Query", "?")
            i = row.get("Impressions", 0)
            c = row.get("Clicks", 0)
            p = row.get("AveragePosition", row.get("Position", 0))
            print(f"  {i:>5} imp | {c:>3} clk | pos {p:>5} | {q}")
    except Exception as ex:
        print(f"  失败: {ex}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("BING_API_KEY", DEFAULT_KEY))
    ap.add_argument("--site", required=True, help="裸域名，如 tradelink-exp.com")
    ap.add_argument("--days", type=int, default=28)
    args = ap.parse_args()

    key_path = os.path.expanduser(args.key)
    if not os.path.exists(key_path):
        sys.exit(f"找不到 key 文件: {key_path}\n"
                 f"先到 Bing Webmaster → Settings → API Access 生成 API key，"
                 f"放 ~/.config/seo-tools/bing-api-key.txt。")

    key = open(key_path).read().strip()
    site = "https://" + normalize_site(args.site) + "/"
    print(f"=== site: {site} ===")

    site_roles(key, site)
    quota(key, site)
    rank_traffic(key, site, args.days)
    keyword_stats(key, site)


if __name__ == "__main__":
    main()
