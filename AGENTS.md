# seo_tools — 项目说明（给未来的 agent）

GSC + Bing + GA4 + CF Web Analytics + CrUX + PSI 收录/表现/流量/性能复查的共享 CLI，多站点共用。

> 站点拓扑、真实属性 ID、凭证申请步骤属于部署细节，放在本仓库外的内部文档里，本文只留通用结论。

## 运行

- GSC：`.venv/bin/python gsc.py [--site 站点] [--no-inspect] [--compare] [--cannibalization]`
  （不传 `--site` 时用 `sites.json` 的 `gsc_site`；**没配 gsc_site 才**只列站点然后退出。
  `--site` 接受裸域名 / `sc-domain:` 前缀 / 完整 URL 三者等价——`normalize_site` 会把
  `sc-domain:` 一并规整掉，与 `pick_site` 的裸域名比对口径一致）。⚠️ **默认会跑最多 50 条 URL Inspection（`--inspect-limit`，每条 sleep 1s + 接口本身慢）→ 单次约 3–5 分钟**；只做趋势/收录复查时**加 `--no-inspect`**（实测 7 秒完成）。2026-10-02 实测：不加时 200s 超时仍无输出，易被误判为"卡死/凭证坏了"——**不是**，凭证与接口都是好的。
- Bing：`.venv/bin/python bing.py --site 域名`
- GA4：`.venv/bin/python ga.py [--property 属性ID]`（账号 ID ≠ 属性 ID，`runReport` 用属性 ID）
- IndexNow：`indexnow.py`（推送，非查询；key 在 `~/.config/seo-tools/indexnow.json`，按 host 配置）——从某站点项目的 submit-indexnow.mjs 移植为共享版（2026-10-02），URL 源=线上 sitemap（`--sitemap` 可重复）或 `--file`
- CF Web Analytics：`.venv/bin/python cf.py`（GraphQL RUM，`viewer.accounts` 下，过滤用 accountTag+siteTag）；`--edge` = zone 级 `httpRequestsAdaptiveGroups` 按日×状态码（旧 URL 301 趋势观测，2026-10-02 加）——**默认只统计 `requestSource: "eyeball"`（真实客户端，含爬虫）**，`--all-sources` 才含全部来源（含 `edgeWorkerCacheAPI` 遥测行）
- CrUX：`.venv/bin/python crux.py [--url 单页] [--form-factor PHONE|DESKTOP]`（真实用户 Core Web Vitals；默认 origin 读 `sites.json`；key 在 `~/.config/seo-tools/crux-api-key.txt`，GCP 项目里 API 限制=仅 Chrome UX Report API）
- PSI：`.venv/bin/python psi.py [--url …] [--strategy mobile|desktop] [--only field|lab]`（默认 key=`~/.config/seo-tools/google-sa.json` —— **与 GSC/GA4 同一把 SA**，无需另存）（**鉴权：Service Account JSON 即可，scope 必须是 `openid`**——实测 2026-10-02：`cloud-platform`/`cloud-platform.read-only`/`userinfo.email` 均 403 `ACCESS_TOKEN_SCOPE_INSUFFICIENT`，只有 `openid` 通过；同一把 `google-sa.json` 可直接用，**无需另建 API key**。PageSpeed Insights：**实验室数据由 Google 侧跑 Lighthouse** + **CrUX 现场数据**，因此不受我们本机代理/异地出口干扰；也可用独立 API key，GCP 项目里启用 PageSpeed Insights API 后创建即可，免费）

## 站点默认值

真实属性 ID / 域名一律**不写进代码**。解析顺序见 `config.py`：

```
命令行 flag  →  环境变量  →  ~/.config/seo-tools/sites.json  →  报错并提示怎么配
```

环境变量：`GSC_SITE` / `CF_ACCOUNT` / `CF_SITE` / `CF_ZONE` / `GA_PROPERTY` / `CRUX_ORIGIN` / `PSI_URL`。

⚠️ **`normalize_site` 必须去掉 `sc-domain:` 前缀**（2026-10-04 修）：`pick_site` 是拿裸域名
比对的，若入参带着前缀则永远匹配不上。曾因此 `--site sc-domain:xxx` 静默失败。
改 `normalize_site` 时别把这一步去掉。

## GSC 查询成本（2026-10-03 加 --compare / --cannibalization 时定的约束）

Google Search Analytics 的**负载**（load quota）不是按次数算，是按查询开销算。官方文档：

> *"Queries grouped/filtered by page AND query string are the most expensive."*
> *"Query load increases with the date range queried."*

**成本分档**（从便宜到贵）：

