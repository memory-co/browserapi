"""**JPG 那条画面** —— Chromium 自己截,一张一张推。

    Page.startScreencast → screencastFrame → screencastFrameAck

三条腿里最普适的那条:**什么都显示得出来**,视频、canvas、WebGL 都在里面
([c §3](../docs/v2/works/c-view.md))。代价是整屏重编码,滚动时最费。

**它不认识 `xpra.py` 和 `rrweb.py`,也不该认识** —— 三条并列的腿,
谁也不是谁的基础;一旦串起来,"换一条"就不再是换一条
([j §5](../docs/v2/works/j-layout.md#5-依赖方向扁平之后层要靠规矩守))。

编排(跟哪个 tab、有几个观看者、背压、切换)不在这儿,在 `screen.py`。
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from webmuxd.quality import Adaptor

log = logging.getLogger("webmuxd.jpg")


class JpgSource:
    """一个 session 的 JPG 画面源。

    **它只管一件事:让 Chromium 开始/停止吐帧,并且立刻回 ack。**
    帧往哪儿去、谁在看、慢了降多少 —— 都是 `screen.py` 的事。
    """

    def __init__(self, cdp: Any, *, fmt: str = "jpeg", quality: int = 80,
                 min_quality: int = 25, dsf: float = 1.0) -> None:
        self.cdp = cdp
        self.format = fmt
        #: 设备像素比。**截图尺寸要跟着乘它**,否则 Chromium 会把 2x 画面
        #: 缩回 CSS 尺寸再编码,细节就没了。
        self.dsf = dsf if dsf and dsf > 0 else 1.0
        self.adaptor = Adaptor(quality, lossless=(fmt == "png"), floor=min_quality)
        #: 每次 start 递增 —— 客户端靠它丢掉切 tab 前的残帧。
        self.cast_id = 0
        self.on = False

    async def start(self, sid: str, *, width: int, height: int) -> None:
        self.cast_id += 1
        params: dict[str, Any] = {
            "format": self.format,
            # **跟着乘 dsf**,否则 Chromium 把 2x 画面缩回 CSS 尺寸再编码
            "maxWidth": int(width * self.dsf),
            "maxHeight": int(height * self.dsf),
            "everyNthFrame": self.adaptor.every_nth,
        }
        if self.format != "png":              # png 无损,quality 对它无效
            params["quality"] = self.adaptor.quality
        await self.cdp.send("Page.startScreencast", params, session_id=sid)
        self.on = True

    async def stop(self, sid: str | None) -> None:
        was, self.on = self.on, False
        if not was or sid is None:
            return
        with contextlib.suppress(Exception):
            await self.cdp.send("Page.stopScreencast", {}, session_id=sid)

    async def ack(self, sid: str, cast_session: int) -> None:
        """**环 A:无条件、立刻。** 不回 Chromium 就停流,
        而且这跟客户端回不回 ack 没有任何关系([c1 §1](../docs/v2/works/c1-quality.md))。"""
        with contextlib.suppress(Exception):
            await self.cdp.send("Page.screencastFrameAck", {"sessionId": cast_session},
                                session_id=sid, timeout=5)

    def stats(self) -> dict[str, Any]:
        return {"on": self.on, "cast_id": self.cast_id, "format": self.format,
                "quality": self.adaptor.quality, "dsf": self.dsf,
                "every_nth": self.adaptor.every_nth}
