"""整屏是 rrweb,只读;鼠标、光标、文字全走 CDP。

    python3 examples/rrweb_console/serve.py --port 8090
    # 打开 http://<这台机器>:8090/

和上半屏截屏、下半屏重放的那个对比工具([live_replay](../live_replay/))不同,
这里只有**一块画面** —— 它是 rrweb 重放出来的 DOM。

**那块画面是死的。** 它 `pointer-events: none`,上面盖着一层透明的接收层;
代码里**没有任何一条路把事件送进重放出来的 DOM**。看它就像看视频。
真正生效的只有一条:

```
你的鼠标/键盘 → 接收层 → WS → Input.dispatchMouseEvent / insertText → 真正那个 tab
                                → 页面变了 → rrweb 事件 → 画面跟着变
```

这正是设计里那条:**画面来源可以有多条,输入永远只有一条**
([b §1](../../docs/v2/works/b-input.md#1-收口在哪))。

三件事由 CDP 负责,rrweb 一件都不碰:

| | 怎么来的 |
| --- | --- |
| **鼠标位置** | 接收层量出页面坐标 → `Input.dispatchMouseEvent` |
| **光标形状** | 页面里的探针报 `getComputedStyle(el).cursor`,**过白名单**再用 |
| **文字 / IME** | 组字在本地完成,`compositionend` 之后才 `Input.insertText` |

资源(图片、字体、样式、普通视频)全部经本服务转发,重放端不回原站
—— 实测 B 站那一页,不转发时 30 张图破 25 张。
**但 MSE / `blob:` 的视频画面拿不到**,那不是地址问题,是根本没有地址。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import shutil
import signal
import socket
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

from webmuxd.cdp import CDP
from webmuxd.processes import resolve_browser

HERE = Path(__file__).parent
PAGE = (HERE / "page.html").read_text(encoding="utf-8")
CACHE = Path.home() / ".cache" / "webmuxd-examples"
RRWEB_URL = "https://cdn.jsdelivr.net/npm/rrweb@latest/dist/rrweb.umd.cjs"
RRWEB_CSS = "https://cdn.jsdelivr.net/npm/rrweb@latest/dist/style.css"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")

W, H = 1280, 800

#: **光标只认这几个关键字,其余一律降级成 `default`。**
#: 取值会写进观看端的 `style.cursor`,而远端页面不可信 ——
#: 白名单和黑名单的区别是:没见过的默认被拒([b §5](../../docs/v2/works/b-input.md#5-光标同步))。
CURSORS = frozenset("""
auto default none context-menu help pointer progress wait cell crosshair text
vertical-text alias copy move no-drop not-allowed grab grabbing e-resize
n-resize ne-resize nw-resize s-resize se-resize sw-resize w-resize ew-resize
ns-resize nesw-resize nwse-resize col-resize row-resize all-scroll zoom-in
zoom-out
""".split())

URL_ATTRS = ("src", "poster", "xlink:href", "data")
HREF_TAGS = ("link", "image", "use")

#: 注进页面的两样东西:rrweb 记录器 + 光标探针。
#: 两条守卫是必须的 —— 注入脚本对每个新文档生效,包括记录器自己造的 about:blank
#: iframe,不挡住就会自我递归(实测每秒新建二十来个,主快照直接被饿死)。
INJECT_JS = """
(() => {
  if (window.__wmOn) return;
  if (window.top !== window) return;
  if (!/^https?:$/.test(location.protocol)) return;
  window.__wmOn = 1;

  // ---- 光标探针 ----
  // 合成事件同样会触发 mousemove,所以这条在没有真实鼠标的情况下照样有效。
  let lastCur = "";
  addEventListener("mousemove", (e) => {
    const el = document.elementFromPoint(e.clientX, e.clientY);
    const c = el ? getComputedStyle(el).cursor : "default";
    if (c !== lastCur) { lastCur = c; try { window.__wmCursor(c); } catch (_) {} }
  }, true);

  // ---- rrweb ----
  try {
    rrweb.record({
      emit(e) { try { window.__wmEmit(JSON.stringify(e)); } catch (_) {} },
      recordCanvas: true,
      sampling: { canvas: 10 },
      inlineStylesheet: true,
    });
  } catch (e) {
    try { window.__wmEmit(JSON.stringify({ type: 99, err: String(e) })); } catch (_) {}
  }
})()
"""


def vendor(name: str, url: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / name
    if not f.exists():
        import urllib.request
        print(f"  下载 {name} …")
        with urllib.request.urlopen(url, timeout=60) as r:
            f.write_bytes(r.read())
    return f.read_bytes()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Console:
    def __init__(self) -> None:
        self.cdp: CDP | None = None
        self.sid = ""
        self.proc: subprocess.Popen | None = None
        self.profile = ""
        self.viewers: set[web.WebSocketResponse] = set()
        self.rr: list[str] = []
        self.res: dict[str, tuple[str, bytes]] = {}
        self.page_url = ""
        self.cursor = "default"
        self.bytes = {"rr": 0, "res": 0}
        self._pending: dict[str, dict] = {}
        #: 正在挡路的那个 JS 对话框。**必须有人应答,否则渲染进程永远卡着** ——
        #: 开了 `Page.enable` 之后 Chrome 就把它交给客户端等着,
        #: 而卡住的表现是"鼠标点了没反应",不是报错(g §1)。
        self.dialog: dict | None = None
        self._dlg_timer: asyncio.TimerHandle | None = None

    # ------------------------------------------------------------------ 起

    async def start(self, url: str) -> None:
        exe = resolve_browser()
        port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="rrconsole-")
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

        for name in ("__wmEmit", "__wmCursor"):
            await self.cdp.send("Runtime.addBinding", {"name": name},
                                session_id=self.sid)
        src = (vendor("rrweb.js", RRWEB_URL).decode("utf-8")
               # 那个分号是必须的:UMD 最后一行是 `}))`,后面直接跟 `(() => …)()`
               # 会被当成"调用上一个表达式的结果"。
               + "\n;\n" + INJECT_JS)
        await self.cdp.send("Page.addScriptToEvaluateOnNewDocument",
                            {"source": src}, session_id=self.sid)

        self.cdp.on("Runtime.bindingCalled", self._on_binding)
        self.cdp.on("Page.frameNavigated", self._on_nav)
        self.cdp.on("Network.responseReceived", self._on_resp)
        self.cdp.on("Network.loadingFinished", self._on_done)
        self.cdp.on("Page.javascriptDialogOpening", self._on_dialog)
        self.cdp.on("Page.javascriptDialogClosed", self._on_dialog_closed)

    # ---------------------------------------------------------- 页面传出来

    def _on_binding(self, params: dict, _sid: str | None) -> None:
        name, payload = params.get("name"), params.get("payload") or ""
        if name == "__wmCursor":
            # **白名单**:没见过的一律 default。远端页面能决定观看端光标的前提
            # 是它只能在这个封闭集合里选。
            c = payload.split(",")[0].strip().strip("'\"")
            c = c if c in CURSORS else "default"
            if c != self.cursor:
                self.cursor = c
                self._push({"c": "cursor", "v": c})
            return
        if name != "__wmEmit":
            return
        try:
            t = json.loads(payload).get("type")
        except Exception:
            return
        if t == 99:
            print("！页面里出错:", payload[:300])
            return
        payload = self._rewrite(payload)
        if t == 4:                       # Meta:新的一页,从这里重新攒
            self.rr = [payload]
        else:
            self.rr.append(payload)
            if len(self.rr) > 8000:
                self.rr = self.rr[-4000:]
        self.bytes["rr"] += len(payload)
        self._push({"c": "rr", "e": payload, "b": self.bytes})

    # ----------------------------------------------------- 挡路的对话框

    def _on_dialog(self, params: dict, _sid: str | None) -> None:
        """**一个 alert 就能把整个会话冻住。** 实测:弹出之前 CDP 往返 3ms,
        弹出之后连着三次十二秒都不回 —— 因为渲染进程在等应答。"""
        self.dialog = {"kind": params.get("type", "alert"),
                       "message": params.get("message", ""),
                       "prompt": params.get("defaultPrompt", "")}
        self._push({"c": "dialog", **self.dialog})
        if self._dlg_timer:
            self._dlg_timer.cancel()
        # **兜底:没人答就自己取消。** 不替使用者决定,但也绝不允许永久卡住 ——
        # 超时一律偏向"取消"(g §3)。
        self._dlg_timer = asyncio.get_running_loop().call_later(
            25, lambda: asyncio.create_task(self.answer(False, "", auto=True)))

    def _on_dialog_closed(self, _params: dict, _sid: str | None) -> None:
        self.dialog = None
        if self._dlg_timer:
            self._dlg_timer.cancel()
            self._dlg_timer = None
        self._push({"c": "dialog", "kind": None})

    async def answer(self, accept: bool, text: str = "", *, auto: bool = False) -> None:
        if not self.dialog:
            return
        # **先把要用的东西取出来。** 应答成功会立刻触发 `javascriptDialogClosed`,
        # 那个回调把 `self.dialog` 置空 —— 之后再读它就是 None。
        what = (self.dialog.get("message") or "")[:80]
        try:
            await self.cdp.send("Page.handleJavaScriptDialog",
                                {"accept": accept, "promptText": text},
                                session_id=self.sid)
        except Exception as e:
            print("应答对话框失败:", e)
            return
        if auto:
            print(f"！没人应答,自动取消了一个对话框:{what}")

    def _on_nav(self, params: dict, _sid: str | None) -> None:
        f = params.get("frame") or {}
        if f.get("parentId"):
            return
        self.page_url = f.get("url", "") or self.page_url
        self._push({"c": "url", "v": self.page_url})

    def _push(self, msg: dict) -> None:
        blob = json.dumps(msg)
        for ws in list(self.viewers):
            if not ws.closed:
                asyncio.create_task(ws.send_str(blob))

    # ------------------------------------------------- 资源:一律经过我们

    def _rw(self, url: str) -> str:
        if not url or not url.startswith(("http://", "https://")):
            return url               # data: / blob: / 相对地址都不动
        return f"/res?u={quote(url, safe='')}"

    def _rw_css(self, css: str) -> str:
        return re.sub(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)",
                      lambda m: f"url({self._rw(m.group(1))})", css)

    def _rw_node(self, n: Any) -> None:
        """按结构走,不用正则扫整串 —— 正则会误伤正文里长得像地址的文字。"""
        if isinstance(n, list):
            for x in n:
                self._rw_node(x)
            return
        if not isinstance(n, dict):
            return
        a = n.get("attributes")
        if isinstance(a, dict):
            tag = (n.get("tagName") or "").lower()
            for k in URL_ATTRS:
                if isinstance(a.get(k), str):
                    a[k] = self._rw(a[k])
            if tag in HREF_TAGS and isinstance(a.get("href"), str):
                a["href"] = self._rw(a["href"])
            if isinstance(a.get("srcset"), str):
                a["srcset"] = ", ".join(
                    " ".join([self._rw(p.split(" ")[0])] + p.split(" ")[1:])
                    for p in (x.strip() for x in a["srcset"].split(",")) if p)
            for k in ("style", "_cssText"):
                if isinstance(a.get(k), str):
                    a[k] = self._rw_css(a[k])
        for k in ("childNodes", "adds", "node", "texts", "removes"):
            v = n.get(k)
            if isinstance(v, (list, dict)):
                self._rw_node(v)

    def _rewrite(self, payload: str) -> str:
        try:
            e = json.loads(payload)
        except Exception:
            return payload
        self._rw_node(e.get("data"))
        return json.dumps(e, ensure_ascii=False)

    def _on_resp(self, params: dict, _sid: str | None) -> None:
        if params.get("type") in ("Image", "Media", "Font", "Stylesheet", "Other"):
            r = params.get("response") or {}
            self._pending[params["requestId"]] = {"url": r.get("url", ""),
                                                  "mime": r.get("mimeType", "")}

    def _on_done(self, params: dict, _sid: str | None) -> None:
        info = self._pending.pop(params.get("requestId", ""), None)
        if info and info["url"] and info["url"] not in self.res:
            asyncio.create_task(self._grab(params["requestId"], info))

    async def _grab(self, rid: str, info: dict) -> None:
        try:
            r = await self.cdp.send("Network.getResponseBody",
                                    {"requestId": rid}, session_id=self.sid)
        except Exception:
            return                   # 已经被浏览器丢了,`/res` 会自己去取
        body = r.get("body") or ""
        raw = base64.b64decode(body) if r.get("base64Encoded") else body.encode()
        if len(raw) <= 8 * 1024 * 1024:
            self.res[info["url"]] = (info["mime"] or "application/octet-stream", raw)
            self.bytes["res"] += len(raw)

    async def fetch_res(self, url: str) -> tuple[str, bytes] | None:
        """手上没有就去上游取。**带 Referer 和 UA** —— 很多 CDN 不带就 403,
        那正是"让重放端自己回原站拿"靠不住的原因。"""
        hit = self.res.get(url)
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
        self.res[url] = (mime, body)
        self.bytes["res"] += len(body)
        return self.res[url]

    # ---------------------------------------------------- 输入:唯一的入口

    async def input(self, m: dict) -> None:
        """**观看端能表达的意图只有这几种。** 这就是安全收口:
        不是"过滤掉危险的",而是"只能说这几句话"。"""
        k = m.get("t")
        if k == "dialog":
            await self.answer(bool(m.get("accept")), m.get("text", ""))
            return
        if k == "mouse":
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": m["type"], "x": m["x"], "y": m["y"],
                "button": m.get("button", "left"),
                "clickCount": int(m.get("clickCount", 1)),
                "buttons": int(m.get("buttons", 0)),
                "modifiers": int(m.get("mod", 0))}, session_id=self.sid)
        elif k == "wheel":
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": m["x"], "y": m["y"],
                "deltaX": m.get("dx", 0), "deltaY": m.get("dy", 0)},
                session_id=self.sid)
        elif k == "text":
            # **组字在本地做完才到这儿。** 中间态不发,远端不会收到一串字母。
            await self.cdp.send("Input.insertText", {"text": m["text"]},
                                session_id=self.sid)
        elif k == "key":
            for t in ("keyDown", "keyUp"):
                await self.cdp.send("Input.dispatchKeyEvent", {
                    "type": t, "key": m["key"], "code": m.get("code", ""),
                    "windowsVirtualKeyCode": int(m.get("vk", 0)),
                    "modifiers": int(m.get("mod", 0))}, session_id=self.sid)
        elif k == "nav":
            u = m.get("url", "").strip()
            if not u:
                return
            if not u.startswith(("http://", "https://")):
                u = "https://" + u
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
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--bind", default="0.0.0.0")
    #: `SELF` 换成本服务的地址 —— 默认打开自检页
    ap.add_argument("--url", default="SELF/demo")
    args = ap.parse_args()

    vendor("rrweb.js", RRWEB_URL)
    vendor("rrweb.css", RRWEB_CSS)
    con = Console()
    await con.start("about:blank")

    async def index(_r):
        return web.Response(text=PAGE.replace("__W__", str(W)).replace("__H__", str(H)),
                            content_type="text/html")

    async def vendor_file(request):
        name = request.match_info["name"]
        if name not in ("rrweb.js", "rrweb.css"):
            return web.Response(status=404)
        return web.Response(
            body=vendor(name, RRWEB_URL if name.endswith(".js") else RRWEB_CSS),
            content_type="text/css" if name.endswith(".css") else "application/javascript")

    async def res(request):
        u = request.query.get("u", "")
        if not u.startswith(("http://", "https://")):
            return web.Response(status=400)
        hit = await con.fetch_res(u)
        if not hit:
            raise web.HTTPFound(u)      # 取不到就退回原地址,不比不做代理更差
        mime, blob = hit
        return web.Response(body=blob, content_type=mime.split(";")[0].strip(),
                            headers={"Cache-Control": "max-age=300"})

    async def events(_r):
        return web.json_response({"events": con.rr, "cursor": con.cursor,
                                  "url": con.page_url})

    async def channel(request):
        ws = web.WebSocketResponse(heartbeat=None, max_msg_size=0)
        await ws.prepare(request)
        con.viewers.add(ws)
        await ws.send_str(json.dumps({"c": "url", "v": con.page_url}))
        try:
            async for msg in ws:
                if msg.type is WSMsgType.TEXT:
                    try:
                        await con.input(json.loads(msg.data))
                    except Exception as e:
                        # **卡住必须让观看端看见。** 只写日志的话,
                        # 使用者看到的是"鼠标点了没反应",查不到任何东西。
                        print("input 出错:", e)
                        con._push({"c": "stuck", "why": str(e)[:120]})
        finally:
            con.viewers.discard(ws)
        return ws

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/vendor/{name}", vendor_file)
    app.router.add_get("/demo", lambda _r: web.Response(
        text=(HERE / "demo.html").read_text(encoding="utf-8"),
        content_type="text/html"))
    app.router.add_get("/res", res)
    app.router.add_get("/rr/events", events)

    async def probe(request):
        """**照直问真页面。** 排查时要能分清"输入没进去"和"画面没更新" ——
        这两件事的表现一模一样,而修法完全不同。"""
        r = await con.cdp.send(
            "Runtime.evaluate",
            {"expression": request.query.get("e", "document.title"),
             "returnByValue": True}, session_id=con.sid)
        return web.json_response({"v": (r.get("result") or {}).get("value"),
                                  "err": r.get("exceptionDetails")})

    app.router.add_get("/probe", probe)
    app.router.add_get("/ws", channel)
    app.router.add_get("/favicon.ico", lambda _r: web.Response(status=204))

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, args.bind, args.port).start()
    start = args.url.replace("SELF", f"http://127.0.0.1:{args.port}")
    await con.input({"t": "nav", "url": start})
    print(f"\n  打开  http://127.0.0.1:{args.port}/   (也监听 {args.bind})\n"
          f"  画面是 rrweb 重放的,只读;鼠标、光标、文字全走 CDP\n"
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
