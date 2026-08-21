"""环境记录 —— `~/.webmuxd.json`(docs/v2/works/07-runtime.md §4.4)。

**这不是配置文件,是机器的事实。** `webmuxd install` 探一遍写下来,
之后所有命令读它。

    {"version": 2, "at": "…",
     "default_browser": {"path": "~/.cache/webmuxd/chrome-152…/chrome",
                         "version": "152.0.7977.42",
                         "source": "chrome-for-testing"}}

**键在 = 探到了,键不在 = 没探到。** 没有 `default_browser` 就是
"这个网络环境下不到那个浏览器",于是留空让人自己填 —— 而不是记一个
不存在的路径骗后面的自己。

v1 记的是 docker 和镜像;**v2 不再关心机器上有没有 docker**(works/07 §2),
那两个键连同 `default_container` 一起没了。格式版本因此从 1 跳到 2 ——
老记录读不动就当没有,重新探。

三条规矩:

1. **没有记录就现探。** 不存在不是错误 —— `install` 省的是重复开销,
   不是"必须先装"。写脚本的人不该被一个 CLI 步骤挡住。
2. **信记录,但别替它兜底。** 记录会撒谎(你 `rm -rf` 了缓存目录它不知道),
   所以按记录去起,起不来就报错**并让人重跑 install**。
3. **不静默重探。** 每次都重探等于 install 白做;时探时不探更糟 ——
   你就不知道自己看到的是什么时候的事实。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

#: 记录格式的版本。**格式变了老记录就当没有** —— 重新探,而不是猜字段。
#:
#: 2 → 3:从"只记浏览器"扩成 [d §1](../docs/v2/works/d-install.md#1-产出一份路径表)
#: 那张完整的路径表。老记录缺后面那些键,补不出来也不该猜 —— 重新探一遍。
FORMAT_VERSION = 3

#: 记录里认得的键。多出来的原样留着(是别人写的,不该被我们吃掉),
#: 但我们只读这几个。
#:
#: **每一项都要有一个"runtime 拿它干什么"**,否则就不该记 ——
#: 记了没人读的东西,过期了也没人发现。
#:
#:   default_browser  起浏览器,并锁住版本
#:   fonts_dir        下下来的中文字体在哪
#:   xpra             起 VNC 那条:bin / 它自己的解释器 / 版本
#:   xvfb             传给 `--xvfb=`,**不由发行版配置决定**
#:   rrweb            DOM 那条的记录器:版本 + 落在哪
KEYS = ("default_browser", "fonts_dir", "xpra", "xvfb", "rrweb")


def path() -> Path:
    return Path(os.environ.get("WEBMUXD_ENV_FILE")
                or (Path.home() / ".webmuxd.json"))


def load() -> dict[str, Any] | None:
    """读记录。没有、读不动、版本对不上,一律当没有。"""
    p = path()
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != FORMAT_VERSION:
        return None
    return data


def save(record: dict[str, Any]) -> Path:
    """整份重写。**值是 None 的键直接不写** —— 没探到就是没有,
    留一个旧值比留空更糟。"""
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {k: v for k, v in record.items() if v is not None}
    out = {"version": FORMAT_VERSION,
           "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           **body}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    tmp.replace(p)                       # 原子替换,别让半份记录被读到
    return p


def get(key: str) -> Any:
    """记录里的某个值,没有就 None。"""
    rec = load()
    return (rec or {}).get(key)


def stale_hint(what: str) -> str:
    """记录说有、实际没有时的那句提示。**要指出该重跑 install**。"""
    return f"记录里说{what},但它不在了 —— 跑一下 `webmuxd install` 重新探"
