"""画面来自 Playwright 那套 DOM 快照(按操作打点),只读;输入全走 CDP。

    python3 examples/trace_console/serve.py --port 9090
    # 打开 http://<这台机器>:9090/

和 [rrweb_console](../rrweb_console/) 是同一个外壳、同一条输入路径,
**只换了画面从哪来** —— 所以两个端口可以并排开着直接比。

| | rrweb(8090 那个) | 这里 |
| --- | --- | --- |
| 画面 | **增量链**:一张全量快照 + 之后每一次 DOM 变更 | **离散全量快照**:每次操作前后各打一张 |
| 一条坏了 | **之后全错**,且不自恢复 | **只错这一张**,下一张照样对 |
| 页面里注入 | rrweb 记录器,**五百多 KB** | 只有一个**十几行的光标探针** |
| 中间过程 | 连续,动画看得到 | **没有**,只有"操作前 / 操作后"两态 |

第三行是这条路被低估的地方:**它不需要往页面里塞一个大库。**
快照是我们从外面用 `Runtime.evaluate` 拉的,页面里只多一个探针。

第四行是它的代价,而且这个代价对"记录 tab 操作行为"这个目标不算代价 ——
你关心的本来就是每次操作前后的状态差。

**画面是死的。** 重放出来的 DOM 整个 `pointer-events: none`,
上面盖着一层接收层。所有输入翻译成 `Input.*` 送进真正那个 tab
([b §1](../../docs/v2/works/b-input.md#1-收口在哪))。

顺带:这里攒的就是**一份真的 Playwright trace**,`/trace.zip` 下下来
`npx playwright show-trace` 直接能开。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import mimetypes
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

from webmuxd.cdp import CDP
from webmuxd.processes import resolve_browser

HERE = Path(__file__).parent
PAGE = (HERE / "page.html").read_text(encoding="utf-8")
SNAPSHOT_JS = (HERE.parent / "trace_export" / "snapshot.js").read_text(encoding="utf-8")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")

W, H = 1280, 800
TRACE_VERSION = 8
#: 保留多少条动作。**要有上限** —— 每次都重拼整包,不封顶的话越用越慢。
KEEP = 40
#: 操作之后等这么久再打「后」那张,给页面反应时间。
SETTLE = 0.35

#: 光标白名单。取值会写进观看端的 `style.cursor`,而远端页面不可信 ——
#: 没见过的一律降级 `default`([b §5](../../docs/v2/works/b-input.md#5-光标同步))。
CURSORS = frozenset("""
auto default none context-menu help pointer progress wait cell crosshair text
vertical-text alias copy move no-drop not-allowed grab grabbing e-resize
n-resize ne-resize nw-resize s-resize se-resize sw-resize w-resize ew-resize
ns-resize nesw-resize nwse-resize col-resize row-resize all-scroll zoom-in
zoom-out
""".split())

URL_ATTRS = ("src", "poster", "xlink:href", "data")
HREF_TAGS = ("link", "image", "use")

#: 页面里**只注入这一个探针**。对比一下:rrweb 那条要注五百多 KB。
PROBE_JS = """
(() => {
  if (window.__tcOn) return;
  if (window.top !== window) return;
  if (!/^https?:$/.test(location.protocol)) return;
  window.__tcOn = 1;
  let last = "";
  addEventListener("mousemove", (e) => {
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const c = el ? getComputedStyle(el).cursor : "default";
    if (c !== last) { last = c; try { window.__tcCursor(c); } catch (_) {} }
  }, true);
})()
"""

#: 命中什么,用来给动作起名字 —— 和 webmuxd 的 `hit` 是一回事。
HIT_JS = """(x, y) => {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const label = (el.getAttribute('aria-label') || el.innerText ||
                 el.getAttribute('placeholder') || el.name || el.id || el.tagName)
                .toString().trim().replace(/\\s+/g, ' ').slice(0, 28);
  return { label, bbox: [+r.x.toFixed(1), +r.y.toFixed(1),
                         +r.width.toFixed(1), +r.height.toFixed(1)] };
}"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Trace:
    """攒一份真的 Playwright trace,并且随时能拼成 zip。"""

    def __init__(self) -> None:
        self.t0 = time.time()
        self.wall0 = self.t0 * 1000
        self.actions: list[dict] = []          # {callId, title, method, params, t0, t1, point, before, after}
        self.res: dict[str, tuple[str, bytes]] = {}   # url -> (mime, bytes)
        self.seq = 0

    def ms(self) -> float:
        return (time.time() - self.t0) * 1000

    def add(self, a: dict) -> None:
        self.actions.append(a)
        if len(self.actions) > KEEP:
            self.actions = self.actions[-KEEP:]

    def zip(self) -> bytes:
        ev: list[dict] = [{
            "version": TRACE_VERSION, "type": "context-options", "origin": "library",
            "browserName": "chromium", "platform": "linux",
            "wallTime": self.wall0, "monotonicTime": 0.0,
            "title": "webmuxd · trace 控制台", "sdkLanguage": "python",
            "options": {"viewport": {"width": W, "height": H},
                        "deviceScaleFactor": 1},
        }]
        files: dict[str, bytes] = {}
        net: list[str] = []
        used: set[str] = set()

        for a in self.actions:
            cid, pid = a["callId"], "page@main"
            before = {"type": "before", "callId": cid, "startTime": a["t0"],
                      "title": a["title"], "class": "Tab", "method": a["method"],
                      "params": a.get("params") or {}, "pageId": pid}
            if a.get("before"):
                before["beforeSnapshot"] = f"before@{cid}"
            ev.append(before)
            for tag in ("before", "after"):
                snap = a.get(tag)
                if not snap:
                    continue
                if tag == "after":
                    if a.get("point"):
                        ev.append({"type": "input", "callId": cid, "point": a["point"]})
                    ev.append({"type": "after", "callId": cid, "endTime": a["t1"],
                               "afterSnapshot": f"after@{cid}"})
                ev.append(self._snap_event(snap, f"{tag}@{cid}", cid, pid,
                                           a["t0"] if tag == "before" else a["t1"]))
                used.update(snap.get("urls") or [])
            if not a.get("after"):
                ev.append({"type": "after", "callId": cid, "endTime": a["t1"]})

        # **资源打进包里,不指回我们。** trace viewer 是 https 的,
        # 指回一个 http 地址会被当混合内容拦掉 —— 打进包它就同源了。
        for url in used:
            hit = self.res.get(url)
            if not hit:
                continue
            mime, blob = hit
            ext = mimetypes.guess_extension(mime.split(";")[0].strip()) or ".bin"
            sha = hashlib.sha1(blob).hexdigest() + ext
            files[f"resources/{sha}"] = blob
            net.append(json.dumps({"type": "resource-snapshot", "snapshot": {
                "pageref": "page@main", "_frameref": "frame@main",
                "_monotonicTime": 0, "_resourceType": "image",
                "startedDateTime": "1970-01-01T00:00:00.000Z", "time": 0,
                "cache": {}, "timings": {},
                "request": {"method": "GET", "url": url, "httpVersion": "HTTP/1.1",
                            "cookies": [], "headers": [], "queryString": [],
                            "headersSize": -1, "bodySize": 0},
                "response": {"status": 200, "statusText": "OK",
                             "httpVersion": "HTTP/1.1", "cookies": [], "headers": [],
                             "content": {"size": len(blob), "mimeType": mime,
                                         "compression": 0, "_sha1": sha},
                             "headersSize": -1, "bodySize": len(blob),
                             "redirectURL": "", "_transferSize": len(blob)},
            }}, ensure_ascii=False))

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr("trace.trace",
                       "\n".join(json.dumps(e, ensure_ascii=False) for e in ev))
            z.writestr("trace.network", "\n".join(net))
            for name, blob in files.items():
                z.writestr(name, blob)
        return buf.getvalue()

    @staticmethod
    def _snap_event(snap: dict, name: str, cid: str, pid: str, ts: float) -> dict:
        return {"type": "frame-snapshot", "snapshot": {
            "callId": cid, "snapshotName": name, "pageId": pid,
            "frameId": "frame@main", "frameUrl": snap.get("url") or "about:blank",
            "timestamp": ts, "collectionTime": 0,
            "doctype": snap.get("doctype") or None, "html": snap["html"],
            "resourceOverrides": [], "isMainFrame": True,
            "viewport": snap.get("viewport") or {"width": W, "height": H},
        }}


