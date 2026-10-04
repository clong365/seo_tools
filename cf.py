#!/usr/bin/env python3
"""Cloudflare Web Analytics 流量复查 — GraphQL（RUM）只读（共享版）。

用法:
    .venv/bin/python cf.py                  # 站点取自 sites.json
    .venv/bin/python cf.py --site <siteTag>
    .venv/bin/python cf.py --edge           # 需 cf_zone
"""
import argparse
import datetime as dt
import json
import os
import sys

import requests

import config

GRAPHQL_URL = "https://api.cloudflare.com/client/v4/graphql"
AE_SQL_URL = "https://api.cloudflare.com/client/v4/accounts/{account}/analytics_engine/sql"
DEFAULT_KEY = "~/.config/seo-tools/cf-api-token.txt"
TIMEOUT = 30
# AE 走 ClickHouse 式查询，耗时不如有界的 GraphQL；且调用方是定时监控，
# 一次误超时就是漏一轮。实测常规 1–2.4s，留足余量。
AE_TIMEOUT = 60


# AE 预设查询。{dataset} 由配置代入——dataset 名是部署细节，不进源码。
PRESETS = {
    "3h": (
        "SELECT blob4 AS kind, count() AS n\n"
        "FROM {dataset}\n"
        "WHERE timestamp >= NOW() - INTERVAL '3' HOUR\n"
        "GROUP BY blob4\n"
        "ORDER BY n DESC\n"
        "FORMAT JSON"
    ),
}


def build_sql(preset=None, sql_file=None, dataset=None):
    """构造 AE SQL 文本。--preset 与 --sql-file 二选一。

    预设模板的 {dataset} 由配置代入；末尾必须是 FORMAT JSON，
    否则 AE 返回 NDJSON，与 cf CLI 输出结构对不上。
    """
    if preset and sql_file:
        sys.exit("--preset 与 --sql-file 只能二选一")
    if not preset and not sql_file:
        sys.exit("请指定 --preset <预设名> 或 --sql-file <SQL 路径>")
    if sql_file:
        path = os.path.expanduser(sql_file)
        try:
            with open(path) as f:
                return f.read()
        except OSError as ex:
            sys.exit(f"读不了 SQL 文件 {path}: {ex}")
    if preset not in PRESETS:
        sys.exit(f"未知预设 {preset!r}。可用: {', '.join(sorted(PRESETS))}")
    if not dataset:
        sys.exit("预设查询需要 dataset：--dataset 或 sites.json 的 ae_dataset")
    return PRESETS[preset].format(dataset=dataset)


def ae_query(token, account, sql):
    """POST Workers Analytics Engine SQL 端点，返回解析后的 JSON。

    请求体是**纯 SQL 文本**（不是 JSON 包装），与 cf CLI 的行为一致。
    任何失败都抛 RuntimeError 并带上响应体——缺权限时要能直接看出缺哪个，
    **不许静默降级成空结果**。
    """
    url = AE_SQL_URL.format(account=account)
    r = requests.post(url,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "text/plain"},
                      data=sql.encode(), timeout=AE_TIMEOUT)
    try:
        body = r.json()
    except ValueError:
        body = None
    if r.status_code >= 400:
        detail = (body or {}).get("errors") or r.text[:300]
        raise RuntimeError(f"HTTP {r.status_code}: {detail}")
    if isinstance(body, dict) and body.get("errors"):
        raise RuntimeError(f"响应带 errors: {body['errors']}")
    return body


def ae_report(token, account, preset, sql_file, dataset=None, conf_path=None):
    """跑 AE 查询，结果以 JSON 打到 stdout（便于 cron 直接管道给 jq）。

    dataset 未显式给时回退 sites.json 的 ae_dataset——dataset 名是部署细节，
    不该要求每次敲在命令行里。
    """
    ds = dataset or config.resolve("ae_dataset", "CF_AE_DATASET", None, conf_path)
    sql = build_sql(preset=preset, sql_file=sql_file, dataset=ds)
    try:
        body = ae_query(token, account, sql)
    except Exception as ex:
        sys.exit(f"AE 查询失败: {ex}")
    print(json.dumps(body, ensure_ascii=False, indent=2))


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


