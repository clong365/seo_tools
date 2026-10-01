# Bing Webmaster 收录/表现复查（API key 只读方案）

用 Bing Webmaster Tools API + API key 脚本化复查收录/表现，免手动登录。

## 为什么

- Bing 也有 Webmaster API，鉴权比 GSC 简单：一个静态 **API key**（按用户，非按站点）。
- 大陆直连 `ssl.bing.com` 可达，**无需代理**（与 GSC 不同）。

## 当前状态

| 项 | 值 |
| --- | --- |
| API key | `~/.config/seo-tools/bing-api-key.txt`（不进 git，按用户多域名通用） |
| 脚本 | `bing.py` |

## 用法

```bash
.venv/bin/python bing.py --site tradelink-exp.com
.venv/bin/python bing.py --site xianmi.co
```

`--site` 传裸域名，脚本自动拼 `https://<域名>/`。输出四块：站点角色（校验 key）／ URL 提交配额／ Rank & Traffic（每日印象点击）／ 关键词表现（Top 查询）。

## 一次性配置（重装系统后照此重建）

1. 登录 <https://www.bing.com/webmasters>
2. 右上角 **Settings → API Access** → 同意条款 → **Generate API Key**
   （每用户一把，通用于该用户所有已验证站点）
3. 把 key 存到 `~/.config/seo-tools/bing-api-key.txt`：

```bash
mkdir -p ~/.config/seo-tools
echo "你的key" > ~/.config/seo-tools/bing-api-key.txt
chmod 600 ~/.config/seo-tools/bing-api-key.txt
```

## 与 GSC 的差异

- **鉴权**：Bing = 静态 API key（简单）；GSC = service account OAuth（复杂）。
- **没有** GSC 那种「逐 URL 是否已收录」的 URL Inspection 读接口——Bing 逐页索引状态是 UI-only。
- 需要请求收录时用 `SubmitUrl` / `SubmitUrlBatch`（写操作；配额每日 100 / 每月 3100），`bing.py` 默认不做。
- 旧 SOAP/POX API 已于 2026-08-31 退役，用 JSON/REST（端点 `https://ssl.bing.com/webmaster/api.svc/json/`）。

## 安全

- API key 不进 git（放 `~/.config/seo-tools/`，仓库外）。
- 脚本异常消息已脱敏，不打印含 apikey 的 URL。
