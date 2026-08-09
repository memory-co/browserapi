"""`container` runtime —— `docker run` 一个 kasm 镜像。**默认的那个。**

要隔离、要能扛 server 重启就用它:容器不是 server 的子进程,
**`kill-server` 之后它活着**,server 重启后按 label 重新发现并接管
(works/05 §3.2)。

## 用原厂镜像,不自己 build

跑的就是 `kasmweb/chromium:1.18.0`,**没有派生层**。桌面、KasmVNC、
窗口管理器、Chromium 全是 kasm 做好的;我们往里加的东西只有一个
`docker exec` 进去的中继(见下),不需要镜像里装任何我们的代码。

代价是 sessiond 跑在**你这边**而不是容器里。换来的是:镜像随便换
(`--image` 指哪个都行)、起 session 不用等 pip、`webmuxd install`
只需要回答"docker 通不通、镜像拉不拉得到"。

镜像里是 **Chromium 不是 Chrome** —— Chrome 是专有软件,再分发受限(works/01 §3)。

## 那一跳中继是干什么的

Chromium 把调试端口**绑死在容器内的 127.0.0.1** 上 —— 给
`--remote-debugging-address=0.0.0.0` 也没用(实测 `kasmweb/chromium:1.18.0`
+ Chromium 139,`/proc/net/tcp` 里始终是 `0100007F:2406`)。
所以 `-p` 映射不到它。

于是用镜像自带的 python3 在容器里起一个二十行的 TCP 中继:
`0.0.0.0:9223 → 127.0.0.1:9222`,再把 9223 映射到宿主机的
**127.0.0.1**。Chromium 那边看到的仍然是本地连接。

**这一跳把 CDP 暴露到了宿主机的 loopback 上** —— 它和 webmuxd API
同一个可达范围,能连上它的人本来也能连 API。但它比 API 更底层、
没有动作日志,所以三个口一律只绑 `127.0.0.1`:要放出去是上层的决定。
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

#: kasm 官方镜像 —— 桌面那一半是它做的,我们不重复造,也不在它上面加层。
IMAGE = os.environ.get("WEBMUXD_IMAGE", "kasmweb/chromium:1.18.0")
#: 打在容器上的标签 —— server 重启后靠它把跑着的 session 认回来。
LABEL = "webmuxd.session"

#: 容器里的端口,固定。对外映射成什么由调用方决定(端口必须自己传)。
VNC_INNER, CDP_INNER, CDP_RELAY = 6901, 9222, 9223

#: kasm 的登录名是写死的,密码是 `VNC_PW`,**而且它要求至少 6 位** ——
#: 短了容器会直接退出,报一句和密码毫无关系的 `kill: usage:`。
VNC_USER, VNC_PW_MIN = "kasm_user", 6

#: 容器里那一跳。只用镜像自带的 python3,不装任何东西。
RELAY_SRC = """
import asyncio, sys
async def pipe(r, w):
    try:
        while True:
            d = await r.read(65536)
            if not d:
                break
            w.write(d); await w.drain()
    except Exception:
        pass
    finally:
        try: w.close()
        except Exception: pass
async def on(cr, cw):
    try:
        sr, sw = await asyncio.open_connection("127.0.0.1", %d)
    except Exception:
        cw.close(); return
    await asyncio.gather(pipe(cr, sw), pipe(sr, cw))
async def main():
    s = await asyncio.start_server(on, "0.0.0.0", %d)
    await s.serve_forever()
