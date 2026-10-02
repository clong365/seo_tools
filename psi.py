#!/usr/bin/env python3
"""PageSpeed Insights（PSI）复查 —— 实验室（Lighthouse）+ 现场（CrUX）双口径。

为什么用 PSI 而不是本机跑 Lighthouse：
    本机出口经代理（或异地），网络类指标（TTFB/LCP）全是被出口扭曲的假象——
    2026-10-02 已两次踩坑（main 本机 0.9s、review 欧洲出口 0.6s，而零 R2 对照实验
    证明真实基线是"客户端↔colo"的网络时间）。PSI 由 Google 的测试基础设施跑
    Lighthouse，并同时返回 CrUX **现场数据**，因此不受我们本机网络干扰。

用法:
    .venv/bin/python psi.py                                  # 默认 https://www.xianmi.co/
    .venv/bin/python psi.py --url https://www.xianmi.co/p01/a/109/ --strategy mobile
    .venv/bin/python psi.py --only field                     # 只看 CrUX 现场数据
    .venv/bin/python psi.py --only lab --strategy desktop
key 放 ~/.config/seo-tools/psi-api-key.txt（普通 API key，非 service account）。
    GCP 项目里启用 "PageSpeed Insights API" 后创建 API key 即可（免费，无需计费账号）。
"""
import argparse
import json
import os
import sys

import requests

API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
DEFAULT_KEY = "~/.config/seo-tools/psi-sa.json"   # 实测可用（SA + scope openid）；也可指向 API key 文本文件
DEFAULT_URL = "https://www.xianmi.co/"
TIMEOUT = 120

# Lighthouse 分类（分数 0–1）→ 中文标签
CATEGORIES = {
    "performance": "性能",
    "accessibility": "无障碍",
    "best-practices": "最佳实践",
    "seo": "SEO",
}

# 关心的实验室指标 → (good 上限 ms 或分数阈值, 单位)
LAB_METRICS = {
    "first-contentful-paint": (1800, "ms", "FCP 首次内容绘制"),
    "largest-contentful-paint": (2500, "ms", "LCP 最大内容绘制"),
    "total-blocking-time": (200, "ms", "TBT 总阻塞时间"),
    "cumulative-layout-shift": (0.1, "", "CLS 累积布局偏移"),
    "speed-index": (3400, "", "SI 速度指数"),
    "server-response-time": (800, "ms", "TTFB 服务器响应（Google 侧实测）"),
}

# CrUX 现场指标（PSI 的 loadingExperience / originLoadingExperience）
FIELD_METRICS = {
    "LARGEST_CONTENTFUL_PAINT_MS": ("LCP 最大内容绘制", "ms"),
    "INTERACTION_TO_NEXT_PAINT": ("INP 交互到下次绘制", "ms"),
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": ("CLS 累积布局偏移", ""),
    "FIRST_CONTENTFUL_PAINT_MS": ("FCP 首次内容绘制", "ms"),
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": ("TTFB 首字节时间", "ms"),
}
CATEGORY_RANK = {"FAST": "好", "AVERAGE": "需改进", "SLOW": "差"}


def load_key(path):
    """返回 (mode, value)：mode='sa' 时 value=JSON 路径（用 Bearer token）；mode='apikey' 时 value=密钥串。

    两种都支持：Service Account JSON（本项目已有 `gsc-sa.json`，同一把可用）或普通 API key 文本。
    """
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        sys.exit(
            f"找不到 key 文件: {p}\n"
            "在 GCP 项目里启用 PageSpeed Insights API 后：①把 Service Account JSON 放该路径，"
            "或 ②创建 API key 后把密钥文本写入该文件。两者都可用。"
        )
    raw = open(p, encoding="utf-8").read().strip()
    if raw.startswith("{"):
        try:
            doc = json.loads(raw)
        except Exception as e:
            sys.exit(f"key 文件不是合法 JSON：{e}")
        if doc.get("type") == "service_account":
            return "sa", p
        sys.exit("JSON key 文件不是 service_account 类型。")
    return "apikey", raw


def sa_token(path):
    """用 Service Account 换 access token（Bearer）。"""
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    creds = service_account.Credentials.from_service_account_file(
        # 实测（2026-10-02）：PSI 用 SA 鉴权时所需 scope 是 openid；cloud-platform 等会 403
        # （ACCESS_TOKEN_SCOPE_INSUFFICIENT）。openid 即可通。
        path, scopes=["openid"]
    )
    creds.refresh(Request())
    return creds.token


