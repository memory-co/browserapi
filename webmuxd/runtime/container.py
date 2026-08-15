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
import socket
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from webmuxd import env
from webmuxd.runtime.base import Handle, require_ports, unavailable, wait_http

#: kasm 官方镜像 —— 桌面那一半是它做的,我们不重复造,也不在它上面加层。
IMAGE = os.environ.get("WEBMUXD_IMAGE", "ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0")
#: 默认分辨率。**它同时是桌面尺寸和浏览器窗口尺寸** —— 两个不一致的话,
#: 窗口比桌面大就被裁、小就留白,而"人看到的画面和截图是同一个"是这东西的全部意义。
#:
#: 取 1024x768 是因为**默认镜像(kasm)的桌面就固定在这个尺寸**
#: (它的 `VNC_RESOLUTION` 改不动,见 docker/kasmweb-chromium/README)。
#: 跟着它,默认路径上窗口和桌面才对得齐。
#:
#: 用环境变量兜底,是为了让默认值本身可配(不用每次调用都传)。
DEFAULT_WINDOW_SIZE = os.environ.get("WEBMUXD_VIEWPORT", "1024x768")

#: 打在容器上的标签 —— server 重启后靠它把跑着的 session 认回来。
LABEL = "webmuxd.session"

#: 密码下限。kasm 少于 6 位会**直接退出**,而且报的错和密码毫无关系
#: (`kill: usage:`),所以统一在这儿拦住。
PW_MIN = 6


