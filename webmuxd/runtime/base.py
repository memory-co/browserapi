"""runtime —— **三层概念里的第三层,也是 tmux 没有的那一个**
(docs/v1/works/05-server-session-runtime.md §4)。

它只回答一个问题:**这个 session 怎么被拉起来。**

选一次,之后所有代码都一样 —— 拿到 session 之后,`container` / `process` /
`remote` 对调用方完全没有区别。这是这层抽象的全部意义。

**不可用时抛,不降级。** docker 不通就报错,不静默换成 `process` ——
那等于把页面偷偷挪到你自己机器上跑,没有隔离。
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from webmuxd.errors import PortInUse, RuntimeUnavailable


@dataclass
class Handle:
    """一个起来了的 session 的把柄。

    `kind` 决定 `kill-server` 之后它死不死:`process` 是 server 的子进程,
    跟着死;`container` 和 `remote` 活着(works/05 §3.2)。
    """

    kind: str
    id: str
    api_port: int
    view_port: int
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.api_port}"

    @property
    def view_url(self) -> str:
        """没有画面时是空的 —— 装作有画面比没画面更糟。

        KasmVNC 走的是自签名 https,所以 scheme 由 runtime 说了算。
        """
        if not self.view_port:
            return ""
        return f"{self.detail.get('view_scheme', 'http')}://127.0.0.1:{self.view_port}"


class Runtime(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        """能不能用,以及不能用时那句**有用的**提示。"""

    def start(self, id: str, *, api_port: int, view_port: int,
              **opts: Any) -> Handle: ...

    def stop(self, handle: Handle) -> None: ...

    def alive(self, handle: Handle) -> bool: ...


# ---------------------------------------------------------------------------

def port_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def require_ports(*ports: int) -> None:
    """**端口是部署决定的,我们不替你换一个。** 被占了就说被占了。"""
    for p in ports:
        if not port_free(p):
            raise PortInUse(f"端口 {p} 被占了", code="port_in_use",
                            details={"port": p})


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
