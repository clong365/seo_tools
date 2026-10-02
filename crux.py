#!/usr/bin/env python3
"""CrUX（Chrome UX Report）真实用户 Core Web Vitals 复查。

数据来自选择加入统计的 Chrome 用户，按 origin 或单 URL 给 p75 与好/需改进/差分布。

用法:
    .venv/bin/python crux.py                                  # 默认 origin https://www.xianmi.co
    .venv/bin/python crux.py --url https://www.xianmi.co/p02/
    .venv/bin/python crux.py --form-factor PHONE
key 放 ~/.config/seo-tools/crux-api-key.txt（普通 API key，非 service account）。
"""
import argparse
import os
import sys

import requests

API_URL = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
DEFAULT_KEY = "~/.config/seo-tools/crux-api-key.txt"
DEFAULT_ORIGIN = "https://www.xianmi.co"
TIMEOUT = 30

# 指标 → (阈值 good 上限, 阈值 NI 上限, 单位, 说明)；CLS 无单位
METRICS = {
    "largest_contentful_paint": (2500, 4000, "ms", "LCP 最大内容绘制"),
    "interaction_to_next_paint": (200, 500, "ms", "INP 交互到下次绘制"),
    "cumulative_layout_shift": (0.1, 0.25, "", "CLS 累积布局偏移"),
    "first_contentful_paint": (1800, 3000, "ms", "FCP 首次内容绘制"),
    "experimental_time_to_first_byte": (800, 1800, "ms", "TTFB 首字节时间"),
}


def load_key(path):
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        sys.exit(f"找不到 key 文件: {p}\n在 GCP 建 API key（限 Chrome UX Report API）后写入该文件。")
    return open(p).read().strip()


def build_body(origin=None, url=None, form_factor=None, metrics=None):
    body = {"metrics": metrics or list(METRICS)}
    if origin:
        body["origin"] = origin
    if url:
        body["url"] = url
    if form_factor:
        body["formFactor"] = form_factor
    return body


def classify(value, good_max, ni_max):
    if value <= good_max:
        return "好"
    if value <= ni_max:
        return "需改进"
    return "差"


def density_shares(histogram):
    """直方图 → 好/需改进/差 占比（CrUX 直方图三段顺序即此三分）。"""
    shares = [h.get("density", 0) for h in histogram]
    while len(shares) < 3:
        shares.append(0)
    return shares[0], shares[1], shares[2]


def run_query(key, body):
    r = requests.post(f"{API_URL}?key={key}", json=body, timeout=TIMEOUT)
    if r.status_code == 404:
        return None, "该 origin/URL 无 CrUX 数据（流量样本不足或非 Chrome 用户）"
    if r.status_code == 403:
        return None, "403：key 无效、未启用 Chrome UX Report API 或密钥限制不含该 API"
    try:
        r.raise_for_status()
    except Exception as ex:
        return None, str(ex)
    return r.json().get("record", {}), None


def print_record(key_desc, record):
    print(f"\n=== CrUX · {key_desc} ===")
    if record is None:
        return
    coll = record.get("collectionPeriod", {})
    if coll:
        print(f"  采集期 {coll.get('firstDate', {}).get('year','?')}-{coll.get('firstDate', {}).get('month','?')}"
              f" ~ {coll.get('lastDate', {}).get('year','?')}-{coll.get('lastDate', {}).get('month','?')}")
    for name, (good_max, ni_max, unit, label) in METRICS.items():
        m = record.get("metrics", {}).get(name)
        if not m:
            continue
        p75 = m.get("percentiles", {}).get("p75")
        try:
            p75n = float(p75)
        except (TypeError, ValueError):
            p75n = None
        verdict = classify(p75n, good_max, ni_max) if p75n is not None else "?"
        shares = density_shares(m.get("histogram", []))
        print(f"  {label:26} p75={p75}{unit or ''}  [{verdict}]  "
              f"好 {shares[0]*100:.1f}% / 需改进 {shares[1]*100:.1f}% / 差 {shares[2]*100:.1f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("CRUX_API_KEY", DEFAULT_KEY))
    ap.add_argument("--origin", default=DEFAULT_ORIGIN)
    ap.add_argument("--url", help="查单页而非 origin（互斥，优先 url）")
    ap.add_argument("--form-factor", choices=["PHONE", "DESKTOP", "TABLET"], help="不传=全部设备汇总")
    args = ap.parse_args()

    key = load_key(args.key)
    body = build_body(origin=None if args.url else args.origin, url=args.url,
                      form_factor=args.form_factor)
    desc = args.url or args.origin
    if args.form_factor:
        desc += f"（{args.form_factor}）"

    record, err = run_query(key, body)
    if err:
        print(f"{desc}: {err}")
        return
    print_record(desc, record)


if __name__ == "__main__":
    main()
