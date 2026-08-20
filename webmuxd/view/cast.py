"""画面自己产 —— `Page.startScreencast` 那一头。

docs/v2/works/01-frame-source.md 的落地。三条规矩,每一条都有实测撑着:

**① 环 A 无条件立刻回。** `Page.screencastFrameAck` 是 CDP 的流控,不回 Chromium
就不再产帧。把它和客户端的 ack 串起来,一个慢客户端能**把整条流拖死**
([02 §2](../../docs/v2/works/02-frame-protocol.md))。

**② `active` 就是 screencast 挂在哪个 target 上。** 后台 tab 不产帧
(本轮实测:三个 tab 同开,前台 41 帧,另两个各 0 帧),所以**帧本身就是
active 的证据**,漂移在物理上不可能 —— 真漂了就是黑屏,立刻可见
([05 §2](../../docs/v2/works/05-active-tab.md))。

**③ 切 tab 用显式 stop → activate → start。** 还有一种"全都开着只发 activate"
的写法,实测延迟一样(14–39 ms),但它把正确性押在"后台 tab 不产帧"这条
**实现细节**上 —— 那是 Chromium 的渲染器节流策略,不是 CDP 的契约。
延迟没差别,就选不押注的那个([05 §3](../../docs/v2/works/05-active-tab.md))。

没人看的时候整条流是停的 —— screencast 在第一个观看者进来时才开。
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from webmuxd.errors import BadRequest
from webmuxd.view import modes
from webmuxd.view.input import Translator
from webmuxd.view.protocol import build_header
from webmuxd.view.quality import Adaptor
from webmuxd.view.viewer import Viewer

if TYPE_CHECKING:                                    # pragma: no cover
    from webmuxd.serve.session import Session

log = logging.getLogger("webmuxd.view")

#: 默认视口。和 v1 保持一致(CHANGELOG 0.3.0)。
DEFAULT_W, DEFAULT_H = 1024, 768
#: `jpeg` / `png` / `webp` —— 实测只有这三种,`avif` / `bmp` 会被拒。
#: **默认 jpeg,不按内容自动切**(02 §4①)。
DEFAULT_FORMAT = "jpeg"
DEFAULT_QUALITY = 80


class Screencaster:
    """一个 session 一份画面,所有观看者看同一个 tab([05 §5](../../docs/v2/works/05-active-tab.md))。"""

    def __init__(self, session: "Session", *, width: int = DEFAULT_W,
                 height: int = DEFAULT_H, fmt: str = DEFAULT_FORMAT,
                 quality: int = DEFAULT_QUALITY, dsf: float = 1.0,
                 min_quality: int = 25, transport: str = modes.JPG,
                 has_xpra: bool = False) -> None:
        self.session = session
        #: **画面从哪来 —— 这是几种模式之间唯一的差别**
        #: ([c §7](../../docs/v2/works/c-view.md#7-接缝切在哪))。
        #:
        #: 不是 JPG 时这个类**照常干所有别的活**:跟着 tab 走(`Target.activateTarget`)、
        #: 收输入、发光标、管观看者名单 —— 只有 `Page.startScreencast` 那三行不发。
        #: 那条原则落到代码上就是下面几个 `if not self.own_frames: return`,
        #: 没有第二处分叉。
        self.mode = modes.canon(transport) or modes.JPG
        #: 画面归不归我们截。JPG 归;VNC 的来自 xpra,DOM 的来自页面里的记录器。
        self.own_frames = self.mode == modes.JPG
        #: 视口归不归我们定。**这和上面那条不是一回事** ——
        #: DOM 不用我们截图,但**视口必须由我们钉住**:重放出来的布局就是按它排的。
        #: 只有 VNC 不能设 —— 那边画面尺寸是 X 显示的尺寸,再 override 一次
        #: 会让页面被渲染成另一个尺寸而窗口不变,画面里一圈空白。
        self.own_viewport = self.mode != modes.VNC
        #: **这台 session 上能切到哪几种。**
        #: 不是"现在用哪种",是"以后能选哪几种" —— VNC 要真实的 X 显示,
        #: 无头浏览器没有,而有没有是起 session 时定的,运行时改不了。
        self.available = modes.available_in(headed=has_xpra or transport == modes.VNC)
        #: DOM 那条的事件源。别的模式下是 None。
        #: **在 `__init__` 里就建好,不能等 `start()`** —— tab 的 attach 可能
        #: 更早,那时 `self.dom` 还是 None,记录器就漏装了。
        #: 漏装的表现是:模式对、日志说装上了,而页面里 `typeof rrweb` 是
        #: `undefined`、事件一条没有,**全程不报错**。
        self.dom = None
        if self.mode == modes.DOM:
            from webmuxd.view.dom import DomSource
            self.dom = DomSource(push=self._tell_raw)
        self._warned_resize = False
        self.width, self.height = width, height
        self.format = fmt
        #: 渲染倍率。**只用来匹配观看端的 dpr,不是"越大越清晰"**
        #: ([02 §4③](../../docs/v2/works/02-frame-protocol.md))——dpr=1 的屏上
        #: dsf=2 实测锐度反而低 18%,还多花 2.6 倍带宽。
        #:
        #: 真正让它生效的是**浏览器启动参数** `--force-device-scale-factor`,
        #: 这儿只是跟着把 maxWidth/maxHeight 乘上去;漏了这一步 Chromium 会把
        #: 2x 的画面缩回 CSS 尺寸再编码,等于白做。
        self.dsf = dsf if dsf and dsf > 0 else 1.0
        self.viewers: set[Viewer] = set()
        self.adaptor = Adaptor(quality, lossless=(fmt == "png"),
                               floor=min_quality)

        self._tab: str | None = None          # 正在截的 tab
        self._sid: str | None = None          # 它的 CDP sessionId
        self._cast_id = 0                     # 每次 start 递增
        self._frame_id = 0
        self._on = False
        self._lock = asyncio.Lock()
        self._last_meta: tuple[int, int] | None = None
        self.frames = 0
        self.bytes_out = 0

    # ------------------------------------------------------------------ 接线

    async def start(self) -> None:
        self.session.cdp.on("Page.screencastFrame", self._on_frame)

    async def close(self) -> None:
        await self._stop_cast()
        self.viewers.clear()

    # ------------------------------------------------------------- 观看者进出

    async def add_viewer(self, v: Viewer) -> None:
        self.viewers.add(v)
        if len(self.viewers) == 1:
            await self.follow(self.session.tabs.active, force=True)
        if self.dom is not None:
            # **新来的要从最近一张全量快照接上,不能从半路接** ——
            # 增量链从中间开始重放出来的是一棵错的 DOM,而且不报错
            # ([c §5.5](../../docs/v2/works/c-view.md#55-背压不能沿用丢旧保新))。
            for e in self.dom.snapshot_for_new_viewer():
                with contextlib.suppress(Exception):
                    await v.tell("dom", e=e)

    async def remove_viewer(self, v: Viewer) -> None:
        v.closed = True
        self.viewers.discard(v)
        if not self.viewers:
            # **没人看就不产帧。** 这不是省事,是正确 —— 整块屏一直在那儿
            # 是 VNC 的毛病,我们没有理由继承。
            await self._stop_cast()

    # ------------------------------------------------------------- 跟着 tab 走

    async def follow(self, tab_id: str | None, *, force: bool = False) -> None:
        """把 screencast 搬到 `tab_id` 上。`active` 变了就该调它。"""
        if not self.viewers:
            self._tab = tab_id                # 记下来,等有人看再开
            return
        if tab_id is None:
            await self._stop_cast()
            return
        if tab_id == self._tab and self._on and not force:
            return
        async with self._lock:
            await self._stop_cast(locked=True)
            self._tab = tab_id
            try:
                sid = await self.session.cdp_session_for(tab_id)
            except Exception as e:
                log.warning("attach 不上 %s: %s", tab_id, e)
                return
            self._sid = sid
            if self.dom is not None:
                # **记录器挂在这个 target 上。** 同一个 target 只挂一次;
                # 挂不上就报出来 —— 静默失败的表现是"DOM 模式下画面永远不出来",
                # 和"页面没动"分不清。
                try:
                    await self.dom.arm(self.session.cdp, sid)
                except Exception as e:            # noqa: BLE001
                    log.error("DOM 画面挂不上:%s", e)
            # **必须 activate,否则一帧都不会有** —— 本轮实测
            with contextlib.suppress(Exception):
                tab = self.session.tabs.get(tab_id)
                await self.session.cdp.send("Target.activateTarget",
                                            {"targetId": tab.target_id})
            await self._apply_viewport()
            await self._start_cast(locked=True)
        await self._tell_all("cast", tab=tab_id, w=self.width, h=self.height,
                             format=self.format, quality=self.adaptor.quality,
                             dsf=self.dsf)

    async def _start_cast(self, *, locked: bool = False) -> None:
        if not self.own_frames:
            # 画面由 xpra 那条连接下来,**这里一个 CDP 截图命令都不发** ——
            # 两条都开着等于同一份画面编码两遍。
            return
        if self._sid is None:
            return
        self._cast_id += 1
        params: dict[str, Any] = {
            "format": self.format,
            # **跟着乘 dsf**,否则 Chromium 把 2x 画面缩回 CSS 尺寸再编码
            "maxWidth": int(self.width * self.dsf),
            "maxHeight": int(self.height * self.dsf),
            "everyNthFrame": self.adaptor.every_nth,
        }
        if self.format != "png":              # png 无损,quality 对它无效
            params["quality"] = self.adaptor.quality
        await self.session.cdp.send("Page.startScreencast", params,
                                    session_id=self._sid)
        self._on = True

    async def _stop_cast(self, *, locked: bool = False) -> None:
        if not self.own_frames:
            self._on = False
            return
        if not self._on or self._sid is None:
            self._on = False
            return
        self._on = False
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Page.stopScreencast", {},
                                        session_id=self._sid)

    async def _apply_viewport(self) -> None:
        """视口是 per-tab 的,一条 CDP 命令([c1](../../docs/v2/works/c1-quality.md))。"""
        if not self.own_viewport:
            # **VNC 下画面尺寸是那个 X 显示的尺寸,不是 CDP 说了算的。**
            # 这时候再 setDeviceMetricsOverride,页面会被渲染成另一个尺寸,
            # 而窗口不变 —— 结果是画面里一圈空白。所以不发。
            return
        if self._sid is None:
            return
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Emulation.setDeviceMetricsOverride", {
                "width": self.width, "height": self.height,
                "deviceScaleFactor": 0, "mobile": False}, session_id=self._sid)

    async def resize(self, width: int, height: int) -> None:
        if not self.own_viewport:
            # 尺寸由 `xpra --resize-display=WxH` 定死,浏览器窗口拉大拉小
            # 不改变它 —— **说一次,别每次都吵**。
            if not self._warned_resize:
                self._warned_resize = True
                log.info("xpra 模式下画面尺寸是固定的(%dx%d),忽略客户端的 resize",
                         self.width, self.height)
            return
        width = max(200, min(4096, int(width)))
        height = max(200, min(4096, int(height)))
        if (width, height) == (self.width, self.height):
            return
        self.width, self.height = width, height
        async with self._lock:
            await self._apply_viewport()
            if self._on:
                await self._start_cast(locked=True)    # 重发一次,带上新尺寸
        await self._tell_all("cast", tab=self._tab, w=width, h=height,
                             format=self.format, quality=self.adaptor.quality)

    # ------------------------------------------------------------------ 收帧

    def _on_frame(self, params: dict, sid: str | None) -> None:
        # **环 A:无条件、立刻。** 不回 Chromium 就停流,而且这跟客户端
        # 回不回 ack 没有任何关系。
        session_id = params.get("sessionId")
        if session_id is not None and sid:
            asyncio.create_task(self._ack_chrome(sid, session_id))
        if sid != self._sid or not self._on or not self.viewers:
            return
        asyncio.create_task(self._fanout(params))

    async def _ack_chrome(self, sid: str, cast_session: int) -> None:
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Page.screencastFrameAck",
                                        {"sessionId": cast_session},
                                        session_id=sid, timeout=5)

    async def _fanout(self, params: dict) -> None:
        try:
            raw = base64.b64decode(params["data"])
        except Exception:
            return
        self._frame_id += 1
        self.frames += 1
        self.bytes_out += len(raw)

        tab = self.session.tabs._by_id.get(self._tab) if self._tab else None
        target_id = tab.target_id if tab else ""
        frame = build_header(self._cast_id, self._frame_id, target_id) + raw

        meta = params.get("metadata") or {}
        size = (int(meta.get("deviceWidth") or 0), int(meta.get("deviceHeight") or 0))
        if size != self._last_meta and all(size):
            self._last_meta = size
            await self._tell_all("meta", frame_w=size[0], frame_h=size[1],
                                 css_w=self.width, css_h=self.height)

        for v in list(self.viewers):
            with contextlib.suppress(Exception):
                await v.offer(frame, self._frame_id)

    # ------------------------------------------------------------------ ack

    async def on_viewer_ack(self, v: Viewer, frame_id: int | None = None) -> None:
        """`frame_id` 是客户端回显的帧号。**对不上就只恢复额度、不算 RTT**
        ([09 §6.3](../../docs/v2/works/09-wire-format.md))。"""
        rtt = await v.on_ack(frame_id)
        if rtt is None:
            return
        before = self.adaptor.quality
        changed = self.adaptor.feed(rtt)
        if changed is None:
            return
        # **进 scrollback,不只是刷一下状态栏。**
        #
        # 状态栏只有当前值,而"画质什么时候降的、降之前 RTT 多少"是事后才会问的
        # 问题 —— 那正是 scrollback 存在的意义(v1/works/03)。用已有的 `session`
        # 类目:它本来就装 session_started / chrome_restarted 这种系统自己做的事,
        # 不用为此新开一类。
        self.session.log.append(
            "session", event="quality_changed",
            quality=changed.quality, every_nth=changed.every_nth,
            rtt_ms=round(rtt), direction="down" if changed.quality < before else "up")
        log.info("RTT 自适应:quality=%d everyNthFrame=%d(RTT %dms)",
                 changed.quality, changed.every_nth, rtt)
        async with self._lock:
            if self._on:
                await self._start_cast(locked=True)
        await self._tell_all("quality", quality=changed.quality,
                             every_nth=changed.every_nth)

    # ------------------------------------------------------------------ 输入

    async def handle_input(self, msg: dict) -> None:
        """观看者的一次输入。**打在正在被截的那个 target 上**,去不到别的 tab。"""
        if self._sid is None:
            return
        # **v2 里"是不是人"不用再靠相关性猜** —— 它就是从我们自己这条 WS 进来的
        # (v1 得靠页面探针 + 时间窗口反推,works/06 §3.2)。
        # 只有按下和敲键算,移动和滚轮不算 —— 否则鼠标一动 API 就被让路窗口挡住。
        if msg.get("type") in ("key", "text") or (
                msg.get("type") == "mouse" and msg.get("event") == "down"):
            self.session.note_human_activity(str(msg.get("type")))
        await Translator(self.session.cdp, self._sid).handle(msg)

    async def _tell_raw(self, msg: dict[str, Any]) -> None:
        """DOM 那条的事件直接发给所有观看者。**不进帧的额度环** ——
        它不是帧,丢一条就断链(§5.5),那套"留最新丢最旧"在这儿是错的。"""
        kind = msg.pop("type", "dom")
        await self._tell_all(kind, **msg)

    async def _tell_all(self, type_: str, **payload: Any) -> None:
        for v in list(self.viewers):
            with contextlib.suppress(Exception):
                await v.tell(type_, **payload)

    # ------------------------------------------------------------- 换一种画面

    async def switch(self, mode: str, *, why: str = "人选的") -> dict[str, Any]:
        """换一种画面。**切的只有这一样东西。**

        之所以能这么窄,是因为**没有状态要迁移**:哪些 tab、当前 URL、
        页面里已经填了什么,全在 Chromium 里,不在任何一条来源里 ——
        来源是只读的观测者,观测者换人,被观测的东西不知道
        ([c §9.2](../../docs/v2/works/c-view.md#92-切的只有一样东西))。

        **切不了就报错,不悄悄留在原来那种。** 悄悄留着的话,
        使用者以为自己换了、画质却没变,比报错难查得多。
        """
        want = modes.canon(mode)
        if want is None:
            raise BadRequest(
                f"没有 {mode!r} 这种画面,只有 "
                + " / ".join(modes.label(m) for m in modes.MODES),
                code="bad_request")
        if want not in self.available:
            # **这不是"暂时不行",是这台 session 上根本没有。**
            # 起的时候没要有头,就没有那个 X 显示 —— 说清楚为什么,
            # 以及该怎么才能有。
            raise BadRequest(
                f"这个 session 上没有 {modes.label(want)} 这种画面,"
                f"只有 {' / '.join(modes.label(m) for m in self.available)}",
                code="bad_request",
                details={"available": list(self.available),
                         "why": "VNC 要一个真实的 X 显示,而这个 session 是无头起的 —— "
                                "起的时候选 --transport vnc 才会有",
                         "hint": "重新起一个 session:webmuxd new … --transport vnc"})
        if want == self.mode:
            return self.mode_info()

        old = self.mode
        await self._stop_cast()
        self.mode = want
        self.own_frames = want == modes.JPG
        self.own_viewport = want != modes.VNC
        if want == modes.DOM and self.dom is None:
            from webmuxd.view.dom import DomSource
            self.dom = DomSource(push=self._tell_raw)
            # **中途切到 DOM,当前这一页是没有记录器的。**
            # 注入只对之后的文档生效 —— 这一条还没解,见
            # docs/v2/issues/dom-注入登记了但不执行.md
            log.warning("中途切到 DOM:当前页没有记录器,要等下一次导航")
        if self.own_frames or self.own_viewport:
            await self._apply_viewport()
        await self._start_cast()

        info = self.mode_info(why=why, was=old)
        # **切了必须说出来**([c §9.5](../../docs/v2/works/c-view.md#95-切了必须说出来))——
        # 画面变了而人不知道为什么,比画面差本身更糟。
        log.info("画面从 %s 换成 %s(%s)", modes.label(old), modes.label(want), why)
        self.session.log.append("session", event="view_mode",
                                mode=want, was=old, why=why)
        await self._tell_all("mode", **info)
        return info

    def mode_info(self, *, why: str = "", was: str = "") -> dict[str, Any]:
        """现在是哪种、能切哪几种。**界面不该自己再写一遍这些字。**"""
        out: dict[str, Any] = {
            "mode": self.mode,
            "label": modes.label(self.mode),
            "available": [m for m in modes.choices() if m["name"] in self.available],
        }
        if why:
            out["why"] = why
        if was:
            out["was"] = was
        return out

    # ------------------------------------------------------------------ 观测

    def stats(self) -> dict[str, Any]:
        return {
            "transport": self.mode,
            "mode": self.mode,
            "mode_label": modes.label(self.mode),
            "on": self._on, "tab": self._tab, "cast_id": self._cast_id,
            "frames": self.frames, "bytes": self.bytes_out,
            "format": self.format, "quality": self.adaptor.quality,
            "dsf": self.dsf,
            "every_nth": self.adaptor.every_nth,
            "w": self.width, "h": self.height,
            "viewers": [v.stats() for v in self.viewers],
            "available": list(self.available),
            **({"dom": self.dom.stats()} if self.dom is not None else {}),
        }
