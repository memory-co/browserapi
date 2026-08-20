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

**装是默认行为,不是一个开关。** 0.7.0 之前要加 `--with-deps` 才动包管理器;
现在探到缺了就装 —— `install` 的职责就是"跑之前把环境弄好",探到却不装等于
把活原样退回去。**只有没 root 时才退化成打印**,那时候我们确实做不了。

姿态还是 playwright 那个:**装不了就明说缺什么、给出完整的那行命令,绝不静默**
(§4.3)。包名和发行版差异在 [deps.py](deps.py)。
"""

from __future__ import annotations

import os
import shutil
import platform
import sys
from typing import Any

from webmuxd import browser, env, xpra as xpra_mod
from webmuxd.cli import deps

OK, WARN = "✓", "⚠"


def _w(s: str) -> int:
    """字符串占几列。**中文是双宽的** —— 按字符数补空格,加一行中文标签
    就会把整块输出弄歪。原来那几个 `:<9` / `:<10` / `:<11` 是手调出来的。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, width: int) -> str:
    return s + " " * max(0, width - _w(s))


def _cut(s: str, width: int) -> str:
    """按显示宽度截断,不是按字符数。"""
    out, n = "", 0
    for c in s:
        n += _w(c)
        if n > width:
            return out
        out += c
    return out


def install(*, version: str = browser.PINNED, mirror: str | None = None,
            force: bool = False, with_deps: bool = False,
            out=sys.stdout, **_compat: Any) -> dict[str, Any]:
    say = lambda *a: print(*a, file=out)      # noqa: E731
    say("探测环境…")
    say(f"  {_pad('python', 10)} {_pad(platform.python_version(), 38)} {OK}")

    record: dict[str, Any] = {}

    fam = deps.detect()
    rooted = deps.can_root()
    if fam is None:
        say(f"  {_pad('包管理', 10)} {_pad('没探到 —— 缺什么只能打印出来', 38)} {WARN}")
    elif rooted:
        say(f"  {_pad('包管理', 10)} {_pad(fam.name + ',可以装', 38)} {OK}")
    else:
        say(f"  {_pad('包管理', 10)} {_pad(fam.name + ',没有 root —— 只打印', 38)} {WARN}")
    if with_deps:
        # **旧参数不静默吞。** 它现在是默认行为了,说一声比装作没看见好。
        say("     (--with-deps 已经是默认行为了,这个参数可以不用加)")

    # ---------------------------------------------------------------- 浏览器
    have = browser.find(version)
    if have and not force:
        say(f"  {_pad('浏览器', 10)} {_pad('chrome ' + version + ' 已经下过', 38)} {OK}")
        path = have
    else:
        # 目录在、标记不在 —— 要么是上次装到一半,要么是 0.5.1 之前装的
        # (那时候还没有标记这回事)。**重下 150 MB 不能不吭声。**
        if not force and browser.install_dir(version).exists():
            say(f"  {_pad('浏览器', 10)} {_pad('装了一半或是旧版本装的,重下一次', 38)} {WARN}")
        # **传进来的赢**:显式给了源就不探 —— 探测是"这台机器上哪个快"的事实,
        # 而你指定哪个是你的选择(v1/cli/install.md §3 那条规矩)
        chosen = mirror or os.environ.get("WEBMUXD_BROWSER_MIRROR")
        if not chosen:
            chosen = _pick_mirror(version, say)
        try:
            say(f"  {_pad('浏览器', 10)} {_pad('下 chrome ' + version + ' …', 38)}")
            path = browser.install(version, mirror=chosen, force=force,
                                   on_progress=_progress(out))
            say(f"\r  {_pad('浏览器', 10)} {_pad('chrome ' + version, 38)} {OK}")
        except Exception as e:
            # **不记一个下不到的路径。** 键不在,就是"你得自己填"。
            #
            # 原因**整句打出来,不截断** —— 截在半句上的提示等于没有提示,
            # 而这儿的原因(DNS 不通 / 403 / 连接超时)决定了下一步该做什么。
            say(f"\r  {_pad('浏览器', 10)} {_pad('下不到', 38)} {WARN}")
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
        def libs():
            m = browser.missing_libs(path)
            return (not m), ("缺 " + ", ".join(m[:3])) if m else ""

        _ensure(say, fam, rooted, "共享库", libs,
                fam.chrome if fam else deps.APT.chrome)
        # **裸服务器渲染中文全是豆腐块** —— 和代码无关,但撞上的人一定会以为是 bug
        _ensure(say, fam, rooted, "中文字体",
                lambda: (browser.has_cjk_font(), browser.FONT_HINT[1]),
                fam.font if fam else deps.APT.font, good_text="有")

        record["default_browser"] = {
            "path": path, "version": version, "source": "chrome-for-testing",
        }

    # ------------------------------------------------------------------ xpra
    # **画面默认走 xpra**(works/11 §6),所以它和浏览器一样是"跑之前要有的东西",
    # 不是一个可选的加分项。装不上也要把话说完:怎么装、以及不想装可以走哪条。
    ok = _ensure(say, fam, rooted, "xpra", xpra_mod.available,
                 fam.xpra if fam else deps.APT.xpra,
                 tail="不想装的话:webmuxd new … --transport jpg(或 dom)")
    if ok:
        # **记的是路径,不是"装好了"**([d §1](../../docs/v2/works/d-install.md#1-产出一份路径表))。
        # 每次重新探的问题不在耗时,在于**结果可能和上次不一样** ——
        # 装了新的 xpra、改了 PATH、在 venv 里跑,任一情形都会变,
        # 而报错不会指出"这次用的和上次不是同一个"。
        table = xpra_mod.probe()
        table["vfb"] = "Xvfb"                  # 显式钉死,不读发行版配置
        record["xpra"] = table
        # Xvfb 单独记一条:runtime 直接把它传给 `--xvfb=`
        vfb = shutil.which("Xvfb")
        if vfb:
            record["xvfb"] = vfb
        say(f"  {'':10} xpra {table.get('version', '?')} · "
            f"解释器 {table.get('python', '(读不出 shebang)')}")

    # 字体目录:**下下来的字体在哪**。探不到就不写 —— 键不在 = 没探到。
    fonts = browser.FONT_DIR if hasattr(browser, "FONT_DIR") else None
    if fonts and os.path.isdir(str(fonts)):
        record["fonts_dir"] = str(fonts)

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
    say(f"  {_pad('下载源', 10)} 探测中…")
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
        print(f"\r  {_pad('浏览器', 10)} {_pad(f'下 chrome … {pct}%', 38)}", end="", file=out)
    return cb


