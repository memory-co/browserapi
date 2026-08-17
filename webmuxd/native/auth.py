"""HTTP Basic 认证 —— docs/v2/works/06-no-desktop.md,§5 里排在"应该"那一档。

`Fetch.authRequired` 能把 401 的挑战拦下来,回填走 `Fetch.continueWithAuth`。

**但它默认不开,这一条要说清楚。**

拦 auth 的唯一办法是 `Fetch.enable`,而一旦开了,**这个 target 的每一个请求都要
过我们的手**再 `continueRequest` 放行 —— 一个页面几十上百个请求,全部多绕一趟
Python。那是个实打实的性能税,而 Basic 认证在今天已经很少见。

所以:**遇到再开**。不开的时候,401 会照常渲染成服务器返回的那个页面 ——
是**看得见的失败**,不是页面静止在那儿。这和"必须做"那三类的性质不同,
它们不拦就是彻底卡死。

    POST /api/auth {origin, user, password}   ← 设一次凭证,顺带打开拦截
    DELETE /api/auth                          ← 关掉,把税退回去
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:                                    # pragma: no cover
    from webmuxd.serve.session import Session


class BasicAuth:
    kind = "auth"

    def __init__(self, session: "Session") -> None:
        self.session = session
        #: origin → (user, password)。`""` 那把是"所有站点都用它"。
        self.creds: dict[str, tuple[str, str]] = {}
        self.on = False

    def attach(self) -> None:
        self.session.cdp.on("Fetch.authRequired", self._auth)
        self.session.cdp.on("Fetch.requestPaused", self._paused)

    # ------------------------------------------------------------------ 开关

    async def set(self, *, origin: str = "", user: str, password: str) -> dict[str, Any]:
        self.creds[origin] = (user, password)
        await self._enable()
        # **凭证不进日志** —— 和动作层那条一样,记账时看到的是掩码
        self.session.log.append("auth", event="credentials_set",
                                origin=origin or "*", user=user, password="***")
        return {"ok": True, "origin": origin or "*", "on": self.on}

    async def clear(self) -> dict[str, Any]:
        self.creds.clear()
        await self._disable()
        self.session.log.append("auth", event="credentials_cleared")
        return {"ok": True, "on": self.on}

    async def _enable(self) -> None:
        if self.on:
            return
        for tab_id in list(self.session._sessions):
            sid = self.session._sessions[tab_id]
            with contextlib.suppress(Exception):
                await self.session.cdp.send(
                    "Fetch.enable",
                    {"handleAuthRequests": True,
                     "patterns": [{"urlPattern": "*"}]},
                    session_id=sid)
        self.on = True

    async def _disable(self) -> None:
        if not self.on:
            return
        for sid in list(self.session._sessions.values()):
            with contextlib.suppress(Exception):
                await self.session.cdp.send("Fetch.disable", {}, session_id=sid)
        self.on = False

    async def enable_for(self, session_id: str) -> None:
        """新 tab 进来时接上 —— 只在已经开着的时候。"""
        if not self.on:
            return
        with contextlib.suppress(Exception):
            await self.session.cdp.send(
                "Fetch.enable",
                {"handleAuthRequests": True, "patterns": [{"urlPattern": "*"}]},
                session_id=session_id)

    # ------------------------------------------------------------------ 事件

    def _paused(self, params: dict, sid: str | None) -> None:
        """**立刻放行。** 我们要的只是 authRequired,别的请求一个都不改。"""
        import asyncio
        rid = params.get("requestId")
        if not rid:
            return
        asyncio.create_task(self._continue(rid, sid))

    async def _continue(self, rid: str, sid: str | None) -> None:
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Fetch.continueRequest",
                                        {"requestId": rid}, session_id=sid)

    def _auth(self, params: dict, sid: str | None) -> None:
        import asyncio
        asyncio.create_task(self._answer(params, sid))

    async def _answer(self, params: dict, sid: str | None) -> None:
        url = (params.get("request") or {}).get("url", "")
        origin = ""
        with contextlib.suppress(Exception):
            u = urlparse(url)
            origin = f"{u.scheme}://{u.netloc}"
        cred = self.creds.get(origin) or self.creds.get("")
        tab_id = self.session._tab_of_session(sid)

        if cred is None:
            # **不猜、不重试。** 没凭证就取消,并且**说出来** ——
            # 页面白屏时日志里得有这一行
            self.session.log.append("auth", event="no_credentials",
                                    tab=tab_id, origin=origin)
            self.session._emit("auth.required", {"tab": tab_id, "origin": origin,
                                                 "answered": False})
            body = {"response": "CancelAuth"}
        else:
            self.session.log.append("auth", event="answered", tab=tab_id,
                                    origin=origin, user=cred[0], password="***")
            self.session._emit("auth.required", {"tab": tab_id, "origin": origin,
                                                 "answered": True})
            body = {"response": "ProvideCredentials",
                    "username": cred[0], "password": cred[1]}
        with contextlib.suppress(Exception):
            await self.session.cdp.send(
                "Fetch.continueWithAuth",
                {"requestId": params.get("requestId"), "authChallengeResponse": body},
                session_id=sid)
