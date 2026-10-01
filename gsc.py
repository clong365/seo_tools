#!/usr/bin/env python3
"""GSC 收录/表现复查 — service account 只读（共享版）。

用法:
    .venv/bin/python gsc.py               # 列出 key 能访问的所有站点
    .venv/bin/python gsc.py --site xianmi.co
"""
import argparse
import datetime as dt
import ipaddress
import os
import re
import socket
import sys
import time
from urllib.parse import quote, urlsplit, urljoin

import requests

SCOPES = [
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/webmasters.readonly",
]
DEFAULT_KEY = "~/.config/seo-tools/gsc-sa.json"
SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
SITEMAPS_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/sitemaps"
ANALYTICS_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
TIMEOUT = 30


def normalize_site(s):
    s = (s or "").strip().rstrip("/")
    s = re.sub(r"^https?://", "", s)
    return s.split("/", 1)[0]


def pick_site(sites, want):
    want = normalize_site(want)
    for s in sites:
        if normalize_site(s) == want:
            return s
    for s in sites:
        if want in s:
            return s
    return None


def parse_sitemap_locs(xml_text):
    return re.findall(r"<loc>\s*(.*?)\s*</loc>", xml_text or "")


def is_sitemap_index(locs):
    return bool(locs) and all(loc.rstrip("/").endswith(".xml") for loc in locs)


def _is_public_http_url(url):
    """SSRF 防护：仅放行 http/https 且主机（字面量或 DNS 解析结果）全为公网地址的 URL。"""
    try:
        u = urlsplit(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        host = u.hostname.lower().rstrip(".")
        try:
            ips = [ipaddress.ip_address(host)]
        except ValueError:
            try:
                ips = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)]
            except socket.gaierror:
                return False
        return all(not (ip.is_loopback or ip.is_private or ip.is_link_local
                        or ip.is_reserved or ip.is_unspecified) for ip in ips)
    except (ValueError, OSError):
        return False


def _fetch_guarded(url, hops=3):
    """SSRF 防护的 fetch：校验 URL，逐跳校验并跟随重定向（相对 Location 用 urljoin）。"""
    cur = url
    for _ in range(hops + 1):
        if not _is_public_http_url(cur):
            return None
        r = requests.get(cur, timeout=30, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            cur = urljoin(cur, r.headers["Location"])
            continue
        return r
    return None


def get_token(key_path):
    from google.oauth2 import service_account
    import google.auth.transport.requests as grequests
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=SCOPES)
    creds.refresh(grequests.Request())  # requests 自动走 https_proxy 代理
    return creds.token


def api(token, method, url, **kw):
    headers = {"Authorization": f"Bearer {token}"}
    kw.setdefault("timeout", TIMEOUT)
    return requests.request(method, url, headers=headers, **kw)


def list_sites(token):
    r = api(token, "GET", SITES_URL)
    r.raise_for_status()
    return [s.get("siteUrl", "") for s in r.json().get("siteEntry", [])]


def gsc_site_to_base_url(site):
    if site.startswith("sc-domain:"):
        return "https://" + site.split(":", 1)[1].rstrip("/") + "/"
    return site.rstrip("/") + "/"


def fetch_sitemap_urls(base_url):
    """取页面 URL；兼容平铺 sitemap.xml 与索引 sitemap-index.xml（下钻一层）。"""
    for name in ("sitemap.xml", "sitemap-index.xml"):
        try:
            r = requests.get(base_url + name, timeout=20)
            r.raise_for_status()
        except requests.RequestException:
            continue
        locs = parse_sitemap_locs(r.text)
        if not locs:
            continue
        if is_sitemap_index(locs):
            urls = []
            for sub in locs:
                rr = _fetch_guarded(sub)
                if rr is None:
                    continue
                try:
                    rr.raise_for_status()
                    urls.extend(parse_sitemap_locs(rr.text))
                except requests.RequestException:
                    continue
            return urls
        return locs
    return []


