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
    total = (len(urls) + BATCH - 1) // BATCH
    for i in range(0, len(urls), BATCH):
        batch = urls[i:i + BATCH]
        n = i // BATCH + 1
        if dry_run:
            print(f"  批次 {n}/{total}（{len(batch)} 个）: dry-run 跳过")
            continue
        r = requests.post(API_URL, json=make_payload(host, key, batch), timeout=TIMEOUT)
        print(f"  批次 {n}/{total}（{len(batch)} 个）: HTTP {r.status_code}")


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
    push(site, key, urls, args.dry_run)


if __name__ == "__main__":
    main()
