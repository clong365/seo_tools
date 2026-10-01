# seo_tools — GSC / Bing Webmaster 复查

tradelink、xianmi 及将来项目共用的 SEO 收录/表现复查脚本。

## 环境（uv）

```bash
uv venv
uv pip install google-auth requests
```

## key 配置（放仓库外）

- GSC service account：`~/.config/seo-tools/gsc-sa.json`
- Bing API key：`~/.config/seo-tools/bing-api-key.txt`

## 用法

```bash
.venv/bin/python gsc.py                      # 列出 key 能访问的所有站点
.venv/bin/python gsc.py --site xianmi.co
.venv/bin/python bing.py --site tradelink-exp.com
```

大陆访问 GSC 需 `https_proxy` 代理；Bing 直连即可。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```
