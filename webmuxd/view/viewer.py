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
ACK_CREDIT = 2
#: 没额度时缓冲几帧。**满了丢最旧的。**
BUFFER = 3


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
        self._buf: deque[bytes] = deque(maxlen=BUFFER)
        self._sent_at: deque[float] = deque()
        self.frames_sent = 0
        self.frames_dropped = 0
        self.rtt_ms: float | None = None
        self.closed = False

    # ------------------------------------------------------------------ 发

    async def offer(self, frame: bytes) -> None:
        """给它一帧。有额度就发,没有就进缓冲。"""
        if self.closed:
            return
        if self.credit > 0:
            await self._write(frame)
            return
        if len(self._buf) == BUFFER:
            self.frames_dropped += 1        # **丢最旧的**,deque(maxlen) 自动做
        self._buf.append(frame)

    async def _write(self, frame: bytes) -> None:
        self.credit -= 1
        self._sent_at.append(time.monotonic())
        self.frames_sent += 1
        await self._send_bytes(frame)

    async def on_ack(self) -> float | None:
        """客户端回了一个 ack。返回这一帧的 RTT(毫秒),算不出来就 None。"""
        rtt = None
        if self._sent_at:
            rtt = (time.monotonic() - self._sent_at.popleft()) * 1000
            self.rtt_ms = rtt
        self.credit = min(ACK_CREDIT, self.credit + 1)
        # 缓冲里**只取最新那帧**,其余全丢 —— 过期帧没有价值
        if self._buf and self.credit > 0:
            newest = self._buf[-1]
            self.frames_dropped += len(self._buf) - 1
            self._buf.clear()
            await self._write(newest)
        return rtt

    async def tell(self, type_: str, **payload: Any) -> None:
        if not self.closed:
            await self._send_json({"type": type_, **payload})

    def stats(self) -> dict[str, Any]:
        return {"name": self.name, "writable": self.writable,
                "sent": self.frames_sent, "dropped": self.frames_dropped,
                "rtt_ms": round(self.rtt_ms, 1) if self.rtt_ms else None,
                "credit": self.credit, "buffered": len(self._buf)}
