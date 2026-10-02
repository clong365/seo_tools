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
