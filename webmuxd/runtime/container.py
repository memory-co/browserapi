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
import sys
from dataclasses import dataclass
from typing import Any

from webmuxd import env
from webmuxd.runtime.base import Handle, require_ports, unavailable, wait_http

#: kasm 官方镜像 —— 桌面那一半是它做的,我们不重复造,也不在它上面加层。
IMAGE = os.environ.get("WEBMUXD_IMAGE", "webmuxd/kasmweb-chromium:1.18.0")
#: 打在容器上的标签 —— server 重启后靠它把跑着的 session 认回来。
LABEL = "webmuxd.session"

#: 密码下限。kasm 少于 6 位会**直接退出**,而且报的错和密码毫无关系
#: (`kill: usage:`),所以统一在这儿拦住。
PW_MIN = 6

#: docker 给容器的那个宿主机地址。`--add-host` 把它写进容器的 hosts。
HOST_ALIAS = "host.docker.internal"

#: 一段二十行的 TCP 转发。**两个方向都用它**,只是监听和目标不同:
#:
#: - CDP:容器内 `0.0.0.0:9223` → `127.0.0.1:9222`
#:   (Chromium 只肯听容器内的 lo,`-p` 是 DNAT 到 eth0,够不着)
#: - localhost 映射:容器内 `127.0.0.1:<port>` → `host.docker.internal:<port>`
#:   (让容器里的 `localhost:3000` 就是你机器上的 `localhost:3000`)
#:
#: 用 `python3 -c` 喂进去,**不依赖镜像里装了什么** —— 镜像因此可以完全原厂。
def relay_src(listen: str, listen_port: int, target: str, target_port: int) -> str:
    return f"""
import asyncio
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
        sr, sw = await asyncio.open_connection({target!r}, {target_port})
    except Exception:
        cw.close(); return
    await asyncio.gather(pipe(cr, sw), pipe(sr, cw))
async def main():
    s = await asyncio.start_server(on, {listen!r}, {listen_port})
    await s.serve_forever()
asyncio.run(main())
"""


