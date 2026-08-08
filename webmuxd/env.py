"""环境记录 —— `~/.webmuxd.json`(docs/v1/cli/install.md)。

**`.conf` 是你的选择,`.json` 是机器的事实。** 这份是后者:
`webmuxd install` 探一遍写下来,之后所有命令读它,不再每次去 `docker info`。

三条规矩:

1. **没有记录就现探。** 不存在不是错误 —— `install` 省的是重复开销,
   不是"必须先装"。写脚本的人不该被一个 CLI 步骤挡住。
2. **信记录,但别替它兜底。** 记录会撒谎(你卸了 chromium 它不知道),
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
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {"version": FORMAT_VERSION,
              "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              **record}
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1))
    tmp.replace(p)                       # 原子替换,别让半份记录被读到
    return p


def runtime_info(name: str) -> dict[str, Any] | None:
    """某个 runtime 的那一段。没有记录就返回 None,调用方去现探。"""
    rec = load()
    if not rec:
        return None
    got = (rec.get("runtimes") or {}).get(name)
    return got if isinstance(got, dict) else None


def stale_hint(what: str) -> str:
    """记录说有、实际没有时的那句提示。**要指出该重跑 install**。"""
    return f"记录里说{what},但它不在了 —— 跑一下 `webmuxd install` 重新探"