def sitemaps_report(token, site):
    print("\n=== Sitemap 状态 ===")
    try:
        r = api(token, "GET", SITEMAPS_URL.format(site=quote(site, safe="")))
        r.raise_for_status()
        entries = r.json().get("sitemap", [])
        if not entries:
            print("  (无 sitemap 提交记录)")
            return
        for e in entries:
            path = e.get("path")
            for c in e.get("contents", []):
                t = c.get("type", "?")
                print(f"  {path}\n    {t}: submitted={c.get('submitted','?')} "
                      f"indexed={c.get('indexed','?')} errors={c.get('errors','?')}")
    except Exception as ex:
        print(f"  sitemap 读取失败: {ex}")


def search_analytics(token, site, days):
    end = dt.date.today() - dt.timedelta(days=3)
    start = end - dt.timedelta(days=days - 1)
    s, e = start.isoformat(), end.isoformat()
    url = ANALYTICS_URL.format(site=quote(site, safe=""))
    print(f"\n=== Search Analytics ({s} ~ {e}) ===")

    def _q(dimensions=None):
        body = {"startDate": s, "endDate": e}
        if dimensions:
            body["dimensions"] = dimensions
            body["rowLimit"] = 100
        r = api(token, "POST", url, json=body)
        r.raise_for_status()
        return r.json()

    try:
        total = _q()
        rows = total.get("rows", [])
        if not rows:
            print("  Impressions=0（尚无曝光，属早期正常）")
            return
        r = rows[0]
        print(f"  曝光 {r.get('impressions',0):.0f} | 点击 {r.get('clicks',0):.0f} | "
              f"CTR {r.get('ctr',0)*100:.2f}% | 平均排名 {r.get('position',0):.1f}")
        print("\n  按页面:")
        for row in _q(["page"]).get("rows", [])[:20]:
            print(f"    {row.get('impressions',0):>6.0f} imp | {row.get('clicks',0):>3.0f} clk | "
                  f"pos {row.get('position',0):.1f} | {row['keys'][0]}")
        print("\n  按国家:")
        for row in _q(["country"]).get("rows", [])[:15]:
            print(f"    {row.get('impressions',0):>6.0f} imp | {row.get('clicks',0):>3.0f} clk | {row['keys'][0]}")
    except Exception as ex:
        print(f"  Search Analytics 失败: {ex}")


def url_inspection(token, site, urls, limit):
    for url in urls[:limit]:
        try:
            r = api(token, "POST", INSPECT_URL, json={"inspectionUrl": url, "siteUrl": site})
            r.raise_for_status()
            ir = r.json().get("inspectionResult", {}).get("indexStatusResult", {})
            verdict = ir.get("verdict", "?")
            coverage = ir.get("coverageState", "?")
            last_crawl = ir.get("lastCrawlTime", "")[:19].replace("T", " ")
            canonical = ir.get("googleCanonical", "?")
            print(f"  [{verdict:>8}] {coverage:40} crawl={last_crawl}  {url}")
            if canonical and canonical != url:
                print(f"              googleCanonical -> {canonical}")
        except Exception as ex:
            print(f"  [ERROR] {url}: {ex}")
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", DEFAULT_KEY))
    ap.add_argument("--site", default=None)
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--inspect-limit", type=int, default=50)
    ap.add_argument("--no-inspect", action="store_true")
    args = ap.parse_args()

    key_path = os.path.expanduser(args.key)
    if not os.path.exists(key_path):
        sys.exit(f"找不到 key 文件: {key_path}\n"
                 f"先到 GCP 建 service account，把 JSON 放 ~/.config/seo-tools/gsc-sa.json。")

    token = get_token(key_path)
    sites = list_sites(token)

    print(f"=== 可访问站点（{len(sites)}）===")
    for s in sites:
        print(f"  {s}")

    if not args.site:
        if not sites:
            sys.exit("service account 未授权任何资源。到 GSC 各资源「用户和权限」添加 client_email 并给「完全」。")
        return

    site = pick_site(sites, args.site)
    if not site:
        sys.exit(f"'{args.site}' 不在可访问列表。可访问: {sites}")

    print(f"\n=== 选中站点: {site} ===")
    sitemaps_report(token, site)
    search_analytics(token, site, args.days)
    if not args.no_inspect:
        urls = fetch_sitemap_urls(gsc_site_to_base_url(site))
        if urls:
            print(f"\n=== URL Inspection（共 {len(urls)} 个 URL）===")
            url_inspection(token, site, urls, args.inspect_limit)


if __name__ == "__main__":
    main()
