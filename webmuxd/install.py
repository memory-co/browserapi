"""`webmuxd install` —— 探一遍,下一个,写下来,别再问。

docs/v2/works/h-runtime.md §4.4。v1 问的两个问题(docker 能用吗、拉得到镜像吗)
**换成了另外两个**:

1. **这个网络环境下得到那个浏览器吗**
2. **系统依赖齐吗**

docker 那一问整个消失 —— v2 不再关心机器上有没有它(§2)。

规矩全部从 [v1/cli/install.md](../docs/v1/cli/install.md) 继承,一条没改:
**幂等**("检查"和"安装"是同一个命令,不需要 `doctor`)、
**探不到就不写那个键**、**不静默重探**、**它不是配置文件**、
**没装过也能用**。

**装是默认行为,不是一个开关。** 0.7.0 之前要加 `--with-deps` 才动包管理器;
现在探到缺了就装 —— `install` 的职责就是"跑之前把环境弄好",探到却不装等于
把活原样退回去。**只有没 root 时才退化成打印**,那时候我们确实做不了。

姿态还是 playwright 那个:**装不了就明说缺什么、给出完整的那行命令,绝不静默**
(§4.3)。包名和发行版差异在 [py](py)。
"""

from __future__ import annotations

import json
import dataclasses
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from typing import Any

from webmuxd import config, models, xpra as xpra_mod
from webmuxd import rrweb as dom_mod
from webmuxd.models import PackageFamily

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


