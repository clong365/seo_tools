# GA4 流量复查（service account 只读方案）

用 Google Analytics Data API + service account 脚本化复查流量，免手动登录 GA4。

## 为什么

- 大陆直连 Google API 被墙，需走代理；手动登录 GA4 每次都要人操作。
- service account 是长期只读凭据，一次授权后脚本随时可跑。

## 当前状态

| 项 | 值 |
| --- | --- |
| 账号 | `370440379`（goodweb） |
| 属性 | `507549889` |
| service account | `googlesearchconsole@lyrical-country-510308-d6.iam.gserviceaccount.com`（与 GSC 共用） |
| 凭据文件 | `~/.config/seo-tools/google-sa.json`（不进 git） |
| 脚本 | `ga.py` |

## 用法

```bash
.venv/bin/python ga.py --property 507549889          # 默认 goodweb
.venv/bin/python ga.py --property <id> --days 90     # 自定义属性/时间窗
.venv/bin/python ga.py --limit 50                    # 每个维度 Top N
```

输出四块：总览 / 按国家 / 按页面 / 按语言（activeUsers · sessions · screenPageViews）。

## 一次性配置（重装系统后照此重建）

### 1. GCP：启用 Analytics Data API

1. <https://console.cloud.google.com/> → 选项目 `lyrical-country-510308-d6`
2. **API 和服务 → 库** → 搜 `Analytics Data API` → 启用

### 2. GA4：授权 service account

3. <https://analytics.google.com/> → 左下角齿轮 **管理**
4. 中间「属性」列选目标属性 → **属性访问管理** → **+ 添加用户**
5. 邮箱填 `googlesearchconsole@lyrical-country-510308-d6.iam.gserviceaccount.com` → 权限选 **「查看者」**（Viewer）

### 3. 本机：放 key（与 GSC 共用同一 JSON，无需重复）

```bash
uv venv && uv pip install google-auth requests
mkdir -p ~/.config/seo-tools
cp <下载的service account json> ~/.config/seo-tools/google-sa.json
chmod 600 ~/.config/seo-tools/google-sa.json
```

## 怎么拿 property ID

- 管理 → 属性设置 → 「属性 ID」
- 或 GA4 地址栏 URL 里 `p` 后面的数字（`#/p507549889/...`）

## 与 GSC 的差异

- 鉴权相同（同一 service account），scope 换成 `analytics.readonly`。
- 标识用 **property ID（数字）**，不是域名；**账号 ID ≠ 属性 ID**（`runReport` 要属性 ID）。
- 大陆需代理（与 GSC 相同）。

## 安全

- key 不进 git（放 `~/.config/seo-tools/`，仓库外）。
