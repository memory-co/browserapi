"""`remote` —— 别人已经把 CDP 端点给你了(docs/v2/works/07-runtime.md §6)。

**我们不起那个浏览器,也不停它。** 起的只有本地这个 sessiond ——
而画面由我们产,所以:

    给一个只有 CDP 的云浏览器配上人能看能上手的画面

这是 v1 做不到的:v1 的 `remote` 要求对面**同时**给出画面口和 CDP,
而云浏览器服务基本只给 CDP。

它同时是"v2 没有开箱隔离"的出口。对 webmuxd 来说这些**是同一件事**,
因为它只看见一个 CDP 端点:云浏览器服务、同事机器上那个 Chrome、
**你自己 `docker run` 起来的一个 chromium** —— 隔离在最后那条上,由你决定。
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from webmuxd.view import modes
from webmuxd.runtime.base import (
    Handle, require_ports, spawn_sessiond, unavailable, wait_http,
)


class RemoteRuntime:
    name = "remote"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def start(self, id: str, *, port: int, cdp: str | None = None,
              data_dir: str | None = None, token: str | None = None,
              bind: str = "127.0.0.1", view: dict[str, Any] | None = None,
              transport: str | None = None, **_opts: Any) -> Handle:
        # **remote 上能用 JPG 和 DOM,不能用 VNC。**
        # VNC 要截的是那个浏览器所在机器上的 X 显示,而 remote 的浏览器根本
        # 不在这台机器上 —— 我们手里只有一个 CDP 端点。
        # **少一个选项不是降级,是这条路上的全集**
        # ([c §9.3](../../docs/v2/works/c-view.md#93-能切到哪几条起-session-的时候就定了))。
        allowed = modes.available_in(headed=False, remote=True)
        transport = modes.canon(transport) or modes.JPG
        # **不静默忽略。** 悄悄给一个 JPG 的画面,等于让人以为自己在看 VNC 的画质。
        if transport not in allowed:
            raise unavailable(
                self.name,
                f"runtime=remote 上没有 {modes.label(transport)} 这种画面",
                f"这条路上只有 {' / '.join(modes.label(m) for m in allowed)} —— "
                "VNC 要截浏览器所在机器上的 X 显示,而 remote 的浏览器不在这儿,"
                "我们手里只有一个 CDP 端点。"
                "要 VNC 就在那台机器上直接跑 webmuxd")
        if not cdp:
            raise unavailable(self.name, "runtime=remote 得给 cdp=",
                              "cdp 指向对面那个浏览器的 CDP 端点,"
                              "http://host:port 或 ws://…")
        require_ports(port)
        # `http://` 的先探一下,**探不到就直说** —— 起完 sessiond 再发现
        # 连不上,报的错会指向我们自己而不是那个端点。
        # `ws://` 没有可探的 HTTP 面,交给 sessiond 去连。
        if cdp.startswith("http") and not wait_http(cdp.rstrip("/") + "/json/version", 10):
            raise unavailable(self.name, f"{cdp} 探不到",
                              "确认对面在跑,而且这台机器连得上")

        work = data_dir or tempfile.mkdtemp(prefix=f"webmuxd-{id}-")
        os.makedirs(work, exist_ok=True)
        proc = spawn_sessiond(cdp, port=port, bind=bind, view=view,
                              data=os.path.join(work, "data"), token=token)
        if not wait_http(f"http://127.0.0.1:{port}/healthz", 30):
            proc.terminate()
            raise unavailable(self.name, "sessiond 没起来",
                              f"手工跑一遍看报什么:python -m webmuxd.serve --cdp {cdp}")
        return Handle(self.name, id, port,
                      {"cdp": cdp, "work": work, "owned_browser": False,
                       "pids": {"sessiond": proc.pid}, "_procs": {"sessiond": proc}})

    def stop(self, handle: Handle) -> None:
        """停本地的 sessiond,**对面一个字节都不动**。"""
        import contextlib
        import signal
        procs = handle.detail.get("_procs") or {}
        p = procs.get("sessiond")
        if p is not None:
            with contextlib.suppress(Exception):
                p.terminate()
                p.wait(timeout=5)
            return
        pid = (handle.detail.get("pids") or {}).get("sessiond")
        if pid:
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)

    def alive(self, handle: Handle) -> bool:
        return wait_http(f"http://127.0.0.1:{handle.port}/healthz", 3)
