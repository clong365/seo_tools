#!/usr/bin/env python3
"""Cloudflare Web Analytics 流量复查 — GraphQL（RUM）只读（共享版）。

用法:
    .venv/bin/python cf.py --site 406eb07464064ef680745db6a060efba
"""
import argparse
import datetime as dt
import os
import sys

import requests

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
DEFAULT_KEY = "~/.config/seo-tools/cf-api-token.txt"
DEFAULT_ACCOUNT = "397a5866d88bb11a4f17b710d74f30c8"
DEFAULT_SITE = "406eb07464064ef680745db6a060efba"  # xianmi.co
TIMEOUT = 30


def extract_rows(resp):
    """GraphQL 响应 → [(维度dict, count, visits), ...]。"""
    accounts = resp.get("data", {}).get("viewer", {}).get("accounts", [])
    if not accounts:
        return []
    groups = accounts[0].get("rumPageloadEventsAdaptiveGroups", [])
    rows = []
    for g in groups:
        dims = g.get("dimensions", {})
        count = g.get("count", 0)
        visits = (g.get("sum") or {}).get("visits", 0)
        rows.append((dims, count, visits))
    return rows


def build_query(account, site, start, end, dimension=None):
    """构造 RUM 查询；dimension 为 None 时只取汇总。"""
    dim = f"dimensions {{ {dimension} }}" if dimension else ""
    return f'''
{{
  viewer {{
    accounts(filter: {{accountTag: "{account}"}}) {{
      rumPageloadEventsAdaptiveGroups(
        limit: 5000
        filter: {{siteTag: "{site}", datetime_geq: "{start}", datetime_leq: "{end}"}}
      ) {{
        count
        sum {{ visits }}
        {dim}
      }}
    }}
  }}
}}
'''


def run_query(token, query):
    r = requests.post(GRAPHQL_URL,
                      headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                      json={"query": query}, timeout=TIMEOUT)
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(f"GraphQL 错误: {body['errors']}")
    return body


def date_range(days):
    end = dt.datetime.now(dt.timezone.utc)
    start = end - dt.timedelta(days=days)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")


def print_block(title, resp, dim):
    rows = extract_rows(resp)
    print(f"\n=== {title} ===")
    if not rows:
        print("  (无数据)")
        return
    for d, count, visits in rows:
        label = d.get(dim, "?") if dim else "total"
        print(f"  visits {visits:>7} | views {count:>7} | {label}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("CF_API_TOKEN", DEFAULT_KEY))
    ap.add_argument("--account", default=os.environ.get("CF_ACCOUNT", DEFAULT_ACCOUNT))
    ap.add_argument("--site", default=os.environ.get("CF_SITE", DEFAULT_SITE))
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    key_path = os.path.expanduser(args.key)
    if not os.path.exists(key_path):
        sys.exit(f"找不到 token 文件: {key_path}\n把 CF API token 放 ~/.config/seo-tools/cf-api-token.txt。")

    token = open(key_path).read().strip()
    start, end = date_range(args.days)
    print(f"=== CF Web Analytics（近 {args.days} 天，site {args.site}）===")

    try:
        resp = run_query(token, build_query(args.account, args.site, start, end))
        rows = extract_rows(resp)
        print_block("总览", resp, None)
        if rows:
            total_views = sum(r[1] for r in rows)
            total_visits = sum(r[2] for r in rows)
            print(f"  → 合计 views {total_views} / visits {total_visits}")
    except Exception as ex:
        print(f"  总览失败: {ex}")

    for dim, label in [("countryName", "按国家"), ("requestPath", "按页面"), ("deviceType", "按设备")]:
        try:
            resp = run_query(token, build_query(args.account, args.site, start, end, dim))
            print_block(label, resp, dim)
        except Exception as ex:
            print(f"  {label}失败: {ex}")


if __name__ == "__main__":
    main()
