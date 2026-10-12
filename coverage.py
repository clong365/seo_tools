#!/usr/bin/env python3
"""GSC Coverage 手动导出导入器 + 两期对比（共享版）。

GSC Coverage（网页索引）无 API 可查，只能控制台手动导出。本工具把导出物
（整包 zip 或解压后的目录，含 drilldown 子目录的 Table.csv）规范化入本地
SQLite，之后可跨期 diff（新增/消失/桶间迁移）。

用法:
    .venv/bin/python coverage.py import <导出zip或目录> --date 2026-10-12
    .venv/bin/python coverage.py diff 2026-10-07 2026-10-12 [--bucket "Not found (404)"] [--full]
    .venv/bin/python coverage.py buckets            # 列出已有快照日期

存储与 snapshot.py 同一个库（默认 ~/projects/seo/data/snapshots.db）。

导出物形态（GSC 控制台「导出数据」）:
    Chart.csv / Critical issues.csv / Non-critical issues.csv / Metadata.csv
    <drilldown子目录>/Table.csv      # URL,Last crawled —— URL 清单的来源
    <drilldown子目录>/Metadata.csv   # Issue 行给出桶的正式名（缺省回退目录名）
"""
import argparse
import csv
import os
import sys
import tempfile
import zipfile

import snapshot

DEFAULT_DB = snapshot.DEFAULT_DB


def open_db(path=DEFAULT_DB):
    return snapshot.open_db(path)


# ---------- 解析 ----------

def _read_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.reader(f))


def _to_int(s):
    return int((s or "0").replace(",", "").strip() or 0)


def parse_issues_csv(text):
    """Critical/Non-critical issues.csv → [{reason, source, validation, pages}]。"""
    rows = []
    for r in csv.DictReader(text.lstrip("﻿").splitlines()):
        reason = (r.get("Reason") or "").strip()
        if reason:
            rows.append({"reason": reason,
                         "source": (r.get("Source") or "").strip(),
                         "validation": (r.get("Validation") or "").strip(),
                         "pages": _to_int(r.get("Pages"))})
    return rows


def parse_metadata_csv(text):
    """Metadata.csv（Property,Value 两列）→ dict。"""
    out = {}
    for r in csv.DictReader(text.splitlines()):
        k, v = (r.get("Property") or "").strip(), (r.get("Value") or "").strip()
        if k:
            out[k] = v
    return out


def parse_table_csv(text):
    """drilldown Table.csv → [(url, last_crawled)]；Last crawled 列可缺。"""
    out = []
    for r in csv.DictReader(text.splitlines()):
        url = (r.get("URL") or "").strip()
        if url:
            out.append((url, (r.get("Last crawled") or "").strip()))
    return out


# ---------- 导入 ----------

def _find_file(dirpath, want_name):
    """目录里大小写不敏感地找文件（GSC 导出文件名带空格，各版大小写不完全稳定）。"""
    for name in os.listdir(dirpath):
        if name.lower() == want_name.lower():
            return os.path.join(dirpath, name)
    return None


