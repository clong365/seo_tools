# seo_tools — 项目说明（给未来的 agent）

GSC + Bing Webmaster 收录/表现复查的共享 CLI，供 tradelink、xianmi 及将来项目共用。

## 运行

- GSC：`.venv/bin/python gsc.py [--site 域名]`（不传 --site 列所有可访问站点）
- Bing：`.venv/bin/python bing.py --site 域名`

## 关键约束

- 依赖仅 google-auth + requests，uv 管理（`uv venv && uv pip install google-auth requests`）。
- key 放 `~/.config/seo-tools/`（gsc-sa.json / bing-api-key.txt），**绝不进 git**。
- 大陆访问 GSC 必须走 `https_proxy` 代理（requests 自动读环境变量）；Bing `ssl.bing.com` 直连。
- Bing apikey 只能放 query string（官方鉴权），异常消息必须脱敏（`call()` 已处理，别改回）。
- 单测 stdlib unittest：`.venv/bin/python -m unittest discover -s tests -v`。
- 改脚本 HTTP 层保持 requests，别引入 httplib2 / google-api-python-client。
