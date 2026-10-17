#!/usr/bin/env python3
"""每日历史快照 — GA4 / GSC / CF 边缘状态码 / /md/ 429 入本地 SQLite（共享版）。

GSC Coverage 与 GA4 Realtime 无历史可查，本工具每天落一份快照到本地库，
供跨日对比（coverage.py 管 GSC Coverage 手动导出，本脚本管 API 可查的源）。

用法:
    .venv/bin/python snapshot.py run                      # 快照昨天（默认）
    .venv/bin/python snapshot.py run --date 2026-10-11    # 补/刷指定日（幂等，同日重跑覆盖）

存储: ~/projects/seo/data/snapshots.db（仓外；--db 或 SEO_SNAPSHOT_DB 可改）。
代理: cron 环境没有交互 shell 的代理变量，Google 源必须走代理——启动时读
~/.config/seo-tools/proxy.env（KEY=VALUE，setdefault 语义不覆盖已有环境变量）；
CF 源保持直连口径（trust_env=False，不吃注入的代理）+ 超时重试一次。
cron 口径: 退出码 0=全部源成功；任一源失败=该源数据不写、其余照写，
stderr 打 `FAIL <源>: <错误>` 且退出码 1 —— 监控按退出码非零告警即可。
"""
import argparse
import datetime as dt
import os
import sqlite3
import sys

import requests

import cf
import config
import ga
import gsc

DEFAULT_DB = os.environ.get("SEO_SNAPSHOT_DB", "~/projects/seo/data/snapshots.db")
GA4_METRICS = ["screenPageViews", "engagedSessions", "sessions", "activeUsers"]
TW_PREFIX = "/zh-tw/"  # 简繁分组口径：路径前缀即语言版本
# cron 环境没有交互 shell 的代理变量；Google 源必须走代理，故启动时从这里补
PROXY_ENV_FILE = os.environ.get("SEO_PROXY_ENV", "~/.config/seo-tools/proxy.env")


def load_env_file(path):
    """读 KEY=VALUE env 文件 → dict。缺文件/注释/空行容忍；支持 export 前缀与引号。"""
    out = {}
    try:
        with open(os.path.expanduser(path)) as f:
            lines = f.readlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ").strip()
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        if k.strip():
            out[k.strip()] = v
    return out


def apply_env_file(path=PROXY_ENV_FILE):
    """setdefault 语义注入 env 文件：已存在的环境变量（交互 shell/crontab 行内 env）优先。"""
    for k, v in load_env_file(path).items():
        os.environ.setdefault(k, v)


def direct_cf_session():
    """CF 口径=直连更稳：trust_env=False，不吃 apply_env_file 注入的代理变量。"""
    s = requests.Session()
    s.trust_env = False
    return s

SCHEMA = """
CREATE TABLE IF NOT EXISTS ga4_daily (
  date TEXT NOT NULL,
  section TEXT NOT NULL,          -- cn=简体页（非 /zh-tw/ 前缀）| tw=繁体页
  screen_page_views INTEGER NOT NULL,
  engaged_sessions INTEGER NOT NULL,
  sessions INTEGER NOT NULL,
  active_users INTEGER NOT NULL,
  PRIMARY KEY (date, section)
);
CREATE TABLE IF NOT EXISTS gsc_daily (
  date TEXT NOT NULL,
  site TEXT NOT NULL,
  clicks REAL NOT NULL,
  impressions REAL NOT NULL,
  ctr REAL NOT NULL,
  position REAL NOT NULL,
  PRIMARY KEY (date, site)
);
CREATE TABLE IF NOT EXISTS cf_edge_daily (
  date TEXT NOT NULL,
  status INTEGER NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY (date, status)
);
CREATE TABLE IF NOT EXISTS cf_md429_daily (
  date TEXT NOT NULL,
  host TEXT NOT NULL,
  count INTEGER NOT NULL,
  PRIMARY KEY (date, host)
);
CREATE TABLE IF NOT EXISTS coverage_summary (
  date TEXT NOT NULL,
  bucket TEXT NOT NULL,           -- GSC issue 名，如 "Page with redirect"
  severity TEXT NOT NULL,         -- critical | non_critical
  source TEXT,
  validation TEXT,
  pages INTEGER NOT NULL,
  PRIMARY KEY (date, bucket)
);
CREATE TABLE IF NOT EXISTS coverage_urls (
  date TEXT NOT NULL,
  bucket TEXT NOT NULL,
  url TEXT NOT NULL,
  last_crawled TEXT,
  PRIMARY KEY (date, bucket, url)
);
"""


