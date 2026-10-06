#!/usr/bin/env python3
"""百度搜索资源平台主动推送（共享版）— 把 URL 推送给百度，加速发现/收录。

用法:
    .venv/bin/python baidu.py --site https://www.example.com                 # 拉线上 sitemap 全量推送
    .venv/bin/python baidu.py --site https://www.example.com --file urls.txt # 只推文件里的 URL（日常更新）
    .venv/bin/python baidu.py --site https://www.example.com --dry-run       # 只统计不推送

token 配置在 ~/.config/seo-tools/baidu.json（{"https://www.example.com": "平台给的 token"}）。
token 在 ziyuan.baidu.com「资源提交-主动推送」页可见；不进 git。

⚠️ 配额现实（2023-09 起政策收紧，2026 仍有效）：百度按站点质量动态给额度，
老站常见 100 条/天，新站/未实名站可能只有 0~10 条。推送响应里的 remain 字段
是当天剩余额度的唯一权威来源——本工具逐批打印，remain 归零即停推，别把
「推送成功」当「会收录」（官方明确不保证收录）。

网络注意：data.zz.baidu.com 是国内 endpoint，请直连访问（勿走海外代理，
否则可能被风控或超时）。本工具默认忽略 http_proxy/https_proxy 环境变量。
"""
import argparse
import json
import os
import re
import sys

import requests

import config

API_URL = "http://data.zz.baidu.com/urls"
DEFAULT_CONF = "~/.config/seo-tools/baidu.json"
BATCH = 2000  # 百度单次 POST 上限（官方文档口径）
TIMEOUT = 60

# 国内 endpoint，绕过本机可能存在的代理环境变量
SESSION = requests.Session()
SESSION.trust_env = False


def load_token(conf_path, site):
    path = os.path.expanduser(conf_path)
    if not os.path.exists(path):
        sys.exit(f"找不到 token 配置: {path}\n格式: {{\"{site}\": \"token\"}}")
    conf = json.load(open(path))
    if site not in conf:
        sys.exit(f"{path} 里没有 {site} 的 token（已有: {', '.join(conf)}）")
    return conf[site]


def fetch_sitemap_urls(site, paths):
    """拉 sitemap index 并下钻全部子 sitemap，返回 URL 列表。"""
    urls = []
    for p in paths:
        index = f"{site}{p}"
        try:
            r = SESSION.get(index, timeout=TIMEOUT)
            r.raise_for_status()
            subs = re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text)
        except Exception as ex:
            print(f"  拉取 {index} 失败: {ex}")
            continue
        print(f"  {index}: {len(subs)} 个子 sitemap")
        for sub in subs:
            try:
                r = SESSION.get(sub, timeout=TIMEOUT)
                r.raise_for_status()
                found = re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text)
                urls.extend(found)
                print(f"    {sub}: {len(found)}")
            except Exception as ex:
                print(f"    {sub}: 拉取失败 {ex}")
    return urls


def push(site, token, urls, dry_run):
    """推送并返回每批结果 [{batch, ok, detail, remain}, ...]。

    单批失败不中断剩余批次（与 indexnow.py 同纪律：响亮失败、不安静少发），
    但 remain==0（当日额度用尽）时提前停止——后面再发也是白费且可能扣分。
    """
    total = (len(urls) + BATCH - 1) // BATCH
    results = []
    for i in range(0, len(urls), BATCH):
        batch = urls[i:i + BATCH]
        n = i // BATCH + 1
        if dry_run:
            print(f"  批次 {n}/{total}（{len(batch)} 个）: dry-run 跳过")
            continue
        try:
            r = SESSION.post(f"{API_URL}?site={site}&token={token}",
                             data="\n".join(batch).encode("utf-8"),
                             headers={"Content-Type": "text/plain"},
                             timeout=TIMEOUT)
            body = r.json()
        except Exception as ex:
            results.append({"batch": n, "ok": False, "detail": f"{type(ex).__name__}: {ex}", "remain": None})
            print(f"  批次 {n}/{total}（{len(batch)} 个）: {ex} ✗")
            continue
        if "success" in body:
            results.append({"batch": n, "ok": True,
                            "detail": f"success={body['success']}", "remain": body.get("remain")})
            print(f"  批次 {n}/{total}（{len(batch)} 个）: success={body['success']} remain={body.get('remain')}")
            if body.get("remain") == 0:
                print("  ⚠️ 当日额度用尽（remain=0），停止后续批次。")
                break
        else:
            detail = f"error={body.get('error')} {body.get('message', '')}"
            results.append({"batch": n, "ok": False, "detail": detail, "remain": body.get("remain")})
            print(f"  批次 {n}/{total}（{len(batch)} 个）: {detail} ✗")
            # not_same_site / token 类错误是无恢复价值的，直接停
            if body.get("error") in ("site_error", "empty_content", "not_same_site"):
                print("  ⚠️ 配置类错误，停止后续批次。")
                break
    return results


def summarize(results):
    if not results:
        return "  汇总：无批次（dry-run，未发送）"
    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    lines = [f"  汇总：共 {len(results)} 批 | 成功 {len(ok)} | 失败 {len(bad)}"]
    remains = [r["remain"] for r in results if r.get("remain") is not None]
    if remains:
        lines.append(f"  当日剩余额度（最后一批报告）: {remains[-1]}")
    if bad:
        lines.append("  失败批次：")
        lines.extend(f"    批次 {r['batch']}: {r['detail']}" for r in bad)
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=None,
                    help="站点完整 origin，须与百度平台里添加的站点一致（默认读 sites.json 的 origin）")
    ap.add_argument("--conf", default=os.environ.get("BAIDU_CONF", DEFAULT_CONF))
    ap.add_argument("--file", help="只推文件里列出的 URL（每行一个）")
    ap.add_argument("--sitemap", action="append", dest="sitemaps",
                    help="sitemap index 路径，可重复；默认 /sitemap-index.xml。"
                         "双语站全量: --sitemap /sitemap-index.xml --sitemap /zh-tw/sitemap-index.xml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    site = config.require("origin", "BAIDU_SITE", args.site).rstrip("/")
    token = load_token(args.conf, site)

    if args.file:
        urls = [u.strip() for u in open(args.file) if u.strip()]
        print(f"从 {args.file} 读入 {len(urls)} 个 URL")
    else:
        paths = args.sitemaps or ["/sitemap-index.xml"]
        print(f"拉取 {site} 的 sitemap…")
        urls = fetch_sitemap_urls(site, paths)
    if not urls:
        sys.exit("没有可推送的 URL。")

    print(f"推送 {len(urls)} 个 URL（{site}）…")
    results = push(site, token, urls, args.dry_run)
    print(summarize(results))
    if any(not r["ok"] for r in results):
        sys.exit("推送未全部成功：见上方失败批次汇总。")


if __name__ == "__main__":
    main()