def _read_text(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def _import_dir(conn, root, date):
    """从已解压目录导入。返回计数 dict；找不到任何可导入内容时 sys.exit。"""
    # 1) 桶汇总：Critical / Non-critical issues.csv
    summary = []
    for fname, severity in (("Critical issues.csv", "critical"),
                            ("Non-critical issues.csv", "non_critical")):
        p = _find_file(root, fname)
        if p:
            for row in parse_issues_csv(_read_text(p)):
                summary.append((row, severity))

    # 2) drilldown：任何含 Table.csv 的子目录（桶名取 Metadata.csv 的 Issue 行）
    url_rows = []  # (bucket, url, last_crawled)
    buckets_with_urls = set()
    for base, dirs, files in os.walk(root):
        table = next((f for f in files if f.lower() == "table.csv"), None)
        if not table:
            continue
        meta = next((f for f in files if f.lower() == "metadata.csv"), None)
        bucket = None
        if meta:
            bucket = parse_metadata_csv(_read_text(os.path.join(base, meta))).get("Issue")
        bucket = bucket or os.path.basename(base)
        for url, last_crawled in parse_table_csv(_read_text(os.path.join(base, table))):
            url_rows.append((bucket, url, last_crawled))
        buckets_with_urls.add(bucket)

    if not summary and not url_rows:
        sys.exit(f"{root} 里没找到 GSC Coverage 导出物"
                 f"（既无 *issues.csv 也无 drilldown 的 Table.csv）")

    # 幂等：同日重导整体替换，不是叠加
    conn.execute("DELETE FROM coverage_summary WHERE date = ?", (date,))
    conn.execute("DELETE FROM coverage_urls WHERE date = ?", (date,))
    conn.executemany(
        "INSERT INTO coverage_summary (date, bucket, severity, source, validation, pages)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [(date, r["reason"], sev, r["source"], r["validation"], r["pages"])
         for r, sev in summary])
    conn.executemany(
        "INSERT OR REPLACE INTO coverage_urls (date, bucket, url, last_crawled)"
        " VALUES (?, ?, ?, ?)",
        [(date, b, u, lc) for b, u, lc in url_rows])
    conn.commit()
    return {"buckets": len(summary), "buckets_with_urls": len(buckets_with_urls),
            "urls": len(url_rows)}


def import_export(conn, path, date):
    """导入一个导出 zip 或目录。"""
    path = os.path.expanduser(path)
    if zipfile.is_zipfile(path):
        with tempfile.TemporaryDirectory() as tmp:
            with zipfile.ZipFile(path) as z:
                z.extractall(tmp)
            # zip 里可能再套一层同名目录，下钻到含导出物的那层
            return _import_dir(conn, _descend(tmp), date)
    if os.path.isdir(path):
        return _import_dir(conn, path, date)
    sys.exit(f"既不是 zip 也不是目录: {path}")


def _descend(root):
    """zip 解开只有一层外壳目录时自动下钻。"""
    entries = os.listdir(root)
    while len(entries) == 1 and os.path.isdir(os.path.join(root, entries[0])):
        root = os.path.join(root, entries[0])
        entries = os.listdir(root)
    return root


# ---------- 对比 ----------

def _url_map(conn, date):
    """date → {url: set(buckets)}。"""
    out = {}
    for bucket, url in conn.execute(
            "SELECT bucket, url FROM coverage_urls WHERE date = ?", (date,)):
        out.setdefault(url, set()).add(bucket)
    return out


def _summary_map(conn, date):
    return {b: p for b, p in conn.execute(
        "SELECT bucket, pages FROM coverage_summary WHERE date = ?", (date,))}


def _known_dates(conn):
    return {r[0] for t in ("coverage_urls", "coverage_summary")
            for r in conn.execute(f"SELECT DISTINCT date FROM {t}")}


def diff_snapshots(conn, date_a, date_b, bucket=None):
    """两期对比。

    不加 --bucket（全局视角）：
      added   = B 期才出现的 URL（A 期任何桶都没有），按 B 期桶归类
      removed = A 期有、B 期任何桶都没有的 URL，按 A 期桶归类
      migrated= 两期都在但桶变了的 URL → (url, 旧桶, 新桶)
    加 --bucket（单桶视角）：该桶的纯集合差（进/出都列出，不做迁移归并）。
    """
    known = _known_dates(conn)
    for d in (date_a, date_b):
        if d not in known:
            sys.exit(f"没有 {d} 的快照。已有: {', '.join(sorted(known)) or '(空)'}")

    map_a, map_b = _url_map(conn, date_a), _url_map(conn, date_b)

    def by_bucket(mapping, urls):
        out = {}
        for u in sorted(urls):
            for b in sorted(mapping[u]):
                out.setdefault(b, []).append(u)
        return out

    if bucket:
        in_a = {u for u, bs in map_a.items() if bucket in bs}
        in_b = {u for u, bs in map_b.items() if bucket in bs}
        added = {bucket: sorted(in_b - in_a)} if in_b - in_a else {}
        removed = {bucket: sorted(in_a - in_b)} if in_a - in_b else {}
        migrated = []
    else:
        added = by_bucket(map_b, set(map_b) - set(map_a))
        removed = by_bucket(map_a, set(map_a) - set(map_b))
        migrated = [(u, "|".join(sorted(map_a[u])), "|".join(sorted(map_b[u])))
                    for u in sorted(set(map_a) & set(map_b))
                    if map_a[u] != map_b[u]]

    sum_a, sum_b = _summary_map(conn, date_a), _summary_map(conn, date_b)
    summary = {b: (sum_a.get(b), sum_b.get(b))
               for b in sorted(set(sum_a) | set(sum_b))
               if sum_a.get(b) != sum_b.get(b)}
    return {"added": added, "removed": removed, "migrated": migrated,
            "summary": summary}