def build_edge_query(zone, start_date, end_date, eyeball=True):
    """zone 级边缘请求按 日期×状态码 统计（含无执行 JS 的爬虫，RUM 的补集口径）。

    默认只统计 requestSource="eyeball"（真实客户端，含爬虫）——**必须**这样做：
    Worker 的 Cache API 调用会被 CF 记成 requestSource="edgeWorkerCacheAPI" 的
    额外行（2026-10-02 review 实测：当日 504 记录 100% 来自该来源、真实客户端
    504=0；204 的 16 倍暴涨同源），不过滤会把遥测噪声当成站点故障。
    """
    src = ', requestSource: "eyeball"' if eyeball else ''
    return f'''
{{
  viewer {{
    zones(filter: {{zoneTag: "{zone}"}}) {{
      httpRequestsAdaptiveGroups(
        limit: 5000
        filter: {{date_geq: "{start_date}", date_leq: "{end_date}"{src}}}
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
    ap.add_argument("--account", default=None, help="CF accountTag（默认读 sites.json）")
    ap.add_argument("--site", default=None, help="CF siteTag（默认读 sites.json）")
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--edge", action="store_true",
                    help="zone 级边缘请求按日×状态码（301/404 趋势，含无 JS 爬虫）")
    ap.add_argument("--all-sources", action="store_true",
                    help="--edge 时不过滤 requestSource（含 edgeWorkerCacheAPI 遥测行；默认只统计 eyeball）")
    ap.add_argument("--zone", default=None, help="CF zone ID，--edge 用（默认读 sites.json）")
    ap.add_argument("--ae", action="store_true",
                    help="Workers Analytics Engine SQL 查询（输出纯 JSON）")
    ap.add_argument("--preset", help="--ae 用预设查询，如 3h")
    ap.add_argument("--sql-file", help="--ae 用 SQL 文件路径（与 --preset 二选一）")
    ap.add_argument("--dataset", default=None,
                    help="AE dataset 名，预设查询用（默认读 sites.json 的 ae_dataset）")
    args = ap.parse_args()

    key_path = os.path.expanduser(args.key)
    if not os.path.exists(key_path):
        sys.exit(f"找不到 token 文件: {key_path}\n把 CF API token 放 ~/.config/seo-tools/cf-api-token.txt。")

    token = open(key_path).read().strip()

    if args.ae:
        account = config.require("cf_account", "CF_ACCOUNT", args.account)
        ae_report(token, account, args.preset, args.sql_file, dataset=args.dataset)
        return

    if args.edge:
        zone = config.require("cf_zone", "CF_ZONE", args.zone)
        end_d = dt.date.today() - dt.timedelta(days=1)
        start_d = end_d - dt.timedelta(days=args.days - 1)
        scope = "全部来源（含 Cache API 遥测）" if args.all_sources else "仅 eyeball（真实客户端）"
        print(f"=== CF 边缘请求（{start_d} ~ {end_d}，zone {zone}，{scope}）===")
        try:
            resp = run_query(token, build_edge_query(
                zone, start_d.isoformat(), end_d.isoformat(), eyeball=not args.all_sources))
            print_edge(resp)
        except Exception as ex:
            print(f"  边缘查询失败: {ex}")
        return

    account = config.require("cf_account", "CF_ACCOUNT", args.account)
    site = config.require("cf_site", "CF_SITE", args.site)

    start, end = date_range(args.days)
    print(f"=== CF Web Analytics（近 {args.days} 天，site {site}）===")

    try:
        resp = run_query(token, build_query(account, site, start, end))
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
            resp = run_query(token, build_query(account, site, start, end, dim))
            print_block(label, resp, dim)
        except Exception as ex:
            print(f"  {label}失败: {ex}")


if __name__ == "__main__":
    main()