asyncio.run(main())
""" % (CDP_INNER, CDP_RELAY)


class ContainerRuntime:
    name = "container"

    def __init__(self, image: str | None = None, docker: str | None = None) -> None:
        self.image = image or env.get("default_container") or IMAGE
        self.docker = docker or env.get("docker") or "docker"
        # 只有**真有记录、而且调用方没指定 docker** 时才信记录;
        # 没记录就现探 —— 没装过也要照常能用(install.md §5)
        self._recorded = bool(env.get("docker")) and docker is None

    def available(self) -> tuple[bool, str]:
        if self._recorded:
            # **信记录,不每次 `docker info`** —— 那是每条命令 100ms+ 的白开销
            return True, ""
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
              token: str | None = None, image: str | None = None,
              tab_max: int | None = None, log_limit: int | None = None,
              human_yield: int | None = None, **_opts: Any) -> Handle:
        ok, why = self.available()
        if not ok:
            # **不静默降级** —— 换成 process 等于把页面偷偷挪到你自己机器上跑
            raise unavailable(self.name, why,
                              "可以改用 runtime=process,但那样没有隔离"
                              "(页面跑在你自己机器上)")
        require_ports(api_port, vnc_port)
        img = image or self.image

        vnc_pw = token or secrets.token_urlsafe(9)
        if len(vnc_pw) < VNC_PW_MIN:
            # kasm 那边的失败信息毫无线索,所以在这儿拦住
            raise unavailable(self.name,
                              f"VNC 密码至少 {VNC_PW_MIN} 位,给的是 {len(vnc_pw)} 位",
                              "kasm 会因为这个直接退出,而且报的错和密码没关系")

        w, _, h = viewport.partition("x")
        app_args = [f"--remote-debugging-port={CDP_INNER}",
                    "--start-maximized", f"--window-size={w},{h or 800}"]
        if proxy:
            app_args.append(f"--proxy-server={proxy}")

        relay_port = _free_port()
        args = [self.docker, "run", "-d",
                "--name", f"webmuxd-{id}",
                "--label", f"{LABEL}={id}",
                "--shm-size=1g",                 # 少于 1G Chromium 会崩
                # **一律只绑 127.0.0.1** —— 要放出去是上层的决定,不是我们的默认
                "-p", f"127.0.0.1:{vnc_port}:{VNC_INNER}",
                "-p", f"127.0.0.1:{relay_port}:{CDP_RELAY}",
                "-e", f"VNC_PW={vnc_pw}",
                "-e", f"LAUNCH_URL={url}",
                "-e", f"APP_ARGS={' '.join(app_args)}"]
        if volume:
            args += ["-v", f"{volume}:/data"]
        args.append(img)

        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            raise unavailable(self.name, f"docker run 失败:{r.stderr.strip()[:200]}",
                              "先手工 docker run 一次看看")
        cid = r.stdout.strip()

        procs: dict[str, Any] = {}
        try:
            self._wait_cdp(cid)
            self._start_relay(cid, relay_port)
            procs["sessiond"] = _spawn_sessiond(
                api_port, f"http://127.0.0.1:{relay_port}", id,
                tab_max=tab_max, log_limit=log_limit, human_yield=human_yield)
            if not wait_http(f"http://127.0.0.1:{api_port}/healthz", 30):
                raise unavailable(self.name, "sessiond 没起来",
                                  "手工跑一遍 python -m webmuxd.serve 看报什么")
        except Exception:
            _kill(procs)
            subprocess.run([self.docker, "rm", "-f", cid], capture_output=True)
            raise

        return Handle(self.name, id, api_port, vnc_port,
                      {"container_id": cid, "image": img,
                       "cdp_port": relay_port,
                       "vnc_scheme": "https",     # KasmVNC 是自签名 https
                       "vnc_user": VNC_USER, "vnc_password": vnc_pw,
                       "pids": {k: p.pid for k, p in procs.items()},
                       "_procs": procs})

    def _wait_cdp(self, cid: str) -> None:
        """等容器里的 Chromium 把调试口开起来。**在容器里等**,外面还连不上。"""
        r = subprocess.run(
            [self.docker, "exec", cid, "bash", "-c",
             f"for i in $(seq 1 90); do "
             f"curl -sf http://127.0.0.1:{CDP_INNER}/json/version >/dev/null "
             f"&& exit 0; sleep 1; done; exit 1"],
            capture_output=True, text=True, timeout=150)
        if r.returncode != 0:
            raise unavailable(self.name, "容器起来了,但 Chromium 的 CDP 没开",
                              f"docker logs {cid[:12]} 看看 chromium 起没起")

    def _start_relay(self, cid: str, relay_port: int) -> None:
        subprocess.run([self.docker, "exec", "-d", cid,
                        "python3", "-c", RELAY_SRC], capture_output=True)
        if not wait_http(f"http://127.0.0.1:{relay_port}/json/version", 20):
            raise unavailable(self.name, "容器里那一跳中继没起来",
                              f"docker exec {cid[:12]} python3 -c … 手工跑一遍")

    # ------------------------------------------------------------------ 管

    def stop(self, handle: Handle) -> None:
        _kill(handle.detail.get("_procs") or {},
              (handle.detail.get("pids") or {}).values())
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
        """**server 重启后把跑着的容器认回来** —— 它们本来就活着。

        注意认回来的只有容器;sessiond 是 server 的子进程,跟着 server 死了,
        所以接管的一方要自己重新起一个。
        """
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
            vnc = _published(ports, VNC_INNER)
            cdp = _published(ports, CDP_RELAY)
            out.append(Handle(self.name, sid, 0, vnc or 0,
                              {"container_id": cid, "adopted": True,
                               "cdp_port": cdp, "vnc_scheme": "https",
                               "vnc_user": VNC_USER}))
        return out


# ---------------------------------------------------------------------------

def _spawn_sessiond(api_port: int, cdp: str, id: str, *, tab_max: int | None,
                    log_limit: int | None, human_yield: int | None):
    import sys
    import tempfile
    data = os.path.join(tempfile.gettempdir(), f"webmuxd-{id}")
    child = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))
    for key, val in (("WEBMUXD_TAB_MAX", tab_max), ("WEBMUXD_LOG_LIMIT", log_limit),
                     ("WEBMUXD_HUMAN_YIELD", human_yield)):
        if val is not None:
            child[key] = str(val)
    # `start_new_session` —— 脱离调用者的进程组。CLI 是一次性的命令,
    # 不脱离的话 `webmuxd new` 一退出就把 sessiond 带走了。
    return subprocess.Popen(
        [sys.executable, "-m", "webmuxd.serve", "--cdp", cdp,
         "--host", "127.0.0.1", "--port", str(api_port), "--data", data],
        env=child, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)


def _kill(procs: dict, pids=()) -> None:
    import contextlib
    import signal
    for p in procs.values():
        with contextlib.suppress(Exception):
            p.terminate()
    if not procs:
        for pid in pids:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _published(ports: str, inner: int) -> int | None:
    for chunk in ports.split(","):
        chunk = chunk.strip()
        if f"->{inner}/tcp" in chunk:
            host = chunk.split("->")[0]
            return int(host.rsplit(":", 1)[-1])
    return None


def _published_of(docker: str, cid: str, inner: int) -> int | None:
    r = subprocess.run([docker, "inspect", "-f", "{{json .NetworkSettings.Ports}}",
                        cid], capture_output=True, text=True)
    try:
        binds = (json.loads(r.stdout or "{}").get(f"{inner}/tcp")) or []
    except Exception:
        return None
    return int(binds[0]["HostPort"]) if binds else None
