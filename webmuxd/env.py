"""环境记录 —— `~/.webmuxd.json`(docs/v1/cli/install.md)。

**这不是配置文件,是机器的事实。** `webmuxd install` 探一遍写下来,
之后所有命令读它,不再每次去 `docker info`。

    {"version": 1, "at": "…",
     "docker": "/usr/bin/docker", "docker_version": "29.7.2",
     "default_container": "kasmweb/chromium:1.18.0"}

**键在 = 探到了,键不在 = 没探到。** 没有 `default_container` 就是
"这个网络环境拉不到那个镜像",于是留空让人自己填 —— 而不是记一个
拉不下来的名字骗后面的自己。

三条规矩:

1. **没有记录就现探。** 不存在不是错误 —— `install` 省的是重复开销,
   不是"必须先装"。写脚本的人不该被一个 CLI 步骤挡住。
2. **信记录,但别替它兜底。** 记录会撒谎(你删了镜像它不知道),
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
FORMAT_VERSION = 1

#: 记录里认得的键。多出来的原样留着(是别人写的,不该被我们吃掉),
#: 但我们只读这几个。
KEYS = ("docker", "docker_version", "default_container")


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
