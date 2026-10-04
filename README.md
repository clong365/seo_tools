# seo_tools — GSC / Bing / GA4 / CF Web Analytics 复查

多站点共用的 SEO 收录 / 表现 / 流量复查 CLI。

## 环境（uv）

```bash
uv venv
uv pip install google-auth requests
```

## 凭证配置（全部放仓库外，绝不进 git）

统一放 `~/.config/seo-tools/`：

| 文件 | 用于 | 说明 |
|---|---|---|
| `google-sa.json` | GSC / GA4 / PSI | Service Account JSON，一把通用于三者 |
| `bing-api-key.txt` | Bing Webmaster | API key |
| `cf-api-token.txt` | CF Web Analytics | API token（Bearer） |
| `indexnow.json` | IndexNow | 按 host 配置的推送 key |
| `crux-api-key.txt` | CrUX | API key（**只能 API key**，SA token 不行） |
| `sites.json` | 各脚本默认站点 | 见下 |

每个数据源怎么申请、要开哪些 API、scope 给什么，属于部署细节，写在各自项目的内部文档里；本文只讲用法。要点：

- GSC / GA4 / PSI 可共用同一把 service account；**CrUX 是例外，只能 API key**。
- PSI 用 SA 时 scope 必须是 `openid`（其他 scope 一律 403）。
- GA4 用 property ID（数字），不是域名；GSC 用站点资源名。

## 站点默认值

脚本不带参数时的默认站点从 `~/.config/seo-tools/sites.json` 读，环境变量可覆盖，都没有则报错：

```json
{
  "gsc_site": "example.com",
  "cf_account": "<CF accountTag>",
  "cf_site": "<CF siteTag>",
  "cf_zone": "<CF zoneTag>",
  "ga_property": "<GA4 property ID>",
  "ae_dataset": "<AE dataset 名>",
  "origin": "https://www.example.com",
  "indexnow_host": "www.example.com"
}
```

解析顺序：**命令行 flag → 环境变量 → `sites.json` → 报错并提示怎么配**。

对应环境变量：`GSC_SITE` / `CF_ACCOUNT` / `CF_SITE` / `CF_ZONE` / `GA_PROPERTY` /
`CF_AE_DATASET` / `CRUX_ORIGIN` / `PSI_URL`。

## 用法

```bash
.venv/bin/python gsc.py                      # 复查 sites.json 的 gsc_site（不配则只列站点）
.venv/bin/python gsc.py --site example.com   # 复查指定站点
.venv/bin/python gsc.py --site example.com --no-inspect   # 只看趋势，跳过 URL Inspection（快很多）
.venv/bin/python gsc.py --site example.com --compare        # 本期 vs 上一等长期的涨跌页/查询
.venv/bin/python gsc.py --site example.com --cannibalization  # ⚠️ 贵查询，见下
.venv/bin/python bing.py --site example.com
.venv/bin/python ga.py                       # 默认 property 来自 sites.json
.venv/bin/python cf.py                       # CF Web Analytics（RUM）
.venv/bin/python cf.py --edge                # zone 边缘按日×状态码（301/404 趋势，含无 JS 爬虫）
.venv/bin/python cf.py --ae --preset 3h     # Workers Analytics Engine SQL（输出纯 JSON）
.venv/bin/python cf.py --ae --sql-file q.sql # 任意 AE SQL
.venv/bin/python crux.py                     # CrUX 真实用户 Core Web Vitals
.venv/bin/python psi.py                      # PSI：实验室 Lighthouse + 现场 CrUX 双口径
.venv/bin/python indexnow.py --file urls.txt # IndexNow 增量推送（先 --dry-run 预演）
```

### Workers Analytics Engine（`--ae`）

`POST /accounts/{account}/analytics_engine/sql`，请求体是**纯 SQL 文本**，与
`--edge` 同一把 API token。输出**纯 JSON**（与 cf CLI 结构一致），便于 `| jq` 解析。

- `--preset 3h`：近 3 小时 301/410 分组计数。dataset 名从 `sites.json` 的 `ae_dataset` 取。
- `--sql-file <path>`：跑任意 SQL，与 `--preset` 二选一。
- SQL 末尾加 `FORMAT JSON` 得单一 JSON，否则 NDJSON；**返回的数值是字符串**，求和前要转 `int`。

`--site` 接受三种写法：裸域名 `example.com`、GSC 资源名 `sc-domain:example.com`、
完整 URL `https://www.example.com/`——三者等价，都会匹配到同一个 GSC 资源。

大陆访问 GSC / GA4 需 `https_proxy` 代理；Bing、CF 直连即可。

⚠️ `gsc.py` **默认会跑最多 50 条 URL Inspection**（每条 sleep 1s + 接口本身慢）→ 单次约 3–5 分钟。只做趋势 / 收录复查时加 `--no-inspect`。

### ⚠️ `--cannibalization` 是贵查询，默认关闭

它必须按 **query + page 双维分组**查 Search Analytics。Google 官方文档原话：

> *"Queries grouped/filtered by page AND query string are the most expensive."*

而且**查询负载随日期范围变长而增加**（查 6 个月远贵于查 1 天）。

因此：

- **默认关闭**，只在显式传 `--cannibalization` 时才跑
- 日期范围别给大（默认 28 天已经够用）
- **跑完把结果缓存下来复用**，别当每次复查的默认开销
- 想省钱先用 `--days 14` 试探

`--compare` 不受此影响：它是两次单维查询 + 本地 join，不碰双维分组。

判读注意：同一页的**尾斜杠变体**（`/a/18077` 与 `/a/18077/`）会自动归并成一页，不计为竞争；
归并后仍会标出「N 个 URL 变体」——那是 canonical 问题，不是内容竞争。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```
