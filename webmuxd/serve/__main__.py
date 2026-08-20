"""sessiond —— 一个 session 一个进程。

    python -m webmuxd.serve --cdp http://127.0.0.1:9222 --port 7900

**一个口**:人打开 `/` 看画面,代码打 `/api/…`,帧和输入走 `WS /api/view`
(docs/v2/works/04-one-port.md)。

v1 里它必须跑在容器里 —— Chromium 把调试口绑死在 loopback,而容器是另一个
network namespace。**v2 没有容器,这条前提就没了**(works/07 §3)。
"""

from __future__ import annotations

from webmuxd.view import modes

import argparse
import asyncio
import logging
import os

from aiohttp import web

from webmuxd.core.cdp import CDP
from webmuxd.serve.app import build
from webmuxd.serve.session import Session


async def _run(args: argparse.Namespace) -> None:
    cdp = await CDP.connect(args.cdp)
    session = Session(cdp, data_dir=args.data, view={
        "width": args.width, "height": args.height,
        "fmt": args.format, "quality": args.quality, "dsf": args.dsf,
        "min_quality": args.min_quality, "transport": args.transport})
    await session.start()

    runner = web.AppRunner(build(session, xpra_ws=args.xpra_ws))
    await runner.setup()
    site = web.TCPSite(runner, args.bind, args.port)
    await site.start()
    logging.info("sessiond 起来了:画面 http://%s:%d/  API /api  (CDP %s,画面走 %s)",
                 args.bind, args.port, args.cdp, args.transport)
    if args.bind not in ("127.0.0.1", "localhost", "::1"):
        logging.warning("绑在 %s —— **这台机器网络能到的人,拿到 token 就能"
                        "操作这个浏览器**", args.bind)
    try:
        await asyncio.Event().wait()          # 一直跑到被杀
    finally:
        await session.close()
        await runner.cleanup()
        await cdp.close()


def main() -> None:
    p = argparse.ArgumentParser(prog="sessiond")
    p.add_argument("--cdp", default=os.environ.get("WEBMUXD_CDP",
                                                  "http://127.0.0.1:9222"))
    # **默认只绑回环。**
    #
    # v1 这儿是 `0.0.0.0`,那时候 sessiond 跑在容器里 —— 那个 `0.0.0.0` 是
    # **容器内的**,外面还有 `docker -p` 那一层决定暴不暴露。v2 没有容器了,
    # `0.0.0.0` 就是真的 0.0.0.0([works/07 §2](../../docs/v2/works/07-runtime.md))
    # —— 前提变了,默认值必须跟着变。
    #
    # 而且 v2 的 `/` 是**能直接操作浏览器**的画面口,不是 v1 那个纯 API 口。
    p.add_argument("--bind", "--host", dest="bind", default="127.0.0.1",
                   help="绑哪个地址。默认只绑本机;填 0.0.0.0 就是对外开放")
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("WEBMUXD_PORT", "7900")))
    p.add_argument("--data", default=os.environ.get("WEBMUXD_DATA", "/data"))
    # 清晰度那三个独立的旋钮([02 §4](../../docs/v2/works/02-frame-protocol.md))
    p.add_argument("--width", type=int, default=1024)
    p.add_argument("--height", type=int, default=768)
    p.add_argument("--format", default="jpeg", choices=["jpeg", "png", "webp"])
    p.add_argument("--quality", type=int, default=80)
    p.add_argument("--min-quality", type=int, default=25, dest="min_quality")
    p.add_argument("--dsf", type=float, default=1.0)
    # **画面用哪种。** 默认 JPG —— 它开箱即用。
    # 取值归一交给 `view.modes`,**这儿不再写第二份名单** ——
    # 写两份的下场刚踩过:上层已经改叫 vnc,这里还只认 xpra,
    # 报的是 argparse 的 `invalid choice`,和"画面"两个字都不沾边。
    p.add_argument("--transport", default=modes.JPG,
                   metavar="{jpg,vnc,dom}")
    p.add_argument("--xpra-ws", dest="xpra_ws", default="",
                   help="VNC 那条上游 xpra 的 ws 地址")
    args = p.parse_args()
    canon = modes.canon(args.transport)
    if canon is None:
        p.error(f"没有 {args.transport!r} 这种画面,只有 "
                + " / ".join(modes.label(m) for m in modes.MODES))
    args.transport = canon
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
