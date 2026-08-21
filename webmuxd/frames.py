"""帧头和上行消息 —— docs/v2/works/e1-wire-format.md §1。

**28 字节定长头 + 图片裸字节**,不是 JSON。CDP 给的是 base64,原样塞进 JSON
转发要多花 33% 体积和两次编解码([e1](../docs/v2/works/e1-wire-format.md))。

布局和 BrowserBox 一致:

    0–3    castSessionId   每次 startScreencast 递增,用来丢弃切 tab 前的残帧
    4–7    frameId         单调递增
    8–23   targetId        32 个 hex 字符切成 4 个 uint32 LE
    24–27  保留
"""

from __future__ import annotations

import struct

from webmuxd.models import FrameHeader

HEADER_SIZE = 28

_HEADER = struct.Struct("<7I")          # 7 个 uint32 LE = 28 字节


def pack_target(target_id: str) -> tuple[int, int, int, int]:
    """32 个 hex 字符 → 4 个 uint32。

    短了补零、长了截断 —— **头是定长的**,这里绝不能因为一个奇怪的 targetId
    就让整条流错位。
    """
    h = (target_id or "").ljust(32, "0")[:32]
    out = []
    for i in range(4):
        chunk = h[i * 8:(i + 1) * 8]
        try:
            out.append(int(chunk, 16))
        except ValueError:
            out.append(0)
    return tuple(out)                    # type: ignore[return-value]


def build_header(cast_session_id: int, frame_id: int, target_id: str) -> bytes:
    a, b, c, d = pack_target(target_id)
    return _HEADER.pack(cast_session_id & 0xFFFFFFFF, frame_id & 0xFFFFFFFF,
                        a, b, c, d, 0)


def parse_header(buf: bytes) -> FrameHeader:
    """给测试和客户端用。"""
    if len(buf) < HEADER_SIZE:
        raise ValueError(f"帧头不足 {HEADER_SIZE} 字节")
    cast, frame, a, b, c, d, _ = _HEADER.unpack(buf[:HEADER_SIZE])
    return FrameHeader(cast_session_id=cast, frame_id=frame,
                       target_id="".join(f"{x:08x}" for x in (a, b, c, d)))


#: 上行认得的消息类型。**白名单** —— 观看者能表达的意图就这些
#: ([b](../docs/v2/works/b-input.md))。
UPSTREAM = frozenset({
    "ack",          # 收到一帧
    "mouse", "wheel", "key", "text",     # 输入,见 view/input.py
    "resize",       # 改视口
    "tab",          # 切 tab
    "mode",         # 换一种画面(c §9)—— 只换画面来源,不碰别的
})
