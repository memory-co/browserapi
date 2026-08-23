"""**浏览器把哪一页放在前台 —— 那就是 `active`。**

tab 表里的每一样都来自浏览器自己的 target 表:开、关、url、title。
`active` 原来是唯一的例外:我们单方面记一本账,再用 `Target.activateTarget`
把浏览器拽过来对齐。那本账有一个没写出来的前提 —— **只有我们会动前台** ——
而它是错的:页面 `target=_blank` 开出来的 tab,Chromium 直接切过去,不发任何事件。

漂了之后两条腿各错各的、都不报错:VNC 上人看到的是新那页而 tab 条指着旧那页;
JPG 上截屏挂在一个后台 target 上,画面冻在最后一帧,**看着还挺一致**。

现在那个例外没了:

> **`active` 是观测值。我们的命令只是发个信号,等那一页自己报回来才算数。**

让浏览器说了算的理由不是"省事",是**它判得对**:同一个 `target=_blank` 链接,
普通左键前台开、Ctrl+左键和中键后台开 —— 人的意图靠手势表达,Chromium 解释它。
我们没有比这更好的判据(那条三种点法的实测在 `v2_browser_new_tab`,
因为它要走完整条输入腿)。

这儿的判据一律取自**页面那一侧**的 `document.visibilityState`,
经第二条 CDP 连接读回来。拿我们那张表去验我们那张表,漂的时候一样是绿的。

对应 [f §3](../../docs/v2/works/f-tabs.md)。
"""

import asyncio
import contextlib
import time

import pytest

from webmuxd.cdp import CDP
from webmuxd.sessions import Session

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def live(chromium_endpoint, tmp_path):
    """一个真的 session,外加**一条独立的 CDP 用来读真相**。

    第二条连接就是那个逃生舱:我们看到的东西,标准工具能独立看到。

    **先把这个 Chromium 上残留的 page target 清干净。** `chromium_endpoint`
    是 session 级的 —— 整个测试跑共用一个浏览器。而这儿问的是"**前台是谁**",
    一个别的用例留下来的 tab 会直接把答案搅浑:`Session.start()` 会把它们
    一并收进表里,于是"只有 active 那个 visible"这条判据从一开始就不成立。
    (单跑绿、跑全量红,就是这么来的。)
    """
    conn = await CDP.connect(chromium_endpoint)
    for t in (await conn.send("Target.getTargets"))["targetInfos"]:
        if t.get("type") == "page":
            with contextlib.suppress(Exception):
                await conn.send("Target.closeTarget", {"targetId": t["targetId"]})
    session = Session(conn, data_dir=tmp_path, human_yield_ms=0)
    await session.start()
    truth = await CDP.connect(chromium_endpoint)
    try:
        yield session, truth
    finally:
        await truth.close()
        with contextlib.suppress(Exception):
            await session.close()
        await conn.close()


async def visibility(truth: CDP, target_id: str) -> str:
    """问那一页自己:你是不是在前台。**不问我们那张表。**"""
    sid = (await truth.send("Target.attachToTarget",
                            {"targetId": target_id, "flatten": True}))["sessionId"]
    try:
        r = await truth.send(
            "Runtime.evaluate",
            {"expression": "document.visibilityState", "returnByValue": True},
            session_id=sid)
        return r["result"]["value"]
    finally:
        with contextlib.suppress(Exception):
            await truth.send("Target.detachFromTarget", {"sessionId": sid})


async def until(pred, timeout: float = 8.0, what: str = ""):
    """等那件事发生,**不睡一个秒数**。"""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = pred()
        if asyncio.iscoroutine(last):
            last = await last
        if last:
            return last
        await asyncio.sleep(0.1)
    raise AssertionError(f"等不到:{what}(最后一次看到 {last!r})")


