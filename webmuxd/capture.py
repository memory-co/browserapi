"""**从页面上读出来的两样东西:一张图,和正文。**

    GET /api/screenshot   → Page.captureScreenshot
    GET /api/text         → document.body.innerText

就这么多。**这是"读"这一面的全部。**

> 这儿以前是 `observe.py`:一次调用回一包东西 —— 筛过的元素表、编好的号、
> 一次观测的 id、盲区 notes、页面信息、截图、正文。砍掉了。
>
> 判据是这项目那句老话:**tmux 会做这个吗?** 它有 `capture-pane`,
> 就是这两样;它没有"把屏幕上的东西筛一遍编上号再给你"。
> 那是一套**关于 agent 该怎么用浏览器的意见**,而意见该留在调用方那边。
>
> 元素表没有消失,它在 [`locate.py`](locate.py) —— 但那是 `act` 定位用的,
> `click("登录")` 需要它。**它是动作的一部分,不是一个读的口子。**
> 详见 [i §3](../docs/v2/works/i-agent-surface.md);
> 线上那两个口子在 [v2/api](../docs/v2/api/)。
"""

from __future__ import annotations

import base64
from typing import Any

from webmuxd.cdp import CDP, CDPError


async def screenshot(cdp: CDP, sid: str, *, full_page: bool = False) -> bytes:
    """那一刻的页面。**WebP,不是 PNG** —— 同样画质小一半。

    要像素就得在前台:Chromium 不渲染后台 tab,拍出来是白的或旧的。
    切到前台是 `sessions.py` 的事,这儿只管拍。
    """
    params: dict[str, Any] = {"format": "webp", "quality": 80}
    if full_page:
        # 整个滚动区域 —— **拍的不是人看到的东西**,要"所见即所得"就别带它
        params["captureBeyondViewport"] = True
    r = await cdp.send("Page.captureScreenshot", params, session_id=sid, timeout=20)
    return base64.b64decode(r["data"])


async def text(cdp: CDP, sid: str) -> str:
    """正文。**`innerText` 不是 `textContent`** —— 前者是"看得见的字",
    后者会把 `<script>` 里的代码和 `display:none` 的东西一起给你。

    取不到就回空串:一个读不出正文的页面(比如纯 canvas)不是错误。
    """
    try:
        r = await cdp.send(
            "Runtime.evaluate",
            {"expression": "document.body ? document.body.innerText : ''",
             "returnByValue": True}, session_id=sid)
        return r["result"].get("value") or ""
    except CDPError:
        return ""