def install(*, version: str = config.PINNED, mirror: str | None = None,
            force: bool = False, with_deps: bool = False,
            out=sys.stdout, **_compat: Any) -> models.MachineFacts:
    say = lambda *a: print(*a, file=out)      # noqa: E731
    say("探测环境…")
    say(f"  {_pad('python', 10)} {_pad(platform.python_version(), 38)} {OK}")

    #: 这一趟探出来的**事实**。形状在 `models.MachineFacts` ——
    #: **没探到的字段留 None,`save()` 一个都不会写。**
    facts = models.MachineFacts()

    fam = detect()
    rooted = can_root()
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
    have = config.find(version)
    if have and not force:
        say(f"  {_pad('浏览器', 10)} {_pad('chrome ' + version + ' 已经下过', 38)} {OK}")
        path = have
    else:
        # 目录在、标记不在 —— 要么是上次装到一半,要么是 0.5.1 之前装的
        # (那时候还没有标记这回事)。**重下 150 MB 不能不吭声。**
        if not force and config.install_dir(version).exists():
            say(f"  {_pad('浏览器', 10)} {_pad('装了一半或是旧版本装的,重下一次', 38)} {WARN}")
        # **传进来的赢**:显式给了源就不探 —— 探测是"这台机器上哪个快"的事实,
        # 而你指定哪个是你的选择(v1/cli/install.md §3 那条规矩)
        chosen = mirror or os.environ.get("WEBMUXD_BROWSER_MIRROR")
        if not chosen:
            chosen = _pick_mirror(version, say)
        try:
            say(f"  {_pad('浏览器', 10)} {_pad('下 chrome ' + version + ' …', 38)}")
            path = install_browser(version, mirror=chosen, force=force,
                                   on_progress=_progress(out))
            say(f"\r  {_pad('浏览器', 10)} {_pad('chrome ' + version, 38)} {OK}")
        except Exception as e:
            # **不记一个下不到的路径。** 键不在,就是"你得自己填"。
            #
            # 原因**整句打出来,不截断** —— 截在半句上的提示等于没有提示,
            # 而这儿的原因(DNS 不通 / 403 / 连接超时)决定了下一步该做什么。
            say(f"\r  {_pad('浏览器', 10)} {_pad('下不到', 38)} {WARN}")
            say(f"     {e}")
            sysone = config.find_system()
            if sysone:
                say(f"     系统里有一个:{sysone}")
                say(f"     用它:webmuxd new --browser {sysone}")
                say(f"     换源再试:WEBMUXD_BROWSER_MIRROR={CN_MIRROR}")
            else:
                say(f"     换个源再试:WEBMUXD_BROWSER_MIRROR={CN_MIRROR}")
            path = None

    # ---------------------------------------------------------------- 依赖
    if path:
        def libs():
            m = config.missing_libs(path)
            return (not m), ("缺 " + ", ".join(m[:3])) if m else ""

        _ensure(say, fam, rooted, "共享库", libs,
                fam.chrome if fam else APT.chrome)
        # **裸服务器渲染中文全是豆腐块** —— 和代码无关,但撞上的人一定会以为是 bug
        _ensure(say, fam, rooted, "中文字体",
                lambda: (config.has_cjk_font(), config.FONT_HINT[1]),
                fam.font if fam else APT.font, good_text="有")

        facts.browser = models.BrowserFact(path, version, "chrome-for-testing")

    # ------------------------------------------------------------------ xpra
    # **画面默认走 xpra**(works/11 §6),所以它和浏览器一样是"跑之前要有的东西",
    # 不是一个可选的加分项。装不上也要把话说完:怎么装、以及不想装可以走哪条。
    ok = _ensure(say, fam, rooted, "xpra", xpra_mod.available,
                 fam.xpra if fam else APT.xpra,
                 tail="不想装的话:webmuxd new … --transport jpg(或 dom)")
    if ok:
        # **记的是路径,不是"装好了"**([d §1](../docs/v2/works/d-install.md#1-产出一份路径表))。
        # 每次重新探的问题不在耗时,在于**结果可能和上次不一样** ——
        # 装了新的 xpra、改了 PATH、在 venv 里跑,任一情形都会变,
        # 而报错不会指出"这次用的和上次不是同一个"。
        # **显式钉死 `vfb`,不读发行版配置。**
        facts.xpra = dataclasses.replace(xpra_mod.probe(), vfb="Xorg+dummy")
        # X server 单独记一条:起进程的人直接把它传给 `--xvfb=`。
        # **是 Xorg + dummy 驱动,不是 Xvfb** —— Xvfb 的显示尺寸改不了,
        # 人把窗口拉大画面也不跟,理由写在 `xpra.xvfb()`。
        facts.xvfb = xpra_mod.XORG if xpra_mod.dummy_driver() else ""
        say(f"  {'':10} xpra {facts.xpra.version or '?'} · "
            f"解释器 {facts.xpra.python or '(读不出 shebang)'}")

    # ------------------------------------------------------------- DOM 那条
    # **属于数据,所以下载**([d §2](../docs/v2/works/d-install.md#2-每样东西从哪来))。
    # 和浏览器、字体同一档:在这儿下,不在起 session 的时候现下 ——
    # 现下的话第一次起会卡在网络上,而离线的机器要到那一刻才知道。
    ok_dom, why_dom = dom_mod.ready()
    if not ok_dom:
        try:
            dom_mod.download()
            ok_dom = True
        except Exception as e:                    # noqa: BLE001
            why_dom = str(e)
    if ok_dom:
        say(f"  {_pad('DOM 画面', 10)} "
            f"{_pad('rrweb ' + dom_mod.RRWEB_VERSION, 38)} {OK}")
        facts.rrweb = models.RrwebFact(dom_mod.RRWEB_VERSION,
                                       str(dom_mod.paths()["js"]))
    else:
        # **不静默略过。** DOM 是三种画面之一,下不到就说清楚:
        # 影响的是哪一种、另外两种还在。
        say(f"  {_pad('DOM 画面', 10)} "
            f"{_pad('下不到 rrweb:' + why_dom[:24], 38)} {WARN}")
        say("     只影响 --transport dom;jpg / vnc 不受影响")

    # 字体目录(`fonts_dir`):**今天不写这个键。** install 不下字体,只在缺的时候
    # 给一句 `apt-get install fonts-noto-cjk` —— 没下过就没有"在哪"可记。
    # 键不在 = 没探到,这正是它该有的样子。

    p = config.save(facts)
    say("")
    say(f"记录写到 {p}")
    if facts.browser is None:
        say(f"{WARN} 没有 default_browser —— 起 session 时得 --browser 指一个")
    return facts


