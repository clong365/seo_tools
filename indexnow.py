#!/usr/bin/env python3
"""IndexNow 主动推送（共享版）— 把站点 URL 推送给 Bing 等支持 IndexNow 的引擎。

用法:
    .venv/bin/python indexnow.py --site www.example.com                 # 拉线上 sitemap 全量推送
    .venv/bin/python indexnow.py --site www.example.com --file urls.txt # 只推文件里的 URL（日常更新）
    .venv/bin/python indexnow.py --site www.example.com --dry-run       # 只统计不推送

站点 key 配置在 ~/.config/seo-tools/indexnow.json（{"host": "32位hex key"}）。
key 按 IndexNow 协议本就公开（托管在 https://<host>/<key>.txt 验证归属），但仍按约定不进 git。
"""
import argparse
import json
import os
import re
import sys

import requests

import config

API_URL = "https://api.indexnow.org/indexnow"
DEFAULT_CONF = "~/.config/seo-tools/indexnow.json"
BATCH = 10000  # IndexNow 单次请求上限
TIMEOUT = 60


def load_key(conf_path, host):
    path = os.path.expanduser(conf_path)
    if not os.path.exists(path):
        sys.exit(f"找不到 key 配置: {path}\n格式: {{\"{host}\": \"32位hex key\"}}")
    conf = json.load(open(path))
    if host not in conf:
        sys.exit(f"{path} 里没有 {host} 的 key（已有: {', '.join(conf)}）")
    return conf[host]


def fetch_sitemap_urls(host, paths):
    """拉 sitemap index 并下钻全部子 sitemap，返回 URL 列表。"""
    urls = []
    for p in paths:
        index = f"https://{host}{p}"
        try:
            r = requests.get(index, timeout=TIMEOUT)
            r.raise_for_status()
            subs = re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text)
        except Exception as ex:
            print(f"  拉取 {index} 失败: {ex}")
            continue
        print(f"  {index}: {len(subs)} 个子 sitemap")
        for sub in subs:
            try:
                r = requests.get(sub, timeout=TIMEOUT)
                r.raise_for_status()
                found = re.findall(r"<loc>\s*(.*?)\s*</loc>", r.text)
                urls.extend(found)
                print(f"    {sub}: {len(found)}")
            except Exception as ex:
                print(f"    {sub}: 拉取失败 {ex}")
    return urls


def make_payload(host, key, batch):
    return {
        "host": host,
        "key": key,
        "keyLocation": f"https://{host}/{key}.txt",
        "urlList": batch,
    }


def push(host, key, urls, dry_run):
    """推送并返回每批结果 [{batch, ok, detail}, ...]。

    单批失败**不中断**剩余批次（逐批独立、可重复提交、无副作用），
    但**绝不安静地少发**：每批记录结果，末尾由 summarize() 汇总，
    任一批失败则 exit_code() 给非零——保持响亮失败，别让 CI/cron 当成功。

    ⚠️ 两种失败路径不同，别混：
      - **HTTP 非 2xx**：requests.post 正常返回，按 status_code 判失败。
        （历史：旧实现根本不看 status code、只打印，所以 500 从来不会中断循环。）
      - **requests.post 抛异常**：网络层错误。旧实现会直接中断循环、
        导致只推第 1 批——这才是要防的路径，现捕获后记为失败并继续。
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
            r = requests.post(API_URL, json=make_payload(host, key, batch), timeout=TIMEOUT)
            ok = r.ok
            detail = f"HTTP {r.status_code}"
        except Exception as ex:
            ok = False
            detail = f"{type(ex).__name__}: {ex}"
        results.append({"batch": n, "ok": ok, "detail": detail})
        print(f"  批次 {n}/{total}（{len(batch)} 个）: {detail}{'' if ok else ' ✗'}")
    return results


def summarize(results):
    """汇总字符串：总批数 / 成功 / 失败，失败逐条列出批号与原因。"""
    if not results:
        return "  汇总：无批次（dry-run，未发送）"
    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    lines = [f"  汇总：共 {len(results)} 批 | 成功 {len(ok)} | 失败 {len(bad)}"]
    if bad:
        lines.append("  失败批次：")
        lines.extend(f"    批次 {r['batch']}: {r['detail']}" for r in bad)
    return "\n".join(lines)


def exit_code(results):
    """任一批失败 → 1；全部成功或无批次 → 0。"""
    return 1 if any(not r["ok"] for r in results) else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=None, help="host，须存在于 indexnow.json（默认读 sites.json）")
    ap.add_argument("--conf", default=os.environ.get("INDEXNOW_CONF", DEFAULT_CONF))
    ap.add_argument("--file", help="只推文件里列出的 URL（每行一个）")
    ap.add_argument("--sitemap", action="append", dest="sitemaps",
                    help="sitemap index 路径，可重复；默认 /sitemap-index.xml。"
                         "双语站全量: --sitemap /sitemap-index.xml --sitemap /zh-tw/sitemap-index.xml")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    site = config.require("indexnow_host", "INDEXNOW_HOST", args.site)
    key = load_key(args.conf, site)

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
    results = push(site, key, urls, args.dry_run)
    print(summarize(results))
    if exit_code(results):
        sys.exit("推送未全部成功：见上方失败批次汇总。")


if __name__ == "__main__":
    main()