def list_dates(conn):
    """[(date, 汇总桶数, URL 行数)]，按日期升序。"""
    dates = sorted(_known_dates(conn))
    out = []
    for d in dates:
        nb = conn.execute(
            "SELECT COUNT(*) FROM coverage_summary WHERE date = ?", (d,)).fetchone()[0]
        nu = conn.execute(
            "SELECT COUNT(*) FROM coverage_urls WHERE date = ?", (d,)).fetchone()[0]
        out.append((d, nb, nu))
    return out


# ---------- CLI ----------

def _print_urls(title, mapping, full):
    total = sum(len(v) for v in mapping.values())
    print(f"\n  {title}（{total}）:")
    for b, urls in sorted(mapping.items()):
        print(f"    [{b}] {len(urls)} 条")
        shown = urls if full else urls[:100]
        for u in shown:
            print(f"      {u}")
        if not full and len(urls) > 100:
            print(f"      … 其余 {len(urls) - 100} 条略（--full 全量）")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB, help="SQLite 路径")
    sub = ap.add_subparsers(dest="cmd", required=True)

    imp = sub.add_parser("import", help="导入导出 zip 或目录")
    imp.add_argument("path")
    imp.add_argument("--date", required=True, help="快照日期 YYYY-MM-DD（导出当日）")

    dif = sub.add_parser("diff", help="两期对比（新增/消失/桶间迁移）")
    dif.add_argument("date_a")
    dif.add_argument("date_b")
    dif.add_argument("--bucket", default=None, help="只看一个桶（纯集合差）")
    dif.add_argument("--full", action="store_true", help="URL 清单不截断")

    sub.add_parser("buckets", help="列出已有快照日期")
    args = ap.parse_args()

    conn = open_db(args.db)
    try:
        if args.cmd == "import":
            try:
                date = snapshot.resolve_date(args.date)
            except ValueError:
                sys.exit(f"--date 必须是 YYYY-MM-DD: {args.date!r}")
            counts = import_export(conn, args.path, date)
            print(f"已导入 {date}: 汇总桶 {counts['buckets']} 个，"
                  f"drilldown 桶 {counts['buckets_with_urls']} 个，URL {counts['urls']} 条"
                  f" → {os.path.expanduser(args.db)}")

        elif args.cmd == "buckets":
            dates = list_dates(conn)
            if not dates:
                print("(库中还没有 coverage 快照，先 coverage.py import)")
            print(f"  {'日期':12}{'汇总桶':>8}{'URL 行数':>10}")
            for d, nb, nu in dates:
                print(f"  {d:12}{nb:>8}{nu:>10}")

        elif args.cmd == "diff":
            d = diff_snapshots(conn, args.date_a, args.date_b, bucket=args.bucket)
            print(f"=== Coverage diff {args.date_a} → {args.date_b}"
                  + (f"（仅桶 {args.bucket}）" if args.bucket else "") + " ===")
            if d["summary"]:
                print("\n  桶计数变化:")
                for b, (pa, pb) in d["summary"].items():
                    print(f"    {pa if pa is not None else '—':>8} → "
                          f"{pb if pb is not None else '—':<8} {b}")
            _print_urls("新增", d["added"], args.full)
            _print_urls("消失", d["removed"], args.full)
            print(f"\n  桶间迁移（{len(d['migrated'])}）:")
            for u, fa, fb in d["migrated"][:None if args.full else 100]:
                print(f"    {fa} → {fb}  {u}")
            if not args.full and len(d["migrated"]) > 100:
                print(f"    … 其余 {len(d['migrated']) - 100} 条略（--full 全量）")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
