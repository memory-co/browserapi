"""一个 session 的编排层 —— 把引擎那几块接起来。

**这一层没有业务逻辑**,业务在 `core/` 里。它管的是那些"跨模块才成立"的规矩:

- **一个 session 同时只跑一个动作**,并发调返回 `409 busy`,不排队、不交错。
- **要像素就得在前台**:`observe` / `screenshot` 指向非激活 tab 时先切过去 ——
  Chromium 不渲染后台 tab,拍出来是白的或旧的(sdk/tab/read.md §3)。
- **`seq` 一个计数器**,日志和事件共用,所以两边对得齐。
- **凭证不进日志**:明文在执行层解开,记账时看到的是掩码。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any, Callable

from webmuxd.core import observe as observe_mod, shim
from webmuxd.core.act import MASK, Executor
from webmuxd.core.cdp import CDP
from webmuxd.core.log import Log, Seq
from webmuxd.core.observe import Observation
from webmuxd.core.tabs import TabTable
from webmuxd.errors import Busy, BusyHuman, TabGone
from webmuxd.native import Natives
from webmuxd.view import cursor as cursor_probe
from webmuxd.view.cast import Screencaster

#: 人在 VNC 里动过之后,API 让路多少毫秒(api/README §5)。0 = 关掉这个行为。
HUMAN_YIELD_MS = 3000


class Session:
    """sessiond 的核心对象。一个进程一个。"""

    def __init__(self, cdp: CDP, *, data_dir: str | Path = "/data",
                 tab_max: int | None = None, human_yield_ms: int = HUMAN_YIELD_MS,
                 secrets: Any = None) -> None:
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
        #: 画面。v2 里它是我们自己的([works/01](../../docs/v2/works/01-frame-source.md))
        self.view = Screencaster(self)
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
        #: ([works/06](../../docs/v2/works/06-no-desktop.md))
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
        if info.get("type") == "page":
            self._pending_sessions[info["targetId"]] = params["sessionId"]

    _pending_sessions: dict[str, str] = {}

    #: 我们自己刚派发完动作的时间点。这之后这么久内的输入算我们的,不算人的。
    _SELF_WINDOW = 0.4

    def _on_binding(self, params: dict, sid: str | None) -> None:
        """页面报上来一次输入。**是人还是我们,靠相关性分**。"""
        if params.get("name") != shim.BINDING:
            return
        if time.monotonic() - self._dispatched_at < self._SELF_WINDOW:
            return                          # 这是我们刚发的那一下
        import json as _json
        try:
            info = _json.loads(params.get("payload") or "{}")
        except Exception:
            info = {}
        if info.get("kind") == "cursor":
            # 光标形状变了 —— 不是人的输入,不开让路窗口,也不进日志
            shape = cursor_probe.sanitize(info.get("cursor", ""))
            asyncio.create_task(self.view._tell_all("cursor", cursor=shape))
            return
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
        ex = Executor(self.cdp, sid, secrets=self.secrets)
        await ex.start()
        # **popup 一律转成 tab**(works/07 §4)—— 装在页面层,
        # 因为只有页面自己调原生 open 才能保住 opener 关系。
        await shim.install(self.cdp, sid)
        await shim.install_input_watch(self.cdp, sid)
        await cursor_probe.install(self.cdp, sid)
        await self.native.attach_target(sid)
        self._exec[tab_id] = ex
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

    async def observe(self, *, tab: str | None = None, **kw: Any) -> Observation:
        tab_id = self.resolve_tab(tab)
        activated = await self.bring_to_front(tab_id)   # 要像素就得在前台
        ex_sid = self._sessions.get(tab_id)
        if ex_sid is None:
            await self.executor_for(tab_id)
            ex_sid = self._sessions[tab_id]
        obs = await observe_mod.observe(
            self.cdp, ex_sid, tab=tab_id, tabs=self.tabs.list_json()["tabs"], **kw)
        if activated:
            obs.notes.append("为了拍这张图,这个 tab 被切到了前台")
        return obs

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
