"""`container` runtime —— `docker run` 一个 kasm 镜像。**默认的那个。**

要隔离、要能扛 server 重启就用它:容器不是 server 的子进程,
**`kill-server` 之后它活着**,server 重启后按 label 重新发现并接管
(works/05 §3.2)。

镜像里是 **Chromium 不是 Chrome** —— Chrome 是专有软件,再分发受限,
而我们要发一个镜像出去(works/01 §3)。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from webmuxd.runtime.base import Handle, require_ports, unavailable, wait_http

IMAGE = os.environ.get("WEBMUXD_IMAGE", "webmuxd/operator:1.0")
#: 打在容器上的标签 —— server 重启后靠它把跑着的 session 认回来。
LABEL = "webmuxd.session"


class ContainerRuntime:
    name = "container"

    def __init__(self, image: str = IMAGE, docker: str = "docker") -> None:
        self.image = image
        self.docker = docker

    def available(self) -> tuple[bool, str]:
        if not shutil.which(self.docker):
            return False, f"找不到 {self.docker} 命令"
        try:
            r = subprocess.run([self.docker, "info"], capture_output=True, timeout=10)
        except Exception as e:
            return False, f"{self.docker} info 跑不起来:{e}"
        if r.returncode != 0:
            return False, "docker 不可用(daemon 没起来,或者当前用户没权限)"
        return True, ""

    def start(self, id: str, *, api_port: int, vnc_port: int,
              url: str = "about:blank", viewport: str = "1280x800",
              volume: str | None = None, proxy: str | None = None,
              token: str | None = None, **_opts: Any) -> Handle:
        ok, why = self.available()
        if not ok:
            # **不静默降级** —— 换成 process 等于把页面偷偷挪到你自己机器上跑
            raise unavailable(self.name, why,
                              "可以改用 runtime=process,但那样没有隔离"
                              "(页面跑在你自己机器上)")
        require_ports(api_port, vnc_port)

        args = [self.docker, "run", "-d",
                "--name", f"webmuxd-{id}",
                "--label", f"{LABEL}={id}",
                "--shm-size=1g",                 # 少于 1G Chromium 会崩
                "-p", f"{vnc_port}:6901",
                "-p", f"{api_port}:7900",
                "-e", f"WEBMUXD_VIEWPORT={viewport}",
                "-e", f"WEBMUXD_START_URL={url}"]
        if token:
            args += ["-e", f"WEBMUXD_TOKEN={token}"]
        if proxy:
            args += ["-e", f"WEBMUXD_PROXY={proxy}"]
        if volume:
            args += ["-v", f"{volume}:/data"]
        args.append(self.image)

        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            raise unavailable(self.name, f"docker run 失败:{r.stderr.strip()[:200]}",
                              "先手工 docker run 一次看看")
        cid = r.stdout.strip()

        if not wait_http(f"http://127.0.0.1:{api_port}/healthz", 60):
            logs = subprocess.run([self.docker, "logs", "--tail", "20", cid],
                                  capture_output=True, text=True).stdout
            subprocess.run([self.docker, "rm", "-f", cid], capture_output=True)
            raise unavailable(self.name, "容器起来了但 sessiond 没应答",
                              f"docker logs {cid[:12]} 看看:{logs.strip()[-300:]}")

        return Handle(self.name, id, api_port, vnc_port, {"container_id": cid})

    def stop(self, handle: Handle) -> None:
        cid = handle.detail.get("container_id")
        if cid:
            subprocess.run([self.docker, "rm", "-f", cid], capture_output=True)

    def alive(self, handle: Handle) -> bool:
        cid = handle.detail.get("container_id")
        if not cid:
            return False
        r = subprocess.run([self.docker, "inspect", "-f", "{{.State.Running}}", cid],
                           capture_output=True, text=True)
        return r.stdout.strip() == "true"

    def discover(self) -> list[Handle]:
        """**server 重启后把跑着的容器认回来** —— 它们本来就活着。"""
        r = subprocess.run(
            [self.docker, "ps", "--filter", f"label={LABEL}",
             "--format", "{{.ID}}\t{{.Label \"" + LABEL + "\"}}\t{{.Ports}}"],
            capture_output=True, text=True)
        out: list[Handle] = []
        for line in r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            cid, sid, ports = parts
            api = _published(ports, 7900)
            vnc = _published(ports, 6901)
            if api:
                out.append(Handle(self.name, sid, api, vnc or 0,
                                  {"container_id": cid, "adopted": True}))
        return out


def _published(ports: str, inner: int) -> int | None:
    for chunk in ports.split(","):
        chunk = chunk.strip()
        if f"->{inner}/tcp" in chunk:
            host = chunk.split("->")[0]
            return int(host.rsplit(":", 1)[-1])
    return None
