"""站点默认值解析 — 命令行 flag > 环境变量 > ~/.config/seo-tools/sites.json > 报错。

真实标识符（属性 ID、CF tag、域名）一律不写进源码，走这里。
"""
import json
import os
import sys

DEFAULT_CONF = os.environ.get("SEO_SITES_CONF", "~/.config/seo-tools/sites.json")


def load_sites(conf_path=None):
    """读 sites.json；文件缺失或不是 JSON 对象时返回 {}。"""
    path = os.path.expanduser(conf_path or DEFAULT_CONF)
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve(key, env_var, cli_value=None, conf_path=None):
    """flag > 环境变量 > sites.json[key]；都取不到返回 None。

    cli_value 传 None 表示「未在命令行给出」，不能当成空值去覆盖后面的来源。
    """
    if cli_value:
        return cli_value
    val = os.environ.get(env_var)
    if val:
        return val
    val = load_sites(conf_path).get(key)
    return val or None


def require(key, env_var, cli_value=None, conf_path=None):
    """同 resolve；取不到则退出，并说明三种配法。"""
    val = resolve(key, env_var, cli_value, conf_path)
    if val:
        return val
    conf = os.path.expanduser(conf_path or DEFAULT_CONF)
    sys.exit(
        f"缺少 {key}。\n"
        f"三种配法任选：\n"
        f"  1. 命令行参数直接传\n"
        f"  2. 环境变量 {env_var}=<值>\n"
        f"  3. 在 sites.json 配置里加 \"{key}\": \"<值>\"（查找路径：{conf}）"
    )
