"""浏览器从哪来 —— `webmuxd install` 下一个。

docs/v2/works/07-runtime.md §4。v1 的浏览器藏在镜像里,v2 **不发镜像也不要求你
本机装 chromium**:照着 playwright 的姿态,把它当一个下载物,落在我们自己的
缓存目录。

**钉死版本是重点,不是顺带。** `tests/chrome_facts/` 那一整个场景的定义是
「我们对 CDP 的假设逐条量过」,而"换 Chromium 大版本先跑它"这句话在版本不确定时
根本没法执行 —— 你不知道自己现在跑的是哪一版。所以:

    改 PINNED → 跑一遍 chrome_facts → 过了才发版

选 Chrome for Testing 的理由**只有一条,就是钉死版本**:官方托管、有稳定的版本
索引、不会自己升级。codec 不是理由([07 §4.2](../docs/v2/works/07-runtime.md))。
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

#: **每个 release 钉一个。** 改它要跑 `tests/chrome_facts/`。
PINNED = "152.0.7977.42"

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
#: 抄的是 playwright 的 `INSTALLATION_COMPLETE`([works/10 §4.2](../docs/v2/works/10-install.md))。
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


def download_url(version: str = PINNED, mirror: str | None = None) -> str:
    base = (mirror or os.environ.get("WEBMUXD_BROWSER_MIRROR")
            or DEFAULT_MIRROR).rstrip("/")
    slug = platform_slug()
    return f"{base}/{version}/{slug}/chrome-{slug}.zip"


def latest_stable(timeout: float = 10.0) -> str:
    with urllib.request.urlopen(VERSIONS_URL, timeout=timeout) as r:
        return json.load(r)["channels"]["Stable"]["version"]


def probe_mirrors(version: str = PINNED, *,
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


def fastest_mirror(version: str = PINNED) -> tuple[str, str, float | None]:
    """挑一个。全都探不通就退回官方 —— **不静默失败,让下载去报错**。"""
    ranked = probe_mirrors(version)
    if ranked and ranked[0][2] is not None:
        return ranked[0]
    return "官方", DEFAULT_MIRROR, None


def install(version: str = PINNED, *, mirror: str | None = None,
            force: bool = False, on_progress=None) -> str:
    """下一个,返回可执行文件路径。

    **幂等** —— 已经在了就直接返回,不重下([v1/cli/install.md](../docs/v1/cli/install.md)
    那条规矩原样继承)。`force=True` 才重来。
    """
    have = find(version)
    if have and not force:
        return have

    dest = install_dir(version)
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

    exe = binary_path(version)
    if not exe.exists():
        shutil.rmtree(dest, ignore_errors=True)
        raise RuntimeError(f"解压完没找到 {exe} —— 这个源给的包不是我们要的那个")
    # zip 不保留权限位
    for p in exe.parent.rglob("*"):
        if p.is_file() and (p.suffix == "" or p.name.endswith(".sh")):
            p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    # **最后一步才写标记。** 前面任何一步被打断,这个文件就不在,
    # 下一次 `find()` 会如实说"没装好"。
    marker_path(version).write_text(version)
    return str(exe)


# --------------------------------------------------------------------- 依赖

def missing_libs(exe: str) -> list[str]:
    """`ldd` 里 not found 的那些。

    **以前镜像替用户扛掉了这些,现在落到裸机上** —— 所以这一步不能省,
    而且**探不到就明说,绝不静默**([07 §4.3](../docs/v2/works/07-runtime.md))。
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
