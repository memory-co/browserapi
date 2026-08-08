"""`container` runtime —— `docker run` 一个 kasm 镜像。**默认的那个。**

要隔离、要能扛 server 重启就用它:容器不是 server 的子进程,
**`kill-server` 之后它活着**,server 重启后按 label 重新发现并接管
(works/05 §3.2)。

镜像里是 **Chromium 不是 Chrome** —— Chrome 是专有软件,再分发受限,
而我们要发一个镜像出去(works/01 §3)。底座直接用官方的
`kasmweb/chromium`:桌面、KasmVNC、窗口管理器它都做好了,
我们只往上加一层 python + webmuxd。

## sessiond 跑在容器里面

**CDP 端口一次都不往外暴露。** Chromium 把调试端口绑死在
容器内的 127.0.0.1 上(`--remote-debugging-address` 已经不起作用了 ——
实测 1.18.0 + Chromium 139),所以从外面根本连不上,
而这正是我们要的:对外只有两个口,**KasmVNC 给人,webmuxd API 给代码**。

sessiond 用 `docker exec` 起在容器里,和 Chromium 同一个 network namespace。
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
from typing import Any

from webmuxd import env
from webmuxd.runtime.base import Handle, require_ports, unavailable, wait_http

#: kasm 官方镜像 —— 桌面那一半是它做的,我们不重复造。
BASE_IMAGE = os.environ.get("WEBMUXD_BASE_IMAGE", "kasmweb/chromium:1.18.0")
#: 在它上面加了 python + webmuxd 的那层。`webmuxd install` 本地 build,不推仓库。
IMAGE = os.environ.get("WEBMUXD_IMAGE", "webmuxd/kasm-chromium:0.1.0")
#: 打在容器上的标签 —— server 重启后靠它把跑着的 session 认回来。
LABEL = "webmuxd.session"

#: 容器里的端口,固定。对外映射成什么由调用方决定(端口必须自己传)。
VNC_INNER, API_INNER, CDP_INNER = 6901, 7900, 9222

#: kasm 的登录名是写死的,密码是 `VNC_PW`。
VNC_USER = "kasm_user"

#: 加料层。**只有两条 RUN** —— 底座已经是个能用的桌面了。
DOCKERFILE = """\
FROM {base}
USER root
RUN apt-get update \\
 && apt-get install -y --no-install-recommends python3-pip \\
 && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir "webmuxd=={version}"
