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
from dataclasses import dataclass, field
from typing import Any

from webmuxd.core import locate
from webmuxd.core.cdp import CDP, CDPError
from webmuxd.core.locate import Element, Snapshot

#: 正文摘要给多少字(§1 的 `text=digest`)。
DIGEST_CHARS = 4000

#: 标注层用的颜色 —— 高对比,不挑页面背景。
_MARK_BG = "#ff2d55"


@dataclass
class Observation:
    """一次观测。`id` 是给按编号定位用的 —— 页面变了就该抛,
    而不是点到编号相同的另一个东西(§4)。"""

    id: str
    tab: str | None
    at: str
    page: dict[str, Any]
    elements: list[Element]
    screenshot: bytes = b""
    plain_screenshot: bytes = b""
    text: str = ""
    tabs: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    filter_version: int = locate.FILTER_VERSION

    def as_prompt(self) -> str:
        """紧凑表示,直接进 prompt(§1.3)。"""
        return "\n".join(e.as_line() for e in self.elements)

    def to_json(self, *, shot_url: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "observation_id": self.id, "tab": self.tab, "at": self.at,
            "page": self.page,
            "elements": [e.to_json() for e in self.elements],
            "tabs": self.tabs, "notes": self.notes,
            "filter_version": self.filter_version,
        }
        if self.text:
            out["text"] = self.text
        if shot_url:
            out["screenshot"] = {
                "url": shot_url, "plain_url": shot_url + "?annotate=false",
                "w": self.page.get("viewport", {}).get("w"),
                "h": self.page.get("viewport", {}).get("h"),
                "format": "webp",
            }
        return out


async def observe(
    cdp: CDP,
    session_id: str,
    *,
    tab: str | None = None,
    annotate: bool = True,
    viewport_only: bool = False,
    max_elements: int = locate.MAX_ELEMENTS,
    text: str = "digest",
    tabs: list[dict[str, Any]] | None = None,
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

    plain = await _capture(cdp, session_id)
    marked = plain
    if annotate and snap.elements:
        marked = await _capture_annotated(cdp, session_id, snap)

    return Observation(
        id="obs_" + uuid.uuid4().hex[:16],
        tab=tab, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        page=page, elements=snap.elements,
        screenshot=marked, plain_screenshot=plain,
        text=body, tabs=tabs or [], notes=notes)


# ---------------------------------------------------------------------------

_PAGE_JS = """(() => JSON.stringify({
  url: location.href, title: document.title,
  loading: document.readyState !== 'complete',
  scrollY: window.scrollY, maxY: Math.max(0, document.body
      ? document.body.scrollHeight - window.innerHeight : 0),
  w: window.innerWidth, h: window.innerHeight,
  screenW: screen.width, screenH: screen.height
}))()"""


async def _page_info(cdp: CDP, sid: str) -> dict[str, Any]:
    try:
        r = await cdp.send("Runtime.evaluate",
                           {"expression": _PAGE_JS, "returnByValue": True},
                           session_id=sid)
        d = json.loads(r["result"]["value"])
    except Exception:
        return {}
    return {"url": d["url"], "title": d["title"], "loading": d["loading"],
            "scroll": {"y": d["scrollY"], "max_y": d["maxY"]},
            "viewport": {"w": d["w"], "h": d["h"]},
            # 桌面分辨率。**观看者一连上来就可能改掉它**(Xvnc 开着
            # `-AcceptSetDesktopSize`),一变响应式站点就重排、上一次的坐标作废。
            # 带出来,调用方才能发现"地动了"。
            "screen": {"w": d.get("screenW"), "h": d.get("screenH")}}


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


# ---------------------------------------------------------------------------
# Set-of-Mark:在截图上画编号
# ---------------------------------------------------------------------------

_MARK_JS = """(marks) => {
  const layer = document.createElement('div');
  layer.id = '__webmuxd_marks';
  layer.style.cssText =
    'position:fixed;inset:0;z-index:2147483647;pointer-events:none';
  for (const m of marks) {
    const box = document.createElement('div');
    box.style.cssText =
      `position:absolute;left:${m.x}px;top:${m.y}px;width:${m.w}px;height:${m.h}px;`
      + `border:2px solid ${m.c};box-sizing:border-box`;
    const tag = document.createElement('div');
    tag.textContent = m.n;
    tag.style.cssText =
      `position:absolute;left:${m.x}px;top:${Math.max(0, m.y - 15)}px;`
      + `background:${m.c};color:#fff;font:11px/13px monospace;padding:0 3px;`
      + 'border-radius:2px';
    layer.appendChild(box); layer.appendChild(tag);
  }
  document.documentElement.appendChild(layer);
  return true;
}"""


async def _capture_annotated(cdp: CDP, sid: str, snap: Snapshot) -> bytes:
    """在页面上临时铺一层带编号的框,拍完立刻撤掉。

    **标注层是临时的、`pointer-events:none` 的**,而且是在元素表抓完**之后**
    才铺的 —— 否则它自己会被下一次快照当成页面内容。
    """
    marks = [{"n": e.id, "x": e.bbox[0], "y": e.bbox[1],
              "w": e.bbox[2], "h": e.bbox[3], "c": _MARK_BG}
             for e in snap.elements if e.in_viewport]
    if not marks:
        return await _capture(cdp, sid)
    try:
        await cdp.send("Runtime.evaluate", {
            "expression": f"({_MARK_JS})({json.dumps(marks)})",
            "returnByValue": True}, session_id=sid, timeout=10)
        return await _capture(cdp, sid)
    finally:
        # 撤掉。**finally 里做** —— 拍照失败也不能把标注层留在页面上,
        # 那会污染后面所有的观测和人看到的画面。
        try:
            await cdp.send("Runtime.evaluate", {
                "expression": "document.getElementById('__webmuxd_marks')?.remove()"},
                session_id=sid, timeout=5)
        except Exception:
            pass
