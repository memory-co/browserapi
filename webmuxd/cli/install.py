"""`webmuxd install` —— 探一遍,写下来,别再问(docs/v1/cli/install.md)。

**它只回答两个问题:**

1. docker 能用吗
2. 这个网络环境拉得到那个镜像吗

就这两条。**它不 build 任何东西,也不预先 `docker pull`** ——
镜像是 kasm 原厂的,`docker run` 自己会拉;这里只是提前告诉你拉不拉得到,
免得你在起 session 的时候才发现。

**幂等**:再跑一次就是重新探一遍,所以"检查"和"安装"是同一个命令,
不需要单独的 `doctor`。
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from typing import Any

from webmuxd import env
from webmuxd.runtime.container import IMAGE

OK, WARN = "✓", "⚠"


def install(*, image: str = IMAGE, out=sys.stdout, **_compat: Any) -> dict[str, Any]:
    say = lambda *a: print(*a, file=out)      # noqa: E731
    say("探测环境…")

    say(f"  {'python':<11} {platform.python_version():<34} {OK}")

    docker = shutil.which("docker")
    version = _run([docker, "version", "--format", "{{.Server.Version}}"]) if docker else None
    if not version:
        why = "找不到 docker 命令" if not docker else \
              "docker daemon 没起来,或者当前用户没权限"
        say(f"  {'docker':<11} {why:<34} {WARN}")
        record = {"docker": docker}
    else:
        say(f"  {'docker':<11} {version:<34} {OK}")
        record = {"docker": docker, "docker_version": version}

    # **只问拉不拉得到,不真拉。** `docker manifest inspect` 一秒出结果,
    # 而 `docker pull` 是 4 GB —— 探测不该顺手做一件那么重的事。
    if version:
        if _reachable(docker, image):
            say(f"  {'镜像':<11} {image:<34} {OK}")
            record["default_container"] = image
        else:
            say(f"  {'镜像':<11} {(image + ' 拉不到'):<34} {WARN}")
            # **不记一个拉不下来的名字。** 键不在,就是"你得自己填"。
            say(f"     这个网络环境到不了 registry。"
                f"自己指一个:webmuxd new --image <你的镜像>")

    p = env.save(record)
    say("")
    say(f"记录写到 {p}")
    if not record.get("default_container"):
        say(f"{WARN} 没有 default_container —— container runtime 得每次指定 --image")
    return record


# ---------------------------------------------------------------------------

def _reachable(docker: str, image: str) -> bool:
    """本机已经有,或者 registry 上问得到。"""
    if _run([docker, "image", "inspect", "-f", "{{.Id}}", image]):
        return True
    try:
        r = subprocess.run([docker, "manifest", "inspect", image],
                           capture_output=True, text=True, timeout=60)
    except Exception:
        return False
    return r.returncode == 0


def _run(args: list[str]) -> str | None:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    return r.stdout.strip() if r.returncode == 0 else None
