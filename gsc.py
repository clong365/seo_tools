#!/usr/bin/env python3
"""GSC 收录/表现复查 — service account 只读（共享版）。

用法:
    .venv/bin/python gsc.py               # 列出 key 能访问的所有站点
    .venv/bin/python gsc.py --site example.com
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

import config

SCOPES = [
    "https://www.googleapis.com/auth/webmasters",
    "https://www.googleapis.com/auth/webmasters.readonly",
]
DEFAULT_KEY = "~/.config/seo-tools/google-sa.json"
SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
SITEMAPS_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/sitemaps"
ANALYTICS_URL = "https://www.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
TIMEOUT = 30


def normalize_site(s):
    """规整为裸域名：去协议/路径/尾斜杠，以及 GSC 资源名的 sc-domain: 前缀。

    前缀必须在这里去掉——pick_site 是拿裸域名比对的，
    入参若带着 sc-domain: 就永远匹配不上（实测踩过）。
    """
    s = (s or "").strip().rstrip("/")
    s = re.sub(r"^https?://", "", s)
    s = s.split("/", 1)[0]
    return s.removeprefix("sc-domain:")


def _bare_host(s):
    return normalize_site(s)


def pick_site(sites, want):
    want = normalize_site(want)
    for s in sites:
        if _bare_host(s) == want:
            return s
    for s in sites:
        if _bare_host(s) == "www." + want:
            return s
    return None


def choose_site(sites, cli_value, conf_path=None):
    """选 GSC 资源名：命令行 > sites.json 的 gsc_site；都没有返回 None（调用方只列站点）。

    入参三种写法都接受：裸域名、sc-domain: 前缀、完整 URL。
    """
    want = cli_value or config.resolve("gsc_site", "GSC_SITE", None, conf_path)
    return pick_site(sites, want) if want else None


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
        try:
            r = requests.get(cur, timeout=30, allow_redirects=False)
        except requests.RequestException:
            return None
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


def period_ranges(days, today=None):
    """当前期与基线期（紧邻的等长前一段）→ (cur_start, cur_end, base_start, base_end)。

    当前期截止 3 天前：GSC 最近几天数据不全，取了也是空的。
    """
    today = today or dt.date.today()
    end = today - dt.timedelta(days=3)
    start = end - dt.timedelta(days=days - 1)
    base_end = start - dt.timedelta(days=1)
    base_start = base_end - dt.timedelta(days=days - 1)
    return start, end, base_start, base_end


def diff_rows(cur_rows, base_rows, key_index=0):
    """两期 GSC 行按维度键 join，算变化量。

    只在一期出现的键也保留：新增页 d 为正、消失页 d 为负。
    返回按 d_clicks 降序。
    """
    def key_of(row):
        return row.get("keys", [""])[key_index]

    cur = {key_of(r): r for r in cur_rows}
    base = {key_of(r): r for r in base_rows}
    out = []
    for k in cur.keys() | base.keys():
        c, b = cur.get(k), base.get(k)
        cm = c or {"clicks": 0, "impressions": 0, "position": 0}
        bm = b or {"clicks": 0, "impressions": 0, "position": 0}
        out.append({
            "key": k,
            "cur": c,
            "base": b,
            "d_clicks": cm.get("clicks", 0) - bm.get("clicks", 0),
            "d_impressions": cm.get("impressions", 0) - bm.get("impressions", 0),
            "d_position": cm.get("position", 0) - bm.get("position", 0),
        })
    out.sort(key=lambda r: r["d_clicks"], reverse=True)
    return out


def normalize_page(url):
    """去尾斜杠，让 /a/18077 与 /a/18077/ 视为同一页。

    只做这一项规范化：够用且不误伤（大小写、查询串、语言前缀都可能是不同内容，
    不能一并归并——/zh-tw/ 前缀是另一篇，属真竞争）。
    """
    u = (url or "").rstrip("/")
    return u or "/"


def find_cannibalization(rows, min_impressions=10):
    """从 dimensions=["query","page"] 的行里找「同词多页」竞争。

    ⚠️ **这是 GSC Search Analytics 里最贵的一档查询**。官方文档原话：
    "Queries grouped/filtered by page AND query string are the most expensive."
    且查询负载随日期范围变长而增加。所以 --cannibalization **默认关闭**，
    只在显式指定时才跑，跑完缓存结果复用，别当每次复查的默认开销。

    ⚠️ 页身份用 normalize_page() 归一：**尾斜杠变体是同一页**，不能算竞争
    （实测站点上 /p02/a/835/18077 与 /p02/a/835/18077/ 同词分列两行，
    不归并会输出大量假阳性）。归并后仍在 variants 里保留原 URL——
    「同一页有多个 URL 变体」本身是 canonical 问题，值得单独看。

    只保留有实质曝光（>= min_impressions）的页面；leading = 点击最多的页。
    「领先页变化」需再跑一次同样的双维查询做两期对比，成本翻倍，故不做。
    """
    by_query = {}
    for r in rows:
        keys = r.get("keys", [])
        if len(keys) < 2:
            continue
        q, raw = keys[0], keys[1]
        imp = r.get("impressions", 0)
        if imp < min_impressions:
            continue
        by_query.setdefault(q, {}).setdefault(normalize_page(raw), []).append(
            (raw, r.get("clicks", 0), imp, r.get("position", 0)))

    out = []
    for q, pages in by_query.items():
        if len(pages) < 2:
            continue
        entries = []
        for norm, variants in pages.items():
            clicks = sum(v[1] for v in variants)
            imps = sum(v[2] for v in variants)
            pos = (sum(v[3] * v[2] for v in variants) / imps) if imps else 0.0
            entries.append({"page": norm, "variants": variants,
                            "clicks": clicks, "impressions": imps, "position": pos})
        entries.sort(key=lambda e: e["clicks"], reverse=True)
        out.append({"query": q, "pages": entries, "leading": entries[0]["page"]})
    out.sort(key=lambda o: -sum(p["impressions"] for p in o["pages"]))
    return out


def query_analytics(token, site, start, end, dimensions=None, row_limit=100):
    """查 Search Analytics。start/end 传 ISO 日期字符串；dimensions 为 None 时取汇总。"""
    body = {"startDate": start, "endDate": end}
    if dimensions:
        body["dimensions"] = dimensions
        body["rowLimit"] = row_limit
    url = ANALYTICS_URL.format(site=quote(site, safe=""))
    r = api(token, "POST", url, json=body)
    r.raise_for_status()
    return r.json()


def search_analytics(token, site, days):
    end = dt.date.today() - dt.timedelta(days=3)
    start = end - dt.timedelta(days=days - 1)
    s, e = start.isoformat(), end.isoformat()
    print(f"\n=== Search Analytics ({s} ~ {e}) ===")

    def _q(dimensions=None):
        return query_analytics(token, site, s, e, dimensions)

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


def compare_report(token, site, days):
    """本期 vs 紧邻的等长前一段：涨跌页 / 涨跌查询。

    两期各自是一次单维查询，join 在本地做，不碰双维分组的贵查询。
    """
    cur_s, cur_e, base_s, base_e = period_ranges(days)
    print(f"\n=== 期段对比 ===")
    print(f"  本期   {cur_s} ~ {cur_e}")
    print(f"  对比期 {base_s} ~ {base_e}（紧邻等长前一段）")

    try:
        for label, dims in [("按页面", ["page"]), ("按查询", ["query"])]:
            cur = query_analytics(token, site, cur_s.isoformat(), cur_e.isoformat(),
                                  dims).get("rows", [])
            base = query_analytics(token, site, base_s.isoformat(), base_e.isoformat(),
                                   dims).get("rows", [])
            rows = diff_rows(cur, base)
            gain = [r for r in rows if r["d_clicks"] > 0][:10]
            drop = sorted((r for r in rows if r["d_clicks"] < 0),
                          key=lambda r: r["d_clicks"])[:10]
            print(f"\n  {label} —— 涨幅 Top:")
            if not gain:
                print("    (无)")
            for r in gain:
                print(f"    {r['d_clicks']:+5.0f} clk {r['d_impressions']:+7.0f} imp "
                      f"{r['d_position']:+5.1f} pos | {r['key']}")
            print(f"  {label} —— 跌幅 Top:")
            if not drop:
                print("    (无)")
            for r in drop:
                print(f"    {r['d_clicks']:+5.0f} clk {r['d_impressions']:+7.0f} imp "
                      f"{r['d_position']:+5.1f} pos | {r['key']}")
    except Exception as ex:
        print(f"  期段对比失败: {ex}")


def cannibalization_report(token, site, days, min_impressions=10):
    """同词多页竞争（--cannibalization，**默认关闭**）。

    ⚠️ **这是本脚本最贵的一次查询**：必须按 query+page 双维分组，官方文档称
    "Queries grouped/filtered by page AND query string are the most expensive"，
    且负载随日期范围变长而增加。因此：
      - 默认关闭，只在显式传 --cannibalization 时才跑
      - 跑完把结果缓存下来复用，别当每次复查的默认开销
      - 日期范围别给大（默认 28 天）
    """
    cur_s, cur_e, _, _ = period_ranges(days)
    print(f"\n=== 同词多页竞争（{cur_s} ~ {cur_e}）===")
    print("  ⚠️ 该查询按 query+page 双维分组，是 Search Analytics 里最贵的一档；")
    print("     日期范围越长越贵，故本开关默认关闭。")
    try:
        rows = query_analytics(token, site, cur_s.isoformat(), cur_e.isoformat(),
                               ["query", "page"], row_limit=5000).get("rows", [])
        out = find_cannibalization(rows, min_impressions=min_impressions)
        if not out:
            print("  (未发现同词多页竞争)")
            return
        print(f"  发现 {len(out)} 个 query 有多页有实质曝光（>= {min_impressions} imp）：\n")
        multi_url = 0
        for o in out[:20]:
            print(f"  「{o['query']}」 领先页 {o['leading']}")
            for pg in o["pages"]:
                mark = " ←领先" if pg["page"] == o["leading"] else ""
                var = ""
                if len(pg["variants"]) > 1:
                    multi_url += 1
                    var = f"  （{len(pg['variants'])} 个 URL 变体）"
                print(f"      {pg['impressions']:>6.0f} imp | {pg['clicks']:>3.0f} clk | "
                      f"pos {pg['position']:>5.1f} | {pg['page']}{mark}{var}")
        if multi_url:
            print(f"\n  注：其中 {multi_url} 个页面有多个 URL 变体（多半是尾斜杠不一致），")
            print("      属 canonical 问题而非内容竞争，建议统一后再判读。")
    except Exception as ex:
        print(f"  同词多页查询失败: {ex}")


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
    ap.add_argument("--site", default=None,
                    help="GSC 资源，裸域名 / sc-domain: 前缀 / 完整 URL 皆可（默认读 sites.json 的 gsc_site）")
    ap.add_argument("--days", type=int, default=28)
    ap.add_argument("--inspect-limit", type=int, default=50)
    ap.add_argument("--no-inspect", action="store_true")
    ap.add_argument("--compare", action="store_true",
                    help="输出本期 vs 紧邻等长前一段的涨跌页/查询")
    ap.add_argument("--cannibalization", action="store_true",
                    help="查同词多页竞争。⚠️ 需 query+page 双维分组，是 Search Analytics "
                         "里最贵的查询，且日期范围越长越贵——默认关闭，按需开启")
    args = ap.parse_args()

    key_path = os.path.expanduser(args.key)
    if not os.path.exists(key_path):
        sys.exit(f"找不到 key 文件: {key_path}\n"
                 f"先到 GCP 建 service account，把 JSON 放 ~/.config/seo-tools/google-sa.json。")

    try:
        token = get_token(key_path)
        sites = list_sites(token)
    except Exception as ex:
        sys.exit(f"GSC API 访问失败: {ex}\n"
                 f"检查：key 文件是否有效、service account 是否已授权（把 client_email 加到各资源"
                 f"「用户和权限」给「完全」）、大陆是否已设 https_proxy 代理。")
        return  # 生产环境 sys.exit 抛 SystemExit；此处兜底防测试 mock 后继续

    print(f"=== 可访问站点（{len(sites)}）===")
    for s in sites:
        print(f"  {s}")

    if not sites:
        sys.exit("service account 未授权任何资源。到 GSC 各资源「用户和权限」添加 client_email 并给「完全」。")

    site = choose_site(sites, args.site)
    if site is None:
        want = args.site or config.resolve("gsc_site", "GSC_SITE")
        if not want:
            print("\n（未指定 --site，且 sites.json 里没有 gsc_site → 只列站点）"
                  "\n  在 ~/.config/seo-tools/sites.json 配 gsc_site 后，不带参数即可出报告。")
            return
        sys.exit(f"'{want}' 不在可访问列表。可访问: {sites}")

    print(f"\n=== 选中站点: {site} ===")
    sitemaps_report(token, site)
    search_analytics(token, site, args.days)
    if args.compare:
        compare_report(token, site, args.days)
    if args.cannibalization:
        cannibalization_report(token, site, args.days)
    if not args.no_inspect:
        urls = fetch_sitemap_urls(gsc_site_to_base_url(site))
        if urls:
            print(f"\n=== URL Inspection（共 {len(urls)} 个 URL）===")
            url_inspection(token, site, urls, args.inspect_limit)
        else:
            print("\n=== URL Inspection ===\n  sitemap 未取到 URL，跳过（可能无 sitemap 或抓取失败）")


if __name__ == "__main__":
    main()
