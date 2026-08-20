"""并排跑两条画面通道,看 DOM 流能不能顶掉 xpra 那一格。

    python3 examples/dom_stream/serve.py --port 7955 --url https://example.com
    # 然后浏览器打开 http://<机器>:7955/

**左边是 DOM 流**(把页面序列化成 NodeSnapshot 推过来,观看端自己重排),
**右边是 CDP 截屏**(第一条腿,像素)。同一个 tab、同一时刻,两边都能点。

这是拿来判断的,不是拿来用的 —— 要看的是三件事
([c §13.1](../../docs/v2/works/c-pixels.md#131-rrweb是一条来源但代价买不起)):

1. **画面对不对得上** —— canvas / video / 跨域 iframe 在左边会不会缺
2. **点得准不准** —— 左边点一下,右边的像素证明它到底点着了什么
3. **省多少** —— 状态栏里两条的字节数是分开算的
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from aiohttp import WSMsgType, web

from webmuxd.core.cdp import CDP
from webmuxd.runtime.process import resolve_browser

HERE = Path(__file__).parent
SNAPSHOT_JS = (HERE.parent / "trace_export" / "snapshot.js").read_text(encoding="utf-8")
PAGE = (HERE / "page.html").read_text(encoding="utf-8")
DEMO = (HERE / "demo.html").read_text(encoding="utf-8")

W, H = 1024, 768

#: 真实页面里每个带 id 的元素的位置。**这是量具,不是通道** ——
#: 观看端把替身里同一个 id 的位置和它一比,就知道点下去会不会偏。
#: 它的字节不计进两条通道的账。
BOXES_JS = """(() => {
  const o = {};
  for (const el of document.querySelectorAll('[id]')) {
    const r = el.getBoundingClientRect();
    if (r.width || r.height) o[el.id] = [+r.x.toFixed(1), +r.y.toFixed(1),
                                         +r.width.toFixed(1), +r.height.toFixed(1)];
  }
  return JSON.stringify(o);
})()"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Bridge:
    """一个 tab,两条通道,一份输入。"""

    def __init__(self) -> None:
        self.cdp: CDP | None = None
        self.sid = ""
        self.proc: subprocess.Popen | None = None
        self.profile = ""
        self.viewers: set[web.WebSocketResponse] = set()
        self.bytes = {"dom": 0, "cdp": 0, "_": 0}
        self.counts = {"dom": 0, "cdp": 0, "_": 0}
        self.last_snapshot = ""
        #: **静止页面不产帧。** 观看者是在 screencast 已经跑起来之后才连上的,
        #: 不留最后一帧的话,它会一直看着一块白 —— 第一次跑就踩到了。
        self.last_frame = ""

    async def start(self, url: str) -> None:
        exe = resolve_browser()
        port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="domstream-")
        self.proc = subprocess.Popen(
            [exe, "--headless=new", f"--remote-debugging-port={port}",
             f"--user-data-dir={self.profile}", "--no-first-run",
             f"--window-size={W},{H}", "--no-sandbox", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):                       # 等它把端口听起来
            try:
                self.cdp = await CDP.connect(f"http://127.0.0.1:{port}")
                break
            except Exception:
                await asyncio.sleep(0.25)
        if not self.cdp:
            raise RuntimeError("chrome 的 CDP 端口没等到")

        targets = await self.cdp.send("Target.getTargets")
        page = next(t for t in targets["targetInfos"] if t["type"] == "page")
        r = await self.cdp.send("Target.attachToTarget",
                                {"targetId": page["targetId"], "flatten": True})
        self.sid = r["sessionId"]
        await self.cdp.send("Page.enable", session_id=self.sid)
        await self.cdp.send("Runtime.enable", session_id=self.sid)

        self.cdp.on("Page.screencastFrame", self._on_frame)
        await self.cdp.send("Page.startScreencast",
                            {"format": "jpeg", "quality": 70,
                             "maxWidth": W, "maxHeight": H, "everyNthFrame": 1},
                            session_id=self.sid)
        asyncio.create_task(self._snapshot_loop())

    # ------------------------------------------------------------ 两条下行

    def _on_frame(self, params: dict, _sid: str | None) -> None:
        """第一条腿:整屏 JPEG。**回执必须发**,不发就再也不来帧。"""
        asyncio.create_task(self.cdp.send(
            "Page.screencastFrameAck", {"sessionId": params["sessionId"]},
            session_id=self.sid))
        self.last_frame = params["data"]
        self._push("cdp", {"c": "cdp", "data": params["data"]},
                   size=len(params["data"]) * 3 // 4)

    async def _snapshot_loop(self) -> None:
        """第三条腿的候选:DOM 序列化。

        **按固定节奏拉,不是按变化推** —— 页面里的 MutationObserver 只能告诉
        我们"脏了",序列化本身还是要拉一次。这里 100ms 一次,
        一样的就不发(和"静止不产帧"对齐)。
        """
        while True:
            await asyncio.sleep(0.1)
            if not self.viewers:
                continue
            try:
                r = await self.cdp.send(
                    "Runtime.evaluate",
                    {"expression": SNAPSHOT_JS, "returnByValue": True,
                     "awaitPromise": False}, session_id=self.sid)
                raw = (r.get("result") or {}).get("value")
            except Exception:
                continue
            if not raw or raw == self.last_snapshot:
                continue
            self.last_snapshot = raw
            self._push("dom", {"c": "dom", "snap": raw}, size=len(raw))
            try:
                b = await self.cdp.send(
                    "Runtime.evaluate",
                    {"expression": BOXES_JS, "returnByValue": True},
                    session_id=self.sid)
                boxes = (b.get("result") or {}).get("value")
            except Exception:
                boxes = None
            if boxes:
                self._push("_", {"c": "boxes", "boxes": boxes}, size=0)

    def _push(self, chan: str, msg: dict, *, size: int) -> None:
        self.bytes[chan] += size
        self.counts[chan] += 1
        msg["stats"] = {**self.bytes, "n": dict(self.counts)}
        blob = json.dumps(msg)
        for ws in list(self.viewers):
            if not ws.closed:
                asyncio.create_task(ws.send_str(blob))

    # -------------------------------------------------------------- 上行

    async def input(self, m: dict) -> None:
        """**两个 pane 的输入走同一条路。** 这正是要验的那一点:
        画面来源可以有两条,输入只有一条(b §1)。"""
        k = m.get("t")
        if k == "mouse":
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": m["type"], "x": m["x"], "y": m["y"],
                "button": m.get("button", "left"),
                "clickCount": m.get("clickCount", 1),
                "buttons": m.get("buttons", 0)}, session_id=self.sid)
        elif k == "wheel":
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": m["x"], "y": m["y"],
                "deltaX": m.get("dx", 0), "deltaY": m.get("dy", 0)},
                session_id=self.sid)
        elif k == "text":
            await self.cdp.send("Input.insertText", {"text": m["text"]},
                                session_id=self.sid)
        elif k == "key":
            for t in ("keyDown", "keyUp"):
                await self.cdp.send("Input.dispatchKeyEvent", {
                    "type": t, "key": m["key"], "code": m.get("code", ""),
                    "windowsVirtualKeyCode": m.get("vk", 0)},
                    session_id=self.sid)
        elif k == "nav":
            await self.cdp.send("Page.navigate", {"url": m["url"]},
                                session_id=self.sid)
            self.last_snapshot = ""

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7955)
    ap.add_argument("--bind", default="0.0.0.0")
    #: `SELF` 会替换成本服务的地址 —— 默认打开自带的靶页
    ap.add_argument("--url", default="SELF/demo")
    args = ap.parse_args()

    bridge = Bridge()
    # **先起 chrome 到 about:blank,端口听起来之后再导航** ——
    # 靶页 `/demo` 是这个服务自己提供的,先导过去会打在一个还没听的端口上。
    await bridge.start("about:blank")

    async def index(_r: web.Request) -> web.Response:
        return web.Response(text=PAGE, content_type="text/html")

    async def demo(_r: web.Request) -> web.Response:
        """自带的靶页:canvas、CSS 动画、表单、SVG 各一份 ——
        **DOM 流缺什么,在这一页上一眼就能看见。**"""
        return web.Response(text=DEMO, content_type="text/html")

    async def channel(request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=None, max_msg_size=0)
        await ws.prepare(request)
        bridge.viewers.add(ws)
        bridge.last_snapshot = ""              # 新观看者要一张完整的
        if bridge.last_frame:                  # 像素那条也补上最后一帧
            await ws.send_str(json.dumps({"c": "cdp", "data": bridge.last_frame,
                                          "stats": {**bridge.bytes,
                                                    "n": dict(bridge.counts)}}))
        try:
            async for msg in ws:
                if msg.type is WSMsgType.TEXT:
                    try:
                        await bridge.input(json.loads(msg.data))
                    except Exception as e:
                        print("input 出错:", e)
        finally:
            bridge.viewers.discard(ws)
        return ws

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/demo", demo)
    app.router.add_get("/ws", channel)
    app.router.add_get("/favicon.ico", lambda _r: web.Response(status=204))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, args.bind, args.port)
    await site.start()
    url = args.url.replace("SELF", f"http://127.0.0.1:{args.port}")
    await bridge.input({"t": "nav", "url": url})
    host = os.environ.get("PUBLIC_HOST", "127.0.0.1")
    print(f"\n  打开  http://{host}:{args.port}/\n"
          f"  左边 = DOM 流(观看端重排)   右边 = CDP 截屏(像素)\n"
          f"  页面:{url}\n")
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        bridge.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
