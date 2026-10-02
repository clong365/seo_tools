# GSC 收录复查（service account 只读方案）

用 Google Search Console API + service account 脚本化复查收录/表现，免手动登录 GSC。

## 为什么

- 大陆直连 Google API 被墙，需走代理；手动登录 GSC 每次都需人操作。
- service account 是长期只读凭据，一次授权后脚本随时可跑、可定期复查。

## 当前状态

| 项 | 值 |
| --- | --- |
| GSC 资源 | `sc-domain:tradelink-exp.com`、`sc-domain:xianmi.co`（域名属性，多域名共用） |
| service account | `googlesearchconsole@lyrical-country-510308-d6.iam.gserviceaccount.com` |
| GCP 项目 | `lyrical-country-510308-d6` |
| 凭据文件 | `~/.config/seo-tools/google-sa.json`（不进 git） |
| 脚本 | `gsc.py` |

## 多域名复用

service account 是 GCP 身份，与域名无关：把同一个 `client_email` 添加到任意多个 GSC 资源
（每个资源的 设置 → 用户和权限 → 添加用户 → 选「完全」），一把 JSON key 即可管所有域名。
复查别的域名改 `--site` 即可：`.venv/bin/python gsc.py --site otherdomain.com`。

## 用法

```bash
.venv/bin/python gsc.py                            # 列出该 key 能访问的所有站点
.venv/bin/python gsc.py --site xianmi.co
.venv/bin/python gsc.py --site tradelink-exp.com --no-inspect   # 跳过逐 URL 检查（更快）
```

输出四块：站点列表 / sitemap 提交收录 / Search Analytics（曝光·点击·CTR·排名，按页面/国家）/ 逐 URL 索引判定（PASS/FAIL + 收录状态 + 上次抓取）。逐 URL 检查每 URL 1s 限流，`python -u` 可看实时进度。

## 一次性配置（重装系统后照此重建）

### 1. Google Cloud：建 service account + 拿 key

1. <https://console.cloud.google.com/> 登录，新建项目（如 `lyrical-country-510308-d6`）
2. **API 和服务 → 库** → 搜 `Search Console API` → 启用
3. **IAM 和管理 → 服务账号** → 创建服务账号（名称 `googlesearchconsole`），角色两步直接「继续/完成」
4. 该账号 → **密钥 → 添加密钥 → 创建新密钥 → JSON**，下载

### 2. Google Search Console：授权 service account

5. 打开下载的 JSON，复制 `client_email`
6. <https://search.google.com/search-console> → 每个要查的资源 → **设置 → 用户和权限 → 添加用户** → 粘贴 `client_email` → 权限选 **「完全」**（URL 检查 API 需 Full，「受限」只读不够）

### 3. 本机：建 uv 环境 + 放 key

```bash
uv venv                                    # 创建 .venv（uv 管理，不入库）
uv pip install google-auth requests         # 项目 Python 依赖
mkdir -p ~/.config/seo-tools
cp <下载的json> ~/.config/seo-tools/google-sa.json
chmod 600 ~/.config/seo-tools/google-sa.json
```

## 重装系统 / JSON 丢失怎么办

**JSON 可随时重新生成**——持久资产是 service account + GSC 授权（都在云端），JSON 只是可下载的密钥材料，丢了不影响：

1. GCP 控制台 → IAM 和管理 → 服务账号 → 选 `googlesearchconsole` → 密钥 → 添加密钥 → 创建新密钥 → JSON
2. 放回 `~/.config/seo-tools/google-sa.json`，`chmod 600`
3. service account 邮箱不变，GSC 里的授权**仍在，无需重新授权**
4. 旧 key 建议在控制台删掉/吊销

## 代理要点（大陆）

- 脚本用 `requests`（自动读 `https_proxy` 环境变量），运行环境需有 `https_proxy=http://127.0.0.1:7897` 之类。
- **不要改用 httplib2**——它不读环境代理，会直连 Google 超时。

## 安全

- 私钥 JSON 不进 git：key 放 `~/.config/seo-tools/`（仓库外），`.gitignore` 兜底。私有库也不放 secrets。
- `client_email` 不是秘密，可写进文档；**私钥绝不可进仓库**。