@dataclass
class Profile:
    """一个镜像**长什么样**,从它自己的标签读出来。

    这就是 works/08 §5 那五个问题的答案:画面在哪个口、口令从哪个变量来、
    往 Chromium 塞参数用哪个变量、CDP 在哪个口、能不能一机多开。

    **不硬编码任何一个镜像的变量名。** 加一个新镜像不用改这里 ——
    给它打上标签就行(docker/README.md)。
    """

    window_port: int
    window_scheme: str
    password_env: str
    cdp_port: int
    args_env: str
    url_env: str
    window_user: str = ""
    window_user_env: str = ""
    host_network: str = "single"

    @classmethod
    def read(cls, docker: str, image: str) -> "Profile":
        r = subprocess.run([docker, "inspect", "-f", "{{json .Config.Labels}}", image],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise unavailable("container", f"本机没有镜像 {image}",
                              "先 docker pull,或者按 docker/README.md build 一个 wrapper")
        try:
            got = json.loads(r.stdout or "null") or {}
        except Exception:
            got = {}
        lab = {k[len("webmuxd."):]: v for k, v in got.items() if k.startswith("webmuxd.")}

        if not lab.get("window.port"):
            # **没有标签就不猜。** 猜错的后果是容器起来了、画面在别的口上、
            # 而报错指向"连不上",查半天。
            raise unavailable(
                "container", f"{image} 没有 webmuxd.* 标签,不知道怎么驱动它",
                "用 webmuxd/kasmweb-chromium,或按 docker/README.md 给它加一层")
        return cls(
            window_port=int(lab["window.port"]),
            window_scheme=lab.get("window.scheme", "http"),
            password_env=lab.get("window.password_env", ""),
            cdp_port=int(lab.get("cdp.port", 9222)),
            args_env=lab.get("chromium.args_env", ""),
            url_env=lab.get("chromium.url_env", ""),
            window_user=lab.get("window.user", ""),
            window_user_env=lab.get("window.user_env", ""),
            host_network=lab.get("host_network", "single"),
        )


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
              bind: str = "127.0.0.1", forward: list[int] | None = None,
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
        prof = Profile.read(self.docker, img)

        vnc_pw = token or secrets.token_urlsafe(9)
        if len(vnc_pw) < PW_MIN:
            raise unavailable(self.name,
                              f"画面口令至少 {PW_MIN} 位,给的是 {len(vnc_pw)} 位",
                              "kasm 会因为这个直接退出,而且报的错和密码没关系")

        w, _, h = viewport.partition("x")
        app_args = ["--start-maximized", f"--window-size={w},{h or 800}"]
        if proxy:
            app_args.append(f"--proxy-server={proxy}")

        cdp_host_port = _free_port()
        args = [self.docker, "run", "-d",
                "--name", f"webmuxd-{id}",
                "--label", f"{LABEL}={id}",
                "--shm-size=1g",                 # 少于 1G Chromium 会崩
                # **默认只绑 127.0.0.1。** 要放出去是上层的决定,所以得显式说
                # `bind=`;而且**只有画面口跟着放** —— CDP 那口比 API 更底层、
                # 没有动作日志,能连上它就等于绕过整层,它永远只在本地。
                "-p", f"{bind}:{vnc_port}:{prof.window_port}",
                "-p", f"127.0.0.1:{cdp_host_port}:{prof.cdp_port}",
                "--add-host", f"{HOST_ALIAS}:host-gateway"]
        # 变量名全来自标签 —— 这里没有任何一个镜像的名字
        for env_name, value in ((prof.password_env, vnc_pw),
                                (prof.url_env, url),
                                (prof.args_env, " ".join(app_args)),
                                (prof.window_user_env, "webmuxd")):
            if env_name:
                args += ["-e", f"{env_name}={value}"]
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
            # **CDP 是镜像自己送出来的**(wrapper 那一层负责,docker/README.md),
            # 所以这里直接在宿主机等,不用 exec 进去挂中继。
            if not wait_http(f"http://127.0.0.1:{cdp_host_port}/json/version", 150):
                raise unavailable(self.name, "容器起来了,但 CDP 没出来",
                                  f"docker logs {cid[:12]};"
                                  f"以及确认这个镜像真的转发了 {prof.cdp_port}")
            procs.update(self._forward_localhost(cid, forward or []))
            procs["sessiond"] = _spawn_sessiond(
                api_port, f"http://127.0.0.1:{cdp_host_port}", id,
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
                       "cdp_port": cdp_host_port,
                       "vnc_scheme": prof.window_scheme,
                       "vnc_bind": bind,
                       "vnc_user": prof.window_user or "webmuxd",
                       "vnc_password": vnc_pw,
                       "host_network": prof.host_network,
                       "pids": {k: p.pid for k, p in procs.items()},
                       "_procs": procs})

    def _forward_localhost(self, cid: str, ports: list[int]) -> dict[str, Any]:
        """把**你机器上的 `localhost:<port>`** 搬进容器,名字还叫 `localhost`。

        两跳,因为一跳到不了:

        1. 宿主机这边听 `172.17.0.1:<port>` → `127.0.0.1:<port>`。
           **只绑在 loopback 上的开发服务器,容器是够不着的** ——
           `host-gateway` 走的是宿主机的 docker0 地址,而服务不在那儿听。
           这一跳就是为它准备的;要是那个口上已经有人听(服务本来就绑了
           `0.0.0.0`),绑不上就跳过,本来也不需要。
        2. 容器里听 `127.0.0.1:<port>` → `host.docker.internal:<port>`。
           **必须绑容器的 lo**,不然浏览器里写 `localhost:3000` 还是不对。

        代价说清楚:第 1 跳把那个本来只在 loopback 的服务,暴露给了
        docker0 上的**所有**容器。session 停了就撤。
        """
        out: dict[str, Any] = {}
        if not ports:
            return out
        gw = _docker_gateway(self.docker)
        for port in ports:
            if gw and _port_free(gw, port):
                out[f"fwd{port}"] = subprocess.Popen(
                    [sys.executable, "-c",
                     relay_src(gw, port, "127.0.0.1", port)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    start_new_session=True)
            subprocess.run(
                [self.docker, "exec", "-d", cid, "python3", "-c",
                 relay_src("127.0.0.1", port, HOST_ALIAS, port)],
                capture_output=True)
        return out

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
            vnc = _published_first(ports)
            cdp = None
            out.append(Handle(self.name, sid, 0, vnc or 0,
                              {"container_id": cid, "adopted": True,
                               "cdp_port": cdp,
                               # 认回来的容器**读不到 profile 里的 scheme/登录名**
                               # —— 那要 inspect 镜像,而这里只有 `docker ps` 一行。
                               # 接管的一方要么自己 inspect,要么就当不知道。
                               }))
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


def _docker_gateway(docker: str) -> str:
    r = subprocess.run([docker, "network", "inspect", "bridge", "-f",
                        "{{range .IPAM.Config}}{{.Gateway}}{{end}}"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def _port_free(host: str, port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _published_first(ports: str) -> int | None:
    """认回来的容器,画面口是哪个 —— **不能按固定的容器内端口去找**,
    因为那是 profile 决定的,而这里只有 `docker ps` 那一行。
    取第一个映射到 127.0.0.1 的口就够(CDP 那个也绑 127.0.0.1,但它排在后面)。"""
    for chunk in ports.split(","):
        chunk = chunk.strip()
        if "->" in chunk and chunk.startswith("127.0.0.1:"):
            return int(chunk.split("->")[0].rsplit(":", 1)[-1])
    return None


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
