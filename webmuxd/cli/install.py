"""`webmuxd install` —— 探一遍,下一个,写下来,别再问。

docs/v2/works/07-runtime.md §4.4。v1 问的两个问题(docker 能用吗、拉得到镜像吗)
**换成了另外两个**:

1. **这个网络环境下得到那个浏览器吗**
2. **系统依赖齐吗**

docker 那一问整个消失 —— v2 不再关心机器上有没有它(§2)。

规矩全部从 [v1/cli/install.md](../../docs/v1/cli/install.md) 继承,一条没改:
**幂等**("检查"和"安装"是同一个命令,不需要 `doctor`)、
**探不到就不写那个键**、**不静默重探**、**它不是配置文件**、
**没装过也能用**。

`--with-deps` 照抄 playwright 的姿态:**能装就装,装不了就明说缺什么、
给出那行命令,绝不静默**(§4.3)。
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from typing import Any

from webmuxd import browser, env

OK, WARN = "✓", "⚠"

#: Debian/Ubuntu 上 headless chrome 常缺的那些。别的发行版只打印,不装。
APT_DEPS = (
    "libnss3", "libnspr4", "libatk1.0-0", "libatk-bridge2.0-0", "libcups2",
    "libdrm2", "libxkbcommon0", "libxcomposite1", "libxdamage1", "libxfixes3",
    "libxrandr2", "libgbm1", "libpango-1.0-0", "libcairo2", "libasound2",
    "fonts-noto-cjk",
)


def install(*, version: str = browser.PINNED, mirror: str | None = None,
            force: bool = False, with_deps: bool = False,
            out=sys.stdout, **_compat: Any) -> dict[str, Any]:
    say = lambda *a: print(*a, file=out)      # noqa: E731
    say("探测环境…")
    say(f"  {'python':<11} {platform.python_version():<38} {OK}")

    record: dict[str, Any] = {}

    if with_deps:
        _install_deps(say)

    # ---------------------------------------------------------------- 浏览器
    have = browser.find(version)
    if have and not force:
        say(f"  {'浏览器':<10} {('chrome ' + version + ' 已经下过'):<38} {OK}")
        path = have
    else:
        # **传进来的赢**:显式给了源就不探 —— 探测是"这台机器上哪个快"的事实,
        # 而你指定哪个是你的选择(v1/cli/install.md §3 那条规矩)
        chosen = mirror or os.environ.get("WEBMUXD_BROWSER_MIRROR")
        if not chosen:
            chosen = _pick_mirror(version, say)
        try:
            say(f"  {'浏览器':<10} {('下 chrome ' + version + ' …'):<38}")
            path = browser.install(version, mirror=chosen, force=force,
                                   on_progress=_progress(out))
            say(f"\r  {'浏览器':<10} {('chrome ' + version):<38} {OK}")
        except Exception as e:
            # **不记一个下不到的路径。** 键不在,就是"你得自己填"。
            #
            # 原因**整句打出来,不截断** —— 截在半句上的提示等于没有提示,
            # 而这儿的原因(DNS 不通 / 403 / 连接超时)决定了下一步该做什么。
            say(f"\r  {'浏览器':<10} {'下不到':<38} {WARN}")
            say(f"     {e}")
            sysone = browser.find_system()
            if sysone:
                say(f"     系统里有一个:{sysone}")
                say(f"     用它:webmuxd new --browser {sysone}")
                say(f"     换源再试:WEBMUXD_BROWSER_MIRROR={browser.CN_MIRROR}")
            else:
                say(f"     换个源再试:WEBMUXD_BROWSER_MIRROR={browser.CN_MIRROR}")
            path = None

    # ---------------------------------------------------------------- 依赖
    if path:
        missing = browser.missing_libs(path)
        if missing:
            say(f"  {'共享库':<10} {('缺 ' + ', '.join(missing[:3])):<38} {WARN}")
            say(f"     装上:sudo apt-get install -y {' '.join(APT_DEPS)}")
            say("     或者 `webmuxd install --with-deps`(要 root)")
        else:
            say(f"  {'共享库':<10} {'齐':<38} {OK}")

        if browser.has_cjk_font():
            say(f"  {'中文字体':<9} {'有':<38} {OK}")
        else:
            # **裸服务器渲染中文全是豆腐块** —— 和代码无关,但撞上的人一定会以为是 bug
            say(f"  {'中文字体':<9} {browser.FONT_HINT[1]:<38} {WARN}")
            say(f"     装上:sudo {browser.FONT_HINT[0]}")

        record["default_browser"] = {
            "path": path, "version": version, "source": "chrome-for-testing",
        }

    p = env.save(record)
    say("")
    say(f"记录写到 {p}")
    if not record.get("default_browser"):
        say(f"{WARN} 没有 default_browser —— 起 session 时得 --browser 指一个")
    return record


# ---------------------------------------------------------------------------

def _pick_mirror(version: str, say) -> str:
    """探一遍候选源,挑最快的那个。

    **量的是吞吐,不是能不能连上** —— 下 150 MB 的时候,握手快 20ms 一文不值。
    探不通不是错误,列出来就是了([browser.probe_mirrors](../browser.py))。
    """
    say(f"  {'下载源':<10} 探测中…")
    ranked = browser.probe_mirrors(version)
    for i, (name, _base, kbps) in enumerate(ranked):
        speed = f"{kbps / 1024:.1f} MB/s" if kbps else "探不通"
        mark = OK if i == 0 and kbps else (" " if kbps else WARN)
        say(f"     {name:<16} {speed:<12} {mark}")
    if ranked and ranked[0][2] is not None:
        return ranked[0][1]
    # 全都探不通 —— 退回官方,**让真正的下载去报错**,那儿的信息更有用
    say(f"     都探不通,按官方那个试 —— 下面要是失败,换个源:"
        f"WEBMUXD_BROWSER_MIRROR={browser.CN_MIRROR}")
    return browser.DEFAULT_MIRROR


def _progress(out):
    def cb(done: int, total: int) -> None:
        if not total or not out.isatty():
            return
        pct = done * 100 // total
        print(f"\r  {'浏览器':<10} {f'下 chrome … {pct}%':<38}", end="", file=out)
    return cb


def _install_deps(say) -> None:
    """**能装就装,装不了只打印。** playwright 就是这个姿态,理由见 §4.3。"""
    apt = shutil.which("apt-get")
    if not apt:
        say(f"  {'依赖':<11} {'非 Debian/Ubuntu,自己装':<38} {WARN}")
        say(f"     大致是这些:{' '.join(APT_DEPS)}")
        return
    cmd = ["apt-get", "install", "-y", "-q", *APT_DEPS]
    if shutil.which("sudo"):
        cmd = ["sudo", "-n", *cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except Exception as e:
        r = None
        say(f"  {'依赖':<11} {str(e)[:38]:<38} {WARN}")
    if r is not None and r.returncode == 0:
        say(f"  {'依赖':<11} {'装好了':<38} {OK}")
    elif r is not None:
        say(f"  {'依赖':<11} {'装不了(要 root)':<38} {WARN}")
        say(f"     自己跑:sudo apt-get install -y {' '.join(APT_DEPS)}")
