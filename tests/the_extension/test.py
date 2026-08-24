"""**装进被控浏览器的那个扩展** —— 它装上了没有,以及它真的在干活吗。

和 [`the_layout_holds/`](../the_layout_holds/) 一样是结构性的那一类,
但它必须起一个真浏览器 —— **"扩展装上了"这件事只有浏览器说了算**。

判据一律取自**浏览器那一侧**:`/json` 里那个 service_worker、
以及 `Browser.getWindowForTarget` 给的 `windowId`。拿我们自己的配置
验我们自己的配置,漂的时候一样是绿的。
"""

import asyncio
import contextlib
import json
import time

import pytest

from webmuxd import extension
from webmuxd.cdp import CDP

pytestmark = pytest.mark.asyncio

#: 会让 Chromium 开出一个**独立窗口**的 features。
#: `attributionsrc` 是**故意放在这儿的** —— sidecar 那张白名单放它过去
#: (那是个已知的洞),而这个扩展接得住。见
#: [`webmuxjs/extension/src/popup-to-tab.ts`](../../webmuxjs/extension/src/popup-to-tab.ts)。
POPUPY = ["width=400,height=300,left=10", "popup=1", "attributionsrc"]


def test_建出来了而且给得出参数():
    """**不起浏览器,永远会跑。**

    没建出来时 `path()` 回 `None` 而不是抛 —— 过渡期 sidecar 那半还在,
    缺了它不影响能不能用。但**在这棵树上跑测试时它必须在**,
    否则下面那几条验的是"没装扩展的浏览器"。
    """
    d = extension.path()
    assert d is not None, "扩展没建出来 —— 在 webmuxjs/extension/ 里 npm run build"
    assert (d / "manifest.json").exists() and (d / "sw.js").exists()
    m = json.loads((d / "manifest.json").read_text())
    assert m["manifest_version"] == 3
    # **权限面要小,而且要看得住。** 它不注入页面,所以不需要 host_permissions;
    # 多一条都要有人解释得清为什么。
    assert m["permissions"] == ["tabs"], m["permissions"]
    assert "host_permissions" not in m, "它不该要 host 权限 —— 它不碰页面"
    assert "content_scripts" not in m, "它不该有内容脚本 —— 那是 sidecar 的事"

    args = extension.args()
    assert len(args) == 1 and args[0].startswith("--load-extension=")
    # `--load-extension` 只收目录
    assert args[0].endswith(str(d))


@pytest.fixture
def browser(chromium_endpoint_with_extension):
    return chromium_endpoint_with_extension


async def test_浏览器里真的装上了(browser):
    """判据是**扩展自己报出来的那个标记**,不是我们传了什么参数。

    不靠文件名认它:浏览器自带的组件扩展里也有叫 `sw.js` 的。
    也不靠"我们传了 `--load-extension`":传了不等于装上了。
    """
    conn = await CDP.connect(browser)
    try:
        got = await _until_installed(conn)
        assert got is not None, "扩展没装上,或者它的 service worker 没跑起来"
        assert got["parts"] == ["popup-to-tab"], got
    finally:
        await conn.close()


async def test_popup_一律变成_tab_而且不碰页面(browser):
    """**三种会开出独立窗口的 features,全都得落回主窗口。**

    其中 `attributionsrc` 是 sidecar 那张白名单**放过去**的那个 ——
    这一条同时是"扩展比 shim 严"的证据。
    """
    conn = await CDP.connect(browser)
    try:
        # **先等它真的醒过来。** MV3 的 service worker 是懒启动的 ——
        # 不等就是在测"扩展还没跑起来的那个浏览器",而那会绿得莫名其妙
        # (第一版就这么红过,原因正好相反:红得莫名其妙)。
        assert await _until_installed(conn), "扩展没醒过来"
        t = (await conn.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
        sid = (await conn.send("Target.attachToTarget",
                               {"targetId": t, "flatten": True}))["sessionId"]
        main = (await conn.send("Browser.getWindowForTarget",
                                {"targetId": t}))["windowId"]

        # **页面上一个字节都没注** —— 这一条要先立住,否则下面测的是 shim
        clean = await conn.send(
            "Runtime.evaluate",
            {"expression": "String(window.open).includes('[native code]')"
                           " && typeof window.__wm_side",
             "returnByValue": True}, session_id=sid)
        assert clean["result"]["value"] == "undefined", \
            f"这个浏览器里有人注过东西,测出来的不是扩展:{clean}"

        for feat in POPUPY:
            before = {x["targetId"] for x in
                      (await conn.send("Target.getTargets"))["targetInfos"]}
            await conn.send("Runtime.evaluate", {
                "expression": f'window.open("about:blank","_blank",{json.dumps(feat)})',
                "userGesture": True}, session_id=sid)
            born = await _until_new(conn, before)
            where = await _settles_into(conn, born, main)
            assert where == main, \
                f"features={feat!r} 开出来的没被搬回主窗口(在 {where},主窗口 {main})"
    finally:
        await conn.close()


async def test_noopener_的_null_还在(browser):
    """**搬窗口不该改变页面看到的返回值。**

    `open-shim` 要靠一条正则**记得**把 `noopener` 留下;这边没人插手那个串,
    所以它自动成立 —— 但"自动成立"也要有人验,否则哪天有人加了个过滤就没了。
    """
    conn = await CDP.connect(browser)
    try:
        t = (await conn.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
        sid = (await conn.send("Target.attachToTarget",
                               {"targetId": t, "flatten": True}))["sessionId"]
        r = await conn.send("Runtime.evaluate", {
            "expression": '(() => { const w = window.open("about:blank","_blank",'
                          '"noopener,width=400"); return w === null ? "null" : "Window" })()',
            "userGesture": True, "returnByValue": True}, session_id=sid)
        assert r["result"]["value"] == "null", \
            "带 noopener 开出来的应该是 null —— 有人动了那个 features 串"
    finally:
        await conn.close()


# ---------------------------------------------------------------- 小工具

async def _until_installed(conn: CDP, timeout: float = 15.0) -> dict | None:
    """等扩展报出自己。**不睡一个秒数。**"""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        got = await extension.installed(conn)
        if got:
            return got
        await asyncio.sleep(0.1)
    return None


async def _until_new(conn: CDP, before: set, timeout: float = 8.0) -> str:
    """等那个新 target 出现。**不睡一个秒数。**"""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        now = (await conn.send("Target.getTargets"))["targetInfos"]
        new = [x for x in now if x["targetId"] not in before and x["type"] == "page"]
        if new:
            return new[0]["targetId"]
        await asyncio.sleep(0.05)
    raise AssertionError("window.open 没开出东西来 —— 这条用例什么都没验")


async def _settles_into(conn: CDP, target: str, want: int, timeout: float = 8.0) -> int:
    """等它落到某个窗口上。

    **搬是事后的**:popup 窗口真的被创建了,扩展收到 `onCreated` 才搬 ——
    所以这儿等的是"落定",不是"一开始就在"。
    """
    end = time.monotonic() + timeout
    got = -1
    while time.monotonic() < end:
        with contextlib.suppress(Exception):
            got = (await conn.send("Browser.getWindowForTarget",
                                   {"targetId": target}))["windowId"]
            if got == want:
                return got
        await asyncio.sleep(0.05)
    return got