async def agrees(session: Session, truth: CDP) -> bool:
    """我们说 active 的那个,浏览器也把它放在前台;其余的都在后台。"""
    for tab in session.tabs.list():
        want = "visible" if tab.id == session.tabs.active else "hidden"
        if await visibility(truth, tab.target_id) != want:
            return False
    return True


async def test_浏览器把前台给谁_我们就跟谁(live):
    """**页面自己开了个前台 tab —— 我们跟过去。**

    这一条以前是反着写的("焦点不跟过去"),而那条规矩只写在我们的字段里,
    浏览器那边从没成立过 —— 于是它同时是**假的**和**全绿的**。

    现在是真的,因为判据来自那一页自己:它说自己 `visible`,我们才认。
    """
    session, truth = live
    first = session.tabs.active
    assert first
    await session.executor_for(first)

    sid = await session.cdp_session_for(first)
    r = await session.cdp.send(
        "Runtime.evaluate",
        {"expression": "window.open('about:blank', '_blank')", "userGesture": True},
        session_id=sid)
    # **弹被拦了要当场说。** 不然它会表现成下面那句"等不到",
    # 而"等不到"看着像我们的 bug,其实是这条用例自己没立起来。
    assert (r.get("result") or {}).get("subtype") != "null", \
        f"window.open 返回 null —— 弹窗被拦了,这条用例什么都没验:{r}"

    born = await until(
        lambda: next((t for t in session.tabs.list()
                      if t.id != first and t.reason == "page"), None),
        timeout=20, what="页面把那个 tab 开出来")
    assert born.opener == first, f"该认得爹:{born}"

    # **普通的 `window.open` 是前台开** —— Chromium 这么判的,我们跟着。
    await until(lambda: session.tabs.active == born.id, timeout=20,
                what="active 跟到浏览器真的放在前台那一页上")
    assert await until(lambda: agrees(session, truth),
                       what="表里的 active 和页面自己说的对得上")


async def test_我们发的切换_返回的时候已经是真的了(live):
    """**`activate()` 是"发信号 + 等回流",不是"改字段 + 宣布"。**

    判据很硬:`await activate()` 一返回,**立刻**去问那一页 ——
    不轮询、不重试、不给一点余量。它必须已经是 `visible`。

    原来那句是先改 `self._active` 再发命令,所以它返回得更早、
    而且返回的时候那件事**可能根本没发生**。这次那个"画面上是新闻页、
    tab 条却指着首页"就是这么来的。
    """
    session, truth = live
    first = session.tabs.active
    assert first
    second = await session.tabs.open("about:blank")
    assert session.tabs.active == second.id

    back = await session.tabs.activate(first)
    assert back.id == first
    # **一个 await 都不多。** 返回即为真,否则这条就没意义。
    assert await visibility(truth, session.tabs.get(first).target_id) == "visible", \
        "activate() 返回了,但那一页还不在前台 —— 它宣布得太早"
    assert session.tabs.active == first
    assert await agrees(session, truth)


async def test_别人把前台抢走_我们跟着走(live):
    """这一条验的是**那条订阅**本身。

    tab 早就建好了,抢前台的是一条**独立的 CDP 连接** —— 我们这边没有任何
    代码"知道"发生过这件事。能不能跟上,只取决于那一页报上来的 `foreground`。

    (以前这条叫"我们按得回去"。按回去的前提是 `active` 归我们定 ——
    那个前提没了。**现在浏览器说了算,我们跟着记账。**)
    """
    session, truth = live
    first = session.tabs.active
    assert first
    second = await session.tabs.open("about:blank")
    assert session.tabs.active == second.id
    assert await agrees(session, truth), "起点是对齐的"

    # 第三方动手:直接 activateTarget,**不经过我们那张表**
    await truth.send("Target.activateTarget",
                     {"targetId": session.tabs.get(first).target_id})

    await until(lambda: session.tabs.active == first, timeout=20,
                what="active 跟上第三方切过去的那一页")
    assert await until(lambda: agrees(session, truth), what="跟完之后两边一致")
