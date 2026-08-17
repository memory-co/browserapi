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
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()
    logging.info("sessiond 起来了:画面 http://%s:%d/  API /api  (CDP %s)",
                 args.host, args.port, args.cdp)
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
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("WEBMUXD_PORT", "7900")))
    p.add_argument("--data", default=os.environ.get("WEBMUXD_DATA", "/data"))
    p.add_argument("--host-only", action="store_true",
                   help="只绑 127.0.0.1(等价于 --host 127.0.0.1)")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