def open_db(path=DEFAULT_DB):
    """打开（必要时建库建表）并返回连接。目录不存在会自动创建。"""
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def resolve_date(value):
    """--date 缺省=昨天；给了必须是 YYYY-MM-DD。"""
    if value is None:
        return (dt.date.today() - dt.timedelta(days=1)).isoformat()
    return dt.date.fromisoformat(value).isoformat()  # 格式不对抛 ValueError


# ---------- GA4 ----------

def build_ga4_body(date, section):
    """runReport 请求体：单日、按简繁页路径前缀过滤。

    GA4 language 维度不分简繁，
    用 pagePath 前缀 /zh-tw/ 切——tw=前缀命中，cn=前缀不命中。
    """
    path_filter = {"filter": {"fieldName": "pagePath",
                              "stringFilter": {"matchType": "BEGINS_WITH",
                                               "value": TW_PREFIX}}}
    if section == "tw":
        dim_filter = path_filter
    elif section == "cn":
        dim_filter = {"notExpression": path_filter}
    else:
        raise ValueError(f"未知 section: {section!r}（只认 cn/tw）")
    return {
        "dateRanges": [{"startDate": date, "endDate": date}],
        "metrics": [{"name": m} for m in GA4_METRICS],
        "dimensionFilter": dim_filter,
    }


def ga4_section_values(resp):
    """runReport 响应 → {指标名: int}；无行（当日无流量）时全 0。"""
    _, metrics, rows = ga.format_rows(resp)
    vals = {m: 0 for m in GA4_METRICS}
    if rows:
        for name, v in zip(metrics, rows[0][1]):
            vals[name] = int(float(v or 0))
    return vals


def store_ga4(conn, date, section, values):
    conn.execute(
        "INSERT OR REPLACE INTO ga4_daily"
        " (date, section, screen_page_views, engaged_sessions, sessions, active_users)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (date, section, values["screenPageViews"], values["engagedSessions"],
         values["sessions"], values["activeUsers"]))


def fetch_ga4(conn, date, token, property_id):
    for section in ("cn", "tw"):
        r = requests.post(f"{ga.BASE}/properties/{property_id}:runReport",
                          headers={"Authorization": f"Bearer {token}"},
                          json=build_ga4_body(date, section), timeout=ga.TIMEOUT)
        r.raise_for_status()
        store_ga4(conn, date, section, ga4_section_values(r.json()))


# ---------- GSC ----------

def store_gsc(conn, date, site, row):
    conn.execute(
        "INSERT OR REPLACE INTO gsc_daily (date, site, clicks, impressions, ctr, position)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (date, site, row.get("clicks", 0), row.get("impressions", 0),
         row.get("ctr", 0), row.get("position", 0)))


def fetch_gsc(conn, date, token, site):
    """查 [date-3, date] 小窗口，按行自带日期入库。

    GSC 数据滞后 2-3 天，只查单日会让 cron 每天快照的「昨天」永远落空；
    带 3 天回看窗口，滞后的行在后续运行里幂等补齐。
    """
    start = (dt.date.fromisoformat(date) - dt.timedelta(days=3)).isoformat()
    resp = gsc.query_analytics(token, site, start, date, dimensions=["date"])
    for row in resp.get("rows", []):
        store_gsc(conn, row.get("keys", [date])[0], site, row)


# ---------- CF 边缘 ----------

def store_cf_edge(conn, date, by_status):
    for status, count in by_status.items():
        conn.execute(
            "INSERT OR REPLACE INTO cf_edge_daily (date, status, count) VALUES (?, ?, ?)",
            (date, int(status), int(count)))


def _cf_query(token, query, attempts=2):
    """CF 查询：直连 session + 超时重试一次（cron 场景一次误超时就漏一天）。"""
    session = direct_cf_session()
    for i in range(attempts):
        try:
            return cf.run_query(token, query, session=session)
        except requests.Timeout:
            if i == attempts - 1:
                raise
    raise AssertionError("unreachable")


