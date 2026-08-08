"""`webmuxd install` —— 装一次,之后别再问(docs/v1/cli/install.md)。

**幂等**:再跑一次就是重新探一遍,所以"检查"和"安装"是同一个命令,
不需要单独的 `doctor`。

**探不到的不让整条命令失败**:docker 不通就把 `container` 记成不可用并写下原因,
剩下的照常 —— 一台能用 `process` 的机器不该因为没装 docker 就装不上。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from typing import Any

from webmuxd import env
from webmuxd.runtime.container import BASE_IMAGE, IMAGE, ContainerRuntime
from webmuxd.runtime.process import CHROMIUM_NAMES, VNC_NAMES

OK, WARN, BAD = "✓", "⚠", "✗"


def install(*, pull: bool = True, image: str = IMAGE,
            out=sys.stdout) -> dict[str, Any]:
    say = lambda *a: print(*a, file=out)      # noqa: E731
    say("探测环境…")

    py = platform.python_version()
    say(f"  {'python':<11} {py:<40} {OK}")

    runtimes: dict[str, Any] = {}
    runtimes["container"] = _container(image, pull, say)
    runtimes["process"] = _process(say)
    runtimes["remote"] = {"ok": True}

    usable = [k for k, v in runtimes.items() if v.get("ok")]
    default = "container" if runtimes["container"].get("ok") else (
        "process" if runtimes["process"].get("ok") else "remote")

    record = {"webmuxd": _version(), "runtimes": runtimes,
              "default_runtime": default}
    p = env.save(record)

    say("")
    say(f"可用的 runtime:{'  '.join(usable) or '(一个都没有)'}")
    say(f"默认:{default}")
    say(f"记录写到 {p}")
    return record


# ---------------------------------------------------------------------------

def _container(image: str, pull: bool, say) -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        say(f"  {'docker':<11} {'找不到':<40} {WARN} container runtime 用不了")
        return {"ok": False, "why": "找不到 docker 命令"}

    ver = _run([docker, "version", "--format", "{{.Server.Version}}"])
    if ver is None:
        say(f"  {'docker':<11} {'daemon 不通':<40} {WARN} container runtime 用不了")
        return {"ok": False, "docker": docker,
                "why": "docker daemon 没起来,或者当前用户没权限"}
    say(f"  {'docker':<11} {ver:<40} {OK}")

    info: dict[str, Any] = {"ok": True, "docker": docker, "image": image,
                            "base_image": BASE_IMAGE}
    if not pull:
        info["image_pulled"] = _has_image(docker, image)
        return info
    if _has_image(docker, image):
        say(f"  {'镜像':<11} {image:<40} {OK} 已经有了")
        info["image_pulled"] = True
        return info

    # 底座是 kasm 官方的,拉;加料层是我们的,**本地 build,不推仓库** ——
    # 就两条 RUN,没必要为它维护一个 registry。
    say(f"拉底座 {BASE_IMAGE} …(4 GB 左右,第一次会久)")
    r = subprocess.run([docker, "pull", BASE_IMAGE], capture_output=True, text=True)
    if r.returncode != 0:
        # **拉不到不代表 docker 不能用** —— 记下来,别把整条命令判死
        why = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "拉取失败"
        say(f"  {WARN} 拉不到:{why[:80]}")
        info["image_pulled"] = False
        info["image_why"] = why[:200]
        return info

    say(f"build {image} …(在底座上加 python + webmuxd)")
    ok, err = ContainerRuntime(image=image, docker=docker).build(_version())
    info["image_pulled"] = ok
    if ok:
        say(f"  {OK} 镜像就绪")
    else:
        say(f"  {WARN} build 失败:{err.strip().splitlines()[-1][:80] if err.strip() else ''}")
        info["image_why"] = err[:400]
    return info


def _process(say) -> dict[str, Any]:
    chromium = _which(CHROMIUM_NAMES)
    if not chromium:
        say(f"  {'chromium':<11} {'找不到':<40} {WARN} process runtime 用不了")
        return {"ok": False, "why": "本机没有 chromium",
                "hint": "装一个,或者用 runtime=container(浏览器在镜像里)"}

    ver = _run([chromium, "--version"]) or ""
    say(f"  {'chromium':<11} {f'{chromium} ({ver})'[:40]:<40} {OK}")

    info: dict[str, Any] = {"ok": True, "chromium": chromium,
                            "version": ver, "notes": []}
    vnc = _which(VNC_NAMES)
    if vnc:
        info["vnc"] = vnc
        say(f"  {'Xvnc':<11} {vnc:<40} {OK}")
    else:
        info["vnc"] = None
        # **说出来**:有 API 没画面仍然有用,但假装有画面比没画面更糟
        note = "没有 Xvnc —— 这种 session 只有 API 没有画面"
        info["notes"].append(note)
        say(f"  {'Xvnc':<11} {'找不到':<40} {WARN} {note}")
    return info


def _which(names: tuple[str, ...]) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _run(args: list[str]) -> str | None:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=15)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _has_image(docker: str, image: str) -> bool:
    return _run([docker, "image", "inspect", "-f", "{{.Id}}", image]) is not None


def _version() -> str:
    try:
        from webmuxd import __version__
        return __version__
    except Exception:
        return "0"