class Console:
    def __init__(self) -> None:
        self.cdp: CDP | None = None
        self.sid = ""
        self.proc: subprocess.Popen | None = None
        self.profile = ""
        self.viewers: set[web.WebSocketResponse] = set()
        self.tr = Trace()
        self.page_url = ""
        self.cursor = "default"
        self.shot: dict | None = None          # 最新那张,新观看者直接拿它
        self.version = 0
        self.bytes = {"snap": 0, "res": 0}
        self._pending: dict[str, dict] = {}
        self._settle: asyncio.TimerHandle | None = None
        self._typing: dict | None = None
        self._type_timer: asyncio.TimerHandle | None = None

    # ------------------------------------------------------------------ 起

    async def start(self, url: str) -> None:
        exe = resolve_browser()
        port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="traceconsole-")
        self.proc = subprocess.Popen(
            [exe, "--headless=new", f"--remote-debugging-port={port}",
             f"--user-data-dir={self.profile}", "--no-first-run",
             f"--window-size={W},{H}", "--no-sandbox", url],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                self.cdp = await CDP.connect(f"http://127.0.0.1:{port}")
                break
            except Exception:
                await asyncio.sleep(0.25)
        if not self.cdp:
            raise RuntimeError("chrome 的 CDP 端口没等到")

        t = await self.cdp.send("Target.getTargets")
        page = next(x for x in t["targetInfos"] if x["type"] == "page")
        r = await self.cdp.send("Target.attachToTarget",
                                {"targetId": page["targetId"], "flatten": True})
        self.sid = r["sessionId"]
        for m in ("Page.enable", "Runtime.enable", "Network.enable"):
            await self.cdp.send(m, session_id=self.sid)
        await self.cdp.send("Emulation.setDeviceMetricsOverride",
                            {"width": W, "height": H, "deviceScaleFactor": 1,
                             "mobile": False}, session_id=self.sid)
        await self.cdp.send("Runtime.addBinding", {"name": "__tcCursor"},
                            session_id=self.sid)
        await self.cdp.send("Page.addScriptToEvaluateOnNewDocument",
                            {"source": PROBE_JS}, session_id=self.sid)
        self.cdp.on("Runtime.bindingCalled", self._on_cursor)
        self.cdp.on("Page.frameNavigated", self._on_nav)
        self.cdp.on("Page.loadEventFired", self._on_load)
        self.cdp.on("Network.responseReceived", self._on_resp)
        self.cdp.on("Network.loadingFinished", self._on_done)

    # ------------------------------------------------------------ 画面:拉

    async def snap(self) -> dict | None:
        """**拉一张全量 DOM 快照。** 不是订阅变更 —— 这条路没有增量链,
        所以也没有"错一条之后全错"这回事。"""
        try:
            r = await self.cdp.send(
                "Runtime.evaluate",
                {"expression": SNAPSHOT_JS, "returnByValue": True},
                session_id=self.sid)
            raw = (r.get("result") or {}).get("value")
        except Exception:
            return None
        if not raw:
            return None
        try:
            snap = json.loads(raw)
        except Exception:
            return None
        urls: set[str] = set()
        self._rw_node(snap.get("html"), urls)
        snap["urls"] = sorted(urls)
        self.bytes["snap"] += len(raw)
        return snap

    def publish(self, snap: dict | None, *, why: str) -> None:
        if not snap:
            return
        self.shot = snap
        self.version += 1
        self._push({"c": "shot", "v": self.version, "why": why,
                    "url": snap.get("url", ""), "b": self.bytes,
                    "n": len(self.tr.actions), "snap": snap})

    def _later(self, why: str, delay: float = SETTLE) -> None:
        """页面自己变了(导航完成、资源到齐)也要重打一张,否则画面会停住。
        **这是事件驱动的,不是定时轮询** —— 静止的页面一张都不多打。"""
        if self._settle:
            self._settle.cancel()
        loop = asyncio.get_running_loop()
        self._settle = loop.call_later(
            delay, lambda: asyncio.create_task(self._settled(why)))

    async def _settled(self, why: str) -> None:
        self._settle = None
        self.publish(await self.snap(), why=why)

    # -------------------------------------------------------- 页面传出来

    def _on_cursor(self, params: dict, _sid: str | None) -> None:
        if params.get("name") != "__tcCursor":
            return
        c = (params.get("payload") or "").split(",")[0].strip().strip("'\"")
        c = c if c in CURSORS else "default"
        if c != self.cursor:
            self.cursor = c
            self._push({"c": "cursor", "v": c})

    def _on_nav(self, params: dict, _sid: str | None) -> None:
        f = params.get("frame") or {}
        if f.get("parentId"):
            return
        self.page_url = f.get("url", "") or self.page_url
        self._push({"c": "url", "v": self.page_url})

    def _on_load(self, _params: dict, _sid: str | None) -> None:
        self._later("加载完成", 0.4)

    def _push(self, msg: dict) -> None:
        blob = json.dumps(msg, ensure_ascii=False)
        for ws in list(self.viewers):
            if not ws.closed:
                asyncio.create_task(ws.send_str(blob))

    # ------------------------------------------------- 资源:一律经过我们

    def _rw(self, url: str, seen: set[str]) -> str:
        if not url or not url.startswith(("http://", "https://")):
            return url
        seen.add(url)
        return f"/res?u={quote(url, safe='')}"

    def _rw_css(self, css: str, seen: set[str]) -> str:
        return re.sub(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)",
                      lambda m: f"url({self._rw(m.group(1), seen)})", css)

    def _rw_node(self, n: Any, seen: set[str]) -> None:
        """快照是嵌套数组:`[标签, {属性}, ...子节点]`。按结构走,不用正则扫整串。"""
        if not isinstance(n, list) or not n or not isinstance(n[0], str):
            if isinstance(n, list):
                for x in n:
                    self._rw_node(x, seen)
            return
        tag = n[0].lower()
        if len(n) > 1 and isinstance(n[1], dict):
            a = n[1]
            for k in URL_ATTRS:
                if isinstance(a.get(k), str):
                    a[k] = self._rw(a[k], seen)
            if tag in HREF_TAGS and isinstance(a.get("href"), str):
                a["href"] = self._rw(a["href"], seen)
            if isinstance(a.get("srcset"), str):
                a["srcset"] = ", ".join(
                    " ".join([self._rw(p.split(" ")[0], seen)] + p.split(" ")[1:])
                    for p in (x.strip() for x in a["srcset"].split(",")) if p)
            if isinstance(a.get("style"), str):
                a["style"] = self._rw_css(a["style"], seen)
        for x in n[2:]:
            self._rw_node(x, seen)

    def _on_resp(self, params: dict, _sid: str | None) -> None:
        if params.get("type") in ("Image", "Media", "Font", "Stylesheet", "Other"):
            r = params.get("response") or {}
            self._pending[params["requestId"]] = {"url": r.get("url", ""),
                                                  "mime": r.get("mimeType", "")}

    def _on_done(self, params: dict, _sid: str | None) -> None:
        info = self._pending.pop(params.get("requestId", ""), None)
        if info and info["url"] and info["url"] not in self.tr.res:
            asyncio.create_task(self._grab(params["requestId"], info))
        self._later("资源到齐", 0.6)

    async def _grab(self, rid: str, info: dict) -> None:
        try:
            r = await self.cdp.send("Network.getResponseBody",
                                    {"requestId": rid}, session_id=self.sid)
        except Exception:
            return
        body = r.get("body") or ""
        raw = base64.b64decode(body) if r.get("base64Encoded") else body.encode()
        if len(raw) <= 8 * 1024 * 1024:
            self.tr.res[info["url"]] = (info["mime"] or "application/octet-stream", raw)
            self.bytes["res"] += len(raw)

    async def fetch_res(self, url: str) -> tuple[str, bytes] | None:
        hit = self.tr.res.get(url)
        if hit:
            return hit
        try:
            headers = {"User-Agent": UA}
            if self.page_url:
                headers["Referer"] = self.page_url
            async with ClientSession(timeout=ClientTimeout(total=20)) as sess:
                async with sess.get(url, headers=headers) as r:
                    if r.status >= 400:
                        return None
                    body = await r.read()
                    if len(body) > 8 * 1024 * 1024:
                        return None
                    mime = r.headers.get("Content-Type", "application/octet-stream")
        except Exception:
            return None
        self.tr.res[url] = (mime, body)
        self.bytes["res"] += len(body)
        return self.tr.res[url]

    # ------------------------------------------------------- 动作打点

    async def _hit(self, x: float, y: float) -> dict | None:
        try:
            r = await self.cdp.send(
                "Runtime.evaluate",
                {"expression": f"({HIT_JS})({x}, {y})", "returnByValue": True},
                session_id=self.sid)
            return (r.get("result") or {}).get("value")
        except Exception:
            return None

    async def _act(self, method: str, params: dict, *,
                   point: tuple[float, float] | None = None,
                   before: dict | None = None) -> None:
        """**一次操作 = 前后两张全量快照。** 这就是这条路的全部模型。"""
        self.tr.seq += 1
        cid = f"call@{self.tr.seq}"
        t0 = self.tr.ms()
        before = before or await self.snap()
        hit = await self._hit(*point) if point else None
        label = (hit or {}).get("label") or params.get("text") or params.get("url") or ""
        pt = None
        if hit and hit.get("bbox"):
            x, y, w, h = hit["bbox"]
            pt = {"x": round(x + w / 2, 2), "y": round(y + h / 2, 2)}
        await asyncio.sleep(SETTLE)
        after = await self.snap()
        self.tr.add({"callId": cid, "title": f"[人] {method} {label}".strip(),
                     "method": method, "params": params, "t0": t0,
                     "t1": self.tr.ms(), "point": pt,
                     "before": before, "after": after})
        self.publish(after, why=f"{method} {label}".strip())

    async def _typed(self, ch: str) -> None:
        """连续输入算一条动作,不是一个字一条。"""
        if self._typing is None:
            self._typing = {"text": "", "before": await self.snap()}
        self._typing["text"] += ch
        if self._type_timer:
            self._type_timer.cancel()
        self._type_timer = asyncio.get_running_loop().call_later(
            0.9, lambda: asyncio.create_task(self._flush_typing()))

    async def _flush_typing(self) -> None:
        t, self._typing = self._typing, None
        if self._type_timer:
            self._type_timer.cancel()
            self._type_timer = None
        if t and t["text"]:
            await self._act("type", {"text": t["text"]}, before=t["before"])

    # ---------------------------------------------------- 输入:唯一入口

    async def input(self, m: dict) -> None:
        k = m.get("t")
        if k == "mouse":
            if m["type"] == "mousePressed":
                await self._flush_typing()
                asyncio.create_task(self._act("click", {}, point=(m["x"], m["y"])))
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": m["type"], "x": m["x"], "y": m["y"], "button": "left",
                "clickCount": int(m.get("clickCount", 1)),
                "buttons": int(m.get("buttons", 0)),
                "modifiers": int(m.get("mod", 0))}, session_id=self.sid)
        elif k == "wheel":
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": m["x"], "y": m["y"],
                "deltaX": m.get("dx", 0), "deltaY": m.get("dy", 0)},
                session_id=self.sid)
            self._later("滚动", 0.3)
        elif k == "text":
            await self._typed(m["text"])
            await self.cdp.send("Input.insertText", {"text": m["text"]},
                                session_id=self.sid)
        elif k == "key":
            if m["key"] in ("Enter", "Tab"):
                await self._flush_typing()
            for t in ("keyDown", "keyUp"):
                await self.cdp.send("Input.dispatchKeyEvent", {
                    "type": t, "key": m["key"], "code": m.get("code", ""),
                    "windowsVirtualKeyCode": int(m.get("vk", 0)),
                    "modifiers": int(m.get("mod", 0))}, session_id=self.sid)
            self._later("按键", 0.4)
        elif k == "nav":
            u = m.get("url", "").strip()
            if not u:
                return
            if not u.startswith(("http://", "https://")):
                u = "https://" + u
            await self._flush_typing()
            await self.cdp.send("Page.navigate", {"url": u}, session_id=self.sid)
        elif k in ("back", "forward"):
            h = await self.cdp.send("Page.getNavigationHistory", session_id=self.sid)
            i = h["currentIndex"] + (1 if k == "forward" else -1)
            if 0 <= i < len(h["entries"]):
                await self.cdp.send("Page.navigateToHistoryEntry",
                                    {"entryId": h["entries"][i]["id"]},
                                    session_id=self.sid)
        elif k == "reload":
            await self.cdp.send("Page.reload", session_id=self.sid)
        elif k == "shot":
            self.publish(await self.snap(), why="手动刷新")

    # -------------------------------------------------------------- 收尾

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=5)
        if self.profile:
            shutil.rmtree(self.profile, ignore_errors=True)
            self.profile = ""


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9090)
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--url", default="SELF/demo")
    args = ap.parse_args()

    con = Console()
    await con.start("about:blank")

    async def index(_r):
        return web.Response(text=PAGE.replace("__W__", str(W)).replace("__H__", str(H)),
                            content_type="text/html")

    async def demo(_r):
        return web.Response(text=(HERE.parent / "rrweb_console" / "demo.html")
                            .read_text(encoding="utf-8"), content_type="text/html")

    async def res(request):
        u = request.query.get("u", "")
        if not u.startswith(("http://", "https://")):
            return web.Response(status=400)
        hit = await con.fetch_res(u)
        if not hit:
            raise web.HTTPFound(u)
        mime, blob = hit
        return web.Response(body=blob, content_type=mime.split(";")[0].strip(),
                            headers={"Cache-Control": "max-age=300"})

    async def trace_zip(_r):
        if not con.tr.actions:
            return web.Response(status=404, text="还没有动作")
        return web.Response(body=con.tr.zip(), content_type="application/zip",
                            headers={"Content-Disposition":
                                     'attachment; filename="webmuxd-trace.zip"'})

    async def channel(request):
        ws = web.WebSocketResponse(heartbeat=None, max_msg_size=0)
        await ws.prepare(request)
        con.viewers.add(ws)
        await ws.send_str(json.dumps({"c": "url", "v": con.page_url}))
        await ws.send_str(json.dumps({"c": "cursor", "v": con.cursor}))
        if con.shot:
            await ws.send_str(json.dumps(
                {"c": "shot", "v": con.version, "why": "接上", "b": con.bytes,
                 "url": con.shot.get("url", ""), "n": len(con.tr.actions),
                 "snap": con.shot}, ensure_ascii=False))
        try:
            async for msg in ws:
                if msg.type is WSMsgType.TEXT:
                    try:
                        await con.input(json.loads(msg.data))
                    except Exception as e:
                        print("input 出错:", e)
        finally:
            con.viewers.discard(ws)
        return ws

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/demo", demo)
    app.router.add_get("/res", res)
    app.router.add_get("/trace.zip", trace_zip)
    app.router.add_get("/ws", channel)
    app.router.add_get("/favicon.ico", lambda _r: web.Response(status=204))

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, args.bind, args.port).start()
    start = args.url.replace("SELF", f"http://127.0.0.1:{args.port}")
    await con.input({"t": "nav", "url": start})
    print(f"\n  打开  http://127.0.0.1:{args.port}/   (也监听 {args.bind})\n"
          f"  画面 = Playwright 那套 DOM 快照(按操作打点),只读\n"
          f"  输入 = CDP;/trace.zip 是一份真的 Playwright trace\n"
          f"  起始页:{start}\n")

    done = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, done.set)
        except NotImplementedError:
            pass
    try:
        await done.wait()
    finally:
        print("收工,关掉 chrome…")
        con.stop()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
