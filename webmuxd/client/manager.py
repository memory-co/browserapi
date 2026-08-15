"""`Webmuxd` —— 管理实例(docs/v1/sdk/manager.md)。

**`Webmuxd()` 是个空壳。** 构造它不起容器、不占端口、不跑任何浏览器 ——
它只是"我要开始管 session 了"。**每 `session()` 一个新 id 才起一个 kasm。**
"""

from __future__ import annotations

import os
import threading
from typing import Any

from webmuxd import runtime as rt
from webmuxd.client.session import Session
from webmuxd.client.transport import Transport
from webmuxd.errors import BadRequest


class Webmuxd:
    def __init__(self, url: str | None = None, *, port: int | None = None,
                 token: str | None = None, socket: str | None = None,
                 name: str = "default", user: str = "api",
                 host: str = "127.0.0.1") -> None:
        self.user = user
        self.host = host
        self.token = token or os.environ.get("WEBMUXD_TOKEN") or None
        #: 管理面自己的口 —— **和 session 的两个口无关**。
        #: 不给就不占网络端口,管理走 socket、靠文件权限鉴权。
        self.port = port
        self.socket = socket
        self.name = name
        self._base = (url or (f"http://{host}:{port}" if port else None))
        self._t = Transport(self._base, token=self.token) if self._base else None
        self._live: dict[str, Session] = {}
        self._handles: dict[str, Any] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        where = self._base or f"socket:{self.name}"
        return f"<Webmuxd {where} 管着 {len(self._live)} 个 session>"

    # ------------------------------------------------------------------

    def session(self, id: str, *, api_port: int | None = None,
                view_port: int | None = None, runtime: str = "container",
                user: str | None = None, **kw: Any) -> Session:
        """拿一个 session。**幂等:同一个 id 永远给你同一个。**

        没有 `create()` 也没有 `get()` —— "建"和"取"是同一件事,像 `tmux new -A -s`。

        **端口必须你给,不自动分配**:端口是部署决定的,我们猜一个只会让你的
        配置和实际对不上,而且一个 session 占两个口,自动分配还得替你猜第二个。
        """
        # **旧名不静默吞。** 0.4.0 把三层的名字对齐了(CLI --x / lib x= /
        # 镜像 WEBMUXD_X),旧名落进 `**kw` 会被无声丢掉,然后报一个指向别处的错
        # ——"还不存在,得给 api_port"。宁可在这儿直说。
        for old, new in (("port", "api_port"), ("vnc_port", "view_port"),
                         ("viewport", "window_size"), ("token", "password")):
            if old in kw:
                raise BadRequest(f"`{old}=` 改名叫 `{new}=` 了(0.4.0)",
                                 code="bad_request")

        with self._lock:
            have = self._live.get(id)
            if have is not None:
                # 同一个 id **返回同一个 Python 对象** —— 每个 Session 背后有一条 WS
                # 和一份内存表,给两个就是两条连接、两份可能不一致的表。
                if api_port is not None and have.api_url.endswith(f":{api_port}") is False:
                    raise BadRequest(
                        f"{id} 已经在 {have.api_url},和你给的 api_port={api_port} 对不上",
                        code="bad_request")
                return have

            if api_port is None:
                raise BadRequest(
                    f"session {id!r} 还不存在,得给 api_port 和 view_port —— "
                    "端口是部署决定的,我们不替你分配", code="bad_request")

            api = f"http://{self.host}:{api_port}"
            t = Transport(api, token=self.token)
            owned = False
            if not t.alive():
                # 那个口上什么都没有 → **按 runtime 把它拉起来**。
                # 起不来就抛 RuntimeUnavailable 带 hint,**不静默换一种**
                # (works/05 §4)。
                impl = rt.get(runtime)
                handle = impl.start(id, api_port=api_port, view_port=view_port or 0,
                                    token=self.token, **kw)
                self._handles[id] = (impl, handle)
                api = handle.detail.get("endpoint") or api
                t = Transport(api, token=self.token)
                owned = True                # 这次真的建起来了 → with 退出时归我们关

            # scheme 是 runtime 说了算的 —— KasmVNC 走自签名 https,
            # 报成 http 的话人点过去是连不上的
            handle = (self._handles.get(id) or (None, None))[1]
            vnc = ""
            if view_port:
                scheme = (handle.detail.get("view_scheme") if handle else None) or "http"
                vnc = f"{scheme}://{self.host}:{view_port}"
            sess = Session(id, api, view_url=vnc,
                           token=self.token, user=user or self.user,
                           owned=owned, manager=self,
                           view_login=(handle.detail if handle else None))
            self._live[id] = sess
            return sess

    def sessions(self) -> list[Session]:
        """这个管理实例手里的 session。

        要列**这台机器上所有**的,得问管理面那个口 —— 那属于 runtime 那一层。
        """
        if self._t is not None:
            try:
                listing = self._t.get("/api/sessions")
                return [self.session(s["id"], port=s.get("api_port"),
                                     view_port=s.get("view_port"))
                        for s in listing.get("sessions", [])]
            except Exception:
                pass
        return list(self._live.values())

    def kill(self, id: str) -> None:
        sess = self._live.get(id)
        if sess is not None:
            sess.detach()
        pair = self._handles.pop(id, None)
        if pair is not None:
            impl, handle = pair
            impl.stop(handle)              # remote 的 stop 是空的:不动对面
        self._forget(id)

    def _forget(self, id: str) -> None:
        self._live.pop(id, None)

    def info(self) -> dict:
        if self._t is None:
            return {"version": __import__("webmuxd").__version__, "listen": None,
                    "sessions": {"total": len(self._live)},
                    "runtimes": rt.detect(), "default_runtime": rt.DEFAULT}
        return self._t.get("/api/server")

    def shutdown(self) -> None:
        """**`process` 的跟着死,`container` 和 `remote` 活着**(works/05 §3.2)。"""
        for s in list(self._live.values()):
            s.detach()
        for id_, (impl, handle) in list(self._handles.items()):
            if impl.name == "process":
                impl.stop(handle)
            self._handles.pop(id_, None)
        self._live.clear()
