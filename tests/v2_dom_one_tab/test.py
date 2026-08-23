"""v2 · DOM 那条腿:**只有当前那个 tab 在录。**

整个 session 共用**一条**增量链(`DomSource.events` 是一份,不是每个 tab 一份)。
所以同时录两个 tab 不只是费,是**错的** —— 后台那个的 mutation 会混进
当前这条链里,客户端拿它们去改当前那棵树,改出来的是一棵没人见过的树。

**而它不会报错。** 表现只是"重放偶尔抽一下",查起来毫无头绪。
实测(修之前):当前页一动不动,6 秒里混进来 6 条后台 tab 的 mutation。

顺带押住另一半:**换 tab 之后新连上来的人还得看得见画面。**
换链要清缓冲,而清了就必须补一张新快照 —— 第一版漏了这一步,
静态页切回去之后缓冲空着、页面又没有新事件,那条腿就静悄悄地死了。

要网络的话这条根本写不了:得有一张**一直在动**的页(小站的 `/ticker`)
和一张**一动不动**的页(`/about`),而且两边的变化频率要说得准。
"""

import asyncio
import json
import time

import pytest

from tests import v2kit
from tests.site import site

pytestmark = pytest.mark.slow


@pytest.fixture
def cli(tmp_path):
    with site() as base, v2kit.server(tmp_path) as c:
        c.site = base
        yield c


def listen(port: str, sid: str, *, settle: float = 2, watch: float = 6) -> tuple[int, int]:
    """接上那条 DOM 通道,数两段:**开局补的**,和**之后来的**。

    开局那一段是服务端把缓冲补给新观看者(至少得有 Meta + 全量快照);
    之后那一段才是"现在还有谁在往里写"。
    """
    async def run() -> tuple[int, int]:
        import aiohttp
        head, tail = 0, 0
        async with aiohttp.ClientSession() as cs:
            async with cs.ws_connect(f"http://127.0.0.1:{port}/s/{sid}/channel/rrweb") as ws:
                t0 = time.time()

                async def pump() -> None:
                    nonlocal head, tail
                    async for _ in ws:
                        if time.time() - t0 < settle:
                            head += 1
                        else:
                            tail += 1
                with __import__("contextlib").suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(pump(), timeout=settle + watch)
        return head, tail
    return asyncio.run(run())


def test_only_the_active_tab_records(cli):
    cli.run("new", "--id", "d", "--transport", "dom")
    cli.run("goto", "-t", "d", cli.site + "about")          # 一动不动的一页
    cli.run("new-tab", "-t", "d", "-u", cli.site + "ticker")  # 一直在动的一页
    cli.run("select-tab", "-t", "d:0")                       # 切回不动的那个
    cli.until(lambda: cli.out("url", "-t", "d").strip().endswith("/about"),
              True, what="切回那张不动的页")

    head, tail = listen(str(cli.port), "d")

    # **新连上来的人得看得见东西** —— 至少 Meta + 一张全量快照
    assert head >= 2, f"开局什么都没补给观看端({head} 条)—— 那条腿是死的"
    # **后台那个一直在动的 tab,一条都不该混进来**
    assert tail == 0, f"当前页一动不动,却混进来 {tail} 条 —— 后台 tab 也在录"

    # 切过去之后,轮到它录
    cli.run("select-tab", "-t", "d:1")
    cli.until(lambda: cli.out("url", "-t", "d").strip().endswith("/ticker"),
              True, what="切到会动的那页")
    head2, tail2 = listen(str(cli.port), "d")
    assert head2 >= 2, f"切过去之后开局没补:{head2}"
    assert tail2 > 5, f"切过去了却几乎没有事件({tail2} 条)—— 它没在录"