# ---------------------------------------------------------------------------

def _pick_mirror(version: str, say) -> str:
    """探一遍候选源,挑最快的那个。

    **量的是吞吐,不是能不能连上** —— 下 150 MB 的时候,握手快 20ms 一文不值。
    探不通不是错误,列出来就是了([probe_mirrors](../py))。
    """
    say(f"  {_pad('下载源', 10)} 探测中…")
    ranked = probe_mirrors(version)
    for i, (name, _base, kbps) in enumerate(ranked):
        speed = f"{kbps / 1024:.1f} MB/s" if kbps else "探不通"
        mark = OK if i == 0 and kbps else (" " if kbps else WARN)
        say(f"     {name:<16} {speed:<12} {mark}")
    if ranked and ranked[0][2] is not None:
        return ranked[0][1]
    # 全都探不通 —— 退回官方,**让真正的下载去报错**,那儿的信息更有用
    say(f"     都探不通,按官方那个试 —— 下面要是失败,换个源:"
        f"WEBMUXD_BROWSER_MIRROR={CN_MIRROR}")
    return DEFAULT_MIRROR


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
        say(f"     {line(fam, pkgs)}" if fam is None
            else f"     装上:{line(fam, pkgs)}")
        if tail:
            say(f"     {tail}")
        return False

    say(f"  {_pad(label, 10)} {_pad(_cut(why, 28) + ' —— 装上…', 38)}")
    good, msg = apply(fam, pkgs)
    ok, why = probe()                       # **以重探为准**
    if ok:
        say(f"  {_pad(label, 10)} {_pad('装好了', 38)} {OK}")
        return True
    say(f"  {_pad(label, 10)} {_pad(_cut(msg or why, 38), 38)} {WARN}")
    if not good and msg:
        say(f"     {msg}")
    say(f"     自己跑:{line(fam, pkgs)}")
    if tail:
        say(f"     {tail}")
    return False


# --------------------------------------------------------------------------
# 系统依赖的包名表(原 cli/py)
# --------------------------------------------------------------------------

APT = PackageFamily(
    name="apt-get",
    install=("apt-get", "install", "-y", "-q"),
    chrome=("libnss3", "libnspr4", "libatk1.0-0", "libatk-bridge2.0-0",
            "libcups2", "libdrm2", "libxkbcommon0", "libxcomposite1",
            "libxdamage1", "libxfixes3", "libxrandr2", "libgbm1",
            "libpango-1.0-0", "libcairo2", "libasound2"),
    xpra=("xpra", "xserver-xorg-core", "xserver-xorg-video-dummy", "python3-pil"),
    font=("fonts-noto-cjk",),
)

#: RHEL / CentOS / Rocky / 阿里云。`dnf` 和 `yum` 只差命令名。
_RPM = dict(
    chrome=("nss", "nspr", "atk", "at-spi2-atk", "cups-libs", "libdrm",
            "libxkbcommon", "libXcomposite", "libXdamage", "libXfixes",
            "libXrandr", "mesa-libgbm", "pango", "cairo", "alsa-lib"),
    # **两边的包名完全不一样,都得写出来。** 而且 `xpra` 在 RHEL 系
    # **不在基础源里**,得先加 xpra.org 的源 —— 装不上时我们会说这句。
    xpra=("xpra", "xorg-x11-server-Xorg", "xorg-x11-drv-dummy", "python3-pillow"),
    font=("google-noto-sans-cjk-fonts",),
)
DNF = PackageFamily(name="dnf", install=("dnf", "install", "-y", "-q"), **_RPM)
YUM = PackageFamily(name="yum", install=("yum", "install", "-y", "-q"), **_RPM)

#: 探测顺序。**apt 在前** —— 有些 Debian 机器上也装着 `yum` 之类的东西。
ORDER = (("apt-get", APT), ("dnf", DNF), ("yum", YUM))