def fetch_cf_edge(conn, date, token, zone):
    resp = _cf_query(token, cf.build_edge_query(zone, date, date, eyeball=True))
    store_cf_edge(conn, date, cf.extract_edge_rows(resp).get(date, {}))


def store_cf_md429(conn, date, by_host):
    for host, count in by_host.items():
        conn.execute(
            "INSERT OR REPLACE INTO cf_md429_daily (date, host, count) VALUES (?, ?, ?)",
            (date, host, int(count)))


def fetch_cf_md429(conn, date, token, zone):
    """/md/ 路径 429 日计数（搜索上线配套监控，正常应≈0；判读口径见 AGENTS.md）。"""
    resp = _cf_query(token, cf.build_md429_query(zone, date))
    store_cf_md429(conn, date, cf.extract_md429_rows(resp))


# ---------- 编排 ----------

def run_snapshot(date, db_path, fetchers):
    """按 fetchers={源名: fn(conn, date)} 逐源执行；单源失败不拖垮其余源。

    返回 [(源名, 异常), ...]，空列表=全部成功。同日重跑覆盖（各 store 均 upsert）。
    """
    conn = open_db(db_path)
    failures = []
    try:
        for name, fn in fetchers.items():
            try:
                fn(conn, date)
                conn.commit()
                print(f"  OK   {name}")
            except Exception as ex:
                conn.rollback()
                failures.append((name, ex))
                print(f"  FAIL {name}: {ex}", file=sys.stderr)
    finally:
        conn.close()
    return failures


def build_fetchers(args):
    """按配置构造三源 fetcher；缺哪个配置就在执行时由对应源报错（不连累其他源）。"""
    key_path = os.path.expanduser(args.key)

    def google_token():
        return gsc.get_token(key_path)

    def do_gsc(conn, date):
        site = gsc.choose_site(gsc.list_sites(google_token()), args.site)
        if not site:
            raise RuntimeError("未配 gsc_site（或 --site 不在可访问列表）")
        fetch_gsc(conn, date, google_token(), site)

    def do_ga4(conn, date):
        prop = config.require("ga_property", "GA_PROPERTY", args.property)
        fetch_ga4(conn, date, ga.get_token(key_path), prop)

    def do_cf(conn, date):
        zone = config.require("cf_zone", "CF_ZONE", args.zone)
        cf_key = os.path.expanduser(args.cf_key)
        token = open(cf_key).read().strip()
        fetch_cf_edge(conn, date, token, zone)

    def do_cf_md429(conn, date):
        zone = config.require("cf_zone", "CF_ZONE", args.zone)
        cf_key = os.path.expanduser(args.cf_key)
        token = open(cf_key).read().strip()
        fetch_cf_md429(conn, date, token, zone)

    return {"gsc": do_gsc, "ga4": do_ga4, "cf": do_cf, "cf_md429": do_cf_md429}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="快照指定日（默认昨天），幂等可重跑")
    run.add_argument("--date", default=None, help="YYYY-MM-DD，默认昨天")
    run.add_argument("--db", default=DEFAULT_DB, help="SQLite 路径")
    run.add_argument("--key", default=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS",
                                                     gsc.DEFAULT_KEY))
    run.add_argument("--cf-key", default=os.environ.get("CF_API_TOKEN", cf.DEFAULT_KEY))
    run.add_argument("--site", default=None, help="GSC 资源（默认读 sites.json）")
    run.add_argument("--property", default=None, help="GA4 属性 ID（默认读 sites.json）")
    run.add_argument("--zone", default=None, help="CF zone ID（默认读 sites.json）")
    args = ap.parse_args()

    if args.cmd == "run":
        apply_env_file()  # cron 环境无代理变量：Google 源必须走代理，从 env 文件补
        try:
            date = resolve_date(args.date)
        except ValueError:
            sys.exit(f"--date 必须是 YYYY-MM-DD: {args.date!r}")
        db_path = os.path.expanduser(args.db)
        print(f"=== 快照 {date} → {db_path} ===")
        failures = run_snapshot(date, db_path, build_fetchers(args))
        if failures:
            sys.exit(1)


if __name__ == "__main__":
    main()
