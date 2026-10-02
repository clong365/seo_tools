# seo_tools — 项目说明（给未来的 agent）

GSC + Bing + GA4 + CF Web Analytics 收录/表现/流量复查的共享 CLI，供 tradelink、xianmi 及将来项目共用。

## 运行

- GSC：`.venv/bin/python gsc.py [--site 域名]`（不传 --site 列所有可访问站点）
- Bing：`.venv/bin/python bing.py --site 域名`
- GA4：`.venv/bin/python ga.py --property 属性ID`（账号 ID ≠ 属性 ID，`runReport` 用属性 ID）
- IndexNow：`indexnow.py`（推送，非查询；key 在 `~/.config/seo-tools/indexnow.json`，按 host 配置）——从 xianmi-cn/tools/submit-indexnow.mjs 移植为共享版（2026-10-02），URL 源=线上 sitemap（`--sitemap` 可重复）或 `--file`
- CF Web Analytics：`.venv/bin/python cf.py --site siteTag`（GraphQL RUM，`viewer.accounts` 下，过滤用 accountTag+siteTag）；`--edge` = zone 级 `httpRequestsAdaptiveGroups` 按日×状态码（xianmi 旧 URL 301 趋势观测，2026-10-02 加）

## 关键约束

- 依赖仅 google-auth + requests，uv 管理（`uv venv && uv pip install google-auth requests`）。
- key 放 `~/.config/seo-tools/`（gsc-sa.json / bing-api-key.txt），**绝不进 git**。
- 大陆访问 GSC / GA4 必须走 `https_proxy` 代理（requests 自动读环境变量）；Bing `ssl.bing.com` 直连。
- GA4 scope 用 `analytics.readonly`；属性用 property ID（数字），不是域名。
- CF 用 API token（Bearer），非 service account；CF 分析数据四舍五入到 10。
- Bing apikey 只能放 query string（官方鉴权），异常消息必须脱敏（`call()` 已处理，别改回）。
- 单测 stdlib unittest：`.venv/bin/python -m unittest discover -s tests -v`。
- 改脚本 HTTP 层保持 requests，别引入 httplib2 / google-api-python-client。

## 数据覆盖边界（2026-10-02 审计）

现有凭证覆盖上述全部查询功能，**无需增加权限**。以下是查不到的，别浪费时间找路径：

- **GSC 无 API 可查**（官方未开放，只能看控制台）：收录覆盖率报告（coverage）、抓取统计（crawl stats）、外链、手动处置、Discover。Core Web Vitals 需另接 CrUX API（见下）。
- **GA4**：scope 是 `analytics.readonly`（只读是设计），管理类操作查不到；用户级/Explore 部分维度仅控制台；BigQuery 导出未开通。realtime 报表同 scope 理论可用，未实测。
- **CF**：RUM 与 zone 边缘数据集可读；Workers Logs / Logpush 未配置（要看 worker 运行日志需另开）；**Workers Analytics Engine 查询未验证**（301 专项写入 `xianmi_301` dataset，查询走 GraphQL `accountTag` 下 `analyticsEngineAdaptiveGroups`，预期同一把 cfut_ 令牌已覆盖，首次用到时补记）。
- **百度**：无 API，且相关项目不做百度优化。

## 待补数据源（按需，非阻塞）

- **CrUX API key**：Core Web Vitals（真实用户 LCP/CLS/INP，按 origin 或 URL 查）。需在 GCP 申请一把普通 API key（免费，与 service account 不同物），存 `~/.config/seo-tools/crux-api-key.txt`。触发条件=要评估性能对排名的影响时。
