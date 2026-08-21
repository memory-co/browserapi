""""读"这一面 —— **一张图,和正文,就这两样。**

这儿以前是 `test_observe.py`,对着一个会回一整包东西的 `/api/observe` 校。
那个口子砍了([capture.py](../../webmuxd/capture.py)),所以这一篇也短了 ——
**短本身就是那次决定的样子**。
"""

import asyncio

import pytest

from webmuxd import capture

pytestmark = pytest.mark.asyncio

PAGE = (
    "data:text/html;charset=utf-8,"
    "<title>结算</title>"
    "<button>提交订单</button><button>取消订单</button>"
    "<label for=c>优惠码</label><input id=c>"
    "<p>" + "正文内容。" * 50 + "</p>"
)


async def _goto(cdp, sid, url=PAGE):
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {"url": url}, session_id=sid)
    await asyncio.sleep(0.6)


async def test_截图就是一张_webp(cdp, page):
    """**WebP 不是 PNG** —— 同样画质小一半,而这条流量是要走网络的。"""
    _tid, sid = page
    await _goto(cdp, sid)
    shot = await capture.screenshot(cdp, sid)
    assert shot[:4] == b"RIFF" and shot[8:12] == b"WEBP"


async def test_正文取的是看得见的字(cdp, page):
    """`innerText`,不是 `textContent` —— 后者会把 `<script>` 里的代码
    和 `display:none` 的东西一起给你。"""
    _tid, sid = page
    await _goto(cdp, sid)
    body = await capture.text(cdp, sid)
    assert "正文内容" in body
    assert "提交订单" in body


async def test_读一眼不许改页面(cdp, page):
    """**这是结构性的。**

    以前的 `observe` 会在活页面上铺一层带编号的框再拍,于是观看的人看到一闪
    (docs/v2/issues/标注层会被人看见.md)。现在验的是"**根本没动过**"。
    """
    _tid, sid = page
    await _goto(cdp, sid)

    async def fingerprint():
        r = await cdp.send("Runtime.evaluate", {
            "expression": "document.documentElement.outerHTML.length + '/' "
                          "+ document.querySelectorAll('*').length",
            "returnByValue": True}, session_id=sid)
        return r["result"]["value"]

    before = await fingerprint()
    await capture.screenshot(cdp, sid)
    await capture.text(cdp, sid)
    assert await fingerprint() == before, "读一眼把页面改了"


async def test_读不出正文的页面不算错(cdp, page):
    """纯 canvas 的页面没有正文 —— 那是事实,不是异常。"""
    _tid, sid = page
    await _goto(cdp, sid, "data:text/html,<canvas width=10 height=10></canvas>")
    assert await capture.text(cdp, sid) == ""


async def test_整页和视口是两张图(cdp, page):
    """`full_page` 拍的是整个滚动区域 —— **不是人看到的东西**,
    所以它不是默认。"""
    _tid, sid = page
    await _goto(cdp, sid, "data:text/html,<div style='height:4000px'>长</div>")
    small = await capture.screenshot(cdp, sid)
    big = await capture.screenshot(cdp, sid, full_page=True)
    assert len(big) > len(small)
