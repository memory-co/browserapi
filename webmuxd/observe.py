"""观测 —— docs/v1/api/act.md §1。

**一次调用拿到能直接喂给多模态模型的全部东西**,调用方零解析:
标注好编号的截图 + 元素表 + 正文 + tab 列表 + **盲区说明**。

那个盲区说明(`notes`)是刻意的:不说的话,模型会把"没看见"当成"不存在",
然后自信地做错决定(§1.2)。

**要像素就得在前台。** Chromium 不渲染后台 tab,所以对非激活 tab 观测前
必须先把它切过去 —— 这件事由上层编排(sdk/tab/read.md §3),
这个模块只管当前这个 target。
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

from webmuxd import locate
from webmuxd.cdp import CDP, CDPError
from webmuxd.models import Observation, PageInfo, Scroll, Size, TabInfo

#: 正文摘要给多少字(§1 的 `text=digest`)。
DIGEST_CHARS = 4000

async def observe(
    cdp: CDP,
    session_id: str,
    *,
    tab: str | None = None,
    viewport_only: bool = False,
    max_elements: int = locate.MAX_ELEMENTS,
    text: str = "digest",
    tabs: list[TabInfo] | None = None,
) -> Observation:
    snap = await locate.snapshot(cdp, session_id,
                                 max_elements=max_elements, viewport_only=viewport_only)
    page = await _page_info(cdp, session_id)
    notes = list(snap.notes)
    notes += await _blind_spots(cdp, session_id)

    body = ""
    if text != "none":
        body = await _text(cdp, session_id)
        if text == "digest" and len(body) > DIGEST_CHARS:
            body = body[:DIGEST_CHARS]
            notes.append(f"正文只给了前 {DIGEST_CHARS} 字,完整的用 text=full")

    return Observation(
        id="obs_" + uuid.uuid4().hex[:16],
        tab=tab, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        page=page, elements=snap.elements,
        # **观测不碰页面。** 编号只活在 `elements[].id` 和它的 `bbox` 里 ——
        # 要一张画好框的图,拿 bbox 自己叠
        # (docs/v2/issues/标注层会被人看见.md)。
        screenshot=await _capture(cdp, session_id),
        text=body, tabs=tabs or [], notes=notes,
        filter_version=locate.FILTER_VERSION)


# ---------------------------------------------------------------------------

_PAGE_JS = """(() => JSON.stringify({
  url: location.href, title: document.title,
  loading: document.readyState !== 'complete',
  scrollY: window.scrollY, maxY: Math.max(0, document.body
      ? document.body.scrollHeight - window.innerHeight : 0),
  w: window.innerWidth, h: window.innerHeight,
  screenW: screen.width, screenH: screen.height
}))()"""


async def _page_info(cdp: CDP, sid: str) -> PageInfo:
    try:
        r = await cdp.send("Runtime.evaluate",
                           {"expression": _PAGE_JS, "returnByValue": True},
                           session_id=sid)
        d = json.loads(r["result"]["value"])
    except Exception:
        return PageInfo()
    return PageInfo(
        url=d["url"], title=d["title"], loading=d["loading"],
        scroll=Scroll(d["scrollY"], d["maxY"]),
        viewport=Size(d["w"], d["h"]),
        # 桌面分辨率。**观看者一连上来就可能改掉它**(Xvnc 开着
        # `-AcceptSetDesktopSize`),一变响应式站点就重排、上一次的坐标作废。
        # 带出来,调用方才能发现"地动了"。
        screen=Size.from_json({"w": d.get("screenW"), "h": d.get("screenH")}))


_BLIND_JS = """(() => {
  const frames = [...document.querySelectorAll('iframe')];
  let opaque = 0;
  for (const f of frames) { try { void f.contentDocument.title; } catch (e) { opaque++; } }
  return JSON.stringify({frames: frames.length, opaque,
                         loading: document.readyState !== 'complete'});
})()"""


async def _blind_spots(cdp: CDP, sid: str) -> list[str]:
    """**明确告诉调用方这次观测看不见什么。**

    不说的话,模型会把"没看见"当成"不存在",然后自信地做错决定(§1.2)。
    """
    try:
        r = await cdp.send("Runtime.evaluate",
                           {"expression": _BLIND_JS, "returnByValue": True},
                           session_id=sid)
        d = json.loads(r["result"]["value"])
    except Exception:
        return []
    notes = []
    if d.get("opaque"):
        notes.append(f"页面有 {d['frames']} 个 iframe,其中 {d['opaque']} 个跨域读不到")
    if d.get("loading"):
        notes.append("页面还在加载,看到的可能不是最终样子")
    return notes


async def _text(cdp: CDP, sid: str) -> str:
    try:
        r = await cdp.send(
            "Runtime.evaluate",
            {"expression": "document.body ? document.body.innerText : ''",
             "returnByValue": True}, session_id=sid)
        return r["result"].get("value") or ""
    except CDPError:
        return ""


async def _capture(cdp: CDP, sid: str, *, full_page: bool = False) -> bytes:
    params: dict[str, Any] = {"format": "webp", "quality": 80}
    if full_page:
        # 整个滚动区域 —— **拍的不是人看到的东西**,要"所见即所得"就别带它
        params["captureBeyondViewport"] = True
    r = await cdp.send("Page.captureScreenshot", params, session_id=sid, timeout=20)
    return base64.b64decode(r["data"])
