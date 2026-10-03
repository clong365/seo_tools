#!/usr/bin/env python3
"""GA4 流量复查 — service account 只读（共享版）。

用法:
    .venv/bin/python ga.py                       # 属性取自 sites.json
    .venv/bin/python ga.py --property <属性ID>
"""
import argparse
import os
import sys

import requests

import config

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
DEFAULT_KEY = "~/.config/seo-tools/google-sa.json"
BASE = "https://analyticsdata.googleapis.com/v1beta"
TIMEOUT = 30


def format_rows(resp):
    """runReport 响应 → (维度名列表, 指标名列表, 行列表[(维度值tuple, 指标值tuple)])。"""
    dims = [h["name"] for h in resp.get("dimensionHeaders", [])]
    metrics = [h["name"] for h in resp.get("metricHeaders", [])]
    rows = []
    for row in resp.get("rows", []):
        d = tuple(v["value"] for v in row.get("dimensionValues", []))
        m = tuple(v["value"] for v in row.get("metricValues", []))
        rows.append((d, m))
    return dims, metrics, rows


def get_token(key_path):
    from google.oauth2 import service_account
    import google.auth.transport.requests as grequests
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    creds.refresh(grequests.Request())  # requests 自动走 https_proxy 代理
    return creds.token


def run_report(token, property_id, metrics, dimensions=None, days=28, limit=20):
    url = f"{BASE}/properties/{property_id}:runReport"
    body = {
        "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
        "metrics": [{"name": m} for m in metrics],
    }
    if dimensions:
        body["dimensions"] = [{"name": d} for d in dimensions]
        body["limit"] = str(limit)
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, json=body, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def print_block(title, resp):
    dims, metrics, rows = format_rows(resp)
    print(f"\n=== {title} ===")
    if not rows:
        print("  (无数据)")
        return
    if dims:
        for d, m in rows:
            print(f"  {' / '.join(m):>18}   {' · '.join(d)}")
    else:
        for d, m in rows:
            print("  " + " | ".join(f"{name}={val}" for name, val in zip(metrics, m)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", DEFAULT_KEY))
    ap.add_argument("--property", default=None, help="GA4 属性 ID（默认读 sites.json）")
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    property_id = config.require("ga_property", "GA_PROPERTY", args.property)

    key_path = os.path.expanduser(args.key)
    if not os.path.exists(key_path):
        sys.exit(f"找不到 key 文件: {key_path}\n把 service account JSON 放 ~/.config/seo-tools/google-sa.json。")

    try:
        token = get_token(key_path)
    except Exception as ex:
        sys.exit(f"GA API 访问失败: {ex}\n"
                 f"检查：key 是否有效、是否已在 GA4 属性访问管理里把 client_email 加为「查看者」、"
                 f"大陆是否已设 https_proxy 代理。")
        return  # 防测试 mock sys.exit 后继续

    metrics = ["activeUsers", "sessions", "screenPageViews"]
    print(f"=== GA4 property {property_id}（近 {args.days} 天）===")

    try:
        print_block("总览", run_report(token, property_id, metrics, days=args.days))
    except Exception as ex:
        print(f"  总览失败: {ex}")

    for dim, label in [("country", "按国家"), ("pagePath", "按页面"), ("language", "按语言")]:
        try:
            print_block(label, run_report(token, property_id, metrics,
                                          dimensions=[dim], days=args.days, limit=args.limit))
        except Exception as ex:
            print(f"  {label}失败: {ex}")


if __name__ == "__main__":
    main()
