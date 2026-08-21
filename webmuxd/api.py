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
from webmuxd import sessions as rt
from webmuxd.exceptions import (BadRequest, ChromeGone, TabGone,
                                WebmuxdError, from_response)

#: 定位的六种写法(api/act.md §4)。
_LOCATOR_KEYS = ("text", "role", "name", "label", "element", "observation",
                 "css", "point", "nth")


def _locator(target: Any = None, **kw: Any) -> dict[str, Any]:
    """把 `tab.click("提交订单")` / `tab.click(role=..., name=...)` /
    `tab.click(el)` 统一成一个定位字典。"""
    spec: dict[str, Any] = {}
    if target is not None:
        if isinstance(target, str):
            spec["text"] = target
        elif isinstance(target, dict) and "id" in target:
            spec["element"] = target["id"]           # observe() 拿到的元素
        elif hasattr(target, "id"):
            spec["element"] = target.id
            obs = getattr(target, "observation", None)
            if obs:
                spec["observation"] = obs
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

    def observe(self, **kw: Any) -> "Observation":
        d = self._s._t.get("/api/observe", tab=self.id, **kw)
        return Observation.of(self._s, d)

    def text(self) -> str:
        return self._s._t.get_bytes("/api/text", tab=self.id).decode()

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

    def session(self, id: str, *, port: int | None = None,
                runtime: str | None = None,
                user: str | None = None, **kw: Any) -> Session:
        """拿一个 session。**幂等:同一个 id 永远给你同一个。**

        没有 `create()` 也没有 `get()` —— "建"和"取"是同一件事,像 `tmux new -A -s`。

        **端口必须你给,不自动分配**:端口是部署决定的,我们猜一个只会让你的
        配置和实际对不上。v2 里只有**一个**口 —— 画面和 API 都在它上面
        (works/04 §1),所以这条规矩比 v1 好守。
        """
        # **旧名不静默吞。** 落进 `**kw` 会被无声丢掉,然后报一个指向别处的错
        # ——"还不存在,得给 port"。宁可在这儿直说,并指出为什么没了。
        for old, why in (
                ("api_port", "v2 只有一个口,叫 `port=`(works/04)"),
                ("view_port", "v2 只有一个口,画面和 API 在同一个上(works/04)"),
                ("image", "v2 不碰容器,浏览器用 `browser=` 指(works/07 §2)"),
                ("network", "v2 不碰容器(works/07 §2)"),
                ("vnc_port", "v2 没有 VNC(works/01)"),
                ("viewport", "改名叫 `window_size=`")):
            if old in kw:
                raise BadRequest(f"`{old}=` 没有了 —— {why}", code="bad_request")
        runtime = runtime or rt.DEFAULT

        with self._lock:
            have = self._live.get(id)
            if have is not None:
                # 同一个 id **返回同一个 Python 对象** —— 每个 Session 背后有一条 WS
                # 和一份内存表,给两个就是两条连接、两份可能不一致的表。
                if port is not None and have.api_url.endswith(f":{port}") is False:
                    raise BadRequest(
                        f"{id} 已经在 {have.api_url},和你给的 port={port} 对不上",
                        code="bad_request")
                return have

            if port is None:
                raise BadRequest(
                    f"session {id!r} 还不存在,得给 port —— "
                    "端口是部署决定的,我们不替你分配", code="bad_request")

            api = f"http://{self.host}:{port}"
            t = Transport(api, token=self.token)
            owned = False
            if not t.alive():
                # 那个口上什么都没有 → **按 runtime 把它拉起来**。
                # 起不来就抛 RuntimeUnavailable 带 hint,**不静默换一种**
                # (works/05 §4)。
                impl = rt.get(runtime)
                handle = impl.start(id, port=port, token=self.token, **kw)
                self._handles[id] = (impl, handle)
                t = Transport(api, token=self.token)
                owned = True                # 这次真的建起来了 → with 退出时归我们关

            # **画面就是那个口** —— 没有第二个 scheme 要猜,也没有 VNC 口令
            sess = Session(id, api, view_url=f"http://{self.host}:{port}/",
                           token=self.token, user=user or self.user,
                           owned=owned, manager=self)
            self._live[id] = sess
            return sess

    def sessions(self) -> list[Session]:
        """这个管理实例手里的 session。

        要列**这台机器上所有**的,得问管理面那个口 —— 那属于 runtime 那一层。
        """
        if self._t is not None:
            try:
                listing = self._t.get("/api/sessions")
                return [self.session(s["id"], port=s.get("port"))
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
        """**两种 runtime 的 sessiond 都跟着死** —— 它们都是我们的子进程。

        `remote` 那头的浏览器不归我们,`stop` 不动它(works/07 §6)。
        """
        for s in list(self._live.values()):
            s.detach()
        for id_, (impl, handle) in list(self._handles.items()):
            impl.stop(handle)
            self._handles.pop(id_, None)
        self._live.clear()


# ---------------------------------------------------------------------------
# 观测 —— 数据在 models.Observation,这儿只加"图用到才取"
# ---------------------------------------------------------------------------

class Observation(models.Observation):
    """SDK 这一侧的观测。

    **数据形状不在这儿定义** —— 它就是 `models.Observation`,和服务端同一个类
    ([j §3.1](../docs/v2/works/j-layout.md#31-modelspy所有跨边界的数据在这儿定义一次))。
    这层只多一件事:**截图是用到才去取的**,不是每次 observe 都拖一张图回来。

    靠的是"属性覆盖字段":父类 `__init__` 里那句 `self.screenshot = …`
    会落到下面这个 setter 上,于是字节存进 `_shot`,而读的时候才去发请求。
    """

    _session: Any = None

    @classmethod
    def of(cls, session: Any, d: dict) -> "Observation":
        obs = cls.from_json(d)
        obs._session = session
        return obs

    @property
    def screenshot(self) -> bytes:
        """这次观测那一刻的页面。**用到才去取。**

        **就是页面本身,没有画框的第二个版本。** 编号在 `el.id`,
        位置在 `el.bbox` —— 要 Set-of-Mark 图,拿这两样自己叠
        ([issue](../docs/v2/issues/标注层会被人看见.md))。
        """
        if not self._shot and self._session is not None and self.shot_url:
            self._shot = self._session._t.get_bytes(self.shot_url)
        return self._shot

    @screenshot.setter
    def screenshot(self, v: bytes) -> None:
        self._shot = v

