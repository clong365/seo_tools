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
DEFAULT_ZONE = "35ff812beaa004cd12cd62ff30383fe1"  # xianmi.co zone ID
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


def build_edge_query(zone, start_date, end_date):
    """zone 级边缘请求按 日期×状态码 统计（含不执行 JS 的爬虫，RUM 的补集口径）。"""
    return f'''
{{
  viewer {{
    zones(filter: {{zoneTag: "{zone}"}}) {{
      httpRequestsAdaptiveGroups(
        limit: 5000
        filter: {{date_geq: "{start_date}", date_leq: "{end_date}"}}
        orderBy: [date_ASC, edgeResponseStatus_ASC]
      ) {{
        count
        dimensions {{ date edgeResponseStatus }}
      }}
    }}
  }}
}}
'''


def extract_edge_rows(resp):
    """GraphQL 响应 → {date: {status: count}}。"""
    zones = resp.get("data", {}).get("viewer", {}).get("zones", [])
    out = {}
    if not zones:
        return out
    for g in zones[0].get("httpRequestsAdaptiveGroups", []):
        d = g.get("dimensions", {})
        out.setdefault(d.get("date", "?"), {})[d.get("edgeResponseStatus", 0)] = g.get("count", 0)
    return out


def print_edge(resp):
    by_date = extract_edge_rows(resp)
    print("\n=== 边缘请求按日（zone 级，含无 JS 爬虫）===")
    if not by_date:
        print("  (无数据)")
        return
    print(f"  {'日期':12}{'200':>10}{'301':>10}{'404':>10}{'其他':>10}{'合计':>12}")
    for date in sorted(by_date):
        stats = by_date[date]
        c200 = stats.get(200, 0)
        c301 = stats.get(301, 0)
        c404 = stats.get(404, 0)
        total = sum(stats.values())
        other = total - c200 - c301 - c404
        print(f"  {date:12}{c200:>10}{c301:>10}{c404:>10}{other:>10}{total:>12}")


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
    ap.add_argument("--edge", action="store_true",
                    help="zone 级边缘请求按日×状态码（301/404 趋势，含无 JS 爬虫）")
    ap.add_argument("--zone", default=os.environ.get("CF_ZONE", DEFAULT_ZONE))
    args = ap.parse_args()

    key_path = os.path.expanduser(args.key)
    if not os.path.exists(key_path):
        sys.exit(f"找不到 token 文件: {key_path}\n把 CF API token 放 ~/.config/seo-tools/cf-api-token.txt。")

    token = open(key_path).read().strip()

    if args.edge:
        end_d = dt.date.today() - dt.timedelta(days=1)
        start_d = end_d - dt.timedelta(days=args.days - 1)
        print(f"=== CF 边缘请求（{start_d} ~ {end_d}，zone {args.zone}）===")
        try:
            resp = run_query(token, build_edge_query(args.zone, start_d.isoformat(), end_d.isoformat()))
            print_edge(resp)
        except Exception as ex:
            print(f"  边缘查询失败: {ex}")
        return

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
