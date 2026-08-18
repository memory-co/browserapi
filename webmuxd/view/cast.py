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
                 quality: int = DEFAULT_QUALITY) -> None:
        self.session = session
        self.width, self.height = width, height
        self.format = fmt
        self.viewers: set[Viewer] = set()
        self.adaptor = Adaptor(quality, lossless=(fmt == "png"))

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
            # **必须 activate,否则一帧都不会有** —— 本轮实测
            with contextlib.suppress(Exception):
                tab = self.session.tabs.get(tab_id)
                await self.session.cdp.send("Target.activateTarget",
                                            {"targetId": tab.target_id})
            await self._apply_viewport()
            await self._start_cast(locked=True)
        await self._tell_all("cast", tab=tab_id, w=self.width, h=self.height,
                             format=self.format, quality=self.adaptor.quality)

    async def _start_cast(self, *, locked: bool = False) -> None:
        if self._sid is None:
            return
        self._cast_id += 1
        params: dict[str, Any] = {
            "format": self.format,
            "maxWidth": self.width,
            "maxHeight": self.height,
            "everyNthFrame": self.adaptor.every_nth,
        }
        if self.format != "png":              # png 无损,quality 对它无效
            params["quality"] = self.adaptor.quality
        await self.session.cdp.send("Page.startScreencast", params,
                                    session_id=self._sid)
        self._on = True

    async def _stop_cast(self, *, locked: bool = False) -> None:
        if not self._on or self._sid is None:
            self._on = False
            return
        self._on = False
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Page.stopScreencast", {},
                                        session_id=self._sid)

    async def _apply_viewport(self) -> None:
        """视口是 per-tab 的,一条 CDP 命令([02 §5](../../docs/v2/works/02-frame-protocol.md))。"""
        if self._sid is None:
            return
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Emulation.setDeviceMetricsOverride", {
                "width": self.width, "height": self.height,
                "deviceScaleFactor": 0, "mobile": False}, session_id=self._sid)

    async def resize(self, width: int, height: int) -> None:
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
        changed = self.adaptor.feed(rtt)
        if changed is None:
            return
        log.info("RTT 自适应:quality=%d everyNthFrame=%d",
                 changed.quality, changed.every_nth)
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

    async def _tell_all(self, type_: str, **payload: Any) -> None:
        for v in list(self.viewers):
            with contextlib.suppress(Exception):
                await v.tell(type_, **payload)

    # ------------------------------------------------------------------ 观测

    def stats(self) -> dict[str, Any]:
        return {
            "on": self._on, "tab": self._tab, "cast_id": self._cast_id,
            "frames": self.frames, "bytes": self.bytes_out,
            "format": self.format, "quality": self.adaptor.quality,
            "every_nth": self.adaptor.every_nth,
            "w": self.width, "h": self.height,
            "viewers": [v.stats() for v in self.viewers],
        }
