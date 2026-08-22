"""**画面的编排** —— 跟哪个 tab、谁在看、慢了降多少、换哪一条。

三条腿各自一个文件(`jpg.py` / `xpra.py` / `rrweb.py`),**这儿一条都不实现**;
它管的是那些"跨腿才成立"的事:

- **跟 tab**:切了 tab 画面要跟过去,而且旧 target 的残帧要丢掉
- **管观看者**:每条连接的额度、缓冲、RTT(`Viewer` 在文件后半)
- **背压**:环 A 无条件回 Chromium,环 B 才看客户端([c1](../docs/v2/works/c1-quality.md))
- **切换**:换一条腿,**切不了就报错,不悄悄留在原来那种**

**它不 import `input.py`。** 画面出去、输入进来是两个方向 ——
那是接缝,不是分层([j §3.6](../docs/v2/works/j-layout.md#36-为什么-screenpy-和-inputpy-仍然必须是两个文件))。
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import time
from collections import deque
from typing import Any, Awaitable, Callable, TYPE_CHECKING

from webmuxd import models
from webmuxd.exceptions import BadRequest
from webmuxd.frames import build_header
from webmuxd.jpg import JpgSource

if TYPE_CHECKING:                                    # pragma: no cover
    from webmuxd.sessions import Session

log = logging.getLogger("webmuxd.screen")

#: 默认视口。和 v1 保持一致(CHANGELOG 0.3.0)。
DEFAULT_W, DEFAULT_H = 1024, 768
#: `jpeg` / `png` / `webp` —— 实测只有这三种,`avif` / `bmp` 会被拒。
#: **默认 jpeg,不按内容自动切**(02 §4①)。
DEFAULT_FORMAT = "jpeg"
DEFAULT_QUALITY = 80


class Screencaster:
    """一个 session 一份画面,所有观看者看同一个 tab([f](../docs/v2/works/f-tabs.md))。"""

    def __init__(self, session: "Session", *, width: int = DEFAULT_W,
                 height: int = DEFAULT_H, fmt: str = DEFAULT_FORMAT,
                 quality: int = DEFAULT_QUALITY, dsf: float = 1.0,
                 min_quality: int = 25, transport: str = models.JPG,
                 has_xpra: bool = False) -> None:
        self.session = session
        #: **画面从哪来 —— 这是几种模式之间唯一的差别**
        #: ([c §7](../docs/v2/works/c-view.md#7-接缝切在哪))。
        #:
        #: 不是 JPG 时这个类**照常干所有别的活**:跟着 tab 走(`Target.activateTarget`)、
        #: 收输入、发光标、管观看者名单 —— 只有 `Page.startScreencast` 那三行不发。
        #: 那条原则落到代码上就是下面几个 `if not self.own_frames: return`,
        #: 没有第二处分叉。
        self.mode = models.canon(transport) or models.JPG
        #: 画面归不归我们截。JPG 归;VNC 的来自 xpra,DOM 的来自页面里的记录器。
        self.own_frames = self.mode == models.JPG
        #: 视口归不归我们定。**这和上面那条不是一回事** ——
        #: DOM 不用我们截图,但**视口必须由我们钉住**:重放出来的布局就是按它排的。
        #: 只有 VNC 不能设 —— 那边画面尺寸是 X 显示的尺寸,再 override 一次
        #: 会让页面被渲染成另一个尺寸而窗口不变,画面里一圈空白。
        self.own_viewport = self.mode != models.VNC
        #: **这台 session 上能切到哪几种。**
        #: 不是"现在用哪种",是"以后能选哪几种" —— VNC 要真实的 X 显示,
        #: 无头浏览器没有,而有没有是起 session 时定的,运行时改不了。
        self.available = models.available_in(headed=has_xpra or transport == models.VNC)
        #: DOM 那条的事件源。别的模式下是 None。
        #: **在 `__init__` 里就建好,不能等 `start()`** —— tab 的 attach 可能
        #: 更早,那时 `self.dom` 还是 None,记录器就漏装了。
        #: 漏装的表现是:模式对、日志说装上了,而页面里 `typeof rrweb` 是
        #: `undefined`、事件一条没有,**全程不报错**。
        self.dom = None
        if self.mode == models.DOM:
            from webmuxd.rrweb import DomSource
            self.dom = DomSource()
        self._warned_resize = False
        self.width, self.height = width, height
        #: **JPG 那条腿在 `jpg.py`。** 这儿只编排 —— 跟哪个 tab、谁在看、
        #: 慢了降多少;真正开关 `Page.startScreencast` 的是它。
        #:
        #: `dsf` 那个坑记在 `jpg.py` 里:真正让倍率生效的是浏览器启动参数
        #: `--force-device-scale-factor`,截图尺寸只是跟着乘。
        self.jpg = JpgSource(session.cdp, fmt=fmt, quality=quality,
                             min_quality=min_quality, dsf=dsf)
        self.viewers: set[Viewer] = set()

        self._tab: str | None = None          # 正在截的 tab
        self._sid: str | None = None          # 它的 CDP sessionId
        self._frame_id = 0
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
        if tab_id == self._tab and self.jpg.on and not force:
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
        await self._send_all(models.Cast(
            tab=tab_id, w=self.width, h=self.height, format=self.jpg.format,
            quality=self.jpg.adaptor.quality, dsf=self.jpg.dsf))

    async def _start_cast(self, *, locked: bool = False) -> None:
        if not self.own_frames:
            # 画面由 xpra 那条连接下来,**这里一个 CDP 截图命令都不发** ——
            # 两条都开着等于同一份画面编码两遍。
            return
        if self._sid is None:
            return
        await self.jpg.start(self._sid, width=self.width, height=self.height)

    async def _stop_cast(self, *, locked: bool = False) -> None:
        if not self.own_frames:
            self.jpg.on = False
            return
        await self.jpg.stop(self._sid)

    async def _apply_viewport(self) -> None:
        """视口是 per-tab 的,一条 CDP 命令([c1](../docs/v2/works/c1-quality.md))。"""
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
            if self.jpg.on:
                await self._start_cast(locked=True)    # 重发一次,带上新尺寸
        await self._send_all(models.Cast(
            tab=self._tab, w=width, h=height, format=self.jpg.format,
            quality=self.jpg.adaptor.quality))

    # ------------------------------------------------------------------ 收帧

    def _on_frame(self, params: dict, sid: str | None) -> None:
        # **环 A:无条件、立刻。** 不回 Chromium 就停流,而且这跟客户端
        # 回不回 ack 没有任何关系。
        session_id = params.get("sessionId")
        if session_id is not None and sid:
            asyncio.create_task(self.jpg.ack(sid, session_id))
        if sid != self._sid or not self.jpg.on or not self.viewers:
            return
        asyncio.create_task(self._fanout(params))

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
        frame = build_header(self.jpg.cast_id, self._frame_id, target_id) + raw

        meta = params.get("metadata") or {}
        size = (int(meta.get("deviceWidth") or 0), int(meta.get("deviceHeight") or 0))
        if size != self._last_meta and all(size):
            self._last_meta = size
            await self._send_all(models.Meta(size[0], size[1],
                                             self.width, self.height))

        for v in list(self.viewers):
            with contextlib.suppress(Exception):
                await v.offer(frame, self._frame_id)

    # ------------------------------------------------------------------ ack

    async def on_viewer_ack(self, v: Viewer, frame_id: int | None = None) -> None:
        """`frame_id` 是客户端回显的帧号。**对不上就只恢复额度、不算 RTT**
        ([e1](../docs/v2/works/e1-wire-format.md))。"""
        rtt = await v.on_ack(frame_id)
        if rtt is None:
            return
        before = self.jpg.adaptor.quality
        changed = self.jpg.adaptor.feed(rtt)
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
            if self.jpg.on:
                await self._start_cast(locked=True)
        await self._send_all(models.QualityChanged(changed.quality,
                                                   changed.every_nth))

    # ------------------------------------------------------------------ 输入

    @property
    def target_session(self) -> str | None:
        """**输入打在正在被截的那个 target 上**,去不到别的 tab。

        这儿只回答"是哪个",怎么打是 `input.py` 的事 ——
        画面出去、输入进来是**两个方向**,合在一起写,"只读地看"这件事
        就没有结构上的保证了([j §3.6](../docs/v2/works/j-layout.md#36-为什么-screenpy-和-inputpy-仍然必须是两个文件))。
        """
        return self._sid

    async def _send_all(self, msg: Any) -> None:
        """把一条下行消息发给所有观看者。

        **收一个对象,不收 `(type, **kw)`** —— 那样每个调用点都在自己拼形状,
        而形状是跨语言的([models](models.py) ↔ `protocol/messages.ts`)。
        """
        payload = msg.to_json() if hasattr(msg, "to_json") else msg
        # **每条下行都得带 `type`** —— 观看端按它分流,漏了就是**静默失效**:
        # 消息发出去了、对面一个分支都没进,而且两边都不报错。
        assert "type" in payload, f"下行消息没有 type:{payload!r}"
        for v in list(self.viewers):
            with contextlib.suppress(Exception):
                await v.send(payload)

    # ------------------------------------------------------------- 换一种画面

    async def switch(self, mode: str, *, why: str = "人选的") -> dict[str, Any]:
        """换一种画面。**切的只有这一样东西。**

        之所以能这么窄,是因为**没有状态要迁移**:哪些 tab、当前 URL、
        页面里已经填了什么,全在 Chromium 里,不在任何一条来源里 ——
        来源是只读的观测者,观测者换人,被观测的东西不知道
        ([c §9.2](../docs/v2/works/c-view.md#92-切的只有一样东西))。

        **切不了就报错,不悄悄留在原来那种。** 悄悄留着的话,
        使用者以为自己换了、画质却没变,比报错难查得多。
        """
        want = models.canon(mode)
        if want is None:
            raise BadRequest(
                f"没有 {mode!r} 这种画面,只有 "
                + " / ".join(models.label(m) for m in models.MODES),
                code="bad_request")
        if want not in self.available:
            # **这不是"暂时不行",是这台 session 上根本没有。**
            # 起的时候没要有头,就没有那个 X 显示 —— 说清楚为什么,
            # 以及该怎么才能有。
            raise BadRequest(
                f"这个 session 上没有 {models.label(want)} 这种画面,"
                f"只有 {' / '.join(models.label(m) for m in self.available)}",
                code="bad_request",
                details={"available": list(self.available),
                         "why": "VNC 要一个真实的 X 显示,而这个 session 是无头起的 —— "
                                "起的时候选 --transport vnc 才会有",
                         "hint": "重新起一个 session:webmuxd new … --transport vnc"})
        if want == self.mode:
            return self.mode_info().to_json()

        old = self.mode
        await self._stop_cast()
        self.mode = want
        self.own_frames = want == models.JPG
        self.own_viewport = want != models.VNC
        if want == models.DOM and self.dom is None:
            from webmuxd.rrweb import DomSource
            self.dom = DomSource()
            # **中途切到 DOM,当前这一页是没有记录器的。**
            # 注入只对之后的文档生效 —— 这一条还没解,见
            # docs/v2/issues/dom-注入登记了但不执行.md
            log.warning("中途切到 DOM:当前页没有记录器,要等下一次导航")
        if self.own_frames or self.own_viewport:
            await self._apply_viewport()
        await self._start_cast()

        info = self.mode_info(why=why, was=old)
        # **切了必须说出来**([c §9.5](../docs/v2/works/c-view.md#95-切了必须说出来))——
        # 画面变了而人不知道为什么,比画面差本身更糟。
        log.info("画面从 %s 换成 %s(%s)", models.label(old), models.label(want), why)
        self.session.log.append("session", event="view_mode",
                                mode=want, was=old, why=why)
        await self._send_all(info.as_message())
        return info.to_json()

    def mode_info(self, *, why: str = "", was: str = "") -> models.ModeInfo:
        """现在是哪种、能切哪几种。**形状在 [`models.ModeInfo`](models.py)** ——
        界面不该自己再写一遍这些字,我们也不该在这儿手拼一份。"""
        return models.ModeInfo(self.mode, list(self.available), why=why, was=was)

    # ------------------------------------------------------------------ 观测

    def stats(self) -> dict[str, Any]:
        return {
            "transport": self.mode,
            "mode": self.mode,
            "mode_label": models.label(self.mode),
            **self.jpg.stats(),
            "tab": self._tab,
            "frames": self.frames, "bytes": self.bytes_out,
            "w": self.width, "h": self.height,
            "viewers": [v.stats() for v in self.viewers],
            "available": list(self.available),
            **({"dom": self.dom.stats()} if self.dom is not None else {}),
        }


# --------------------------------------------------------------------------
# 一条观看连接:额度、缓冲、RTT(原 view/viewer.py)
# --------------------------------------------------------------------------

#: 客户端手上最多同时有几帧没 ack。
#: **不是"一次 ack 换一张图"** —— 这是个窗口为 2 的滑动窗口:额度 1 就是严格
#: 乒乓,吞吐被钉死在 `1/RTT`,50ms 的链路上是 20fps 天花板
#: ([e1](../docs/v2/works/e1-wire-format.md))。
ACK_CREDIT = 2
#: 没额度时缓冲几帧。**满了丢最旧的。**
BUFFER = 3
#: 在途帧的时间戳最多留几条。正常情况下不会超过 `ACK_CREDIT`,
#: 这个上限是防"ack 永远不来"时字典无限长。
SENT_CAP = 8


class Viewer:
    """一个观看者。`send_bytes` / `send_json` 由传输层给(aiohttp 的 WS)。"""

    def __init__(self, send_bytes: Callable[[bytes], Awaitable[None]],
                 send_json: Callable[[dict], Awaitable[None]], *,
                 writable: bool = False, name: str = "") -> None:
        self._send_bytes = send_bytes
        self._send_json = send_json
        self.writable = writable
        self.name = name
        self.credit = ACK_CREDIT
        self._buf: deque[tuple[int, bytes]] = deque(maxlen=BUFFER)
        #: **按帧号记账**,不是按顺序。客户端漏回一个 ack 时,按号查表只是少一个
        #: 样本;而"弹最旧的那个时间戳"会永久错位,之后每个 RTT 都算成上一帧的,
        #: 且不会自愈([e1](../docs/v2/works/e1-wire-format.md))。
        self._sent_at: dict[int, float] = {}
        self.frames_sent = 0
        self.frames_dropped = 0
        #: 收到多少个 ack。**心跳补的那些也算在里面** —— 没有这个计数,
        #: "3 秒补一发"到底有没有真的在跑就没法观测。
        self.acks = 0
        self.rtt_ms: float | None = None
        self.closed = False

    # ------------------------------------------------------------------ 发

    async def offer(self, frame: bytes, frame_id: int) -> None:
        """给它一帧。有额度就发,没有就进缓冲。"""
        if self.closed:
            return
        if self.credit > 0:
            await self._write(frame, frame_id)
            return
        if len(self._buf) == BUFFER:
            self.frames_dropped += 1        # **丢最旧的**,deque(maxlen) 自动做
        self._buf.append((frame_id, frame))

    async def _write(self, frame: bytes, frame_id: int) -> None:
        self.credit -= 1
        self._sent_at[frame_id] = time.monotonic()
        if len(self._sent_at) > SENT_CAP:   # ack 一直不来时别让它无限长
            oldest = min(self._sent_at, key=self._sent_at.get)   # type: ignore[arg-type]
            self._sent_at.pop(oldest, None)
        self.frames_sent += 1
        await self._send_bytes(frame)

    async def on_ack(self, frame_id: int | None = None) -> float | None:
        """客户端回了一个 ack。返回这一帧的 RTT(毫秒),算不出来就 None。

        **额度无条件恢复**,哪怕帧号对不上 —— 这正是"3 秒补一个 ack"那条心跳
        能解开死锁的原因([e1](../docs/v2/works/e1-wire-format.md))。
        RTT 则只在帧号对得上时才算,**对不上就跳过,不污染窗口**。
        """
        self.acks += 1
        rtt = None
        sent = self._sent_at.pop(frame_id, None) if frame_id is not None else None
        if sent is not None:
            rtt = (time.monotonic() - sent) * 1000
            self.rtt_ms = rtt

        self.credit = min(ACK_CREDIT, self.credit + 1)
        # 缓冲里**只取最新那帧**,其余全丢 —— 过期帧没有价值
        if self._buf and self.credit > 0:
            newest_id, newest = self._buf[-1]
            self.frames_dropped += len(self._buf) - 1
            self._buf.clear()
            await self._write(newest, newest_id)
        return rtt

    async def send(self, payload: dict[str, Any]) -> None:
        """一条下行 JSON。**payload 里已经带着 `type`** ——
        形状归 [`models`](models.py) 管,这一层只管发出去。"""
        if not self.closed:
            await self._send_json(payload)

    def stats(self) -> dict[str, Any]:
        return {"name": self.name, "writable": self.writable,
                "sent": self.frames_sent, "dropped": self.frames_dropped,
                "acks": self.acks,
                "rtt_ms": round(self.rtt_ms, 1) if self.rtt_ms else None,
                "credit": self.credit, "buffered": len(self._buf)}
