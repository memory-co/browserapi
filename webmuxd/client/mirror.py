"""内存里那份 tab 表 —— sdk/README §3。

**`tab.url` 是读内存,不发请求。**

lib 订着 `WS /api/events`,`tab.created` / `updated` / `activated` / `closed`
四个事件加起来就是一份完整的 tab 表。这份表本来就是为了让外挂的 tab 条
能画出来而设计的(works/04),lib 就是那个 client。

WS 跑在**后台线程的事件循环**里 —— 调用方是同步的,不该因为我们订了个流
就得关心 asyncio。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable

import websockets

log = logging.getLogger("webmuxd.mirror")


class Mirror:
    """一个 session 的 tab 表 + 新鲜度。

    `on_event` 在后台线程里被调用 —— 别在里面做重活。
    """

    def __init__(self, ws_url: str, *, token: str | None = None,
                 refetch: Callable[[], dict] | None = None,
                 on_event: Callable[[dict], None] | None = None) -> None:
        self._url = ws_url
        self._token = token
        self._refetch = refetch
        self._on_event = on_event

        self._tabs: dict[str, dict] = {}
        self._order: list[str] = []
        self._active: str | None = None
        self._lock = threading.RLock()
        self._seq = 0
        self._stale = True
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    # ------------------------------------------------------------------ 读

    @property
    def stale(self) -> bool:
        """WS 断了就是 True。**属性读会退化成直接 GET**(慢,但不骗你)。"""
        return self._stale

    def tabs(self) -> list[dict]:
        with self._lock:
            return [dict(self._tabs[i]) for i in self._order if i in self._tabs]

    def get(self, tab_id: str) -> dict | None:
        with self._lock:
            t = self._tabs.get(tab_id)
            return dict(t) if t else None

    @property
    def active(self) -> str | None:
        with self._lock:
            return self._active

    # ------------------------------------------------------------------ 写

    def load(self, listing: dict) -> None:
        """重新拉全量 —— 起来时、收到 `gap` 时、`chrome.restarted` 时。"""
        with self._lock:
            self._tabs = {t["id"]: dict(t) for t in listing.get("tabs", [])}
            self._order = [t["id"] for t in listing.get("tabs", [])]
            self._active = listing.get("active")
            self._stale = False

    def seed(self, tab: dict) -> None:
        """把一条权威的 Tab 对象种进表里(建 tab 的 201 响应)。"""
        with self._lock:
            tid = tab["id"]
            self._tabs[tid] = {**self._tabs.get(tid, {}), **tab}
            if tid not in self._order:
                self._order.append(tid)
            if tab.get("active"):
                self._active = tid

    def apply_after(self, tab_id: str, after: dict) -> None:
        """把动作响应里的 `after` 回灌进来。

        **这样 `click()` 返回的那一刻 `tab.url` 已经是新的**,不用等 WS 那条
        `tab.updated` 追上来 —— 不这么做就是个竞态(sdk/README §3)。
        """
        with self._lock:
            t = self._tabs.get(tab_id)
            if t and after.get("url"):
                t["url"] = after["url"]

    # --------------------------------------------------------------- 后台

    def start(self, timeout: float = 5.0) -> None:
        self._thread = threading.Thread(target=self._run, name="webmuxd-events",
                                        daemon=True)
        self._thread.start()
        self._ready.wait(timeout)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._pump())
        except Exception:                      # pragma: no cover - 后台线程
            log.debug("事件线程退出", exc_info=True)
        finally:
            loop.close()

    async def _pump(self) -> None:
        while not self._stop.is_set():
            try:
                url = self._url + (f"?after={self._seq}" if self._seq else "")
                headers = [("Authorization", f"Bearer {self._token}")] if self._token else []
                async with websockets.connect(url, additional_headers=headers,
                                              ping_interval=20) as ws:
                    self._full_reload()
                    self._ready.set()
                    async for raw in ws:
                        self._handle(json.loads(raw))
            except Exception as e:
                self._stale = True
                self._ready.set()              # 连不上也别把调用方卡死
                if self._stop.is_set():
                    return
                log.debug("事件流断了,重连中:%s", e)
                await asyncio.sleep(0.5)

    def _full_reload(self) -> None:
        if self._refetch:
            try:
                self.load(self._refetch())
            except Exception:
                self._stale = True

    def _handle(self, e: dict) -> None:
        self._seq = max(self._seq, int(e.get("seq", 0)))
        kind = e.get("type", "")

        # **`gap` 和 `chrome.restarted` 必须重新拉全量。**
        # 增量更新在这两种情况下一定会错(api/events)。
        if kind in ("gap", "chrome.restarted"):
            self._full_reload()
        elif kind == "tab.created":
            tab = e.get("tab") or {}
            with self._lock:
                self._tabs[tab["id"]] = dict(tab)
                if tab["id"] not in self._order:
                    self._order.append(tab["id"])
                if tab.get("active"):
                    self._active = tab["id"]
        elif kind == "tab.updated":
            with self._lock:
                t = self._tabs.get(e.get("id", ""))
                if t:
                    # **字段级合并** —— 整条替换会让 tab 条闪、丢滚动位置
                    t.update(e.get("changed") or {})
        elif kind == "tab.activated":
            with self._lock:
                self._active = e.get("id")
        elif kind == "tab.closed":
            with self._lock:
                tid = e.get("id")
                self._tabs.pop(tid, None)
                if tid in self._order:
                    self._order.remove(tid)
                self._active = e.get("active", self._active)

        self._stale = False
        if self._on_event:
            try:
                self._on_event(e)
            except Exception:
                log.debug("事件回调出错", exc_info=True)

    def wait_for_tab(self, tab_id: str, timeout: float = 3.0) -> dict | None:
        """等某个 tab 出现在表里。`open()` 之后拿句柄用。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            t = self.get(tab_id)
            if t:
                return t
            time.sleep(0.02)
        return None
