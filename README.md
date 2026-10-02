# seo_tools — GSC / Bing / GA4 / CF Web Analytics 复查

tradelink、xianmi 及将来项目共用的 SEO 收录/表现/流量复查脚本。

## 环境（uv）

```bash
uv venv
uv pip install google-auth requests
```

## key 配置（放仓库外）

- GSC service account：`~/.config/seo-tools/gsc-sa.json`（配置见 `docs/gsc-api-setup.md`）
- Bing API key：`~/.config/seo-tools/bing-api-key.txt`（配置见 `docs/bing-api-setup.md`）
- GA4 用同一把 service account：`~/.config/seo-tools/gsc-sa.json`（配置见 `docs/ga-setup.md`）
- CF Web Analytics：`~/.config/seo-tools/cf-api-token.txt`（配置见 `docs/cf-setup.md`）

## 用法

```bash
.venv/bin/python gsc.py                      # 列出 key 能访问的所有站点
.venv/bin/python gsc.py --site xianmi.co
.venv/bin/python bing.py --site tradelink-exp.com
.venv/bin/python ga.py --property 507549889
.venv/bin/python cf.py
.venv/bin/python cf.py --edge           # zone 级边缘请求按日×状态码（301/404 趋势，含无 JS 爬虫）
.venv/bin/python indexnow.py --site www.xianmi.co --sitemap /sitemap-index.xml --sitemap /zh-tw/sitemap-index.xml  # IndexNow 全量推送
.venv/bin/python indexnow.py --file urls.txt     # 增量推送（先 --dry-run 预演）
.venv/bin/python crux.py                 # CrUX 真实用户 Core Web Vitals（--url 单页 / --form-factor PHONE）
```

大陆访问 GSC / GA4 需 `https_proxy` 代理；Bing、CF 直连即可。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```
