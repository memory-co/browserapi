"""一条观看连接 —— 额度、缓冲、RTT、权限。

docs/v2/works/02-frame-protocol.md §2 的**环 B**:客户端每收一帧回一个 ack,
没额度就把新帧塞进一个长度 3 的小缓冲,**留最新丢最旧**。

> 直播画面里过期帧毫无价值,留旧的只会让延迟越积越大。
>
> 这里和 BrowserBox 有个**有意的分歧**:它的 `ack.buffer` 用 `unshift` / `pop`,
> 实际取的是最旧那帧。我们取最新的、其余丢弃。

**慢的那个只是自己掉帧,不拖累别人,也不拖累环 A**(发给 Chromium 的那个 ack
是无条件立刻回的,见 cast.py)。
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Awaitable, Callable

#: 客户端手上最多同时有几帧没 ack。
#: **不是"一次 ack 换一张图"** —— 这是个窗口为 2 的滑动窗口:额度 1 就是严格
#: 乒乓,吞吐被钉死在 `1/RTT`,50ms 的链路上是 20fps 天花板
#: ([09 §1.7](../../docs/v2/works/09-wire-format.md))。
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
        #: 且不会自愈([09 §6.3](../../docs/v2/works/09-wire-format.md))。
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
        能解开死锁的原因([09 §6.4](../../docs/v2/works/09-wire-format.md))。
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

    async def tell(self, type_: str, **payload: Any) -> None:
        if not self.closed:
            await self._send_json({"type": type_, **payload})

    def stats(self) -> dict[str, Any]:
        return {"name": self.name, "writable": self.writable,
                "sent": self.frames_sent, "dropped": self.frames_dropped,
                "acks": self.acks,
                "rtt_ms": round(self.rtt_ms, 1) if self.rtt_ms else None,
                "credit": self.credit, "buffered": len(self._buf)}
