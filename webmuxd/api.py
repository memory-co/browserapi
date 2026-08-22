"""**SDK 这一面** —— 代码里 `import webmuxd` 之后拿到的那三个对象。

    web  = Webmuxd()                                   # 管理实例,空壳
    sess = web.session(id="work", port=7900)
    tab  = sess.open("https://example.com")
    tab.click("登录")

三层套一层,和 CLI 是同一套 HTTP —— **这一面不 import `serve.py`**:
SDK 要能连**别的机器上**的服务端,一旦接进程内的实现,那条路就断了
([j §5](../docs/v2/works/j-layout.md#5-依赖方向扁平之后层要靠规矩守))。

数据形状不在这儿定义,在 `models.py`;这一层只多两件事:
**通过 HTTP 干活**,以及**截图用到才去取**。

> `Tab` 和 `TabInfo` 的区别就是这一层的意义:后者是一条记录,
> 前者带着 `.click()`。对应 requests 里 `Session` 和 `Response`。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

import websockets

from webmuxd import models
from webmuxd.exceptions import (BadRequest, ChromeGone, TabGone,
                                WebmuxdError, from_response)

#: 定位的六种写法(api/act.md §4)。
#: **形状在 [`models.Locator`](models.py)** —— 这儿只转发那张键表,
#: 不再写第二份。写两份的下场:加一种写法要记得改三个地方。
_LOCATOR_KEYS = models.Locator.KEYS


def _locator(target: Any = None, **kw: Any) -> dict[str, Any]:
    """把 `tab.click("提交订单")` / `tab.click(role=..., name=...)` /
    `tab.click(候选里的那一项)` 统一成一个定位字典。"""
    spec: dict[str, Any] = {}
    if target is not None:
        if isinstance(target, models.Element):
            # `tab.click(snap[0])` —— 从 snapshot 里挑一个直接点。
            # 没有号的(`act` 内部那份快照里的)退回 role + name。
            if target.ref:
                spec["ref"] = target.ref
            else:
                spec.update({k: v for k, v in
                             (("role", target.role), ("name", target.name)) if v})
        elif isinstance(target, str):
            # **`@` 打头是号**,别的都是可见文字。这一条要在这儿判,
            # 不能等到服务端 —— 一个叫「@提醒」的按钮不该被当成号
            # (那种时候写 `text="@提醒"`)。
            spec["ref" if target.startswith("@") else "text"] = target
        elif isinstance(target, dict):
            # 定位失败回的候选:有号就拿号,没有就**拿 role + name 重试** ——
            # 那是跨快照仍然成立的说法
            if target.get("ref"):
                spec["ref"] = target["ref"]
            else:
                spec.update({k: v for k, v in target.items()
                             if k in ("role", "name")})
        else:
            raise BadRequest(f"看不懂的定位:{target!r}", code="bad_request")
    for k, v in kw.items():
        if k == "at":
            spec["point"] = list(v)
        elif k in _LOCATOR_KEYS:
            spec[k] = v
    if not spec:
        raise BadRequest("没给定位", code="bad_request")
    return spec


class Tab:
    """一个页面的句柄。从 `sess.open()` 或 `sess.tab()` 拿。"""

    def __init__(self, session: Any, tab_id: str) -> None:
        self._s = session
        self.id = tab_id

    def __repr__(self) -> str:
        try:
            return f"<Tab {self.id} {self.title!r} {self.url}>"
        except TabGone:
            return f"<Tab {self.id} 已经没了>"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Tab) and other.id == self.id and other._s is self._s

    def __hash__(self) -> int:
        return hash((id(self._s), self.id))

    # ------------------------------------------------------- 属性:读内存

    def _row(self) -> dict:
        row = self._s._mirror.get(self.id)
        if row is None:
            if self._s._mirror.stale:            # WS 断了 → 退化成直接问
                listing = self._s._t.get("/api/tabs")
                self._s._mirror.load(listing)
                row = self._s._mirror.get(self.id)
            if row is None:
                last = self._s._last_seen.get(self.id)
                if last is not None:
                    return last                  # 关掉之后属性还能读(最后的值)
                raise TabGone(f"{self.id} 不在了", code="tab_gone",
                              details={"reason": "closed"})
        self._s._last_seen[self.id] = row
        return row

    @property
    def url(self) -> str:
        return self._row().get("url", "")

    @property
    def title(self) -> str:
        return self._row().get("title", "")

    @property
    def loading(self) -> bool:
        return bool(self._row().get("loading"))

    @property
    def active(self) -> bool:
        return self._s._mirror.active == self.id

    @property
    def index(self) -> int:
        return self._row().get("index", -1)

    @property
    def security(self) -> str:
        return self._row().get("security", "neutral")

    @property
    def can_go_back(self) -> bool:
        return bool(self._row().get("can_go_back"))

    @property
    def can_go_forward(self) -> bool:
        return bool(self._row().get("can_go_forward"))

    @property
    def opener(self) -> str | None:
        return self._row().get("opener")

    @property
    def reason(self) -> str | None:
        return self._row().get("reason")

    @property
    def crashed(self) -> bool:
        return bool(self._row().get("crashed"))

    @property
    def dialog(self) -> dict | None:
        """有弹窗挡着时不是 None —— 它会挡住这个 tab 直到有人回应。"""
        return self._row().get("dialog")

    @property
    def closed(self) -> bool:
        return self._s._mirror.get(self.id) is None

    @property
    def favicon_url(self) -> str:
        return f"{self._s.api_url}/api/tabs/{self.id}/favicon"

    @property
    def favicon(self) -> bytes | None:
        """**唯一一个惰性发请求的属性** —— 事件流里只带 URL 不带字节。"""
        try:
            return self._s._t.get_bytes(f"/api/tabs/{self.id}/favicon")
        except Exception:
            return None

    # ------------------------------------------------------------- 导航

    def goto(self, url: str | None = None, *, wait: str = "load",
             timeout: float = 15, history_index: int | None = None) -> "Tab":
        body: dict[str, Any] = {"wait": wait, "timeout_ms": int(timeout * 1000)}
        if history_index is not None:
            body["history_index"] = history_index
        else:
            body["url"] = url
        self._s._t.post(f"/api/tabs/{self.id}/goto", body)
        return self

    def back(self) -> "Tab":
        self._s._t.post(f"/api/tabs/{self.id}/back")
        return self

    def forward(self) -> "Tab":
        self._s._t.post(f"/api/tabs/{self.id}/forward")
        return self

    def reload(self, *, ignore_cache: bool = False) -> "Tab":
        self._s._t.post(f"/api/tabs/{self.id}/reload", {"ignore_cache": ignore_cache})
        return self

    def stop(self) -> "Tab":
        self._s._t.post(f"/api/tabs/{self.id}/stop")
        return self

    def activate(self) -> "Tab":
        self._s._t.post(f"/api/tabs/{self.id}/activate")
        return self

    def close(self) -> dict:
        return self._s._t.delete(f"/api/tabs/{self.id}")

    def history(self) -> dict:
        return self._s._t.get(f"/api/tabs/{self.id}/history")

    def answer(self, accept: bool, text: str = "") -> None:
        """回应 alert / confirm / prompt。

        **不自动回应** —— 该点确定还是取消是你的判断,不是我们的。
        """
        self._s._t.post(f"/api/tabs/{self.id}/dialog",
                        {"accept": accept, "text": text})

    # ------------------------------------------------------------- 动作

    def act(self, actions: list[dict], *, settle: dict | None = None,
            note: str | None = None, user: str | None = None,
            idempotency_key: str | None = None) -> "ActResult":
        """一串动作一次往返,串行执行、遇错即停。

        **`act()` 不抛异常** —— 写 agent 循环时要把候选喂回模型自我纠正,
        而不是被异常打断(sdk/tab/input.md §3)。快捷方法则会抛。
        """
        body: dict[str, Any] = {"tab": self.id, "actions": actions}
        if settle:
            body["settle"] = settle
        if note:
            body["note"] = note
        body["user"] = user or self._s.user
        out = self._s._t.post("/api/act", body)
        r = ActResult(self._s, out)
        for res in out.get("results", []):
            if res.get("after"):
                self._s._mirror.apply_after(self.id, res["after"])
        return r

    def _one(self, spec: dict, **kw: Any) -> "ActResult":
        r = self.act([spec], **kw)
        r.raise_()                     # 快捷方法错了就该炸
        return r

    def click(self, target: Any = None, **kw: Any) -> "ActResult":
        loc = _locator(target, **kw)
        return self._one({"type": "click", **loc,
                          **{k: kw[k] for k in ("button", "count", "modifiers")
                             if k in kw}}, note=kw.get("note"), user=kw.get("user"))

    def hover(self, target: Any = None, **kw: Any) -> "ActResult":
        return self._one({"type": "hover", **_locator(target, **kw)})

    def type(self, target: Any = None, text: str = "", *, clear: bool = False,
             delay: float = 0, secret: str | None = None, **kw: Any) -> "ActResult":
        spec: dict[str, Any] = {"type": "type", **_locator(target, **kw)}
        # `type` 的 text 是**内容**不是定位 —— 这条规格里踩过(api/act.md §4.1)
        spec.pop("text", None)
        if target is not None and isinstance(target, str) and "label" not in spec:
            spec = {"type": "type", "label": target}
        if secret:
            spec["text_ref"] = secret if secret.startswith("secret://") \
                else f"secret://{secret}"
        else:
            spec["text"] = text
        if clear:
            spec["clear"] = True
        if delay:
            spec["delay"] = delay
        return self._one(spec)

    def clear(self, target: Any = None, **kw: Any) -> "ActResult":
        return self._one({"type": "clear", **_locator(target, **kw)})

    def key(self, key: str, *, modifiers: list[str] | None = None) -> "ActResult":
        return self._one({"type": "key", "key": key, "modifiers": modifiers or []})

    def select(self, target: Any = None, *, value: Any = None,
               label: str | None = None, **kw: Any) -> "ActResult":
        spec: dict[str, Any] = {"type": "select", **_locator(target, **kw)}
        spec["value" if value is not None else "label"] = value or label
        return self._one(spec)

    def check(self, target: Any = None, *, checked: bool = True,
              **kw: Any) -> "ActResult":
        return self._one({"type": "check", "checked": checked,
                          **_locator(target, **kw)})

    def scroll(self, *, dy: float = 0, dx: float = 0, to: Any = None) -> "ActResult":
        spec: dict[str, Any] = {"type": "scroll"}
        if to is not None:
            spec["to"] = _locator(to)
        else:
            spec["dy"], spec["dx"] = dy, dx
        return self._one(spec)

    def wait_for(self, *, text: str | None = None, css: str | None = None,
                 url_contains: str | None = None, ms: float | None = None,
                 timeout: float = 5) -> "ActResult":
        spec: dict[str, Any] = {"type": "wait_for", "timeout_ms": int(timeout * 1000)}
        for k, v in (("text", text), ("css", css),
                     ("url_contains", url_contains), ("ms", ms)):
            if v is not None:
                spec[k] = v
        return self._one(spec)

    def extract(self, target: Any = None, *, mode: str = "text",
                attr: str | None = None, **kw: Any) -> Any:
        spec: dict[str, Any] = {"type": "extract", "mode": mode,
                                **_locator(target, **kw)}
        if attr:
            spec["attr"] = attr
        return self._one(spec).results[0].get("value")

    def js(self, expression: str) -> Any:
        """逃生舱。能用,但日志里标黄 —— 回看时看不出干了什么。"""
        return self._one({"type": "js", "expression": expression}).results[0].get("value")

    def upload(self, target: Any, path_or_id: str, **kw: Any) -> "ActResult":
        """也接受本地路径 —— **内部先传一次再用**,省掉调用方自己 upload_file。"""
        import os
        file_id = path_or_id
        if os.path.exists(path_or_id):
            file_id = self._s.upload_file(path_or_id)
        return self._one({"type": "upload", "file_id": file_id,
                          **_locator(target, **kw)})

    # ------------------------------------------------------------- 观测

    def text(self) -> str:
        return self._s._t.get_bytes("/api/text", tab=self.id).decode()

    def snapshot(self, *, interactive: bool = False, selector: str | None = None,
                 viewport: bool = False,
                 max_elements: int = 150) -> models.Snapshot:
        """这一页上有什么。**每一样带一个 `@e1`,可以直接拿去点。**

            snap = tab.snapshot(interactive=True)
            print(snap.as_prompt())
            tab.click(snap[1])          # 或者 tab.click("@e1")

        号**跨命令活着,而且只增不重用** ——
        拿过期的号去点会报错,不会点到另一个东西
        ([RefTable](models.py))。
        """
        params: dict[str, Any] = {"tab": self.id, "interactive": interactive,
                                  "viewport": viewport, "max": max_elements}
        if selector:
            params["selector"] = selector
        return models.Snapshot.from_json(self._s._t.get("/api/snapshot", **params))

    def screenshot(self, path: str | None = None, *,
                   full_page: bool = False) -> bytes:
        data = self._s._t.get_bytes("/api/screenshot", tab=self.id,
                                    full_page=full_page)
        if path:
            with open(path, "wb") as fh:
                fh.write(data)
        return data

    # -------------------------------------------------------------- 日志

    def log(self, **kw: Any) -> list[dict]:
        """这个 tab 干过什么。**按 tab 过滤,不是读单独的文件**。"""
        return self._s.log(tab=self.id, **kw)

    def bundle(self, path: str | None = None) -> bytes:
        return self._s.bundle(path, tab=self.id)


class ActResult:
    """一批动作的结果。`act()` 返回它;快捷方法内部 `raise_()` 之后返回它。"""

    def __init__(self, session: Any, payload: dict) -> None:
        self._s = session
        self.results: list[dict] = payload.get("results", [])
        self.log_from: int | None = payload.get("log_from")

    @property
    def ok(self) -> bool:
        return all(r.get("ok") for r in self.results)

    @property
    def failed(self) -> dict | None:
        return next((r for r in self.results if not r.get("ok")), None)

    @property
    def candidates(self) -> list[dict]:
        """失败那条的候选 —— **方便直接喂回模型**。"""
        f = self.failed
        return (f or {}).get("candidates", [])

    @property
    def new_tabs(self) -> list[Tab]:
        """这批动作开出来的新 tab,**是句柄不是 id**。"""
        out = []
        for r in self.results:
            for t in (r.get("after") or {}).get("new_tabs") or []:
                out.append(Tab(self._s, t["id"]))
        return out

    def raise_(self) -> "ActResult":
        f = self.failed
        if f:
            from webmuxd.exceptions import error_class
            cls = error_class(f.get("error"))
            raise cls(f.get("message", ""), code=f.get("error"),
                      details={"candidates": f.get("candidates", [])})
        return self

    def __repr__(self) -> str:
        return f"<ActResult ok={self.ok} {len(self.results)} 个动作>"


# --------------------------------------------------------------------------
# HTTP 调用(原 client/transport.py)
# --------------------------------------------------------------------------

class Transport:
    """一个 session(或管理面)的 base URL + token。"""

    def __init__(self, base: str, *, token: str | None = None,
                 timeout: float = 30.0) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ------------------------------------------------------------------

    def get(self, path: str, **params: Any) -> Any:
        return self._call("GET", path, params=params)

    def get_bytes(self, path: str, **params: Any) -> bytes:
        return self._call("GET", path, params=params, raw=True)

    def post(self, path: str, body: dict | None = None, **params: Any) -> Any:
        return self._call("POST", path, body=body, params=params)

    def delete(self, path: str, **params: Any) -> Any:
        return self._call("DELETE", path, params=params)

    # ------------------------------------------------------------------

    def _call(self, method: str, path: str, *, body: dict | None = None,
              params: dict | None = None, raw: bool = False) -> Any:
        url = self.base + path
        clean = {k: _q(v) for k, v in (params or {}).items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)

        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = r.read()
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                parsed = json.loads(payload.decode() or "{}")
            except json.JSONDecodeError:
                parsed = {"error": {"message": payload.decode(errors="replace")[:200]}}
            raise from_response(parsed, e.code) from None
        except urllib.error.URLError as e:
            # 连不上 = 那头没了。这是平台级的事,该告警而不是重试动作。
            raise ChromeGone(f"连不上 {self.base}: {e.reason}",
                             code="chrome_gone") from None

        if raw or not ctype.startswith("application/json"):
            return payload
        out = json.loads(payload.decode() or "null")
        if isinstance(out, dict) and out.get("error"):
            raise from_response(out)
        return out

    def alive(self) -> bool:
        try:
            self.get("/api/status")
            return True
        except WebmuxdError:
            return False


def _q(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# --------------------------------------------------------------------------
# 内存里那份 tab 表(原 client/mirror.py)
# --------------------------------------------------------------------------

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
        #: 泵线程的事件循环和当前那条连接 —— **`stop()` 要从外面关它**,
        #: 光设一个标志位是叫不醒阻塞在 `recv` 上的协程的。
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any = None

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
        """收摊。**把那条连接关掉,别只是竖个旗子。**

        原来这儿是"设 `_stop` 然后 `join(timeout=2)`" —— 而泵线程正阻塞在
        `async for raw in ws` 上,**根本没机会去看那面旗子**。于是每次都等满
        两秒:`sess.detach()` 卡两秒,一轮测试里 14 次就是 28 秒。
        **旗子只在循环回到顶上时才被读到,而它回不到顶上。**

        所以现在从这边把 socket 关掉:`async for` 立刻结束,泵看见旗子就退。
        """
        self._stop.set()
        loop, ws = self._loop, self._ws
        if loop is not None and ws is not None and not loop.is_closed():
            with contextlib.suppress(Exception):
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._pump())
        except Exception:                      # pragma: no cover - 后台线程
            log.debug("事件线程退出", exc_info=True)
        finally:
            self._loop = None
            loop.close()

    async def _pump(self) -> None:
        while not self._stop.is_set():
            try:
                url = self._url + (f"?after={self._seq}" if self._seq else "")
                headers = [("Authorization", f"Bearer {self._token}")] if self._token else []
                async with websockets.connect(url, additional_headers=headers,
                                              ping_interval=20) as ws:
                    self._ws = ws
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
            finally:
                self._ws = None

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


# --------------------------------------------------------------------------
# Session(原 client/session.py)
# --------------------------------------------------------------------------

class Session:
    def __init__(self, id: str, api_url: str, *, view_url: str = "",
                 token: str | None = None, user: str = "api",
                 owned: bool = False, manager: Any = None,
                 **_v1: Any) -> None:
        self.id = id
        self.api_url = api_url.rstrip("/")
        #: **画面和 API 同一个口**(works/04 §1)。v1 的 `view_login` /
        #: `view_password` 是 KasmVNC 的规矩,不是我们的 —— 一并删掉,
        #: 权限改成 token(works/04 §3)。
        self.view_url = view_url or (self.api_url + "/")
        self.user = user
        self._t = Transport(self.api_url, token=token)
        self._manager = manager
        #: `with` 只关**这次真的建起来的** —— 接管到别人的,拿到手不等于有权杀
        self._owned = owned
        self._last_seen: dict[str, dict] = {}

        ws = self.api_url.replace("http://", "ws://").replace("https://", "wss://")
        self._mirror = Mirror(ws + "/api/events", token=token,
                              refetch=lambda: self._t.get("/api/tabs"))
        self._mirror.load(self._t.get("/api/tabs"))
        self._mirror.start()

    def __repr__(self) -> str:
        return f"<Session {self.id} {self.api_url} {len(self.tabs)} 个 tab>"

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc: object) -> None:
        if self._owned:
            self.kill()
        else:
            self.detach()

    # ------------------------------------------------------------ tab 表

    @property
    def tabs(self) -> list[Tab]:
        """**读内存,不发请求**(sdk/README §3)。"""
        return [Tab(self, t["id"]) for t in self._mirror.tabs()]

    @property
    def active(self) -> Tab | None:
        a = self._mirror.active
        return Tab(self, a) if a else None

    def tab(self, key: Any = None, *, title: str | None = None) -> Tab:
        """按 id / index / 标题拿一个。**按标题和 index 是本地匹配**,线上只认 id。"""
        rows = self._mirror.tabs()
        if title is not None:
            hits = [t for t in rows if t.get("title") == title] or \
                   [t for t in rows if title in (t.get("title") or "")]
            if len(hits) != 1:
                from webmuxd.exceptions import NotFound
                raise NotFound(
                    f"标题「{title}」匹配到 {len(hits)} 个 tab" if hits
                    else f"没有标题含「{title}」的 tab",
                    code="not_found",
                    details={"candidates": [{"id": t["id"], "name": t.get("title", "")}
                                            for t in rows]})
            return Tab(self, hits[0]["id"])
        if isinstance(key, int):
            try:
                return Tab(self, rows[key]["id"])
            except IndexError:
                raise TabGone(f"没有第 {key} 个 tab", code="tab_gone",
                              details={"reason": "closed"}) from None
        if isinstance(key, str):
            if self._mirror.get(key) is None:
                raise TabGone(f"{key} 不在了", code="tab_gone",
                              details={"reason": "closed"})
            return Tab(self, key)
        raise TypeError("tab() 要 id、index 或 title=")

    def open(self, url: str = "about:blank", *, active: bool = True,
             user: str | None = None) -> Tab:
        """新建 tab + 导航 + 返回句柄 —— **一次请求**,线上本来就是一步。"""
        d = self._t.post("/api/tabs", {"url": url, "active": active,
                                       "user": user or self.user})
        # **拿响应回灌内存**,不等 WS 那条 tab.created 追上来 ——
        # 和动作响应回灌是同一条原则(sdk/README §3),否则 `sess.open(url)`
        # 之后立刻读 `tab.title` 就是个竞态。
        self._mirror.seed(d)
        return Tab(self, d["id"])

    def reorder(self, order: list[str]) -> None:
        """少给的自动排在后面 —— lib 帮你补齐再发。"""
        self._t.post("/api/tabs/reorder", {"order": order})

    def sync(self) -> None:
        """手动重新拉全量。收到 `gap` 时 lib 自己会做,这个是给你兜底的。"""
        self._mirror.load(self._t.get("/api/tabs"))

    @property
    def stale(self) -> bool:
        """WS 断了 → True,内存不保证新鲜(属性读会退化成直接 GET)。"""
        return self._mirror.stale

    # -------------------------------------------------------------- 日志

    def log(self, *, limit: int = 100, after: int | None = None,
            only: str | None = None, user: str | None = None,
            tab: str | None = None, kind: str | None = None) -> list[dict]:
        return self._t.get("/api/log", limit=limit, after=after, only=only,
                           user=user, tab=tab, kind=kind)["entries"]

    def bundle(self, path: str | None = None, *, tab: str | None = None) -> bytes:
        data = self._t.get_bytes("/api/log/bundle", tab=tab)
        if path:
            with open(path, "wb") as fh:
                fh.write(data)
        return data

    # -------------------------------------------------------------- 杂项

    def status(self) -> dict:
        return self._t.get("/api/status")

    def viewport(self) -> dict:
        return self._t.get("/api/viewport")

    def reset(self) -> None:
        self._t.post("/api/reset")
        self.sync()

    def share(self, *, writable: bool = False, ttl: float = 3600) -> dict:
        """**默认只读**,和 API、CLI、ttyd 的默认一致 ——
        lib 不做"代码里方便所以更宽松"这种事。"""
        r = self._t.post("/api/live-token",
                         {"read_only": not writable, "ttl_s": int(ttl)})
        tok = r["token"]
        return {**r,
                "view_url": f"{self.view_url}?t={tok}" if self.view_url else "",
                "api_url": f"{self.api_url}/api?t={tok}"}

    def upload_file(self, path: str) -> str:
        import os
        with open(path, "rb") as fh:
            r = self._t.post("/api/upload", {"name": os.path.basename(path),
                                             "data": fh.read().hex()})
        return r["file_id"]

    def download(self, name: str, to: str | None = None) -> bytes:
        data = self._t.get_bytes(f"/api/download/{name}")
        if to:
            with open(to, "wb") as fh:
                fh.write(data)
        return data

    def detach(self) -> None:
        """断开但**不动那个 session** —— 关掉网页就是 detach,容器照跑。"""
        self._mirror.stop()

    def kill(self) -> None:
        self._mirror.stop()
        if self._manager is not None:
            self._manager._forget(self.id)


# --------------------------------------------------------------------------
# Webmuxd(原 client/manager.py)
# --------------------------------------------------------------------------

class Webmuxd:
    """一个 server 的客户端。

    **端口在这儿,不在 session 上**([k](../docs/v2/works/k-one-server.md)):

        web  = Webmuxd(port=7900)
        sess = web.session(id="demo")
        tab  = sess.open("https://example.com")

    以前是 `web.session(id=, port=)` —— 一个 session 一个端口。
    那是 kasm 留下的:它的 web 口不归我们控制,所以只能一个 session 一个。
    画面换成我们自己产的之后,**那条硬约束没有了**。
    """

    def __init__(self, url: str | None = None, *, port: int | None = None,
                 token: str | None = None, name: str = "default",
                 user: str = "api", host: str = "127.0.0.1", **_v1: Any) -> None:
        self.user = user
        self.host = host
        self.token = token or os.environ.get("WEBMUXD_TOKEN") or None
        self.name = name
        #: **显式传入优先**,其次那份"server 在哪"的记录 ——
        #: 和配置那条老规矩一致([d](../docs/v2/works/d-install.md))。
        self.base = (url or (f"http://{host}:{port}" if port else None)
                     or _recorded_server(name) or f"http://{host}:7900")
        self.base = self.base.rstrip("/")
        self._t = Transport(self.base, token=self.token)
        self._live: dict[str, Session] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return f"<Webmuxd {self.base} 管着 {len(self._live)} 个 session>"

    # ------------------------------------------------------------------

    def list(self) -> list[dict]:
        """server 上有哪些 —— **和 `webmuxd ls`、和列表页是同一份**。"""
        return self._t.get("/api/sessions").get("sessions", [])

    def create(self, id: str, **kw: Any) -> dict:
        """建一个。**同一个 id 再来一次就是接管**,像 `tmux new -A -s`。"""
        body = {"id": id, **{k: v for k, v in kw.items() if v is not None}}
        return self._t.post("/api/sessions", body)

    def session(self, id: str, *, runtime: str | None = None,
                user: str | None = None, **kw: Any) -> Session:
        """拿一个 session。**幂等:同一个 id 永远给你同一个。**

        没有 `create()` 也没有 `get()` —— "建"和"取"是同一件事。
        """
        # **旧名不静默吞。** 落进 `**kw` 会被无声丢掉,然后报一个指向别处的错。
        for old, why in (
                ("port", "端口在 Webmuxd(port=) 上了,一个 server 一个口(k)"),
                ("api_port", "端口在 Webmuxd(port=) 上了(k)"),
                ("view_port", "端口在 Webmuxd(port=) 上了(k)"),
                ("image", "不碰容器,浏览器用 `browser=` 指(h §2)"),
                ("network", "不碰容器(h §2)"),
                ("vnc_port", "没有 VNC 口,画面和 API 同一个口"),
                ("viewport", "改名叫 `window_size=`")):
            if old in kw:
                raise BadRequest(f"`{old}=` 没有了 —— {why}", code="bad_request")

        with self._lock:
            have = self._live.get(id)
            if have is not None:
                # 同一个 id **返回同一个 Python 对象** —— 每个 Session 背后有一条 WS
                # 和一份内存表,给两个就是两条连接、两份可能不一致的表。
                return have
            if not any(r["id"] == id for r in self.list()):
                self.create(id, runtime=runtime, **kw)
            sess = Session(id, f"{self.base}/s/{id}", token=self.token,
                           user=user or self.user, manager=self)
            self._live[id] = sess
            return sess

    def sessions(self) -> list[Session]:
        """server 上的每一个,都变成能操作的 `Session`。

        要**只看这个实例手里已经连上的**,用 `list()` 那个原始表。
        """
        return [self.session(r["id"]) for r in self.list()]

    def kill(self, id: str) -> None:
        sess = self._live.pop(id, None)
        if sess is not None:
            sess.detach()
        self._t.delete(f"/api/sessions/{id}")

    def kill_server(self) -> int:
        """**一个都不许留**,然后 server 自己也走。"""
        for sess in list(self._live.values()):
            sess.detach()
        self._live.clear()
        return int(self._t.delete("/api/server").get("killed", 0))

    def info(self) -> dict:
        return self._t.get("/api/server")

    def _forget(self, id: str) -> None:
        self._live.pop(id, None)


def _recorded_server(name: str) -> str | None:
    """那份"server 在哪"的记录 —— 只读,写是 `webmuxd start` 的事。"""
    import json
    from pathlib import Path
    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    try:
        row = json.loads((Path(base) / "webmuxd" / name / "server.json").read_text())
    except (OSError, ValueError):
        return None
    port = row.get("port") if isinstance(row, dict) else None
    return f"http://127.0.0.1:{port}" if isinstance(port, int) else None
