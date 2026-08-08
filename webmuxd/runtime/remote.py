"""`remote` runtime —— 接一个已经在别处跑着的。

**我们不起它,也不停它。** `DELETE` 只删本地记录,对面仍在运行
(api/server.md §3)。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from webmuxd.runtime.base import Handle, unavailable, wait_http


class RemoteRuntime:
    name = "remote"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def start(self, id: str, *, api_port: int = 0, vnc_port: int = 0,
              endpoint: str | None = None, **_opts: Any) -> Handle:
        if not endpoint:
            raise unavailable(self.name, "runtime=remote 得给 endpoint",
                              "endpoint 指向对面那个 session 的 API")
        if not wait_http(endpoint.rstrip("/") + "/healthz", 10):
            raise unavailable(self.name, f"{endpoint} 探不到",
                              "确认对面在跑,而且这台机器连得上")
        u = urlparse(endpoint)
        return Handle(self.name, id, u.port or 7900, vnc_port,
                      {"endpoint": endpoint.rstrip("/"), "owned": False})

    def stop(self, handle: Handle) -> None:
        """**只删本地记录,不动对面。**"""
        return None

    def alive(self, handle: Handle) -> bool:
        ep = handle.detail.get("endpoint")
        return bool(ep and wait_http(ep + "/healthz", 3))
