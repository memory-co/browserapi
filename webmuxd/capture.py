"""**从页面上读出来的:一张图,和正文。**

    GET /api/screenshot   → Page.captureScreenshot
    GET /api/text         → document.body.innerText

第三样是元素表(`GET /api/snapshot`),它在 [`locate.py`](locate.py) ——
放在那儿是因为**发号那件事和定位是同一套机器**,不是两份。

> 这儿以前是 `observe.py`:一次调用回一包东西 —— 筛过的元素表、编好的号、
> 一次观测的 id、盲区 notes、页面信息、截图、正文。砍掉了,而且**砍对了一半**。
>
> 对的那一半:**一次调用回一整包**不该有。截图、正文、元素表是三件事,
> 要哪样取哪样 —— 这也是 `capture-pane` 的样子。
>
> 错的那一半:连元素表这个口子一起砍了,理由是"那是一套关于 agent
> 该怎么用浏览器的意见"。**但那套意见此刻仍然在跑** ——
> `click("登录")` 每次都要先筛一遍 AX 树。藏起来没让赌注变小,
> 只是让它没法被人调。这一版把旋钮交出去了(`-i` / `-s` / `--viewport`)。
>
> 详见 [i §3](../docs/v2/works/i-agent-surface.md);线上那几个口子在
> [v2/api](../docs/v2/api/)。
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
