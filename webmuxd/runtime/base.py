"""runtime —— **只回答一个问题:这个 session 的 CDP 端点从哪来。**

docs/v2/works/07-runtime.md §1:契约从 v1 的两个端点减成**一个 CDP 端点**。
画面不再是 runtime 的义务 —— 它是 webmuxd 用这个端点自己产的。

于是三分法塌成两种:

    本机起一个    install 下来的 chrome --headless=new      ← 默认
    remote        别人已经把 CDP 端点给你了

**容器不在里面。** 要隔离就把 webmuxd 整个放进容器里跑,那是你的部署决定,
不是我们的参数(§2)。

**不可用时抛,不降级。** 浏览器找不到就报错并说该跑 `webmuxd install`,
不静默换一个 —— 那等于让你以为在跑钉死的那一版。
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from webmuxd.errors import PortInUse, RuntimeUnavailable


@dataclass
class Handle:
    """一个起来了的 session 的把柄。

    **一个 session 一个端口**,画面和 API 落在同一个上(works/04 §1)。

    `kind` 决定 `kill-server` 之后它死不死:两种 runtime 的 sessiond 都是
    server 的子进程,跟着死;`remote` 那头的浏览器不归我们,**不动它**。
    """

    kind: str
    id: str
    port: int
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def view_url(self) -> str:
        """**和 API 同一个口。** v1 那个"没有画面就是空字符串"的分支没有了 ——
        画面是我们自己产的,只要 sessiond 活着它就在。"""
        return f"http://127.0.0.1:{self.port}/"


class Runtime(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        """能不能用,以及不能用时那句**有用的**提示。"""

    def start(self, id: str, *, port: int, **opts: Any) -> Handle: ...

    def stop(self, handle: Handle) -> None: ...

    def alive(self, handle: Handle) -> bool: ...


# ---------------------------------------------------------------------------

def port_free(port: int, host: str = "127.0.0.1") -> bool:
    return _bind_error(port, host) is None


def _bind_error(port: int, host: str) -> OSError | None:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return None
        except OSError as e:
            return e


def require_ports(*ports: int, host: str = "127.0.0.1") -> None:
    """**端口是部署决定的,我们不替你换一个。** 被占了就说被占了。

    **"被占"和"没权限"要分开说** —— 1024 以下要 root,而报"被占了"会让人
    去查根本不存在的那个进程。提示指错方向比没有提示更糟。
    """
    import errno
    for p in ports:
        e = _bind_error(p, host)
        if e is None:
            continue
        if e.errno == errno.EACCES:
            raise PortInUse(f"端口 {p} 要 root 才能绑(1024 以下都要)",
                            code="port_in_use",
                            details={"port": p, "reason": "privileged"})
        raise PortInUse(f"端口 {p} 被占了", code="port_in_use",
                        details={"port": p, "reason": "in_use"})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_http(url: str, timeout: float = 30.0) -> bool:
    import urllib.error
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except urllib.error.HTTPError:
            return True                  # 有响应就算起来了(401 也算)
        except Exception:
            time.sleep(0.25)
    return False


def wait_port(port: int, timeout: float = 30.0, host: str = "127.0.0.1") -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), 0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def unavailable(runtime: str, why: str, hint: str) -> RuntimeUnavailable:
    return RuntimeUnavailable(why, code="runtime_unavailable",
                              details={"runtime": runtime, "hint": hint})


# --------------------------------------------------------------------------
# sessiond —— 两种 runtime 共用这一段:**都是"拿一个 CDP 端点起一个 sessiond"**,
# 区别只在那个端点是我们起的还是你给的。
# --------------------------------------------------------------------------

def spawn_sessiond(cdp: str, *, port: int, data: str, bind: str = "127.0.0.1",
                   token: str | None = None, view: dict[str, Any] | None = None,
                   extra_env: dict[str, str] | None = None) -> subprocess.Popen:
    """起 sessiond,**不等它** —— 等在调用方那儿,因为失败时要连浏览器一起收。

    `start_new_session` 脱离调用者的进程组:CLI 是一次性的命令,不脱离的话
    `webmuxd new` 一退出就把刚起的东西带走了。
    """
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path), **(extra_env or {})}
    if token:
        env["WEBMUXD_TOKEN"] = token
    # **sessiond 自己的输出也不能扔。** 和浏览器那条(works/07)是同一个教训:
    # 扔掉之后它崩了、降质了、报警了,外面一概看不见。落到 data 目录旁边。
    os.makedirs(os.path.dirname(data) or ".", exist_ok=True)
    log_path = os.path.join(os.path.dirname(data) or ".", "sessiond.log")
    log_file = open(log_path, "ab", buffering=0)
    argv = [sys.executable, "-m", "webmuxd.serve", "--cdp", cdp,
            "--bind", bind, "--port", str(port), "--data", data]
    for k, v in (view or {}).items():
        if v is not None:
            argv += [f"--{k}", str(v)]
    return subprocess.Popen(
        argv, env=env, stdout=log_file, stderr=log_file,
        start_new_session=True)
