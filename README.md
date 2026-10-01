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
```

大陆访问 GSC / GA4 需 `https_proxy` 代理；Bing、CF 直连即可。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```
