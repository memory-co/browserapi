"""xpra 那条连接的代理 —— docs/v2/works/11 §2.2 · 12 §7。

浏览器连的是**我们的**口(`WS /xpra`),不是 xpra 的口。两个理由:

**① 一个口**([04](../../docs/v2/works/04-one-port.md))。人拿到的是一个地址。
**② token 在我们这儿校验一次。** xpra 自己的鉴权是进程级的,不认我们的
只读 token。

## 上行白名单

[11 §2.1](../../docs/v2/works/11-xpra.md) 原来写的是"客户端根本不往这条连接
发任何东西"。实测下来那句话是错的 —— 协议要求上行 5 个包,少一个就收不到帧
或者被断开([12 §7](../../docs/v2/works/12-xpra-client.md))。

**但结论更强了:上行是一个闭集,所以能走白名单。**

    白名单:认识的放行,**其余一律丢弃**  ← 新的 packet 类型默认被拒
    黑名单:认出坏的丢掉,其余放行        ← 漏一类就破一个口

于是输入永远到不了 xpra,不管客户端怎么写 —— [03 §1](../../docs/v2/works/03-input.md)
那个"观看者能表达的意图被限制在 CDP `Input` 四个命令里"的收口原样成立,
而且现在是**两层**:客户端不发,代理也不放。

## 只需要解到包名

判断包类型要读 rencodeplus 编出来的数组的第一个元素。**我们不 import xpra**
—— sessiond 的 python 环境不一定有它,而且为了读一个字符串背一个 C 扩展不值。
下面那 20 行只解"数组的第一个元素是个字符串"这一种情况,别的一律当不认识。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from typing import Callable

import aiohttp
from aiohttp import WSMsgType, web

log = logging.getLogger("webmuxd.view.relay")

#: 8 字节头([12 §2](../../docs/v2/works/12-xpra-client.md))。
#: `!BBBBL` = 'P'、proto flags、压缩级别、**包数组下标**、大端长度。
HEADER = struct.Struct("!BBBBL")
MAGIC = ord("P")

#: **客户端能往 xpra 发的全部东西。** 每一条都写清楚不发会怎样 ——
#: 这张表是安全边界,不是配置。
ALLOWED = {
    "hello":            "握手。不发连不上",
    "map-window":       "告诉服务端我在看。**不发一帧都不来**",
    "focus":            "键盘焦点。我们不用键盘走这条,但协议要",
    "damage-sequence":  "帧 ack。这是 xpra 的背压,对应我们的环 B",
    "ping_echo":        "心跳回应。不发一段时间后被服务端断开",
    "disconnect":       "关页面时好好说一声",
}

#: 上行最大包长。握手那个 caps 字典是最大的一个,几 KB;
#: **给一个上限,别让代理成为一个内存放大器**。
MAX_UP = 256 * 1024


def packet_type(body: bytes) -> str | None:
    """从 rencodeplus 的载荷里读出包名。读不出来返回 `None`(→ 丢弃)。

    只认两种形状,因为包名总是个短字符串:

        192+n            定长数组,n 个元素
        59               变长数组,以 127 结尾
        128+n            定长字符串,n 字节
        "<len>:" + bytes 变长字符串
    """
    if not body:
        return None
    head = body[0]
    if head == 59:                                  # CHR_LIST
        i = 1
    elif 192 <= head <= 255:                        # LIST_FIXED_START + len
        i = 1
    else:
        return None
    if i >= len(body):
        return None
    b = body[i]
    if 128 <= b <= 191:                             # STR_FIXED_START + len
        n = b - 128
        return body[i + 1:i + 1 + n].decode("utf-8", "replace")
    if 0x30 <= b <= 0x39:                           # "<len>:" 变长字符串
        j = i
        while j < len(body) and 0x30 <= body[j] <= 0x39:
            j += 1
        if j >= len(body) or body[j] != ord(":"):
            return None
        n = int(body[i:j])
        return body[j + 1:j + 1 + n].decode("utf-8", "replace")
    return None


def screen(frame: bytes) -> tuple[bool, str]:
    """一个上行帧过不过。返回 `(放行, 理由)` —— **理由是给日志的,不是给客户端的**。

    拒绝的四种情况,每一种都不是"可能有问题",而是"我们的客户端不会这么发":
    """
    if len(frame) < HEADER.size:
        return False, "帧比头还短"
    magic, flags, level, index, size = HEADER.unpack_from(frame)
    if magic != MAGIC:
        return False, f"头一个字节不是 'P'({magic})"
    if level != 0:
        # 我们的客户端报 `compression_level: 0`,上行永远不压。
        return False, f"上行带压缩(level={level}),我们的客户端不会这么发"
    if index != 0:
        # 大块二进制是**下行**才有的(像素)。上行没有需要分块的东西。
        return False, f"上行带 chunk 下标({index}),没有该分块的上行包"
    if size > MAX_UP or HEADER.size + size != len(frame):
        return False, f"长度对不上(声明 {size},实到 {len(frame) - HEADER.size})"
    t = packet_type(frame[HEADER.size:])
    if t is None:
        return False, "解不出包名"
    if t not in ALLOWED:
        return False, f"不在白名单里:{t}"
    return True, t


async def pump(request: web.Request, upstream_url: str, *,
               on_reject: Callable[[str], None] | None = None) -> web.WebSocketResponse:
    """把浏览器那条 WS 和 xpra 那条接起来。

    **下行原样透传**(像素,一个字节都不动),**上行过白名单**。
    """
    # **`heartbeat=None`,不是 0。** aiohttp 拿到 0 会 `call_later(0, ping)`,
    # 然后 pong 超时也是 0 —— 连上就立刻判定超时关掉。心跳由 xpra 自己的
    # `ping` / `ping_echo` 做(works/12 §7),这一层不要再加一份。
    ws = web.WebSocketResponse(heartbeat=None, max_msg_size=0,
                               protocols=("binary",))
    await ws.prepare(request)

    rejected: dict[str, int] = {}

    def reject(why: str) -> None:
        rejected[why] = rejected.get(why, 0) + 1
        if rejected[why] == 1:              # **一种理由只吵一次**
            log.warning("xpra 上行丢弃:%s", why)
            if on_reject:
                on_reject(why)

    session = aiohttp.ClientSession()
    try:
        async with session.ws_connect(upstream_url, protocols=("binary",),
                                      max_msg_size=0, heartbeat=None) as up:
            async def down() -> None:
                async for msg in up:
                    if msg.type is WSMsgType.BINARY:
                        await ws.send_bytes(msg.data)
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break
                with contextlib.suppress(Exception):
                    await ws.close()

            task = asyncio.create_task(down())
            try:
                async for msg in ws:
                    if msg.type is not WSMsgType.BINARY:
                        if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break
                        continue
                    ok, why = screen(msg.data)
                    if ok:
                        await up.send_bytes(msg.data)
                    else:
                        reject(why)
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    except aiohttp.ClientError as e:
        log.error("连不上 xpra(%s):%s", upstream_url, e)
        with contextlib.suppress(Exception):
            await ws.close(code=1011, message=b"xpra upstream unreachable")
    finally:
        await session.close()
    if rejected:
        log.info("这条 xpra 连接一共丢了 %d 个上行包:%s",
                 sum(rejected.values()), rejected)
    return ws