def _ensure(say, fam, rooted, label: str, probe, pkgs, tail: str = "",
            good_text: str = "齐") -> bool:
    """探一样东西;缺了就装;装完**再探一遍**。

    最后那次重探不是形式:`apt-get` 返回 0 只说明"命令没报错",
    而我们要的是"现在真的有了"。**判据永远是探测结果,不是安装器的退出码。**
    """
    ok, why = probe()
    if ok:
        say(f"  {_pad(label, 10)} {_pad(good_text, 38)} {OK}")
        return True
    if fam is None or not rooted:
        say(f"  {_pad(label, 10)} {_pad(_cut(why, 38), 38)} {WARN}")
        # 包管理器都没探到的时候,`line()` 返回的是一句话不是一行命令 ——
        # 再套一个"装上:"就成了病句。
        say(f"     {deps.line(fam, pkgs)}" if fam is None
            else f"     装上:{deps.line(fam, pkgs)}")
        if tail:
            say(f"     {tail}")
        return False

    say(f"  {_pad(label, 10)} {_pad(_cut(why, 28) + ' —— 装上…', 38)}")
    good, msg = deps.apply(fam, pkgs)
    ok, why = probe()                       # **以重探为准**
    if ok:
        say(f"  {_pad(label, 10)} {_pad('装好了', 38)} {OK}")
        return True
    say(f"  {_pad(label, 10)} {_pad(_cut(msg or why, 38), 38)} {WARN}")
    if not good and msg:
        say(f"     {msg}")
    say(f"     自己跑:{deps.line(fam, pkgs)}")
    if tail:
        say(f"     {tail}")
    return False