#: xpra 在 RHEL 系不在基础源里,装不上时得说这句。
XPRA_REPO = "https://github.com/Xpra-org/xpra/wiki/Download"


def detect() -> PackageFamily | None:
    """这台机器用哪个包管理器。**探不到就返回 None**,不猜。"""
    for binary, fam in ORDER:
        if shutil.which(binary):
            return fam
    return None


def can_root() -> bool:
    """能不能真的装。**root,或者不要密码的 sudo。**

    要密码的 sudo 不算 —— `webmuxd install` 不是交互式的,卡在密码提示上
    比直接说"没权限"更糟。
    """
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return True
    if not shutil.which("sudo"):
        return False
    try:
        return subprocess.run(["sudo", "-n", "true"], capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False


def command(fam: PackageFamily, pkgs: tuple[str, ...]) -> list[str]:
    cmd = [*fam.install, *pkgs]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    return cmd


def line(fam: PackageFamily | None, pkgs: tuple[str, ...]) -> str:
    """人自己该敲的那行。**给完整的一行,不是"装一下依赖"。**"""
    if fam is None:
        return "这台机器的包管理器没探到,大致要这些:" + " ".join(pkgs)
    return "sudo " + " ".join([*fam.install, *pkgs])


def apply(fam: PackageFamily, pkgs: tuple[str, ...], *,
          timeout: int = 900) -> tuple[bool, str]:
    """装。返回 `(成不成, 说明)`。

    **失败时要分清是哪一种**:源里没有这个包(要加源),还是没权限(要 sudo)。
    """
    try:
        r = subprocess.run(command(fam, pkgs), capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"装了 {timeout} 秒还没完,放弃了"
    except Exception as e:
        return False, str(e)
    if r.returncode == 0:
        return True, ""
    err = ((r.stderr or "") + (r.stdout or "")).strip()
    low = err.lower()
    if any(s in low for s in ("no match for argument", "unable to locate package",
                             "no package", "nothing provides")):
        missing = [p for p in pkgs if p in err]
        return False, ("源里没有" + ("这些包:" + " ".join(missing) if missing else "某个包")
                       + (f" —— xpra 在 RHEL 系要先加源:{XPRA_REPO}"
                          if "xpra" in pkgs else ""))
    if "permission" in low or "are you root" in low or "sudo:" in low:
        return False, "没权限"
    return False, err.splitlines()[-1][:120] if err else f"退出码 {r.returncode}"


# --------------------------------------------------------------------------
# 浏览器:探、下、装(原 py)
# --------------------------------------------------------------------------

#: 官方托管。`WEBMUXD_BROWSER_MIRROR` 换源 —— **国内那条是一等公民,不是补丁**,
#: 这个项目本来就同时发 ghcr 和 CNB。
DEFAULT_MIRROR = "https://storage.googleapis.com/chrome-for-testing-public"
CN_MIRROR = "https://cdn.npmmirror.com/binaries/chrome-for-testing"

#: 候选源。`install` 会**并发探一遍挑最快的**(§probe_mirrors)。
#:
#: 只放**真的托管 Chrome for Testing** 的源。像
#: `https://mirrors.aliyun.com/google-chrome/` 那种看着相关但其实不是的,
#: 不能进这张表 —— 它托管的是 Google Chrome 稳定版的 `.deb` / `.rpm` 安装包,
#: 既不是同一种产物(zip vs 系统包),**也没有版本可钉**(只有 `current`)。
#: 拿它当镜像等于把 §4.1 那条"每个 release 钉一个版本"作废掉。
MIRRORS: tuple[tuple[str, str], ...] = (
    ("官方", DEFAULT_MIRROR),
    ("npmmirror", CN_MIRROR),
    ("npmmirror cdn", "https://registry.npmmirror.com/-/binary/chrome-for-testing"),
)

#: 探测时下多少字节。**量的是吞吐,不是 RTT** —— 一个 ping 快但带宽差的源,
#: 在下 150 MB 的时候更糟。
PROBE_BYTES = 256 * 1024
PROBE_TIMEOUT = 10.0

#: 版本索引,`webmuxd install --latest` 用。
VERSIONS_URL = ("https://googlechromelabs.github.io/chrome-for-testing/"
                "last-known-good-versions.json")

def download_url(version: str = config.PINNED, mirror: str | None = None) -> str:
    base = (mirror or os.environ.get("WEBMUXD_BROWSER_MIRROR")
            or DEFAULT_MIRROR).rstrip("/")
    slug = config.platform_slug()
    return f"{base}/{version}/{slug}/chrome-{slug}.zip"


def latest_stable(timeout: float = 10.0) -> str:
    with urllib.request.urlopen(VERSIONS_URL, timeout=timeout) as r:
        return json.load(r)["channels"]["Stable"]["version"]


def probe_mirrors(version: str = config.PINNED, *,
                  timeout: float = PROBE_TIMEOUT) -> list[tuple[str, str, float | None]]:
    """并发探所有候选源,返回 `[(名字, base, KB/s 或 None)]`,**快的在前**。

    三条讲究:

    1. **探的是真实那个文件**的头 256 KB,不是首页也不是 ping ——
       首页快不代表大文件快,CDN 的回源路径经常不一样。
    2. **量吞吐不量 RTT。** 我们要下的是 150 MB,握手快 20ms 毫无意义。
    3. **探不通不是错误**,那一格是 `None`,排在最后。全都探不通就返回原序,
       让真正的下载去报错 —— 那儿的错误信息比"探测失败"有用。
    """
    import concurrent.futures as cf

    def one(item: tuple[str, str]) -> tuple[str, str, float | None]:
        name, base = item
        url = download_url(version, base)
        req = urllib.request.Request(url, headers={"Range": f"bytes=0-{PROBE_BYTES - 1}"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                n = len(r.read(PROBE_BYTES))
        except Exception:
            return name, base, None
        dt = time.monotonic() - t0
        if not n or dt <= 0:
            return name, base, None
        return name, base, n / 1024 / dt

    with cf.ThreadPoolExecutor(max_workers=len(MIRRORS)) as pool:
        got = list(pool.map(one, MIRRORS))
    return sorted(got, key=lambda r: -(r[2] or -1))


def fastest_mirror(version: str = config.PINNED) -> tuple[str, str, float | None]:
    """挑一个。全都探不通就退回官方 —— **不静默失败,让下载去报错**。"""
    ranked = probe_mirrors(version)
    if ranked and ranked[0][2] is not None:
        return ranked[0]
    return "官方", DEFAULT_MIRROR, None


def install_browser(version: str = config.PINNED, *, mirror: str | None = None,
            force: bool = False, on_progress=None) -> str:
    """下一个,返回可执行文件路径。

    **幂等** —— 已经在了就直接返回,不重下([v1/cli/install.md](../docs/v1/cli/install.md)
    那条规矩原样继承)。`force=True` 才重来。
    """
    have = config.find(version)
    if have and not force:
        return have

    dest = config.install_dir(version)
    if force and dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    url = download_url(version, mirror)
    tmp = dest / ".chrome.zip.part"
    ok = False
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(tmp, "wb") as f:
                while chunk := r.read(1 << 18):
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress:
                        on_progress(done, total)
        with zipfile.ZipFile(tmp) as z:
            z.extractall(dest)
        ok = True
    finally:
        tmp.unlink(missing_ok=True)
        if not ok:
            # **失败就删干净**,别留半个目录给下一次去猜(works/10 §4.3)
            shutil.rmtree(dest, ignore_errors=True)

    exe = config.binary_path(version)
    if not exe.exists():
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(f"解压完没找到 {exe} —— 这个源给的包不是我们要的那个")
    # zip 不保留权限位
    for p in exe.parent.rglob("*"):
        if p.is_file() and (p.suffix == "" or p.name.endswith(".sh")):
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    # **最后一步才写标记。** 前面任何一步被打断,这个文件就不在,
    # 下一次 `config.find()` 会如实说"没装好"。
    config.marker_path(version).write_text(version)
    return str(exe)
