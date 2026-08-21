"""动作执行 —— docs/v1/api/act.md §2 和 §3。

`POST /api/act` 的全部内容就在这儿:**串行执行,遇错即停**,每个动作一条独立结果。

两处值得先说明白,因为它们是这个模块存在的理由:

- **`after.changed` 是一句人话。**「出现『订单已提交』」比「DOM 变了 34 个节点」
  有用一百倍 —— 它是日志里最有信息量的一列(§2.1)。
- **`settle` 决定动作之后等多久。** 等太短会拍到加载中的白屏(日志全是白图),
  等太长吞吐塌陷(§2.2)。
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from typing import Any

from webmuxd import locate
from webmuxd.cdp import CDP, CDPError
from webmuxd.exceptions import (
    BadRequest, NotClickable, NotFound, Timeout, WebmuxdError,
)
from webmuxd.models import ActionResult, Element, PageDigest, Snapshot

#: 打码用的东西。明文只在这儿出现一次,**日志、事件、截图里一律这个**(§3.1)。
MASK = "••••••"

#: settle 的默认上限。等太长吞吐就塌了(§2.2)。
SETTLE_TIMEOUT = 5.0

#: 这几个动作看不出干了什么,日志里标黄(§4)。
OPAQUE_ACTIONS = frozenset({"js"})

_KEYS = {
    "Enter": (13, "Enter", "\r"), "Tab": (9, "Tab", "\t"),
    "Escape": (27, "Escape", ""), "Backspace": (8, "Backspace", ""),
    "Delete": (46, "Delete", ""), "ArrowUp": (38, "ArrowUp", ""),
    "ArrowDown": (40, "ArrowDown", ""), "ArrowLeft": (37, "ArrowLeft", ""),
    "ArrowRight": (39, "ArrowRight", ""), "Home": (36, "Home", ""),
    "End": (35, "End", ""), "PageUp": (33, "PageUp", ""),
    "PageDown": (34, "PageDown", ""), "Space": (32, "Space", " "),
}
_MODIFIER_BITS = {"Alt": 1, "Control": 2, "Ctrl": 2, "Meta": 4, "Command": 4, "Shift": 8}


# ---------------------------------------------------------------------------
# after.changed —— 一句人话
# ---------------------------------------------------------------------------

_DIGEST_JS = """(() => {
  const txt = (document.body && document.body.innerText || '')
      .split('\\n').map(s => s.trim()).filter(s => s.length > 1).slice(0, 400);
  const alerts = [...document.querySelectorAll('[role=alert],[aria-live=assertive]')]
      .map(e => (e.innerText || '').trim()).filter(Boolean).slice(0, 10);
  return JSON.stringify({url: location.href, lines: txt, alerts,
                         forms: document.forms.length});
})()"""


async def digest(cdp: CDP, session_id: str) -> PageDigest:
    """页面的一份粗略指纹,只为算出 `after.changed`。"""
    import json
    try:
        r = await cdp.send("Runtime.evaluate",
                           {"expression": _DIGEST_JS, "returnByValue": True},
                           session_id=session_id, timeout=5)
        d = json.loads(r["result"]["value"])
    except Exception:
        return PageDigest()
    return PageDigest(url=d.get("url", ""), lines=tuple(d.get("lines", [])),
                      alerts=tuple(d.get("alerts", [])), forms=int(d.get("forms", 0)))


def describe_change(before: PageDigest, after: PageDigest) -> str | None:
    """由启发式生成一句人话(§2.1):
    新的 `role=alert` → 新出现的最大文本块 → 消失的表单。

    **算不出来就返回 None,不硬编。** 「页面变了」这种话等于没说。
    """
    new_alerts = [a for a in after.alerts if a not in before.alerts]
    if new_alerts:
        return f"出现『{_clip(new_alerts[0])}』"

    seen = set(before.lines)
    fresh = [l for l in after.lines if l not in seen]
    if fresh:
        biggest = max(fresh, key=len)
        if len(biggest) >= 2:
            return f"出现『{_clip(biggest)}』"

    if before.forms and after.forms < before.forms:
        return "表单消失了"

    gone = [l for l in before.lines if l not in set(after.lines)]
    if gone:
        return f"『{_clip(max(gone, key=len))}』不见了"
    return None


def _clip(s: str, n: int = 30) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------------------------------------------------------------------
# settle —— 动作之后等多久
# ---------------------------------------------------------------------------

class Settler:
    """在飞请求数由 Network 事件维护;DOM 静默靠轮询正文指纹。"""

    def __init__(self, cdp: CDP, session_id: str) -> None:
        self._cdp, self._sid = cdp, session_id
        self._inflight = 0
        self._offs: list[Any] = []

    async def start(self) -> None:
        await self._cdp.send("Network.enable", session_id=self._sid)

        def began(_p: dict, sid: str | None) -> None:
            if sid == self._sid:
                self._inflight += 1

        def ended(_p: dict, sid: str | None) -> None:
            if sid == self._sid:
                self._inflight = max(0, self._inflight - 1)

        self._offs = [
            self._cdp.on("Network.requestWillBeSent", began),
            self._cdp.on("Network.loadingFinished", ended),
            self._cdp.on("Network.loadingFailed", ended),
        ]

    def stop(self) -> None:
        for off in self._offs:
            off()
        self._offs.clear()

    async def settle(self, spec: dict[str, Any] | None) -> None:
        spec = spec or {}
        strategy = spec.get("strategy", "network_idle")
        timeout = float(spec.get("timeout_ms", SETTLE_TIMEOUT * 1000)) / 1000

        if strategy == "none":
            return
        if strategy == "selector":
            css = spec.get("wait_for")
            if not css:
                raise BadRequest("settle=selector 得给 wait_for", code="bad_request")
            await self.wait_for_selector(css, timeout)
            return
        if strategy == "dom_idle":
            await self._dom_quiet(timeout)
            return
        if strategy == "network_idle":
            # 在飞请求为 0 **且** DOM 静默 —— 只看网络会在 SPA 上早退
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and self._inflight > 0:
                await asyncio.sleep(0.05)
            await self._dom_quiet(max(0.2, deadline - time.monotonic()))
            return
        raise BadRequest(f"不认识的 settle 策略:{strategy}", code="bad_request")

    async def _dom_quiet(self, timeout: float, quiet: float = 0.3) -> None:
        """正文指纹连续 `quiet` 秒没变就算静默。**超时不抛** ——
        settle 是"等一下"不是"必须等到",真等不到由后面的断言去发现。"""
        deadline = time.monotonic() + timeout
        last, stable_since = None, time.monotonic()
        while time.monotonic() < deadline:
            h = await self._fingerprint()
            now = time.monotonic()
            if h != last:
                last, stable_since = h, now
            elif now - stable_since >= quiet:
                return
            await asyncio.sleep(0.05)

    async def _fingerprint(self) -> str:
        try:
            r = await self._cdp.send(
                "Runtime.evaluate",
                {"expression": "document.body ? document.body.innerText.length + ':' "
                               "+ document.querySelectorAll('*').length : ''",
                 "returnByValue": True},
                session_id=self._sid, timeout=3)
            return hashlib.md5(str(r["result"].get("value")).encode()).hexdigest()
        except Exception:
            return ""

    async def wait_for_selector(self, css: str, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                r = await self._cdp.send(
                    "Runtime.evaluate",
                    {"expression": f"!!document.querySelector({css!r})",
                     "returnByValue": True}, session_id=self._sid, timeout=3)
                if r["result"].get("value"):
                    return
            except CDPError:
                pass
            await asyncio.sleep(0.05)
        raise Timeout(f"等 {css} 超时", code="timeout", details={"css": css})


# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------

class Executor:
    """在一个 tab 上跑动作。

    `snapshot_fn` 拿元素表 —— 由外面传进来,因为 observe 和 act **必须共用同一份**,
    否则模型看到的编号和点到的东西对不上。
    """

    def __init__(self, cdp: CDP, session_id: str, *, secrets: Any = None) -> None:
        self._cdp, self._sid = cdp, session_id
        self._secrets = secrets
        self._settler = Settler(cdp, session_id)
        self._snap: Snapshot | None = None
        self._snap_id: str | None = None

    async def start(self) -> None:
        await self._settler.start()
        await self._cdp.send("DOM.enable", session_id=self._sid)
        await self._cdp.send("Page.enable", session_id=self._sid)

    def stop(self) -> None:
        self._settler.stop()

    # ------------------------------------------------------------------ 主循环

    async def run(self, actions: list[dict], *,
                  settle: dict | None = None) -> list[ActionResult]:
        """**串行执行,遇错即停。** 失败那条之后的动作一个都不跑 ——
        页面已经不是你以为的样子了,继续跑只会错得更远。"""
        results: list[ActionResult] = []
        for spec in actions:
            r = await self._one(spec, settle)
            results.append(r)
            if not r.ok:
                break
        return results

    async def _one(self, spec: dict, settle: dict | None) -> ActionResult:
        kind = spec.get("type")
        if not kind:
            return ActionResult(False, 0, "?", error="bad_request",
                                message="动作缺 type")
        began = time.monotonic()
        before = await digest(self._cdp, self._sid)
        try:
            value = await self._dispatch(kind, spec)
        except WebmuxdError as e:
            # **动作失败是一条结果,不是一个抛出来的异常**(§2)——
            # 包括 bad_request:一串动作里第三个写错了,前两个的结果不能丢。
            return ActionResult(
                False, int((time.monotonic() - began) * 1000), kind,
                target=_target_of(spec), error=e.code, message=e.message,
                candidates=e.details.get("candidates"),
                opaque=kind in OPAQUE_ACTIONS)
        except CDPError as e:
            return ActionResult(False, int((time.monotonic() - began) * 1000), kind,
                                target=_target_of(spec), error="bad_request",
                                message=str(e))

        await self._settler.settle(settle)
        after = await digest(self._cdp, self._sid)

        info: dict[str, Any] = {"url": after.url}
        changed = describe_change(before, after)
        if changed:
            info["changed"] = changed

        return ActionResult(True, int((time.monotonic() - began) * 1000), kind,
                            target=_target_of(spec), hit=self._last_hit,
                            after=info, value=value,
                            opaque=kind in OPAQUE_ACTIONS or "point" in spec)

    _last_hit: dict[str, Any] | None = None

    # ------------------------------------------------------------------ 分派

    async def _dispatch(self, kind: str, spec: dict) -> Any:
        self._last_hit = None
        fn = getattr(self, f"_do_{kind}", None)
        if fn is None:
            raise BadRequest(f"不认识的动作:{kind}", code="bad_request")
        return await fn(spec)

    # ---- 导航 -------------------------------------------------------------

    async def _do_goto(self, spec: dict) -> None:
        url = spec.get("url") or ""
        from webmuxd.tabs import is_blocked
        if is_blocked(url):
            raise BadRequest(f"{url} 是特权页面,禁止导航", code="blocked_url",
                             details={"url": url})
        await self._cdp.send("Page.navigate", {"url": url}, session_id=self._sid)

    async def _do_back(self, _spec: dict) -> None:
        await self._history_go(-1)

    async def _do_forward(self, _spec: dict) -> None:
        await self._history_go(+1)

    async def _history_go(self, delta: int) -> None:
        h = await self._cdp.send("Page.getNavigationHistory", session_id=self._sid)
        i = h["currentIndex"] + delta
        entries = h["entries"]
        if not (0 <= i < len(entries)):
            # **不静默无操作** —— 你 UI 上按钮的禁用状态和实际行为要对得上
            raise BadRequest("没得" + ("后退" if delta < 0 else "前进"),
                             code="bad_request")
        await self._cdp.send("Page.navigateToHistoryEntry", {"entryId": entries[i]["id"]},
                             session_id=self._sid)

    async def _do_reload(self, spec: dict) -> None:
        await self._cdp.send("Page.reload", {"ignoreCache": bool(spec.get("ignore_cache"))},
                             session_id=self._sid)

    async def _do_stop(self, _spec: dict) -> None:
        await self._cdp.send("Page.stopLoading", session_id=self._sid)

    # ---- 输入 -------------------------------------------------------------

    async def _do_click(self, spec: dict) -> None:
        x, y = await self._point_for(spec)
        button = spec.get("button", "left")
        count = int(spec.get("count", 1))
        mods = _modifiers(spec.get("modifiers"))
        for _ in range(count):
            for kind in ("mousePressed", "mouseReleased"):
                await self._cdp.send("Input.dispatchMouseEvent", {
                    "type": kind, "x": x, "y": y, "button": button,
                    "clickCount": count, "modifiers": mods},
                    session_id=self._sid)

    async def _do_hover(self, spec: dict) -> None:
        x, y = await self._point_for(spec)
        await self._cdp.send("Input.dispatchMouseEvent",
                             {"type": "mouseMoved", "x": x, "y": y},
                             session_id=self._sid)

    async def _do_type(self, spec: dict) -> None:
        el = await self._resolve(spec, "type")
        await self._focus(el)
        if spec.get("clear"):
            await self._select_all_and_delete()
        text = await self._text_of(spec)
        delay = float(spec.get("delay", 0) or 0)
        if delay:
            for ch in text:
                await self._cdp.send("Input.insertText", {"text": ch},
                                     session_id=self._sid)
                await asyncio.sleep(delay / 1000)
        else:
            await self._cdp.send("Input.insertText", {"text": text}, session_id=self._sid)

    async def _do_clear(self, spec: dict) -> None:
        el = await self._resolve(spec, "clear")
        await self._focus(el)
        await self._select_all_and_delete()

    async def _select_all_and_delete(self) -> None:
        for key in ("a",):
            await self._cdp.send("Input.dispatchKeyEvent", {
                "type": "keyDown", "key": key, "modifiers": 2,
                "windowsVirtualKeyCode": 65}, session_id=self._sid)
            await self._cdp.send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": key, "modifiers": 2,
                "windowsVirtualKeyCode": 65}, session_id=self._sid)
        await self._press("Delete")

    async def _do_key(self, spec: dict) -> None:
        await self._press(spec.get("key", ""), _modifiers(spec.get("modifiers")))

    async def _press(self, key: str, modifiers: int = 0) -> None:
        # 「Control+a」这种写法也认
        if "+" in key:
            *mods, key = [p.strip() for p in key.split("+")]
            modifiers |= _modifiers(mods)
        code, name, text = _KEYS.get(key, (ord(key[0]) if key else 0, key, key))
        base = {"key": name, "code": name, "windowsVirtualKeyCode": code,
                "nativeVirtualKeyCode": code, "modifiers": modifiers}
        await self._cdp.send("Input.dispatchKeyEvent",
                             {**base, "type": "keyDown", "text": text},
                             session_id=self._sid)
        await self._cdp.send("Input.dispatchKeyEvent", {**base, "type": "keyUp"},
                             session_id=self._sid)

    async def _do_scroll(self, spec: dict) -> None:
        if "to" in spec:
            el = await self._resolve(spec["to"], "scroll")
            await self._scroll_into_view(el)
            return
        dy = float(spec.get("dy", 0))
        dx = float(spec.get("dx", 0))
        await self._cdp.send("Input.dispatchMouseEvent", {
            "type": "mouseWheel", "x": 10, "y": 10, "deltaX": dx, "deltaY": dy},
            session_id=self._sid)

    async def _do_select(self, spec: dict) -> None:
        el = await self._resolve(spec, "select")
        want = spec.get("value", spec.get("label"))
        by = "value" if "value" in spec else "label"
        await self._eval_on(el, f"""function () {{
            const want = {want!r};
            const opt = [...this.options].find(o =>
                {'o.value === want' if by == 'value' else 'o.textContent.trim() === want'});
            if (!opt) return false;
            this.value = opt.value;
            this.dispatchEvent(new Event('input', {{bubbles: true}}));
            this.dispatchEvent(new Event('change', {{bubbles: true}}));
            return true;
        }}""", expect_true=f"下拉框里没有「{want}」")

    async def _do_check(self, spec: dict) -> None:
        el = await self._resolve(spec, "check")
        want = spec.get("checked", True)
        await self._eval_on(el, f"""function () {{
            if (this.checked !== {str(bool(want)).lower()}) this.click();
            return true;
        }}""")

    async def _do_js(self, spec: dict) -> Any:
        """逃生舱。能用,但日志里标黄 —— 回看时"执行了一段 JS"看不出干了什么。"""
        r = await self._cdp.send("Runtime.evaluate",
                                 {"expression": spec.get("expression", ""),
                                  "returnByValue": True, "awaitPromise": True},
                                 session_id=self._sid)
        if r.get("exceptionDetails"):
            raise BadRequest(f"js 出错:{_js_error(r['exceptionDetails'])}",
                             code="bad_request")
        return r["result"].get("value")

    async def _do_wait_for(self, spec: dict) -> None:
        timeout = float(spec.get("timeout_ms", SETTLE_TIMEOUT * 1000)) / 1000
        if "ms" in spec:
            await asyncio.sleep(float(spec["ms"]) / 1000)
            return
        if "css" in spec:
            await self._settler.wait_for_selector(spec["css"], timeout)
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            d = await digest(self._cdp, self._sid)
            if "text" in spec and any(str(spec["text"]) in l for l in d.lines + d.alerts):
                return
            if "url_contains" in spec and str(spec["url_contains"]) in d.url:
                return
            await asyncio.sleep(0.08)
        raise Timeout(f"等 {spec} 超时", code="timeout", details={"waited": spec})

    async def _do_upload(self, spec: dict) -> None:
        el = await self._resolve(spec, "upload")
        file_id = spec.get("file_id") or spec.get("file")
        if not file_id:
            raise BadRequest("upload 要给 file_id", code="bad_request")
        paths = [str(p) for p in (file_id if isinstance(file_id, list) else [file_id])]
        await self._cdp.send("DOM.setFileInputFiles",
                             {"files": paths, "backendNodeId": el.backend_node_id},
                             session_id=self._sid)

    async def _do_extract(self, spec: dict) -> Any:
        el = await self._resolve(spec, "extract")
        mode = spec.get("mode", "text")
        js = {"text": "function () { return this.innerText; }",
              "html": "function () { return this.outerHTML; }",
              "attr": f"function () {{ return this.getAttribute({spec.get('attr', 'href')!r}); }}",
              "table": """function () { return [...this.querySelectorAll('tr')].map(
                     r => [...r.children].map(c => c.innerText.trim())); }"""}.get(mode)
        if js is None:
            raise BadRequest(f"不认识的 extract mode:{mode}", code="bad_request")
        return await self._eval_on(el, js)

    # ------------------------------------------------------------- 定位/辅助

    def use_snapshot(self, snap: Snapshot, snap_id: str | None = None) -> None:
        """让 act 和 observe 共用同一份元素表 —— 编号必须指同一个东西。"""
        self._snap, self._snap_id = snap, snap_id

    async def _fresh_snapshot(self) -> Snapshot:
        self._snap = await locate.snapshot(self._cdp, self._sid)
        return self._snap

    #: 这几个动作的 `text` 是**要输入的内容**,不是定位 ——
    #: `{"type":"type","label":"手机号","text":"138..."}` 里的 text 显然不是找元素用的。
    #: 规格里没点破这条,但两种用法确实撞在同一个键上(§3 动作表 vs §4 定位)。
    _TEXT_IS_PAYLOAD = frozenset({"type"})

    def _locator_of(self, kind: str, spec: dict) -> dict:
        keys = set(locate.LOCATOR_KEYS)
        if kind in self._TEXT_IS_PAYLOAD:
            keys.discard("text")
        loc = {k: v for k, v in spec.items() if k in keys}
        if not loc:
            raise BadRequest(f"{kind} 没给定位", code="bad_request")
        return loc

    async def _resolve(self, spec: dict, kind: str | None = None) -> Element:
        if kind is not None:
            spec = self._locator_of(kind, spec)
        snap = self._snap or await self._fresh_snapshot()
        try:
            el = locate.resolve(spec, snap, observation_id=self._snap_id)
        except locate._Escape:
            raise
        except NotFound:
            # 元素表可能过期了 —— 重抓一次再判,免得把"刚出现的按钮"报成不存在
            snap = await self._fresh_snapshot()
            el = locate.resolve(spec, snap, observation_id=None)
        self._last_hit = el.to_json()
        return el

    async def _point_for(self, spec: dict) -> tuple[float, float]:
        """算出要点哪儿。`point` 和 `css` 是逃生舱,不走元素表。"""
        if "point" in spec:
            x, y = spec["point"]
            return float(x), float(y)
        if "css" in spec:
            r = await self._cdp.send(
                "Runtime.evaluate",
                {"expression": f"(() => {{const e=document.querySelector({spec['css']!r});"
                               f"if(!e) return null; e.scrollIntoView({{block:'center'}});"
                               f"const b=e.getBoundingClientRect();"
                               f"return [b.x+b.width/2, b.y+b.height/2];}})()",
                 "returnByValue": True}, session_id=self._sid)
            v = r["result"].get("value")
            if not v:
                raise NotFound(f"选择器 {spec['css']} 没匹配到", code="not_found",
                               details={"candidates": []})
            self._last_hit = {"css": spec["css"]}
            return float(v[0]), float(v[1])

        el = await self._resolve(spec, "click")
        if not el.enabled:
            raise NotClickable(f"「{el.name}」是禁用的", code="not_clickable",
                               details={"hit": el.to_json()})
        await self._scroll_into_view(el)
        box = await self._box(el)
        return box[0] + box[2] / 2, box[1] + box[3] / 2

    async def _scroll_into_view(self, el: Element) -> None:
        try:
            await self._cdp.send("DOM.scrollIntoViewIfNeeded",
                                 {"backendNodeId": el.backend_node_id},
                                 session_id=self._sid)
        except CDPError:
            pass

    async def _box(self, el: Element) -> tuple[float, float, float, float]:
        try:
            r = await self._cdp.send("DOM.getBoxModel",
                                     {"backendNodeId": el.backend_node_id},
                                     session_id=self._sid)
        except CDPError as e:
            raise NotClickable(f"「{el.name}」量不到位置,可能被藏起来了",
                               code="not_clickable", details={"hit": el.to_json()}) from e
        q = r["model"]["border"]
        xs, ys = q[0::2], q[1::2]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    async def _focus(self, el: Element) -> None:
        await self._scroll_into_view(el)
        try:
            await self._cdp.send("DOM.focus", {"backendNodeId": el.backend_node_id},
                                 session_id=self._sid)
        except CDPError:
            x, y = await self._point_for({"element": el.id})
            await self._cdp.send("Input.dispatchMouseEvent",
                                 {"type": "mousePressed", "x": x, "y": y,
                                  "button": "left", "clickCount": 1},
                                 session_id=self._sid)
            await self._cdp.send("Input.dispatchMouseEvent",
                                 {"type": "mouseReleased", "x": x, "y": y,
                                  "button": "left", "clickCount": 1},
                                 session_id=self._sid)

    async def _eval_on(self, el: Element, fn: str, *, expect_true: str | None = None) -> Any:
        """在元素上跑一段 JS。

        **必须写成 `function () { ... this ... }`** —— `Runtime.callFunctionOn`
        是把对象绑到 `this`,不是当参数传进去。写成箭头函数的话 `this` 不绑定,
        拿到的是 undefined。踩过。
        """
        obj = await self._cdp.send("DOM.resolveNode",
                                   {"backendNodeId": el.backend_node_id},
                                   session_id=self._sid)
        r = await self._cdp.send("Runtime.callFunctionOn", {
            "objectId": obj["object"]["objectId"], "functionDeclaration": fn,
            "returnByValue": True, "awaitPromise": True}, session_id=self._sid)
        if r.get("exceptionDetails"):
            raise BadRequest(_js_error(r["exceptionDetails"]), code="bad_request")
        v = r["result"].get("value")
        if expect_true and not v:
            raise NotFound(expect_true, code="not_found", details={"candidates": []})
        return v

    async def _text_of(self, spec: dict) -> str:
        """`text_ref` 的明文只在这儿出现一次 —— 上层记日志时看到的是 MASK(§3.1)。"""
        ref = spec.get("text_ref")
        if ref:
            if self._secrets is None:
                raise BadRequest("给了 text_ref 但没配 secrets 后端", code="bad_request")
            return await self._secrets.resolve(ref)
        return str(spec.get("text", ""))


def _js_error(details: dict) -> str:
    """`exceptionDetails.text` 常常只是「Uncaught」—— 真正的原因在 exception 里。"""
    exc = details.get("exception") or {}
    return (exc.get("description") or exc.get("value")
            or details.get("text") or "js 出错")


def _modifiers(mods: Any) -> int:
    if not mods:
        return 0
    if isinstance(mods, str):
        mods = [mods]
    return sum(_MODIFIER_BITS.get(m, 0) for m in mods)


def _target_of(spec: dict) -> dict[str, Any] | None:
    """日志里记"你说要点什么" —— 和 `hit`(实际命中了什么)分开摆,
    一眼看出是认错了元素还是页面变了。**凭证不进日志。**"""
    t = {k: v for k, v in spec.items()
         if k in locate.LOCATOR_KEYS or k in ("url", "key", "dy", "expression", "mode")}
    if "text" in spec and spec.get("_secret"):
        t["text"] = MASK
    if spec.get("text_ref"):
        t["text"] = MASK
        t.pop("text_ref", None)
    return t or None
