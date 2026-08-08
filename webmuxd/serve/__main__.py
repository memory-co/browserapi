"""sessiond —— 容器里那个进程。

    python -m webmuxd.serve --cdp http://127.0.0.1:9222 --port 7900

**它必须跑在容器里**:Chromium 的 Host 头校验挡掉容器外的 CDP 访问
(docs/v1/works/01-container.md §3 实测)。
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
    logging.info("sessiond 起来了:http://%s:%d/api  (CDP %s)",
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
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
