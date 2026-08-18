"""系统包 —— `webmuxd install` 里"把环境弄齐"的那一半。

docs/v2/works/10-install.md §7 挂了很久的一条:**`--with-deps` 只支持
Debian/Ubuntu**。真机上撞了才知道这不是小事 —— 云主机上 RHEL 系很常见,
而那边不光包名不一样,**xpra 默认用的虚拟显示都不一样**
([12 §12.3](../../docs/v2/works/12-xpra-client.md))。

三条规矩:

**① 装,是默认行为,不是一个开关。** `webmuxd install` 的职责就是"跑之前
把环境弄好";探到缺了却不装,等于把活原样退回去。**没有 root 才只打印** ——
那时候我们确实做不了,而不是选择不做。

**② 缺一个就装一整组。** 不去算"哪个包提供了 libnss3" —— 那要 `apt-file` /
`dnf provides`,慢而且不一定装得到。整组装一遍是幂等的,已经有的会被跳过。

**③ 装不上要说清是"没这个包"还是"没权限"。** 两者的下一步完全不同:
前者要加软件源(xpra 在 RHEL 系就不在基础源里),后者要 sudo。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    """一个发行版家族。**包名是唯一真正的差别**,流程是一样的。"""

    name: str
    #: 装包命令(不含包名)
    install: tuple[str, ...]
    #: headless chrome 缺的那些共享库
    chrome: tuple[str, ...]
    #: xpra 那条画面路要的三样
    xpra: tuple[str, ...]
    #: 中文字体 —— 没有它页面里的中文全是豆腐块
    font: tuple[str, ...]


APT = Family(
    name="apt-get",
    install=("apt-get", "install", "-y", "-q"),
    chrome=("libnss3", "libnspr4", "libatk1.0-0", "libatk-bridge2.0-0",
            "libcups2", "libdrm2", "libxkbcommon0", "libxcomposite1",
            "libxdamage1", "libxfixes3", "libxrandr2", "libgbm1",
            "libpango-1.0-0", "libcairo2", "libasound2"),
    xpra=("xpra", "xvfb", "python3-pil"),
    font=("fonts-noto-cjk",),
)

#: RHEL / CentOS / Rocky / 阿里云。`dnf` 和 `yum` 只差命令名。
_RPM = dict(
    chrome=("nss", "nspr", "atk", "at-spi2-atk", "cups-libs", "libdrm",
            "libxkbcommon", "libXcomposite", "libXdamage", "libXfixes",
            "libXrandr", "mesa-libgbm", "pango", "cairo", "alsa-lib"),
    # **`xorg-x11-server-Xvfb`,不是 `xvfb`。** 而且 `xpra` 在 RHEL 系
    # **不在基础源里**,得先加 xpra.org 的源 —— 装不上时我们会说这句。
    xpra=("xpra", "xorg-x11-server-Xvfb", "python3-pillow"),
    font=("google-noto-sans-cjk-fonts",),
)
DNF = Family(name="dnf", install=("dnf", "install", "-y", "-q"), **_RPM)
YUM = Family(name="yum", install=("yum", "install", "-y", "-q"), **_RPM)

#: 探测顺序。**apt 在前** —— 有些 Debian 机器上也装着 `yum` 之类的东西。
ORDER = (("apt-get", APT), ("dnf", DNF), ("yum", YUM))

#: xpra 在 RHEL 系不在基础源里,装不上时得说这句。
XPRA_REPO = "https://github.com/Xpra-org/xpra/wiki/Download"


def detect() -> Family | None:
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


def command(fam: Family, pkgs: tuple[str, ...]) -> list[str]:
    cmd = [*fam.install, *pkgs]
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        cmd = ["sudo", "-n", *cmd]
    return cmd


def line(fam: Family | None, pkgs: tuple[str, ...]) -> str:
    """人自己该敲的那行。**给完整的一行,不是"装一下依赖"。**"""
    if fam is None:
        return "这台机器的包管理器没探到,大致要这些:" + " ".join(pkgs)
    return "sudo " + " ".join([*fam.install, *pkgs])


def apply(fam: Family, pkgs: tuple[str, ...], *,
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
