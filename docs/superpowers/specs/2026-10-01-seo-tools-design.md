# SEO 工具统一项目（seo_tools）设计

- 日期：2026-10-01
- 状态：设计已确认，待实现
- 范围：新建共享仓库 `~/projects/seo_tools`，合并 GSC + Bing Webmaster 复查功能

## 背景与目标

当前 tradelink、xianmi 各自维护一份 GSC/Bing 复查脚本，代码重复。目标是把两路功能合并到一个共享项目
`~/projects/seo_tools`，由 tradelink、xianmi 及将来项目共用，避免每项目一套代码。

- 统一 GSC 凭据：service account `googlesearchconsole@lyrical-country-510308-d6.iam.gserviceaccount.com`
  （已加到所有 GSC 资源，一把 key 管多域名）。
- Bing 凭据：现有 API key（按用户、非按站点，天然多域名通用）。
- 大陆网络：GSC 需走 `https_proxy` 代理；Bing `ssl.bing.com` 直连可达。

## 非目标

- 不做「一次全查所有域名」（sites 清单 + 全查是方案 B，将来站点多了再升级）。
- 不做 pip 可装包 / 控制台入口。
- 不做 URL 提交（写操作）；Bing 的 SubmitUrl/SubmitUrlBatch 默认不启用。
- 不改各站点的网站内容，只做复查。

## 目录结构

```
~/projects/seo_tools/
  gsc.py        # GSC 复查（service account）
  bing.py       # Bing 复查（API key）
  README.md     # 用法 + 配置 + 迁移说明
  .gitignore    # .venv/ __pycache__/ *.pyc
  .venv/        # uv 环境（不入库）
```

## 约定

- `--site` 接受裸域名（推荐，如 `xianmi.co`）或完整 URL（如 `https://xianmi.co/`），脚本统一规整为裸域名后使用。

## 组件设计

### gsc.py

- 依赖：google-auth + requests。
- `--key` 默认 `~/.config/seo-tools/gsc-sa.json`，可 `GOOGLE_APPLICATION_CREDENTIALS` 覆盖。
- `--site` 可选：给 `xianmi.co` 这类裸域名，脚本调 `sites.list()` 取该 key 可访问的所有资源，
  按包含匹配选中最接近的一个（域名属性 `sc-domain:*` 或 URL 前缀 `https://*/`）；不传则只列可访问站点后退出。
- `--days`（默认 28）、`--inspect-limit`（默认 50）、`--no-inspect`。
- 输出四块：可访问站点 / sitemap 状态 / Search Analytics（28 天汇总 + 按页 + 按国家）/ 逐 URL 索引判定。
- sitemap 兼容两种：先取 `/sitemap.xml`，若 404 或解析出的 `<loc>` 都是 `.xml`（索引），
  则改取 `/sitemap-index.xml` 下钻一层，收集页面 URL；否则直接用 `/sitemap.xml` 里的页面 URL。
- 合并来源：tradelink 版（平铺 sitemap）+ xianmi 版（sitemap-index 下钻）。

### bing.py

- 依赖：requests。
- `--key` 默认 `~/.config/seo-tools/bing-api-key.txt`，可 `BING_API_KEY` 覆盖。
- `--site` 必填（裸域名）→ 拼 `https://<域名>/` 作 siteUrl。
- `--days`（默认 28）。
- 输出四块：站点角色（校验 key）/ URL 提交配额 / Rank & Traffic（每日印象点击）/ 关键词表现。
- apikey 拼在 query string（Bing 官方鉴权，无 header 选项）；异常消息已脱敏，不打印含 key 的 URL；
  用 `params=` 统一 URL 编码。

## 配置与凭据

```
~/.config/seo-tools/gsc-sa.json       # service account 私钥 JSON（不进 git）
~/.config/seo-tools/bing-api-key.txt  # Bing API key（不进 git）
```

## 数据流

1. 用户 `cd ~/projects/seo_tools && .venv/bin/python gsc.py --site xianmi.co`
2. 读 key → `sites.list()` 列出可访问资源 → 匹配域名 → sitemap → analytics → URL inspection → 打印报告
3. Bing 同理：读 key → 构造 `https://域名/` → GetSiteRoles / Quota / RankAndTraffic / KeywordStats

## 错误处理与安全

- 缺 key → 明确提示生成步骤并退出。
- 授权失败 / 站点找不到 → 明确提示（含「把 client_email 加到资源的用户和权限」）。
- API 错误 → 脱敏消息（不带含 key 的 URL / 私钥）。
- 私钥与 API key 一律放仓库外，gitignore 兜底。

## 迁移与清理

- **seo_tools**：新增 gsc.py、bing.py、README.md、.gitignore，uv 建 .venv
  （`uv venv` + `uv pip install google-auth requests`），首个 commit。
- **tradelink**：删 `tools/gsc_review.py`、`tools/bing_review.py`、`docs/gsc-api-setup.md`、`docs/bing-api-setup.md`；
  README 删对应工具行与「Python 工具环境」节，改为指向 seo_tools；commit/push。
- **xianmi**（独立仓库）：删 `tools/gsc_review.py`；README/AGENTS 有引用则改指向 seo_tools；commit/push。
- 旧 key 处理：tradelink 的 `~/.config/tradelink/gsc-sa.json`（tradelink-gsc 账号）作废，可删；
  新 key 放 `~/.config/seo-tools/gsc-sa.json`。

## 验证

1. `gsc.py --site tradelink-exp.com` → 预期 16 页全 indexed（对照基线）。
2. `gsc.py --site xianmi.co` → 验证新 key 对 xianmi 已授权 + sitemap-index 下钻路径。
3. `gsc.py`（不传 --site）→ 列出新 key 可访问的所有站点（≥2：tradelink、xianmi）。
4. `bing.py --site tradelink-exp.com` → 正常输出（2 印象基线）。
5. 负向：触发一个 API 错误，确认输出不含 apikey / 私钥。
6. 迁移后回归：tradelink 与 xianmi 仓库 `git status` 干净、README 指向正确。

## 决定记录

- 结构：两个脚本 gsc.py + bing.py（用户选，最小改动）。
- 域名：`--site` 裸域名参数，不做 sites 清单（YAGNI，将来可升级方案 B）。
- 统一 key：GSC 用 googlesearchconsole 一把；Bing 用现有 key。
- 语言/环境：Python + requests，uv 管理环境（对齐 xianmi 的 uv 模式）。
