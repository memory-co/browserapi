"""`Tab` —— 这个库唯一的操作对象(docs/v1/sdk/tab/)。

打开一个网址拿到句柄,之后所有事都在句柄上做:导航、点击、观测。
没有别的"操作器"、"控制器"、"agent" 之类的东西。

**句柄是活的,不是快照。** `tab.url` 读的是内存里那份表(sdk/README §3),
所以 `click()` 返回的那一刻它已经是新的。
"""

from __future__ import annotations

from typing import Any

from webmuxd.errors import BadRequest, TabGone

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
        return self._one({"type": "upload", "file_id": path_or_id,
                          **_locator(target, **kw)})

    # ------------------------------------------------------------- 观测

    def observe(self, **kw: Any) -> Any:
        from webmuxd.client.observation import Observation
        d = self._s._t.get("/api/observe", tab=self.id, **kw)
        return Observation(self._s, d)

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
            from webmuxd.errors import error_class
            cls = error_class(f.get("error"))
            raise cls(f.get("message", ""), code=f.get("error"),
                      details={"candidates": f.get("candidates", [])})
        return self

    def __repr__(self) -> str:
        return f"<ActResult ok={self.ok} {len(self.results)} 个动作>"
