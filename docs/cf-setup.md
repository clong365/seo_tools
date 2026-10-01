# CF Web Analytics 流量复查（GraphQL RUM 只读方案）

用 Cloudflare GraphQL Analytics API 查 Web Analytics（RUM）访客数据，免登录 Dashboard。

## 为什么

- CF Web Analytics 提供精确访客级数据（visits / page views），但 Dashboard 无直接 API 导出。
- GraphQL Analytics API 能脚本化查询 RUM 数据集。
- 大陆直连 `api.cloudflare.com` 可达，**无需代理**。

## 当前状态

| 项 | 值 |
| --- | --- |
| accountTag | `397a5866d88bb11a4f17b710d74f30c8`（Chenlong365 账号） |
| siteTag（xianmi.co） | `406eb07464064ef680745db6a060efba` |
| zone ID（xianmi.co） | `35ff812beaa004cd12cd62ff30383fe1` |
| token | `~/.config/seo-tools/cf-api-token.txt`（不进 git） |
| 脚本 | `cf.py` |

## 用法

```bash
.venv/bin/python cf.py                          # 默认 xianmi.co
.venv/bin/python cf.py --site <siteTag> --days 90
```

输出四块：总览 / 按国家 / 按页面 / 按设备（visits · views）。

## 一次性配置

### 1. 生成 API token（Read analytics and logs，所有区域）

<https://dash.cloudflare.com/profile/api-tokens> → 创建令牌 → 模板「读取分析数据」→
区域资源「所有区域」（不限 zone，账号下所有域名通用）→ 创建。放 `~/.config/seo-tools/cf-api-token.txt`。

### 2. 拿 accountTag / siteTag / zone ID

```bash
cf accounts list          # accountTag = id
cf rum site-info list     # 每个站点的 site_tag（=siteTag）+ zone_tag（=zone ID）
```

## 数据说明

- `sum.visits` = 访客数；`count` = page load 事件数（≈ page views）。
- **CF 分析数据四舍五入到 10**：小数值（100、200…）是约数，大数值（>1 万）精确。
- 维度：`countryName` / `requestPath` / `deviceType` / `date` / `bot` / `refererHost` 等。
- 数据集在 `viewer.accounts` 下（**不是 zones**），过滤用 `accountTag` + `siteTag`。

## 与 GSC/GA4 的差异

- 鉴权：CF API token（Bearer），非 service account。
- cf CLI 只能**管理** Web Analytics（`cf rum site-info`），查统计数据走 GraphQL。
- 大陆直连（无需代理）。

## 安全

- token 不进 git（放 `~/.config/seo-tools/`，仓库外）。
