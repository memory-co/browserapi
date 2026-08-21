"""**读**那份路径表 —— `~/.webmuxd.json`,外加"浏览器在哪"。

**这不是配置文件,是机器的事实。** `webmuxd install` 探一遍写下来,
之后所有命令读它 —— **只有 `install.py` 写,别人只读**
([j §3.3](../docs/v2/works/j-layout.md#33-installpy-写配置configpy-读配置--没有browserpy))。

装完之后"浏览器在哪"就是这里的一行,所以那几个"路径在哪 / 这台机器缺什么"
的探测也在这个文件的后半 —— 起进程的人从这儿读一个路径就够了,
不需要一个模块专门代表"浏览器"这个概念。

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
import platform
import shutil
import subprocess
import sys
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


# --------------------------------------------------------------------------
# 浏览器在哪 —— **装完之后这就是配置里的一行**([j §3.3](../docs/v2/works/j-layout.md#33-installpy-写配置configpy-读配置--没有browserpy))
# --------------------------------------------------------------------------

#: **每个 release 钉一个。** 改它要跑 `tests/chrome_facts/`。
PINNED = "152.0.7977.42"

#: 裸服务器上的老熟人 —— **中文全是豆腐块**和代码无关,任何跑 RBI 的机器都会撞上。
FONT_HINT = ("apt-get install -y fonts-noto-cjk", "缺中文字体,页面里的中文会是豆腐块")


def platform_slug() -> str:
    m = platform.machine().lower()
    if sys.platform == "darwin":
        return "mac-arm64" if m in ("arm64", "aarch64") else "mac-x64"
    if sys.platform.startswith("win"):
        return "win64"
    if m in ("aarch64", "arm64"):
        # CfT 没出 linux-arm64。说清楚,不猜。
        raise RuntimeError("Chrome for Testing 没有 linux-arm64 构建 —— "
                           "用系统的 chromium,或 session(browser=…) 指一个")
    return "linux64"


def cache_root() -> Path:
    """`WEBMUXD_BROWSERS_PATH` 优先,否则 XDG 缓存目录。"""
    p = os.environ.get("WEBMUXD_BROWSERS_PATH")
    if p:
        return Path(p).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base).expanduser() / "webmuxd"


def install_dir(version: str = PINNED) -> Path:
    return cache_root() / f"chrome-{version}"


def binary_path(version: str = PINNED) -> Path:
    d = install_dir(version)
    slug = platform_slug()
    if slug.startswith("mac"):
        return d / f"chrome-{slug}" / "Google Chrome for Testing.app" / \
            "Contents" / "MacOS" / "Google Chrome for Testing"
    if slug == "win64":
        return d / "chrome-win64" / "chrome.exe"
    return d / "chrome-linux64" / "chrome"


#: 装完了才写的标记。**"那个 exe 在"不等于"装完了"** ——
#: 解压到一半被 Ctrl-C、磁盘满、进程被 OOM 杀掉,目录里都会留下一堆看着挺像的
#: 文件,而 `chrome` 恰好可能已经落盘并且已经 chmod 过。实测过:目录里只有一个
#: `chrome`、别的全缺,旧的 `find()` 照样说装好了。
#:
#: 抄的是 playwright 的 `INSTALLATION_COMPLETE`([d](../docs/v2/works/d-install.md))。
MARKER = "INSTALLATION_COMPLETE"


def marker_path(version: str = PINNED) -> Path:
    return install_dir(version) / MARKER


def find(version: str = PINNED) -> str | None:
    """下过**而且下完了**才返回路径,否则 None。**不去猜系统里那个。**"""
    if not marker_path(version).exists():
        return None
    p = binary_path(version)
    return str(p) if p.exists() and os.access(p, os.X_OK) else None


#: 系统里那个 —— `install` 探得到就如实记一笔,但它**不是默认**。
SYSTEM_NAMES = ("chromium", "chromium-browser", "google-chrome",
                "google-chrome-stable", "chrome")


def find_system() -> str | None:
    for n in SYSTEM_NAMES:
        p = shutil.which(n)
        if p:
            return p
    return None



# --------------------------------------------------------------------------
# 这台机器缺什么 —— 探不到就明说,绝不静默
# --------------------------------------------------------------------------

def missing_libs(exe: str) -> list[str]:
    """`ldd` 里 not found 的那些。

    **以前镜像替用户扛掉了这些,现在落到裸机上** —— 所以这一步不能省,
    而且**探不到就明说,绝不静默**([h](../docs/v2/works/h-runtime.md))。
    """
    if not shutil.which("ldd") or sys.platform != "linux":
        return []
    try:
        out = subprocess.run(["ldd", exe], capture_output=True, text=True,
                             timeout=20).stdout
    except Exception:
        return []
    return sorted({line.split("=>")[0].strip()
                   for line in out.splitlines() if "not found" in line})


def has_cjk_font() -> bool:
    if not shutil.which("fc-list"):
        return True                      # 判不了就别乱报警
    try:
        out = subprocess.run(["fc-list", ":lang=zh"], capture_output=True,
                             text=True, timeout=20).stdout
    except Exception:
        return True
    return bool(out.strip())