| 查询 | 维度 | 成本 | 用在哪 |
|---|---|---|---|
| 汇总 | 无 | 最低 | `search_analytics` 总览 |
| 单维 | `page` 或 `query` 或 `country` | 低 | top 页面/国家、**`--compare`** |
| **双维** | **`query` + `page`** | **最贵** | **`--cannibalization`** |

由此定的规矩：

- **`--compare` 用两次单维查询 + 本地 join**，不碰双维分组，因此可以常开。
- **`--cannibalization` 默认关闭**（`action="store_true"`，不传就不查）。要做同词多页分析才开。
- 双维查询的日期范围**别给大**（默认 28 天），`row_limit` 控住（现 5000）。
- **跑完缓存结果复用**，别当每次复查的默认开销。
- 超限报 `quota exceeded`：短周期（10 分钟）等 15 分钟重试；长周期（1 天）只能摊到全天。
  详见 [Usage Limits](https://developers.google.com/webmaster-tools/limits)。

**判读陷阱**：同一页的尾斜杠变体（`/a/1` 与 `/a/1/`）在 GSC 里是两行，
不归并会把 canonical 问题误报成关键词竞争。`find_cannibalization()` 已按
`normalize_page()` 归并，但仍保留 `variants` 列出原 URL——「一页多 URL」本身要单独看。

## 关键约束

- 依赖仅 google-auth + requests，uv 管理（`uv venv && uv pip install google-auth requests`）。
- key 放 `~/.config/seo-tools/`（google-sa.json / bing-api-key.txt / cf-api-token.txt / indexnow.json / crux-api-key.txt / sites.json），**绝不进 git**。
- **真实标识符（属性 ID、CF tag、域名）不进源码**，走 `sites.json` / 环境变量。
- 大陆访问 GSC / GA4 必须走 `https_proxy` 代理（requests 自动读环境变量）；Bing `ssl.bing.com` 直连。
- GA4 scope 用 `analytics.readonly`；属性用 property ID（数字），不是域名。
- CF 用 API token（Bearer），非 service account；CF 分析数据四舍五入到 10。
- Bing apikey 只能放 query string（官方鉴权），异常消息必须脱敏（`call()` 已处理，别改回）。
- 单测 stdlib unittest：`.venv/bin/python -m unittest discover -s tests -v`。
- 改脚本 HTTP 层保持 requests，别引入 httplib2 / google-api-python-client。
- 通用小函数（如 `normalize_site`）各文件各写各的，不为单函数建共享模块；`config.py` 是例外（4 处调用、逻辑不止 3 行）。

## CF GraphQL 速查（2026-10-02 实测）

端点 `https://api.cloudflare.com/client/v4/graphql`，Bearer = cf-api-token.txt。

| 数据集 | 位置 | 用途 | 关键维度 |
|---|---|---|---|
| `rumPageloadEventsAdaptiveGroups` | `viewer.accounts(filter: {accountTag})` | CF Web Analytics（JS beacon，无 JS 爬虫不计） | `siteTag`（过滤）、`countryName`、`requestPath`、`deviceType` |
| `httpRequestsAdaptiveGroups` | `viewer.zones(filter: {zoneTag})` | 边缘真实请求（含无 JS 爬虫） | `date`、`edgeResponseStatus`、**`clientRequestPath`**、`clientCountryName`、**`requestSource`** |

- ⚠️ **路径维度名两头不一样**：RUM 数据集是 `requestPath`，边缘数据集是 **`clientRequestPath`**（写成 `requestPath` 会静默返回 null 结果，不报错——2026-10-02 排查 404 构成时踩过）。
- ⚠️ **查状态码趋势必须加 `requestSource: "eyeball"`**（2026-10-02 review 定性）：Worker 里每次 `caches.default.match/put` 都会被 CF 记成 `requestSource: "edgeWorkerCacheAPI"` 的**额外请求行**——它们带 `clientRequestHTTPProtocol: UNK`、`userAgent` 空、路径是 cache key 形状，且**会出现 504/204**。这不是站点故障：当日实测该来源占 504 记录的 **100%**，而 `requestSource: "eyeball"`（真实客户端，含爬虫）**504 = 0**；同日 204 的 16 倍"暴涨"同源。**不加这个过滤，监控图会被遥测噪声淹没**（对照：200 的 protocol 分布 HTTP/1.1/2/3 齐全、UNK 仅一小部分，UNK 是有区分度的信号）。
  - 另注：`originResponseStatus` 在本数据集下 200/404/504/204 **一律为 0**，是无效值，**不能**当"未到源"的判据。
- 模糊匹配路径用 `clientRequestPath_like: "/page%"`；按计数排序 `orderBy: [count_DESC]`。
- 边缘数据集按 `date`（`date_geq`/`date_leq`，格式 `YYYY-MM-DD`）过滤；RUM 用 `datetime_geq`/`datetime_leq`（ISO8601）。
- Analytics Engine 查询：写 SQL 到文件后 `cf analytics_engine sql query --file q.sql`（SQL 末尾加 `FORMAT JSON` 得单一 JSON，否则 NDJSON；返回的数值是**字符串**，求和前要转 int）。示例：`SELECT blob1 AS family, blob3 AS site, blob4 AS kind, count() AS n FROM <dataset> WHERE timestamp > NOW() - INTERVAL '6' HOUR GROUP BY family, site, kind ORDER BY n DESC FORMAT JSON`（301/410 打点用）。
- 参考实现：`cf.py`（RUM 汇总/国家/路径/设备）与 `cf.py --edge`（zone 边缘按日×状态码）。

## 数据覆盖边界（2026-10-02 审计）

现有凭证覆盖**绝大多数**查询功能。⚠️ **`2026-10-02 更正`：原写"无需增加权限"已被证伪**——见下方"CF 边缘响应时间指标"条（`edgeTimeToFirstByteMs` 两把凭证都无权限，属需另配 scope 的例外）。以下是查不到的，别浪费时间找路径：

- **GSC 无 API 可查**（官方未开放，只能看控制台）：收录覆盖率报告（coverage）、抓取统计（crawl stats）、外链、手动处置、Discover。Core Web Vitals 走 CrUX（见运行节）。
- **GA4**：scope 是 `analytics.readonly`（只读是设计），管理类操作查不到；用户级/Explore 部分维度仅控制台；BigQuery 导出未开通。realtime 报表同 scope 理论可用，未实测。
- **CF 边缘响应时间指标：schema 里有、本 token 拿不到**（2026-10-02 实测）：`ZoneHttpRequestsAdaptiveGroupsAvg/Quantiles` 暴露 `edgeTimeToFirstByteMs`、`edgeDnsResponseTimeMs`、`originResponseDurationMs` 等（含 P25–P999 分位），但查 `avg { edgeTimeToFirstByteMs }` 或 `quantiles { edgeTimeToFirstByteMsP50 }` 一律 **authz 拒绝**（"zone … does not have access to the field"，schema 字段名会小写成 edgetimetofirstbytems，可据此辨认这棵错误）。⚠️ **不要拿 `originResponseDurationMs` 当"取源时延"**：按 colo 分组时绝大多数组返回 null（Worker+Cache API 路径没有传统 origin），仅少数 colo 有值（实测 AMS 42.6ms / CDG 188ms），不能用来做"距离 vs 延迟"判断。**结论：按 colo 测边缘延迟这条路在 API 上不通。** 另一条替代路径（无需 API）：**CF 控制台 → Analytics → Performance 页按 colo 显示 TTFB**，可直接看"各 colo TTFB 是否随距离拉长"。review 另用 cf CLI 的 469-scope OAuth 复测，`edgeTimeToFirstByteMs` **同样 authz 拒绝** → 换凭证解决不了，需另配权限。
- **CF**：RUM 与 zone 边缘数据集可读；Workers Logs / Logpush 未配置（要看 worker 运行日志需另开）；**Workers Analytics Engine 查询未验证**（301 专项写入自建 dataset，查询走 GraphQL `accountTag` 下 `analyticsEngineAdaptiveGroups`，预期同一把 cfut_ 令牌已覆盖，首次用到时补记）。
- **百度**：无 API，且相关项目不做百度优化。
- **两种鉴权不可互换（2026-10-02 实测，别浪费时间试）**：
  - **CrUX 只能 API key**：带 SA token（`openid` 或 `cloud-platform`）请求 → **400 INVALID_ARGUMENT**；SA token + key 参数同时给也 400；**只有 API key 参数**得到 200 ⇒ `crux-api-key.txt` **不可删**。
  - **PSI 反过来**：SA token（**scope 必须 `openid`**）→ 200，无需 API key；`cloud-platform`/`cloud-platform.read-only`/`userinfo.email` 均 403 `ACCESS_TOKEN_SCOPE_INSUFFICIENT`。
  - 同项目同一把 SA 可同时用于 GSC / GA4 / PSI；**CrUX 是个例外**（key-only）。
- **PSI（PageSpeed Insights）**：必须有 API key——**无 key 直连会落到共享默认项目并报 429**（实测 2026-10-02：共享默认项目 `project_number:583797351490` 日配额已耗尽）；字段名注意：现场数据在 `loadingExperience`（URL 级，长尾页常缺失）/`originLoadingExperience`（源级，兜底）。

## 待补数据源（按需，非阻塞）

- （暂无。CrUX 已于 2026-10-02 接入，见运行节。）
