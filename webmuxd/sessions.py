"""**所有会话都归它** —— 建一个、找一个、关一个,以及一个 session 内部的编排。

**这一层没有业务逻辑**,业务在下面那几个文件里。它管的是两件事。

一是**起哪一套**:本机起一个,还是你给一个 CDP 端点 —— 就是一个 if
(文件后半)。"要 VNC 就先起 xpra"这个决定也在这儿,而不在 `processes.py`:
那是第 1 层,不该认识 `xpra.py`
([j §5](../docs/v2/works/j-layout.md#5-依赖方向扁平之后层要靠规矩守))。

二是那些**"跨模块才成立"的规矩**:

- **一个 session 同时只跑一个动作**,并发调返回 `409 busy`,不排队、不交错。
- **要像素就得在前台**:`screenshot` / `text` 指向非激活 tab 时先切过去 ——
  Chromium 不渲染后台 tab,拍出来是白的或旧的(sdk/tab/read.md §3)。
- **`seq` 一个计数器**,日志和事件共用,所以两边对得齐。
- **凭证不进日志**:明文在执行层解开,记账时看到的是掩码。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol

from webmuxd import config, models, processes, xpra as xpra_mod
from webmuxd import cursor as cursor_probe
from webmuxd import capture, locate, probe
from webmuxd.act import MASK, Executor
from webmuxd.browser_ui import Natives
from webmuxd.cdp import CDP
from webmuxd.exceptions import (Busy, BusyHuman, SessionNotFound, TabGone,
                                UsageError, unavailable)
from webmuxd.log import Log, Seq
from webmuxd.models import RefTable, SessionInfo, Snapshot

from webmuxd.screen import Screencaster
from webmuxd.tabs import TabTable

#: 人在 VNC 里动过之后,API 让路多少毫秒(api/README §5)。0 = 关掉这个行为。
HUMAN_YIELD_MS = 3000


log = logging.getLogger("webmuxd.session")

class Session:
    """sessiond 的核心对象。一个进程一个。"""

    def __init__(self, cdp: CDP, *, data_dir: str | Path = "/data",
                 tab_max: int | None = None, human_yield_ms: int = HUMAN_YIELD_MS,
                 secrets: Any = None, view: dict[str, Any] | None = None) -> None:
        self.cdp = cdp
        self.seq = Seq()
        self.log = Log(data_dir, seq=self.seq)
        self.secrets = secrets
        self._human_yield = human_yield_ms / 1000
        self._human_at = 0.0
        self._subscribers: set[asyncio.Queue] = set()
        self._recent: list[dict] = []          # 事件环,断线重连补这段
        self._recent_cap = 1000

        kwargs: dict[str, Any] = {"emit": self._emit}
        if tab_max is not None:
            kwargs["tab_max"] = tab_max
        self.tabs = TabTable(cdp, **kwargs)

        self._exec: dict[str, Executor] = {}
        self._sessions: dict[str, str] = {}    # tab_id -> CDP sessionId
        #: `@e1` 表 —— **一个 session 一张,号只增不重用**
        #: ([models.RefTable](models.py))。`snapshot` 发号,`click @e1` 认号。
        self.refs = RefTable()
        #: 画面。v2 里它是我们自己的([c](../docs/v2/works/c-view.md))
        self.view = Screencaster(self, **(view or {}))
        self._action_lock = asyncio.Lock()
        self.started_at = time.time()
        self.restarts = 0
        self._dispatched_at = 0.0

        root = Path(data_dir)
        self.files_dir = root / "files"
        self.downloads_dir = root / "downloads"
        for d in (self.files_dir, self.downloads_dir):
            d.mkdir(parents=True, exist_ok=True)
        self._tokens: dict[str, tuple[bool, float]] = {}

        #: 六类原生 UI。headless 里它们根本不渲染,只能用 CDP 收回来
        #: ([g](../docs/v2/works/g-native-ui.md))
        self.native = Natives(self)   # 目录建好之后才能造它

    # ------------------------------------------------------------------ 起

    async def start(self) -> None:
        self.cdp.on("Target.attachedToTarget", self._on_attached)
        self.cdp.on("Inspector.targetCrashed", self._on_crashed)
        self.cdp.on("Runtime.bindingCalled", self._on_binding)
        await self.view.start()
        await self.native.attach()
        await self.tabs.start()
        await asyncio.sleep(0.3)               # 让已存在的 target 都进来
        self.log.append("session", event="session_started")
        if not len(self.tabs):
            await self.tabs.open("about:blank")

    def _on_attached(self, params: dict, _sid: str | None) -> None:
        info = params.get("targetInfo", {})
        sid = params["sessionId"]
        waiting = bool(params.get("waitingForDebugger"))
        if info.get("type") != "page":
            # **worker / service worker 立刻放行。** 它们也会被 autoAttach 暂停,
            # 而我们什么都不往里注 —— 不放行的话页面等它,整个卡住。
            if waiting:
                asyncio.create_task(self._resume(sid))
            return
        self._pending_sessions[info["targetId"]] = sid
        if waiting:
            self._waiting.add(sid)
            # **看门狗:没人放行也不能永远停着。**
            # 正常路径是 `executor_for()` 注入完就放;万一那条路没走到
            # (adopt 失败、异常),这里兜底放行并且**说出来** ——
            # 一个永远白着的 tab 查起来毫无线索。
            asyncio.create_task(self._resume_later(sid))

    async def _resume(self, sid: str) -> None:
        with contextlib.suppress(Exception):
            await self.cdp.send("Runtime.runIfWaitingForDebugger", session_id=sid)

    async def _resume_later(self, sid: str, delay: float = 5.0) -> None:
        await asyncio.sleep(delay)
        if sid in self._waiting:
            self._waiting.discard(sid)
            log.warning("没人放行这个 target,兜底放了(sid=%s)—— "
                        "注入那条路没走到,画面里的探针可能是缺的", sid[:8])
            await self._resume(sid)

    async def release(self, sid: str) -> None:
        """注入都做完了,放这个 target 跑。**这一句必须在最后。**"""
        if sid in self._waiting:
            self._waiting.discard(sid)
            await self._resume(sid)

    _pending_sessions: dict[str, str] = {}
    #: 还停着等我们放行的 target。
    _waiting: set[str] = set()

    #: 我们自己刚派发完动作的时间点。这之后这么久内的输入算我们的,不算人的。
    _SELF_WINDOW = 0.4

    def _on_binding(self, params: dict, sid: str | None) -> None:
        """页面报上来一次输入。**是人还是我们,靠相关性分**。"""
        if params.get("name") != probe.BINDING:
            return
        import json as _json
        try:
            info = _json.loads(params.get("payload") or "{}")
        except Exception:
            info = {}

        if info.get("kind") == "cursor":
            # 光标形状变了 —— 不是人的输入,不开让路窗口,也不进日志。
            #
            # **这一条必须在"是不是我们刚发的"之前判。** 光标恰恰是被
            # 我们派发的那次鼠标移动带出来的:观看者移鼠标 → 我们
            # `Input.dispatchMouseEvent` → 页面 `pointermove` → 探针上报。
            # 放在下面的话,**每一次都落在自窗口里被吃掉** ——
            # 于是画面上光标永远是箭头,而且一条错都没有。
            shape = cursor_probe.sanitize(info.get("cursor", ""))
            asyncio.create_task(
                self.view._send_all(models.CursorChanged(shape)))
            return

        if time.monotonic() - self._dispatched_at < self._SELF_WINDOW:
            return                          # 这是我们刚发的那一下
        self.note_human_activity(info.get("kind", "input"))
        tab_id = self._tab_of_session(sid)
        # 人干的**也进日志** —— 这样它才是完整的操作路径,不是"只有 API 干过的事"
        self.log.append("action", tab=tab_id, user="human",
                        action=info.get("kind", "input"),
                        target={"point": [info.get("x"), info.get("y")]},
                        hit={"role": info.get("role"), "name": info.get("name")}
                             if info.get("name") else None,
                        ok=True, ms=0)

    # 弹窗的拦截、超时和记账搬到 `native/dialogs.py` 了 —— v1 只做了"记在 tab 上",
    # 而 v2 没有桌面兜底,还得有事件、超时和日志(works/06 §1)。

    def _tab_of_session(self, sid: str | None) -> str | None:
        if not sid:
            return None
        for tab_id, s in self._sessions.items():
            if s == sid:
                return tab_id
        return None

    def _on_crashed(self, _params: dict, _sid: str | None) -> None:
        self.restarts += 1
        self.log.append("session", event="chrome_restarted", restarts=self.restarts)
        self._emit("chrome.restarted", {"restarts": self.restarts})

    async def close(self) -> None:
        await self.view.close()
        for ex in self._exec.values():
            ex.stop()
        self._exec.clear()

    # ------------------------------------------------------------- 事件流

    def _emit(self, type_: str, payload: dict) -> None:
        evt = {"seq": self.seq.next(), "at": _now(), "type": type_, **payload}
        self._recent.append(evt)
        if len(self._recent) > self._recent_cap:
            self._recent = self._recent[-self._recent_cap:]
        for q in list(self._subscribers):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(evt)

        # **`active` 就是 screencast 挂在哪个 target 上**(works/05 §2)——
        # 所以 active 一变,画面必须跟着搬,否则观看者看到的是黑屏。
        if type_ in ("tab.activated", "tab.closed") and self.view.viewers:
            asyncio.create_task(self.view.follow(self.tabs.active))

        # tab 的生死落盘 —— 事件只在内存里活 1000 条,重启就没了(api/log.md §3)
        if type_ == "tab.created":
            tab = payload.get("tab", {})
            self.log.append("tab", event="opened", tab=tab.get("id"),
                            url=tab.get("url"), title=tab.get("title"),
                            reason=payload.get("reason"), opener=tab.get("opener"))
        elif type_ == "tab.closed":
            self.log.append("tab", event="closed", tab=payload.get("id"),
                            final_url=payload.get("final_url"),
                            reason=payload.get("reason"))
            # tab 没了,它那些 `@e1` 也就没了。**`next_n` 不回退** ——
            # 回退等于重用,而那正是这张表要防的事(models.RefTable)。
            self.refs.forget(str(payload.get("id") or ""))

    def subscribe(self, after: int | None = None) -> tuple[asyncio.Queue, list[dict]]:
        """订事件。`after` 给了就先把那之后的补上;补不齐先发 `gap`。"""
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subscribers.add(q)
        backlog: list[dict] = []
        if after is not None:
            have = [e for e in self._recent if e["seq"] > after]
            oldest = self._recent[0]["seq"] if self._recent else after + 1
            if oldest > after + 1:
                # **收到 gap 就该重新拉全量,不要假装没丢**(api/events)
                backlog.append({"seq": self.seq.current, "at": _now(), "type": "gap",
                                "from": after, "to": oldest - 1})
            backlog += have
        return q, backlog

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def note_human_activity(self, kind: str = "input") -> None:
        """人在 VNC 里动了 —— 开让路窗口。

        **靠相关性判断**:sessiond 知道自己刚派发了什么(它握着动作锁),
        对不上的输入就是人的。窗口边界上会误判,代价只是日志署错名或者
        让路窗口早开晚开一点,不影响正确性(works/06 §3.2)。
        """
        was_idle = not self.human_active
        self._human_at = time.monotonic()
        if was_idle:
            self._emit("human.active", {"kind": kind})

    @property
    def human_active(self) -> bool:
        return (self._human_yield > 0
                and time.monotonic() - self._human_at < self._human_yield)

    # ------------------------------------------------------------- tab 接线

    async def executor_for(self, tab_id: str) -> Executor:
        ex = self._exec.get(tab_id)
        if ex is not None:
            return ex
        tab = self.tabs.get(tab_id)
        sid = self._pending_sessions.get(tab.target_id)
        if sid is None:
            r = await self.cdp.send("Target.attachToTarget",
                                    {"targetId": tab.target_id, "flatten": True})
            sid = r["sessionId"]
        self._sessions[tab_id] = sid
        ex = Executor(self.cdp, sid, secrets=self.secrets,
                      refs=self.refs, tab_id=tab_id)
        await ex.start()
        # **popup 一律转成 tab**(works/07 §4)—— 装在页面层,
        # 因为只有页面自己调原生 open 才能保住 opener 关系。
        # **Runtime 域先开、binding 先装** —— 页面里那三样探针都靠它往回报,
        # 而 `bindingCalled` 只在域开着时才推(probe.enable 的 docstring)
        await probe.enable(self.cdp, sid)
        await probe.install(self.cdp, sid)
        await probe.install_input_watch(self.cdp, sid)
        await cursor_probe.install(self.cdp, sid)
        # **DOM 那条画面的记录器也在这儿装。**
        # 注入只对**之后的文档**生效 —— 等第一个观看者连上再装就晚了,
        # 那时页面早加载完,记录器一个事件都发不出来
        # ([c §9.4](../docs/v2/works/c-view.md#94-切到-dom-要先把记录器注进去))。
        # 这个坑刚踩过:观看端收得到 hello/cast,dom 事件是 0。
        if getattr(self.view, "dom", None) is not None:
            await self.view.dom.arm(self.cdp, sid)
        await self.native.attach_target(sid)
        self._exec[tab_id] = ex
        # **注入全做完才放行。** 在这之前页面一行都还没跑 ——
        # 这就是那个竞态的解法:不是"抢在导航前面",是"页面根本还没开始"。
        await self.release(sid)
        return ex

    async def cdp_session_for(self, tab_id: str) -> str:
        """这个 tab 的 CDP sessionId,没 attach 过就现 attach。

        `view/` 要它来发 `Page.startScreencast` 和 `Input.*`。走的是和动作
        完全相同的那条 attach 路径 —— **画面和操作打在同一个 session 上**。
        """
        await self.executor_for(tab_id)
        return self._sessions[tab_id]

    def resolve_tab(self, tab_id: str | None) -> str:
        """不传就是当前激活的那个 —— 线上才需要这条规则,因为 HTTP 没有句柄
        (api/README §2)。"""
        if tab_id:
            self.tabs.get(tab_id)              # 不在就抛 TabGone
            return tab_id
        if not self.tabs.active:
            raise TabGone("一个 tab 都没有", code="tab_gone",
                          details={"reason": "closed"})
        return self.tabs.active

    async def open_tab(self, url: str = "about:blank", *, activate: bool = True,
                       wait: str = "load", timeout: float = 15.0):
        """建 tab + 导航 + **等到页面可用**。

        `POST /api/tabs {url}` 建完就返回的话,调用方紧接着 click 必然点空 ——
        而"开个新标签页去某个网址"本来就是一件事(works/06 §1),
        那就该像 `goto` 一样默认 `wait=load`。
        """
        tab = await self.tabs.open(url, activate=activate)
        if wait != "none" and url and url != "about:blank":
            with contextlib.suppress(Exception):
                ex = await self.executor_for(tab.id)
                await ex.run([{"type": "wait_for", "url_contains": "",
                               "timeout_ms": 50}])
                await self._wait_ready(tab.id, timeout)
                await self.refresh_tab(tab.id)
        return tab

    async def refresh_tab(self, tab_id: str) -> None:
        """从页面里把 url/title 拿准,不等 `targetInfoChanged`。

        **响应要是权威的**:调用方拿到 201 就该能读 title,而不是再去等一条事件
        (和"动作响应回灌内存"是同一条原则,sdk/README §3)。
        """
        sid = self._sessions.get(tab_id)
        if not sid:
            return
        with contextlib.suppress(Exception):
            r = await self.cdp.send(
                "Runtime.evaluate",
                {"expression": "JSON.stringify([document.title, location.href])",
                 "returnByValue": True}, session_id=sid, timeout=5)
            import json as _json
            title, url = _json.loads(r["result"]["value"])
            self.tabs.update(tab_id, title=title, url=url)

    async def _wait_ready(self, tab_id: str, timeout: float) -> None:
        sid = self._sessions.get(tab_id)
        if not sid:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                r = await self.cdp.send(
                    "Runtime.evaluate",
                    {"expression": "document.readyState", "returnByValue": True},
                    session_id=sid, timeout=5)
                if r["result"].get("value") in ("interactive", "complete"):
                    return
            except Exception:
                return
            await asyncio.sleep(0.05)

    async def bring_to_front(self, tab_id: str) -> bool:
        """**要像素就得在前台。** 返回是否真的切了(响应里要说)。"""
        if self.tabs.active == tab_id:
            return False
        await self.tabs.activate(tab_id)
        return True

    # ---------------------------------------------------------------- 动作

    async def act(self, *, tab: str | None, actions: list[dict],
                  settle: dict | None = None, note: str | None = None,
                  user: str = "api") -> dict[str, Any]:
        if self.human_active:
            left = int((self._human_yield - (time.monotonic() - self._human_at)) * 1000)
            raise BusyHuman("人正在操作", code="busy_human",
                            details={"retry_after_ms": max(0, left)})
        if self._action_lock.locked():
            # **不排队、不交错** —— 排队会让"谁先点"变得不可预测
            raise Busy("已有动作在跑", code="busy", details={})

        tab_id = self.resolve_tab(tab)
        dialog = self.tabs.get(tab_id).dialog
        if dialog:
            # **不自动回应** —— 该点确定还是取消是调用方的判断(api/tabs.md §3)
            raise Busy(f"这个 tab 被 {dialog.get('kind')} 弹窗挡住了",
                       code="busy", details={"dialog": dialog})
        async with self._action_lock:
            self.tabs.mark_busy(tab_id)
            try:
                ex = await self.executor_for(tab_id)
                self._dispatched_at = time.monotonic()
                results = await ex.run(actions, settle=settle)
                self._dispatched_at = time.monotonic()
            finally:
                self.tabs.mark_idle(tab_id)

        log_from = None
        background = tab_id != self.tabs.active
        for r in results:
            self._emit("action.started", {"tab": tab_id, "action": r.action,
                                          "target": r.target, "note": note,
                                          "user": user})
            seq = self.log.append(
                "action", tab=tab_id, user=user, note=note, action=r.action,
                target=_mask(r.target), hit=r.hit, ok=r.ok, ms=r.ms,
                after=r.after or None, error=r.error, message=r.message,
                background=background or None, opaque=r.opaque or None)
            log_from = log_from or seq
            self._emit("action.done", {"seq": seq, "tab": tab_id, "ok": r.ok,
                                       "ms": r.ms, "hit": r.hit, "after": r.after})
            self._emit("log.appended", {"entry": {"seq": seq, "kind": "action"}})

        out: dict[str, Any] = {"results": [r.to_json() for r in results]}
        if log_from:
            out["log_from"] = log_from
        return out

    async def read(self, tab: str | None = None) -> tuple[str, bytes]:
        """读一眼:**正文和一张图,就这两样。**

        **要像素就得在前台** —— Chromium 不渲染后台 tab,拍出来是白的或旧的。
        所以这一下会切 tab,而且它**改状态**
        ([issue](../docs/v2/issues/读一眼会改状态却不排队.md))。
        """
        sid = await self._reading_session(tab)
        return await capture.text(self.cdp, sid), await capture.screenshot(self.cdp, sid)

    async def snapshot(self, tab: str | None = None, *,
                       interactive_only: bool = False,
                       selector: str | None = None,
                       viewport_only: bool = False,
                       max_elements: int = locate.MAX_ELEMENTS) -> Snapshot:
        """这一页上有什么 —— **并且给每一样发一个跨命令能用的号**。

        `read()` 回的是正文和一张图,答的是"人看到了什么";
        这一个答的是"程序能抓到什么",两者都要。

        **不切 tab。** 和 `read()` 不一样:AX 树不需要那个 tab 在前台
        (要像素才需要),所以这一下**不改状态**
        ([那条 issue](../docs/v2/issues/读一眼会改状态却不排队.md)在这儿不适用)。
        """
        tab_id = self.resolve_tab(tab)
        if self._sessions.get(tab_id) is None:
            await self.executor_for(tab_id)
        sid = self._sessions[tab_id]
        snap = await locate.snapshot(
            self.cdp, sid, max_elements=max_elements,
            viewport_only=viewport_only, interactive_only=interactive_only,
            selector=selector)
        # **号要绑住当时那份文档**,不然页面一换旧号可能指到别的东西上
        # ([models.RefTable](models.py))。
        self.refs.assign(snap.elements, tab_id, await locate.document_id(self.cdp, sid))
        return snap

    async def _reading_session(self, tab: str | None) -> str:
        tab_id = self.resolve_tab(tab)
        await self.bring_to_front(tab_id)          # 要像素就得在前台
        if self._sessions.get(tab_id) is None:
            await self.executor_for(tab_id)
        return self._sessions[tab_id]

    def mint_token(self, *, read_only: bool = True, ttl_s: int = 3600) -> str:
        """一次性观看 token。

        **默认只读** —— 和 API、CLI、ttyd 的默认一致。可操作的链接
        能碰调用方所有登录态,那得显式要。
        """
        import secrets as _secrets
        tok = _secrets.token_urlsafe(24)
        self._tokens[tok] = (read_only, time.time() + ttl_s)
        return tok

    def check_token(self, tok: str) -> tuple[bool, bool]:
        """→ (认不认, 是不是只读)。过期的当场清掉。"""
        got = self._tokens.get(tok)
        if not got:
            return False, True
        read_only, expires = got
        if time.time() > expires:
            del self._tokens[tok]
            return False, True
        return True, read_only

    def status(self) -> dict[str, Any]:
        return {
            "ok": True,
            "chrome": {"alive": not self.cdp.closed, "restarts": self.restarts},
            "active_tab": self.tabs.active, "tab_count": len(self.tabs),
            "uptime_s": int(time.time() - self.started_at),
            "log_count": self.log.count(),
            "busy": self._action_lock.locked(),
            "api": {"version": "1.0", "schema": "v1"},
        }


def _mask(target: dict | None) -> dict | None:
    """凭证不进日志 —— 执行层已经换过一次,这里是最后一道(api/act.md §3.1)。"""
    if not target:
        return target
    out = dict(target)
    if "text_ref" in out:
        out.pop("text_ref")
        out["text"] = MASK
    return out


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def resolve_transport(explicit: str | None) -> str:
    """没显式说的时候用哪种画面。**默认 VNC。**

    VNC(xpra)按 damage 区域编码,滚动时 `scroll` 包零字节搬像素 ——
    实测滚一页 Wikipedia,57% 的重绘面积没花一个字节
    ([c §4.1](../docs/v2/works/c-view.md#41-它强在哪以及它的劣势区))。
    这是默认值该给的东西。

    **起不来就抛,不自己换一种。** 静默换等于让你以为自己在看 VNC 的画质,
    而那正是"不可用时抛,不降级"要防的事。退路是**显式说一声**
    ([c §9.5](../docs/v2/works/c-view.md#95-切了必须说出来))。
    """
    if explicit is not None:
        m = models.canon(explicit)
        if m is None:
            raise UsageError(
                f"没有 {explicit!r} 这种画面,只有 "
                + " / ".join(models.label(x) for x in models.MODES)
                + " —— JPG 什么都显示得出来,VNC 连续跟手,DOM 字最清楚最省流量",
                details={"got": explicit, "choices": list(models.MODES)})
        return m
    ok, why = xpra_mod.available()
    if ok:
        return models.VNC
    raise unavailable(
        "process", f"默认走 VNC,但这台机器起不来:{why}",
        "装上:`webmuxd install`(有 root 就自动装,没 root 会打出该跑的那行);"
        "不想装就显式说:`--transport jpg`(什么都显示得出来)"
        "或 `--transport dom`(字最清楚、最省流量)")


# --------------------------------------------------------------------------
# 两种 runtime —— **本机起一个,或者你给一个 CDP 端点**
#
# 进程怎么起、怎么等、怎么收,在 `processes.py`;这儿只决定**起哪一套**。
# 放在 sessions.py 是因为"要 VNC 就先起 xpra"是**会话的编排**,
# 而 `processes.py` 是第 1 层,不该认识 `xpra.py`
# ([j §5](../docs/v2/works/j-layout.md#5-依赖方向扁平之后层要靠规矩守))。
# --------------------------------------------------------------------------

class Runtime(Protocol):
    name: str

    def available(self) -> tuple[bool, str]:
        """能不能用,以及不能用时那句**有用的**提示。"""

    def start(self, id: str, **opts: Any) -> SessionInfo: ...

    def stop(self, handle: SessionInfo) -> None: ...

    def alive(self, handle: SessionInfo) -> bool: ...




class ProcessRuntime:
    name = "process"

    def available(self) -> tuple[bool, str]:
        try:
            processes.resolve_browser()
            return True, ""
        except Exception as e:
            return False, str(e)

    def start(self, id: str, *, url: str = "about:blank",
              window_size: str = "", browser_path: str | None = None,
              proxy: str | None = None, data_dir: str | None = None,
              dsf: float = 1.0, view: dict[str, Any] | None = None,
              transport: str | None = None, **_opts: Any) -> SessionInfo:
        """起一个浏览器,**产出一个 CDP 端点**。

        它不再起 sessiond —— 那个进程没有了,server 自己就是
        ([k §5](../docs/v2/works/k-one-server.md#5-一个进程还是每个-session-一个进程))。
        所以这儿也不再要 `port` / `bind` / `token`:那些是 server 的事。
        """
        asked = transport                      # 用户显式说的,还是默认来的
        transport = resolve_transport(transport)
        # **参数先对,再动机器。** 这一条和浏览器、端口都无关,放最前面 ——
        # 不静默吃掉一个明确给了的参数:dsf 靠的是 `--force-device-scale-factor`
        # 加上 screencast 的 maxWidth/maxHeight 一起乘
        # ([e1](../docs/v2/works/e1-wire-format.md)),而 xpra 那条路上
        # 没有 screencast —— 画面尺寸就是那个 X 显示的尺寸。
        # **给了却不起作用,比报错难查得多。**
        if transport == models.VNC and dsf and dsf != 1.0:
            # **说清 xpra 是你选的还是默认来的。** 没说要 xpra 的人被告知
            # "dsf 在 xpra 上没用",第一反应会是"我什么时候要 xpra 了"。
            which = "--transport vnc" if asked else "默认的 VNC"
            raise unavailable(
                "process", f"--dsf {dsf} 在 {which} 上没有用",
                "xpra 截的是那个 X 显示,倍率得由显示尺寸决定 —— "
                "把 --window-size 开大(比如 2048x1536)是等价的做法;"
                "要 dsf 就用 --transport jpg")
        exe = processes.resolve_browser(browser_path)

        work = data_dir or tempfile.mkdtemp(prefix=f"webmuxd-{id}-")
        os.makedirs(work, exist_ok=True)
        cdp_port = processes.free_port()
        notes: list[str] = []

        # 以前镜像替用户扛掉的那些,现在落到裸机上 —— **明说,不静默**
        missing = config.missing_libs(exe)
        if missing:
            raise unavailable("process", f"浏览器缺共享库:{', '.join(missing[:6])}",
                              "跑 `webmuxd install --with-deps`(要 root),"
                              "或者自己 apt install 上面这些")
        if not config.has_cjk_font():
            notes.append(f"{config.FONT_HINT[1]} —— `{config.FONT_HINT[0]}`")

        if transport == models.VNC:
            return self._start_xpra(
                id, exe=exe, url=url, work=work, cdp_port=cdp_port,
                proxy=proxy, view=view or {}, notes=notes)

        args = [exe, *processes.BASE_ARGS,
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={os.path.join(work, 'profile')}"]
        # **root 下沙箱起不来,这不是选择题。**
        #
        # Chromium 硬拒绝:`Running as root without --no-sandbox is not supported`
        # (crbug 638180)。所以 root + 沙箱**没有能跑的配置** —— 报错让人自己去
        # 查,等于把一个无解的选择丢回去。
        #
        # 而且我们自己推荐的隔离路子(把 webmuxd 装进容器,[works/07 §2])
        # 默认就是 root。所以这儿自动加上,**但要说出来**:
        # 关掉的是安全特性,不能悄悄关。
        as_root = hasattr(os, "geteuid") and os.geteuid() == 0
        if as_root or os.environ.get("WEBMUXD_NO_SANDBOX"):
            args.append("--no-sandbox")
        if as_root and not os.environ.get("WEBMUXD_NO_SANDBOX"):
            notes.append("你是 root —— Chromium 在 root 下必须 --no-sandbox 才起得来"
                         "(crbug 638180),已经替你加上了。**沙箱是关着的**;"
                         "想要它就换个非 root 用户跑")
        if window_size:
            args.append(f"--window-size={window_size.replace('x', ',')}")
        # **只有这条能让 screencast 按 2x 出图。** `Emulation` 里那个
        # `deviceScaleFactor` 对 screencast 完全无效 —— demo 实测过
        # ([e1](../docs/v2/works/e1-wire-format.md))。
        if dsf and dsf != 1.0:
            args.append(f"--force-device-scale-factor={dsf}")
        if proxy:
            args.append(f"--proxy-server={proxy}")
        args.append(url)

        # **浏览器的 stderr 不能扔。** 它起不来的原因就写在里面(root 没关沙箱、
        # 缺共享库、profile 目录不能写……),扔掉之后我们只能让人"手工跑一遍看
        # 报什么" —— 那等于把排查工作原样退回去。0.5.2 之前就是这样。
        log_path = os.path.join(work, "chrome.log")
        procs: dict[str, subprocess.Popen] = {}
        with open(log_path, "wb") as log:
            procs["browser"] = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=log,
                start_new_session=True)
        if not processes.wait_port(cdp_port, 30, proc=procs["browser"]):
            why = processes._tail(log_path)
            # **先说清是哪一种。** 进程还在但没监听,和进程已经退了,
            # 是两件完全不同的事:前者查端口/参数,后者看它临死说了什么。
            # 说错方向的那一句会把人带得很远。
            died = procs["browser"].poll() is not None
            head = ("浏览器起不来,已经退了" if died
                    else "浏览器还在跑,但 CDP 没监听")
            processes._kill_all(procs)
            raise unavailable(
                self.name, head + (f":{why}" if why else ""),
                f"完整日志在 {log_path};手工跑一遍:{' '.join(args[:3])} …")

        return SessionInfo(self.name, id, {
            "cdp": f"http://127.0.0.1:{cdp_port}",
            "cdp_port": cdp_port, "work": work, "browser": exe,
            # **画面模式必须跟着走。** 漏了这一个键踩过一次:
            # `--transport dom` 一路顺利地起来了,而画面用的是默认的 jpg ——
            # 观看端收得到 hello/cast,DOM 事件一条没有,**全程不报错**。
            "view": {**(view or {}), "dsf": dsf, "transport": transport},
            "pids": {k: p.pid for k, p in procs.items()},
            "notes": notes, "_procs": procs})

    # ------------------------------------------------------------------ xpra

    def _start_xpra(self, id: str, *, exe: str, url: str, work: str,
                    cdp_port: int, proxy: str | None, view: dict[str, Any],
                    notes: list[str]) -> SessionInfo:
        """xpra 那条画面路 —— docs/v2/works/11 · 12。

        和上面那条的差别**只有像素从哪来**,所以这儿只多做两件事:
        起 xpra(它顺带拉起 Xvfb 和一个**有头的** chrome),
        然后把上游那个 ws 地址交给 sessiond 去代理。
        """
        w = int(view.get("width") or 1024)
        h = int(view.get("height") or 768)
        display = xpra_mod.free_display()
        ws_port = processes.free_port()
        as_root = hasattr(os, "geteuid") and os.geteuid() == 0
        chrome_argv = xpra_mod.build_chrome_argv(
            exe, cdp_port=cdp_port, profile=os.path.join(work, "profile"),
            url=url, width=w, height=h, proxy=proxy,
            no_sandbox=as_root or bool(os.environ.get("WEBMUXD_NO_SANDBOX")))
        if as_root and not os.environ.get("WEBMUXD_NO_SANDBOX"):
            notes.append("你是 root —— Chromium 在 root 下必须 --no-sandbox 才起得来"
                         "(crbug 638180),已经替你加上了。**沙箱是关着的**")

        sess = xpra_mod.start(display=display, ws_port=ws_port, cdp_port=cdp_port,
                              chrome_argv=chrome_argv, width=w, height=h, work=work)
        # Xvfb + xpra + 有头 chrome,比 headless 那条慢不少 —— 给足时间
        if not processes.wait_port(cdp_port, 60, proc=sess.proc):
            why = xpra_mod.tail(sess.log_path)
            # **先看 xpra 自己还在不在。**
            #
            # 原来这儿一律说"xpra 起来了但浏览器的 CDP 没监听",而真实情况
            # 常常是虚拟显示压根没起来、xpra 自己就退了 —— 那句话把人往
            # 浏览器的方向指,而问题在 X 那一层。**头一句话指错方向,
            # 后面的日志再全也白搭。**
            died = sess.proc.poll() is not None
            head = ("xpra 自己退了 —— 多半是虚拟显示没起来" if died
                    else "xpra 在跑,但浏览器的 CDP 没监听")
            xpra_mod.stop(sess)
            raise unavailable(self.name, head + (f":{why}" if why else ""),
                              f"完整日志在 {sess.log_path}")
        if not processes.wait_port(ws_port, 30, proc=sess.proc):
            xpra_mod.stop(sess)
            raise unavailable(self.name, "xpra 的 ws 口没起来",
                              f"日志在 {sess.log_path};{xpra_mod.tail(sess.log_path)}")

        return SessionInfo(self.name, id, {
            "cdp": f"http://127.0.0.1:{cdp_port}",
            "cdp_port": cdp_port, "work": work, "browser": exe,
            "transport": models.VNC, "display": display,
            "xpra_ws": sess.ws_url, "xpra_ws_port": ws_port,
            "xpra_log": sess.log_path,
            "view": {**view, "transport": models.VNC},
            "pids": {"xpra": sess.proc.pid},
            "notes": notes, "_xpra": sess})

    def stop(self, handle: SessionInfo) -> None:
        # **xpra 先停。** 它 `--exit-with-children`,而且 `xpra stop` 会把
        # Xvfb 和那个有头 chrome 一起收干净。
        sess = handle.detail.get("_xpra")
        if sess is not None:
            xpra_mod.stop(sess)
        procs = handle.detail.get("_procs") or {}
        if procs:
            processes._kill_all(procs)
            return
        for pid in (handle.detail.get("pids") or {}).values():
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)

    def alive(self, handle: SessionInfo) -> bool:
        """**浏览器还在不在。** 它是这条 runtime 唯一起的东西了。"""
        sess = handle.detail.get("_xpra")
        if sess is not None:
            return sess.proc.poll() is None
        p = (handle.detail.get("_procs") or {}).get("browser")
        if p is not None:
            return p.poll() is None
        pid = (handle.detail.get("pids") or {}).get("browser")
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False




# --------------------------------------------------------------------------
# remote:端点是你给的(原 runtime/remote.py)
# --------------------------------------------------------------------------

class RemoteRuntime:
    name = "remote"

    def available(self) -> tuple[bool, str]:
        return True, ""

    def start(self, id: str, *, cdp: str | None = None,
              data_dir: str | None = None, view: dict[str, Any] | None = None,
              transport: str | None = None, **_opts: Any) -> SessionInfo:
        # **remote 上能用 JPG 和 DOM,不能用 VNC。**
        # VNC 要截的是那个浏览器所在机器上的 X 显示,而 remote 的浏览器根本
        # 不在这台机器上 —— 我们手里只有一个 CDP 端点。
        # **少一个选项不是降级,是这条路上的全集**
        # ([c §9.3](../docs/v2/works/c-view.md#93-能切到哪几条起-session-的时候就定了))。
        allowed = models.available_in(headed=False, remote=True)
        transport = models.canon(transport) or models.JPG
        # **不静默忽略。** 悄悄给一个 JPG 的画面,等于让人以为自己在看 VNC 的画质。
        if transport not in allowed:
            raise unavailable(
                self.name,
                f"runtime=remote 上没有 {models.label(transport)} 这种画面",
                f"这条路上只有 {' / '.join(models.label(m) for m in allowed)} —— "
                "VNC 要截浏览器所在机器上的 X 显示,而 remote 的浏览器不在这儿,"
                "我们手里只有一个 CDP 端点。"
                "要 VNC 就在那台机器上直接跑 webmuxd")
        if not cdp:
            raise unavailable(self.name, "runtime=remote 得给 cdp=",
                              "cdp 指向对面那个浏览器的 CDP 端点,"
                              "http://host:port 或 ws://…")
        # `http://` 的先探一下,**探不到就直说** —— 等接上去才发现连不上,
        # 报的错会指向我们自己而不是那个端点。
        # `ws://` 没有可探的 HTTP 面,交给连接那一步。
        if cdp.startswith("http") and not processes.wait_http(cdp.rstrip("/") + "/json/version", 10):
            raise unavailable(self.name, f"{cdp} 探不到",
                              "确认对面在跑,而且这台机器连得上")

        work = data_dir or tempfile.mkdtemp(prefix=f"webmuxd-{id}-")
        os.makedirs(work, exist_ok=True)
        return SessionInfo(self.name, id, {
            "cdp": cdp, "work": work, "owned_browser": False,
            "view": {**(view or {}), "transport": transport}})

    def stop(self, handle: SessionInfo) -> None:
        """**对面一个字节都不动。** 那个浏览器不归我们 ——
        我们这边要收的连接由 `Server.close()` 关掉了,这儿没有进程要杀。"""

    def alive(self, handle: SessionInfo) -> bool:
        """对面还在不在。"""
        cdp = handle.detail.get("cdp") or ""
        if not cdp.startswith("http"):
            return True                        # ws:// 没有可探的 HTTP 面
        return processes.wait_http(cdp.rstrip("/") + "/json/version", 3)


# --------------------------------------------------------------------------
# 起本机还是连 remote —— 就是一个 if(原 runtime/__init__.py)
# --------------------------------------------------------------------------

_MAKERS = {"process": ProcessRuntime, "remote": RemoteRuntime}

#: **本机起一个就是默认。** v1 选 container 的三个理由里,"用户不用装浏览器"
#: 被 `webmuxd install` 接走了,"有画面"被 CDP 接走了,只剩隔离 ——
#: 而隔离不是我们的活(works/07 §5)。
DEFAULT = "process"


def default() -> str:
    return DEFAULT


def get(name: str = DEFAULT) -> Runtime:
    try:
        return _MAKERS[name]()
    except KeyError:
        raise unavailable(name, f"没有 {name!r} 这种 runtime",
                          f"只有 {', '.join(_MAKERS)}"
                          "(容器那条 v2 去掉了,见 docs/v2/works/07 §2)") from None


def detect() -> dict[str, bool]:
    """哪些能用。`remote` 永远能用(端点是你给的),`process` 看有没有浏览器。"""
    out = {}
    for name, make in _MAKERS.items():
        try:
            out[name] = make().available()[0]
        except Exception:
            out[name] = False
    return out


__all__ = ["get", "detect", "default", "DEFAULT", "SessionInfo", "Runtime",
           "ProcessRuntime", "RemoteRuntime"]


# --------------------------------------------------------------------------
# server —— **一个 server 持有全部 session**([k](../docs/v2/works/k-one-server.md))
# --------------------------------------------------------------------------

class Server:
    """所有 session 的那张表:建一个、找一个、关一个。

    **一个进程持有全部 session**,不是"每个 session 一个 sessiond 再代理" ——
    那样每一帧多一跳,而帧是热路径
    ([k §5](../docs/v2/works/k-one-server.md#5-一个进程还是每个-session-一个进程))。

    代价说清楚:**这个进程挂了,所有 session 的连接和 tab 表一起没。**
    和 tmux 一样(`process` 的 pane 是 server 的子进程)。
    """

    def __init__(self, *, data_root: str | Path, bind: str = "127.0.0.1") -> None:
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.bind = bind
        self.started_at = time.time()
        self._sessions: dict[str, Session] = {}
        self._info: dict[str, SessionInfo] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ 查

    def __contains__(self, sid: str) -> bool:
        return sid in self._sessions

    def __len__(self) -> int:
        return len(self._sessions)

    def get(self, sid: str) -> Session:
        """**认不出的 id 就抛,不猜。**"""
        s = self._sessions.get(sid)
        if s is None:
            raise SessionNotFound(
                f"没有叫 {sid!r} 的 session",
                code="session_not_found",
                details={"have": sorted(self._sessions)})
        return s

    def info(self, sid: str) -> SessionInfo:
        return self._info[sid]

    def rows(self) -> list[models.SessionRow]:
        """有哪些 —— **列表页、`webmuxd ls`、`GET /api/sessions` 同一份**。

        形状在 [`models.SessionRow`](models.py),JS 那边有个同名 interface
        跟它对齐。
        """
        out = []
        for sid in sorted(self._sessions):
            s, i = self._sessions[sid], self._info[sid]
            out.append(models.SessionRow(
                id=sid, runtime=i.kind, tabs=len(s.tabs.list()),
                active_tab=s.tabs.active, view=s.view.mode,
                available=list(s.view.available),
                uptime_s=int(time.time() - s.started_at),
                notes=i.detail.get("notes") or []))
        return out

    def list_json(self) -> dict[str, Any]:
        return {"sessions": [r.to_json() for r in self.rows()],
                "uptime_s": int(time.time() - self.started_at)}

    # ------------------------------------------------------------------ 建

    async def create(self, sid: str, *, runtime: str = DEFAULT,
                     **opts: Any) -> SessionInfo:
        """起一个 session:runtime 给一个 CDP 端点,我们在这个进程里接上它。

        **同一个 id 再来一次不是错误** —— 已经在跑就把它给你,
        和 `tmux new -A` 一个意思。
        """
        async with self._lock:
            if sid in self._sessions:
                return self._info[sid]

            work = self.data_root / sid
            info = get(runtime).start(sid, data_dir=str(work), **opts)
            cdp = None
            try:
                cdp = await CDP.connect(info.detail["cdp"])
                session = Session(cdp, data_dir=work / "data", view={
                    **(info.detail.get("view") or {}),
                    "has_xpra": bool(info.detail.get("xpra_ws"))})
                await session.start()
            except Exception:
                # **起了一半要收干净。** 留下一个连不上的 chrome,
                # 下一次 `new` 会撞上那个 profile 目录,报的是完全不相干的错。
                if cdp is not None:
                    with contextlib.suppress(Exception):
                        await cdp.close()
                with contextlib.suppress(Exception):
                    get(runtime).stop(info)
                raise
            self._sessions[sid] = session
            self._info[sid] = info
            log.info("session %s 起来了(%s,画面走 %s)",
                     sid, info.kind, session.view.mode)
            return info

    def adopt(self, sid: str, session: Session,
              info: SessionInfo | None = None) -> None:
        """接管一个**已经建好**的 session。

        `create()` 那条路是"我起浏览器、我连上去";这条是"东西已经在了,
        挂进表里"。今天只有测试用它 —— 但 v1 设想过的"server 重启后
        按标记重新收养"([k §5](../docs/v2/works/k-one-server.md#5-一个进程还是每个-session-一个进程))
        要落地的话,进来的也是这个口子。
        """
        self._sessions[sid] = session
        self._info[sid] = info or SessionInfo("adopted", sid, {})

    # ------------------------------------------------------------------ 关

    async def close(self, sid: str) -> None:
        async with self._lock:
            session = self._sessions.pop(sid, None)
            info = self._info.pop(sid, None)
            if session is None or info is None:
                raise SessionNotFound(f"没有叫 {sid!r} 的 session",
                                      code="session_not_found")
        with contextlib.suppress(Exception):
            await session.close()
        with contextlib.suppress(Exception):
            await session.cdp.close()
        get(info.kind).stop(info)
        log.info("session %s 关了", sid)

    async def close_all(self) -> None:
        """`kill-server`。**一个都不许留** —— 留下的是没人管的 chrome。"""
        for sid in list(self._sessions):
            with contextlib.suppress(Exception):
                await self.close(sid)
