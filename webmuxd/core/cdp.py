"""CDP 连接 —— 引擎和 Chromium 之间那一层。

docs/v1/works/06-tab-sync.md 讲的"CDP → sessiond"这一半就落在这儿。

**为什么不用 Playwright**:works/01 §4 早先写的是用 `connect_over_cdp()`。
但我们需要的东西 Playwright 恰好不给或要绕:
`Target.setDiscoverTargets` 的原始事件、`targetInfo.openerId`、
自己决定 attach 时机。而 Playwright 会替我们建它自己的 tab 模型 ——
和我们的 tab 表打架([works/06 §1](../../docs/v1/works/06-tab-sync.md))。
它擅长的自动等待这类事,我们本来就要自己定义。所以直接说 CDP。

一条 websocket 走完:`flatten` 模式下所有 target 的消息复用同一条连接,
靠 `sessionId` 区分 —— 不用每个 tab 再开一条。
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
from collections.abc import Callable
from typing import Any

import websockets

from webmuxd.errors import ChromeGone

log = logging.getLogger("webmuxd.cdp")

#: 一条 CDP 调用最多等多久。卡住通常意味着渲染进程没了,不是"再等等"。
DEFAULT_TIMEOUT = 30.0


class CDPError(Exception):
    """Chromium 那边回了 `error`。带上原始 code,排查时有用。"""

    def __init__(self, method: str, code: int, message: str, data: str = "") -> None:
        super().__init__(f"{method}: {message}" + (f" ({data})" if data else ""))
        self.method, self.code, self.message, self.data = method, code, message, data


class CDP:
    """一条到 browser 的连接。

        cdp = await CDP.connect("http://127.0.0.1:9222")
        await cdp.send("Target.setDiscoverTargets", {"discover": True})
        cdp.on("Target.targetCreated", handler)

    `send()` 带 `session_id` 就是发给某个 target;不带就是发给 browser。
    """

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: dict[str, list[Callable[[dict, str | None], Any]]] = {}
        self._any: list[Callable[[str, dict, str | None], Any]] = []
        self._pump: asyncio.Task | None = None
        self._closed = asyncio.Event()

    # ---------------------------------------------------------------- 连接

    @classmethod
    async def connect(cls, endpoint: str, *, timeout: float = 10.0) -> "CDP":
        """`endpoint` 是 `http://host:port`(会去问 webSocketDebuggerUrl)
        或者直接一个 `ws://`。"""
        url = endpoint if endpoint.startswith("ws") else await cls._browser_ws(endpoint, timeout)
        ws = await websockets.connect(url, max_size=None, ping_interval=None)
        self = cls(ws)
        self._pump = asyncio.create_task(self._read_loop(), name="cdp-read")
        return self

    @staticmethod
    async def _browser_ws(endpoint: str, timeout: float) -> str:
        """问 `/json/version` 要 ws 地址,**然后把里面的 host:port 换成我们问的那个**。

        Chromium 报的是它自己看到的地址(`127.0.0.1:9222`)。中间但凡隔了
        一层端口映射或转发,那个地址在我们这边就是错的 —— 我们问得到它,
        就该从同一个地方连回去。
        """
        import urllib.parse

        import aiohttp

        base = endpoint.rstrip("/")
        url = base + "/json/version"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                    ws = (await r.json())["webSocketDebuggerUrl"]
        except Exception as e:  # 连不上 = 浏览器没了,这是平台级的事
            raise ChromeGone(f"问不到 CDP 端点({url}): {e}", code="chrome_gone") from e
        return urllib.parse.urlparse(ws)._replace(
            netloc=urllib.parse.urlparse(base).netloc).geturl()

    async def close(self) -> None:
        if self._pump:
            self._pump.cancel()
        await self._ws.close()
        self._closed.set()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    async def __aenter__(self) -> "CDP":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    # ---------------------------------------------------------------- 收

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    self._dispatch(json.loads(raw))
                except Exception:  # 一条消息处理炸了不该拖垮整条连接
                    log.exception("处理 CDP 消息时出错")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("CDP 连接断了: %s", e)
        finally:
            self._closed.set()
            # 还在等的调用别永远挂着 —— 连接没了就是 Chromium 没了
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ChromeGone("CDP 连接断开", code="chrome_gone"))
            self._pending.clear()

    def _dispatch(self, msg: dict) -> None:
        mid = msg.get("id")
        if mid is not None:
            fut = self._pending.pop(mid, None)
            if fut and not fut.done():
                if "error" in msg:
                    e = msg["error"]
                    fut.set_exception(CDPError(
                        self._method_of.pop(mid, "?"),
                        e.get("code", -1), e.get("message", ""), e.get("data", "")))
                else:
                    fut.set_result(msg.get("result", {}))
            return

        method = msg.get("method")
        if not method:
            return
        params = msg.get("params", {})
        sid = msg.get("sessionId")
        for h in self._handlers.get(method, ()):
            self._safe(h, params, sid)
        for h in self._any:
            self._safe(h, method, params, sid)

    @staticmethod
    def _safe(fn: Callable, *args: Any) -> None:
        try:
            r = fn(*args)
            if asyncio.iscoroutine(r):
                asyncio.create_task(r)
        except Exception:
            log.exception("事件处理器出错")

    # ---------------------------------------------------------------- 发

    _method_of: dict[int, str] = {}

    async def send(
        self,
        method: str,
        params: dict | None = None,
        *,
        session_id: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> dict:
        if self.closed:
            raise ChromeGone("CDP 已断开", code="chrome_gone")
        mid = next(self._ids)
        payload: dict[str, Any] = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id

        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        self._method_of[mid] = method
        await self._ws.send(json.dumps(payload))
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(mid, None)
            raise CDPError(method, -1, f"{timeout}s 内没有回应") from None
        finally:
            self._method_of.pop(mid, None)

    # ---------------------------------------------------------------- 订阅

    def on(self, method: str, handler: Callable[[dict, str | None], Any]) -> Callable[[], None]:
        """订一个事件。返回退订函数。handler 收 `(params, session_id)`。"""
        self._handlers.setdefault(method, []).append(handler)

        def off() -> None:
            try:
                self._handlers[method].remove(handler)
            except (KeyError, ValueError):
                pass

        return off

    def on_any(self, handler: Callable[[str, dict, str | None], Any]) -> Callable[[], None]:
        """订所有事件,`(method, params, session_id)`。给探测和排查用。"""
        self._any.append(handler)

        def off() -> None:
            try:
                self._any.remove(handler)
            except ValueError:
                pass

        return off

    async def wait_for(self, method: str, *, timeout: float = 5.0,
                       predicate: Callable[[dict], bool] | None = None) -> dict:
        """等一条事件。测试和"等导航完成"这类地方用。"""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()

        def handler(params: dict, _sid: str | None) -> None:
            if not fut.done() and (predicate is None or predicate(params)):
                fut.set_result(params)

        off = self.on(method, handler)
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            off()