def build_params(url, strategy, categories, key):
    """构造 PSI 查询参数（纯函数，便于单测）。"""
    params = [("url", url), ("strategy", strategy)]
    if key:
        params.append(("key", key))
    for c in categories or CATEGORIES:
        params.append(("category", c))
    return params


def fetch(url, strategy, categories, auth, key=None):
    """auth=('apikey', k) 走 key= 参数；auth=('sa', path) 走 Authorization: Bearer。"""
    if auth[0] == "sa":
        params = build_params(url, strategy, categories, None)
        params = [(k, v) for k, v in params if k != "key"]
        headers = {"Authorization": f"Bearer {sa_token(auth[1])}"}
    else:
        params = build_params(url, strategy, categories, auth[1])
        headers = {}
    r = requests.get(API_URL, params=params, headers=headers, timeout=TIMEOUT)
    if r.status_code != 200:
        try:
            msg = r.json()
        except Exception:
            msg = r.text[:300]
        sys.exit(f"PSI 请求失败 {r.status_code}: {json.dumps(msg, ensure_ascii=False)[:400]}")
    return r.json()


def show_field(data):
    """CrUX 现场数据：URL 级优先，缺失则退源级。"""
    url_exp = data.get("loadingExperience") or {}
    org_exp = data.get("originLoadingExperience") or {}
    exp, scope = (url_exp, "URL 级") if url_exp.get("metrics") else (org_exp, "源级（origin）")
    if not exp.get("metrics"):
        print("\n=== CrUX 现场数据 ===\n  （无：该 URL 与源级均无足够现场样本）")
        return
    print(f"\n=== CrUX 现场数据（{scope}，采集期 {exp.get('id', '?')}）===")
    for key, payload in exp["metrics"].items():
        name, unit = FIELD_METRICS.get(key, (key, ""))
        p75 = payload.get("percentile")
        cat = CATEGORY_RANK.get(payload.get("category", ""), payload.get("category", ""))
        val = f"{p75}{unit}" if unit == "ms" else str(p75)
        dist = payload.get("distributions") or []
        shares = " / ".join(
            f"{d.get('proportion', 0) * 100:.1f}%" for d in dist[:3]
        )
        print(f"  {name:20} p75={val:8} [{cat}]   好/需改进/差 = {shares}")


def show_lab(data):
    lh = data.get("lighthouseResult") or {}
    print(f"\n=== Lighthouse 实验室（{lh.get('lighthouseVersion', '?')}，Google 侧实测）===")
    cats = lh.get("categories") or {}
    for cid, c in cats.items():
        score = c.get("score")
        label = CATEGORIES.get(cid, cid)
        mark = "✓" if (score or 0) >= 0.9 else ("!" if (score or 0) >= 0.5 else "✗")
        print(f"  {label:8} {mark} {round((score or 0) * 100)}")
    audits = lh.get("audits") or {}
    print("  --- 关键指标 ---")
    for aid, (good_max, unit, name) in LAB_METRICS.items():
        a = audits.get(aid)
        if not a:
            continue
        val = a.get("numericValue")
        disp = a.get("displayValue") or "?"
        if val is None:
            print(f"  {name:28} {disp}")
            continue
        if unit == "ms":
            mark = "✓" if val <= good_max else ("!" if val <= good_max * 2 else "✗")
            print(f"  {name:28} {disp:>10} {mark}  ({round(val)}ms)")
        else:
            mark = "✓" if val <= good_max else "✗"
            print(f"  {name:28} {disp:>10} {mark}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("PSI_API_KEY", DEFAULT_KEY))
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--strategy", default="mobile", choices=["mobile", "desktop"])
    ap.add_argument("--only", choices=["field", "lab"], help="只看现场或只看实验室")
    ap.add_argument("--json", action="store_true", help="输出原始 JSON（调试用）")
    args = ap.parse_args()

    auth = load_key(args.key)
    print(f"  （鉴权方式：{'Service Account（Bearer）' if auth[0] == 'sa' else 'API key'}）")
    data = fetch(args.url, args.strategy, None, auth)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2)[:20000])
        return 0

    print(f"=== PSI · {args.url} · {args.strategy} ===")
    if args.only != "lab":
        show_field(data)
    if args.only != "field":
        show_lab(data)
    print(
        "\n判读纪律：**本机 Lighthouse/curl 的网络类指标不可信**（出口经代理或异地）；"
        "这里的实验室数据来自 Google 侧、现场数据来自真实用户，两者才是判据。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