USER 1000
"""


def dockerfile(version: str, base: str = BASE_IMAGE) -> str:
    return DOCKERFILE.format(base=base, version=version)


class ContainerRuntime:
    name = "container"

    def __init__(self, image: str | None = None, docker: str | None = None) -> None:
        rec = env.runtime_info("container")
        self.image = image or (rec or {}).get("image") or IMAGE
        self.docker = docker or (rec or {}).get("docker") or "docker"
        # 只有**真有记录、而且调用方没指定 docker** 时才信记录;
        # 没记录就现探 —— 没装过也要照常能用(install.md §5)
        self._recorded = rec if (rec and docker is None) else None

    def available(self) -> tuple[bool, str]:
        if self._recorded is not None:
            # **信记录,不每次 `docker info`** —— 那是每条命令 100ms+ 的白开销
            return bool(self._recorded.get("ok")), self._recorded.get("why", "")
        if not shutil.which(self.docker):
            return False, f"找不到 {self.docker} 命令"
        try:
            r = subprocess.run([self.docker, "info"], capture_output=True, timeout=10)
        except Exception as e:
            return False, f"{self.docker} info 跑不起来:{e}"
        if r.returncode != 0:
            return False, "docker 不可用(daemon 没起来,或者当前用户没权限)"
        return True, ""

    # ------------------------------------------------------------------ 起

    def start(self, id: str, *, api_port: int, vnc_port: int,
              url: str = "about:blank", viewport: str = "1280x800",
              volume: str | None = None, proxy: str | None = None,
              token: str | None = None, tab_max: int | None = None,
              log_limit: int | None = None, human_yield: int | None = None,
              **_opts: Any) -> Handle:
        ok, why = self.available()
        if not ok:
            # **不静默降级** —— 换成 process 等于把页面偷偷挪到你自己机器上跑
            raise unavailable(self.name, why,
                              "可以改用 runtime=process,但那样没有隔离"
                              "(页面跑在你自己机器上)")
        require_ports(api_port, vnc_port)
        if not self._has_image():
            raise unavailable(self.name, f"本机没有镜像 {self.image}",
                              "跑一下 `webmuxd install`,它会 build 出来")

        vnc_pw = token or secrets.token_urlsafe(9)
        w, _, h = viewport.partition("x")
        app_args = [f"--remote-debugging-port={CDP_INNER}",
                    "--start-maximized", f"--window-size={w},{h or 800}"]
        if proxy:
            app_args.append(f"--proxy-server={proxy}")

        args = [self.docker, "run", "-d",
                "--name", f"webmuxd-{id}",
                "--label", f"{LABEL}={id}",
                "--shm-size=1g",                 # 少于 1G Chromium 会崩
                # **只绑 127.0.0.1** —— 要放出去是上层的决定,不是我们的默认
                "-p", f"127.0.0.1:{vnc_port}:{VNC_INNER}",
                "-p", f"127.0.0.1:{api_port}:{API_INNER}",
                "-e", f"VNC_PW={vnc_pw}",
                "-e", f"LAUNCH_URL={url}",
                "-e", f"APP_ARGS={' '.join(app_args)}"]
        # 容器内部的行为也是**调用方传进来的** —— 没有配置文件那一层,
        # 你在 `session(...)` 里写什么就是什么。
        for key, val in (("WEBMUXD_TAB_MAX", tab_max),
                         ("WEBMUXD_LOG_LIMIT", log_limit),
                         ("WEBMUXD_HUMAN_YIELD", human_yield)):
            if val is not None:
                args += ["-e", f"{key}={val}"]
        if volume:
            args += ["-v", f"{volume}:/data"]
        args.append(self.image)

        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            raise unavailable(self.name, f"docker run 失败:{r.stderr.strip()[:200]}",
                              "先手工 docker run 一次看看")
        cid = r.stdout.strip()

        try:
            self._wait_cdp(cid)
            self._start_sessiond(cid)
        except Exception:
            subprocess.run([self.docker, "rm", "-f", cid], capture_output=True)
            raise

        return Handle(self.name, id, api_port, vnc_port,
                      {"container_id": cid, "image": self.image,
                       "vnc_scheme": "https",     # KasmVNC 是自签名 https
                       "vnc_user": VNC_USER, "vnc_password": vnc_pw})

    def _wait_cdp(self, cid: str) -> None:
        """等容器里的 Chromium 把调试口开起来。**在容器里等**,外面连不上它。"""
        r = subprocess.run(
            [self.docker, "exec", cid, "bash", "-c",
             f"for i in $(seq 1 90); do "
             f"curl -sf http://127.0.0.1:{CDP_INNER}/json/version >/dev/null "
             f"&& exit 0; sleep 1; done; exit 1"],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise unavailable(self.name, "容器起来了,但 Chromium 的 CDP 没开",
                              f"docker logs {cid[:12]} 看看 chromium 起没起")

    def _start_sessiond(self, cid: str) -> None:
        """sessiond 起在容器里 —— **和 Chromium 同一个 network namespace**,
        这样 CDP 一步都不用出去。"""
        subprocess.run(
            [self.docker, "exec", "-d", "-u", "root", cid, "bash", "-c",
             f"mkdir -p /data && exec python3 -m webmuxd.serve "
             f"--cdp http://127.0.0.1:{CDP_INNER} --host 0.0.0.0 "
             f"--port {API_INNER} --data /data >/var/log/sessiond.log 2>&1"],
            capture_output=True, text=True)

        port = _published_of(self.docker, cid, API_INNER)
        if not port or not wait_http(f"http://127.0.0.1:{port}/healthz", 60):
            log = subprocess.run(
                [self.docker, "exec", cid, "tail", "-20", "/var/log/sessiond.log"],
                capture_output=True, text=True).stdout
            raise unavailable(self.name, "容器起来了但 sessiond 没应答",
                              f"容器里的日志:{log.strip()[-400:]}")

    # ------------------------------------------------------------------ 管

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
            api = _published(ports, API_INNER)
            vnc = _published(ports, VNC_INNER)
            if api:
                out.append(Handle(self.name, sid, api, vnc or 0,
                                  {"container_id": cid, "adopted": True,
                                   "vnc_scheme": "https", "vnc_user": VNC_USER}))
        return out

    # ------------------------------------------------------------------ 镜像

    def _has_image(self) -> bool:
        r = subprocess.run([self.docker, "image", "inspect", "-f", "{{.Id}}",
                            self.image], capture_output=True, text=True)
        return r.returncode == 0

    def build(self, version: str, *, base: str = BASE_IMAGE,
              out=None) -> tuple[bool, str]:
        """把加料层 build 出来。**Dockerfile 从 stdin 进去**,不需要构建上下文。"""
        p = subprocess.Popen(
            [self.docker, "build", "-t", self.image, "-"],
            stdin=subprocess.PIPE,
            stdout=(out or subprocess.PIPE), stderr=subprocess.STDOUT,
            text=True)
        stdout, _ = p.communicate(dockerfile(version, base))
        if p.returncode != 0:
            return False, (stdout or "")[-400:]
        return True, ""


def _published_of(docker: str, cid: str, inner: int) -> int | None:
    r = subprocess.run([docker, "inspect", "-f", "{{json .NetworkSettings.Ports}}",
                        cid], capture_output=True, text=True)
    try:
        ports = json.loads(r.stdout or "{}")
    except Exception:
        return None
    binds = ports.get(f"{inner}/tcp") or []
    return int(binds[0]["HostPort"]) if binds else None


def _published(ports: str, inner: int) -> int | None:
    for chunk in ports.split(","):
        chunk = chunk.strip()
        if f"->{inner}/tcp" in chunk:
            host = chunk.split("->")[0]
            return int(host.rsplit(":", 1)[-1])
    return None