@dataclass
class Profile:
    """一个镜像**长什么样**,从它自己的标签读出来。

    这就是 works/08 §5 那五个问题的答案:画面在哪个口、口令从哪个变量来、
    往 Chromium 塞参数用哪个变量、CDP 在哪个口、能不能一机多开。

    **不硬编码任何一个镜像的变量名。** 加一个新镜像不用改这里 ——
    给它打上标签就行(docker/README.md)。
    """

    view_port: int
    view_scheme: str
    password_env: str
    cdp_port: int
    args_env: str
    url_env: str
    view_port_env: str = ""
    view_bind_env: str = ""
    auth_env: str = ""
    tls_env: str = ""
    tz_env: str = ""
    window_size_env: str = ""
    cdp_port_env: str = "WEBMUXD_CDP_PORT"
    view_login: str = ""
    view_login_env: str = ""
    host_network: str = "single"

    @classmethod
    def read(cls, docker: str, image: str, *, pull: bool = True) -> "Profile":
        def inspect() -> subprocess.CompletedProcess:
            return subprocess.run(
                [docker, "inspect", "-f", "{{json .Config.Labels}}", image],
                capture_output=True, text=True)

        r = inspect()
        if r.returncode != 0 and pull:
            # **本机没有就自己拉。** `docker run` 本来就会自动拉,是我们为了读标签
            # 先 inspect 了一下才把它挡住的 —— 那是自己制造的障碍,不是真的要求。
            #
            # 拉是分钟级的事(底座 4 GB),所以**说一声再拉**,别让人对着一个
            # 不动的终端猜。
            print(f"本机没有 {image},先拉一下(第一次会久)…", file=sys.stderr, flush=True)
            got = subprocess.run([docker, "pull", image], capture_output=True, text=True)
            if got.returncode != 0:
                why = (got.stderr.strip().splitlines() or ["拉取失败"])[-1]
                raise unavailable("container", f"拉不到镜像 {image}:{why[:160]}",
                                  "确认名字对不对、这个网络到不到得了 registry;"
                                  "国内可以用 docker.cnb.cool/agentuse/webmuxd/…")
            r = inspect()
        if r.returncode != 0:
            raise unavailable("container", f"本机没有镜像 {image}",
                              "先 docker pull,或者按 docker/README.md build 一个 wrapper")
        try:
            got = json.loads(r.stdout or "null") or {}
        except Exception:
            got = {}
        lab = {k[len("webmuxd."):]: v for k, v in got.items() if k.startswith("webmuxd.")}

        if not lab.get("view.port"):
            # **没有标签就不猜。** 猜错的后果是容器起来了、画面在别的口上、
            # 而报错指向"连不上",查半天。
            raise unavailable(
                "container", f"{image} 没有 webmuxd.* 标签,不知道怎么驱动它",
                "用 webmuxd/kasmweb-chromium,或按 docker/README.md 给它加一层")
        return cls(
            view_port=int(lab["view.port"]),
            view_scheme=lab.get("view.scheme", "http"),
            password_env=lab.get("view.password_env", ""),
            cdp_port=int(lab.get("cdp.port", 9222)),
            args_env=lab.get("chromium.args_env", ""),
            url_env=lab.get("chromium.url_env", ""),
            view_port_env=lab.get("view.port_env", ""),
            view_bind_env=lab.get("view.bind_env", ""),
            auth_env=lab.get("view.auth_env", ""),
            tls_env=lab.get("view.tls_env", ""),
            tz_env=lab.get("tz.env", ""),
            window_size_env=lab.get("window_size.env", ""),
            cdp_port_env=lab.get("cdp.port_env") or "WEBMUXD_CDP_PORT",
            view_login=lab.get("view.login", ""),
            view_login_env=lab.get("view.login_env", ""),
            host_network=lab.get("host.network", "single"),
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

    def start(self, id: str, *, api_port: int, view_port: int,
              url: str = "about:blank", window_size: str = "",
              volume: str | None = None, proxy: str | None = None,
              password: str | None = None,
              login: str | None = None, image: str | None = None,
              cdp_port: int = 0,
              network: str = "host", bind: str = "127.0.0.1",
              auth: bool = True, tls: bool = True, tz: str | None = None,
              tab_max: int | None = None, log_limit: int | None = None,
              human_yield: int | None = None, **_opts: Any) -> Handle:
        ok, why = self.available()
        if not ok:
            # **不静默降级** —— 换成 process 等于把页面偷偷挪到你自己机器上跑
            raise unavailable(self.name, why,
                              "可以改用 runtime=process,但那样没有隔离"
                              "(页面跑在你自己机器上)")
        require_ports(api_port, view_port)
        img = image or self.image
        prof = Profile.read(self.docker, img)

        if auth:
            password = password or secrets.token_urlsafe(9)
            if len(password) < PW_MIN:
                raise unavailable(self.name,
                                  f"画面口令至少 {PW_MIN} 位,给的是 {len(password)} 位",
                                  "kasm 会因为这个直接退出,而且报的错和密码没关系")
        else:
            # **关掉鉴权得镜像支持**,不能默默留着口令装作关了
            if not prof.auth_env:
                raise unavailable(
                    self.name, f"{img} 没说怎么关鉴权(webmuxd.view.auth_env)",
                    "换个镜像,或者别关 —— 画面口一旦对外,没口令就是谁都能用")
            password = ""

        window_size = window_size or DEFAULT_WINDOW_SIZE
        w, _, h = window_size.partition("x")
        app_args = ["--start-maximized", f"--window-size={w},{h or 800}"]
        if proxy:
            app_args.append(f"--proxy-server={proxy}")

        # **不给就自动挑** —— CDP 口只在本机用,没有理由让调用方操心;
        # 但给了就照给的来(要过防火墙、要固定端口的场合)。
        cdp_host_port = cdp_port or _free_port()
        args = [self.docker, "run", "-d",
                "--name", f"webmuxd-{id}",
                "--label", f"{LABEL}={id}",
                "--shm-size=1g"]                 # 少于 1G Chromium 会崩

        if network == "host":
            # **默认。** 换来的是"容器里的 `localhost` 就是你的 `localhost`" ——
            # 调试用的浏览器得能打开你自己机器上跑着的页面,而开发服务器常常
            # 只绑 loopback,bridge 下**根本够不着**(host-gateway 走的是 eth0)。
            #
            # 代价两条:没有网络隔离;**能不能一机多开取决于镜像**
            # (标签 `webmuxd.host_network`,works/08 §6.2)。
            #
            # 没有 `-p`,所以画面口不是映射出来的,是**直接告诉镜像听在那儿**。
            if not prof.view_port_env:
                raise unavailable(
                    self.name, f"{img} 没说画面口怎么改(webmuxd.view.port_env)",
                    "host 网络下没有 -p 可以映射;换 network=\"bridge\" 就不需要它")
            # **把宿主机的 hostname 在容器里钉到回环。**
            #
            # 很多云主机(阿里云是典型)的 /etc/hosts 里没有自己 hostname 的
            # IPv4 记录。host 网络下容器沿用这份 hosts,于是 kasm 启动时
            # `xauth` 拿 hostname 拼显示名(`<主机名>:1`)直接失败,容器起不来
            # —— 而报出来的是 `kill: usage:` 和 `Exited (2)`,和 hostname
            # 一点关系都看不出来。
            #
            # **不去改宿主机的 /etc/hosts** —— 那是为了迁就容器去动系统文件,
            # 而且换台机器还得再来一次。`--add-host` 只作用于这个容器。
            args += ["--network", "host",
                     "--add-host", f"{socket.gethostname()}:127.0.0.1",
                     "-e", f"{prof.view_port_env}={view_port}",
                     "-e", f"{prof.cdp_port_env}={cdp_host_port}"]
            # host 下容器的网络栈就是宿主机的,所以 `bind` 直接传给镜像。
            if prof.view_bind_env:
                args += ["-e", f"{prof.view_bind_env}={bind}"]
            elif bind != "0.0.0.0":
                # **管不住就说管不住**,别让调用方以为它只在本机
                raise unavailable(
                    self.name, f"{img} 没说画面口绑哪个地址怎么配"
                                f"(webmuxd.view.bind_env),没法限制成 {bind}",
                    "换个镜像,或者显式 bind=\"0.0.0.0\" 承认它是对外的")
        else:
            # **要网络隔离、或者那个镜像 host 下开不了多个,就用它。**
            # 代价是容器里的 `localhost` 是它自己的 —— 宿主机上只绑 loopback
            # 的服务够不着。
            #
            # 画面口跟着 `bind` 走(**默认只在本机**,放出去是上层的决定);
            # CDP 口**永远只绑 127.0.0.1** —— 它比 API 更底层、没有动作日志,
            # 能连上就等于绕过整层。
            # **容器内必须绑 0.0.0.0**,否则 `-p` 够不着它(DNAT 到的是 eth0);
            # 对外收不收得住由 `-p` 前面那个地址决定 —— 这一层才是 `bind` 的落点。
            if prof.view_bind_env:
                args += ["-e", f"{prof.view_bind_env}=0.0.0.0"]
            args += ["-p", f"{bind}:{view_port}:{prof.view_port}",
                     "-p", f"127.0.0.1:{cdp_host_port}:{prof.cdp_port}"]
        # 变量名全来自标签 —— 这里没有任何一个镜像的名字
        if prof.auth_env:
            args += ["-e", f"{prof.auth_env}={1 if auth else 0}"]
        if not tls and not prof.tls_env:
            # KasmVNC 就是恒 TLS(实测:拿掉 -sslOnly 也一样)。**说不行就是不行**,
            # 不能让调用方按 http 去拼 URL。
            raise unavailable(self.name, f"{img} 的画面口关不掉 TLS"
                                         f"(没有 webmuxd.view.tls_env)",
                              "它就是 https。要 http 就换个镜像")
        if prof.tls_env:
            args += ["-e", f"{prof.tls_env}={1 if tls else 0}"]
        # 时区。**两个底座都叫 TZ**,所以没什么可翻译的 —— 但仍然走标签,
        # 免得下一个镜像换了名字时这里要改代码。
        if tz and prof.tz_env:
            args += ["-e", f"{prof.tz_env}={tz}"]
        # **桌面分辨率跟着 window_size 一起定。** 早先只把它传给了 Chromium 的
        # --window-size,桌面还是底座的默认(kasm 1024x768),于是窗口比桌面大、
        # 边上被裁 —— 而这东西的全部意义就是"人看到的和截图是同一个"。
        if prof.window_size_env:
            args += ["-e", f"{prof.window_size_env}={window_size}"]
        for env_name, value in ((prof.password_env, password),
                                (prof.url_env, url),
                                (prof.args_env, " ".join(app_args)),
                                (prof.view_login_env, login or "webmuxd")):
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

        return Handle(self.name, id, api_port, view_port,
                      {"container_id": cid, "image": img,
                       "cdp_port": cdp_host_port,
                       # scheme 是**算出来的**:标签给的是默认,而 tls 开关能改它。
                       # 报错的 scheme 会让人拼出一个连不上的 URL。
                       "view_scheme": prof.view_scheme if tls else "http",
                       "network": network,
                       # 两种模式下 `bind` 都真的生效了:host 是镜像自己绑,
                       # bridge 是 `-p` 那一层收着。如实报出来。
                       "view_bind": bind,
                       "view_login": (prof.view_login or "webmuxd") if auth else "",
                       "view_password": password,
                       "auth": auth,
                       "host_network": prof.host_network,
                       "pids": {k: p.pid for k, p in procs.items()},
                       "_procs": procs})

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
