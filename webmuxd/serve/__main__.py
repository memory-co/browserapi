"""sessiond —— 一个 session 一个进程。

    python -m webmuxd.serve --cdp http://127.0.0.1:9222 --port 7900

**一个口**:人打开 `/` 看画面,代码打 `/api/…`,帧和输入走 `WS /api/view`
(docs/v2/works/04-one-port.md)。

v1 里它必须跑在容器里 —— Chromium 把调试口绑死在 loopback,而容器是另一个
network namespace。**v2 没有容器,这条前提就没了**(works/07 §3)。
"""

from __future__ import annotations

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
    session = Session(cdp, data_dir=args.data)
    await session.start()

    runner = web.AppRunner(build(session))
    await runner.setup()
    site = web.TCPSite(runner, args.bind, args.port)
    await site.start()
    logging.info("sessiond 起来了:画面 http://%s:%d/  API /api  (CDP %s)",
                 args.bind, args.port, args.cdp)
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
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
