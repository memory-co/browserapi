"""你用 CDP 流开浏览器,Playwright 的 trace 在旁边实时长出来。

    python3 examples/trace_live/serve.py --port 8090
    # 打开 http://<这台机器>:8090/

上半屏是**能操作的画面**(`Page.startScreencast` 出的帧 + `Input.*` 送回去的
鼠标键盘);下半屏是 **Playwright Trace Viewer**,你每做完一个动作它就多一条。

这一套的关键在于:**Playwright 录不到你的操作。** 它的快照只在自己的 API
调用前后拉([c §13.2](../../docs/v2/works/c-pixels.md#132-playwright-trace根本不是一条来源)),
而这里的输入是裸 `Input.dispatchMouseEvent`。所以 trace 不是它录的 ——
**是我们在自己的动作边界上写的**,格式照它的来。

动作边界在这里就是三样:按下鼠标、敲完一串字、导航。
和 [i §3.2](../../docs/v2/works/i-agent-surface.md#32-什么算一条行为) 是同一条线。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from aiohttp import WSMsgType, web

sys.path.insert(0, str(Path(__file__).parent.parent / "trace_export"))

from to_trace import SNAPSHOT_JS, build_trace  # noqa: E402

from webmuxd.core.cdp import CDP  # noqa: E402
from webmuxd.runtime.process import resolve_browser  # noqa: E402

HERE = Path(__file__).parent
PAGE = (HERE / "page.html").read_text(encoding="utf-8")
W, H = 1024, 768

#: 点在哪、打到谁。**动作要有名字才读得懂** —— 这一步等价于 webmuxd 的 `hit`。
HIT_JS = """(x, y) => {
  const el = document.elementFromPoint(x, y);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const label = (el.getAttribute('aria-label') || el.value || el.innerText ||
                 el.getAttribute('placeholder') || el.name || el.id || el.tagName)
                .toString().trim().slice(0, 24);
  return { label, tag: el.tagName.toLowerCase(),
           bbox: [+r.x.toFixed(1), +r.y.toFixed(1), +r.width.toFixed(1), +r.height.toFixed(1)] };
}"""

#: 动作做完之后等这么久再拍「后」快照 —— 页面要有时间反应。
SETTLE = 0.45
#: 连续打字算一条动作,停这么久就收口。
TYPE_IDLE = 0.9


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Live:
    def __init__(self, user: str) -> None:
        self.user = user
        self.cdp: CDP | None = None
        self.sid = ""
        self.proc: subprocess.Popen | None = None
        self.profile = ""
        self.viewers: set[web.WebSocketResponse] = set()
        self.last_frame = ""
        # 录出来的东西,喂给 build_trace 的就是这三样
        self.actions: list[dict] = []
        self.snapshots: dict[int, dict] = {}
        self.shots: dict[int, bytes] = {}
        self.seq = 0
        self.version = 0
        self.trace: bytes = b""
        self._typing: dict | None = None
        self._type_timer: asyncio.TimerHandle | None = None
        self._t0 = time.time()

    # ------------------------------------------------------------------ 起

    async def start(self, url: str) -> None:
        exe = resolve_browser()
        port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="tracelive-")
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
        for m in ("Page.enable", "Runtime.enable"):
            await self.cdp.send(m, session_id=self.sid)
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.cdp.on("Page.frameNavigated", self._on_nav)
        await self.cdp.send("Page.startScreencast",
                            {"format": "jpeg", "quality": 75,
                             "maxWidth": W, "maxHeight": H, "everyNthFrame": 1},
                            session_id=self.sid)

    # ------------------------------------------------------------ 画面下行

    def _on_frame(self, params: dict, _sid: str | None) -> None:
        asyncio.create_task(self.cdp.send(
            "Page.screencastFrameAck", {"sessionId": params["sessionId"]},
            session_id=self.sid))
        self.last_frame = params["data"]
        self._push({"c": "frame", "data": params["data"]})

    def _on_nav(self, params: dict, _sid: str | None) -> None:
        f = params.get("frame") or {}
        if f.get("parentId"):
            return                                   # 只认主 frame
        asyncio.create_task(self._record("nav", {"url": f.get("url", "")}, None))

    def _push(self, msg: dict) -> None:
        blob = json.dumps(msg)
        for ws in list(self.viewers):
            if not ws.closed:
                asyncio.create_task(ws.send_str(blob))

    # -------------------------------------------------------------- 上行

    async def handle(self, m: dict) -> None:
        k = m.get("t")
        if k == "mouse":
            if m["type"] == "mousePressed":
                await self._flush_typing()
                asyncio.create_task(self._record("click", None, (m["x"], m["y"])))
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": m["type"], "x": m["x"], "y": m["y"], "button": "left",
                "clickCount": 1, "buttons": m.get("buttons", 0)},
                session_id=self.sid)
        elif k == "wheel":
            await self.cdp.send("Input.dispatchMouseEvent", {
                "type": "mouseWheel", "x": m["x"], "y": m["y"],
                "deltaX": m.get("dx", 0), "deltaY": m.get("dy", 0)},
                session_id=self.sid)
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
                    "windowsVirtualKeyCode": m.get("vk", 0)}, session_id=self.sid)
        elif k == "nav":
            await self._flush_typing()
            await self.cdp.send("Page.navigate", {"url": m["url"]},
                                session_id=self.sid)

    # ----------------------------------------------------------- 动作边界

    async def _typed(self, ch: str) -> None:
        """**一串连续的输入算一条动作**,不是一个字一条 —— 否则时间轴上全是噪声。"""
        if self._typing is None:
            self._typing = {"text": "", "before": await self._snap(),
                            "at_ms": time.time() * 1000}
        self._typing["text"] += ch
        if self._type_timer:
            self._type_timer.cancel()
        self._type_timer = asyncio.get_running_loop().call_later(
            TYPE_IDLE, lambda: asyncio.create_task(self._flush_typing()))

    async def _flush_typing(self) -> None:
        t, self._typing = self._typing, None
        if self._type_timer:
            self._type_timer.cancel()
            self._type_timer = None
        if t and t["text"]:
            await self._commit("type", {"text": t["text"]}, None,
                               before=t["before"], at_ms=t["at_ms"])

    async def _record(self, verb: str, target: dict | None,
                      point: tuple[float, float] | None) -> None:
        before = await self._snap()
        hit = None
        if point:
            hit = await self._hit(*point)
            if hit and not target:
                target = {"text": hit.get("label") or hit.get("tag")}
        await self._commit(verb, target or {}, hit, before=before,
                           at_ms=time.time() * 1000)

    async def _commit(self, verb: str, target: dict, hit: dict | None, *,
                      before: dict | None, at_ms: float) -> None:
        """**动作边界就在这里。** 等页面稳一下,拍「后」快照,写成一条 trace 动作。"""
        await asyncio.sleep(SETTLE)
        after = await self._snap()
        self.seq += 1
        seq = self.seq
        self.actions.append({
            "seq": seq, "at_ms": at_ms, "kind": "action", "tab": "t_1",
            "user": self.user, "action": verb, "target": target,
            **({"hit": hit} if hit else {}),
            "ok": True, "ms": round(time.time() * 1000 - at_ms),
        })
        snap = {k: v for k, v in (("before", before), ("after", after)) if v}
        if snap:
            self.snapshots[seq] = snap
        if self.last_frame:
            self.shots[seq] = base64.b64decode(self.last_frame)
        self._rebuild()

    def _rebuild(self) -> None:
        try:
            self.trace = build_trace(
                actions=self.actions, snapshots=self.snapshots, shots=self.shots,
                viewport={"width": W, "height": H},
                title=f"webmuxd · 实时 · {self.user}")
        except Exception as e:            # 有一条坏的不该让整条流停掉
            print("拼 trace 出错:", e)
            return
        self.version += 1
        self._push({"c": "trace", "v": self.version, "n": len(self.actions),
                    "last": self.actions[-1]["action"] if self.actions else ""})

    # ------------------------------------------------------------- 页面里

    async def _snap(self) -> dict | None:
        try:
            r = await self.cdp.send(
                "Runtime.evaluate",
                {"expression": SNAPSHOT_JS, "returnByValue": True},
                session_id=self.sid)
            raw = (r.get("result") or {}).get("value")
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def _hit(self, x: float, y: float) -> dict | None:
        try:
            r = await self.cdp.send(
                "Runtime.evaluate",
                {"expression": f"({HIT_JS})({x}, {y})", "returnByValue": True},
                session_id=self.sid)
            return (r.get("result") or {}).get("value")
        except Exception:
            return None

    # -------------------------------------------------------------- 收尾

    def stop(self) -> None:
        """**等它真的死掉。** `terminate()` 只发信号就返回,不 wait 会留孤儿。"""
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
    ap.add_argument("--url", default="SELF/demo")
    ap.add_argument("--user", default="人")
    #: **默认用托管那份 viewer。** 本地那份要 service worker 才能渲染快照,
    #: 而 service worker 只在安全上下文里注册 —— 从内网 IP 打开就是不安全上下文,
    #: 快照面板会**静默空白**。托管的是 https,怎么访问都能用。
    ap.add_argument("--viewer", default="https://trace.playwright.dev/")
    #: 不想依赖外网时:指到本地那份静态包,例如
    #:   --viewer-dir node_modules/playwright-core/lib/vite/traceViewer
    #: **但要从 127.0.0.1 打开**(端口转发)—— service worker 只在安全上下文注册,
    #: 从内网 IP 访问的话快照面板会静默空白。
    ap.add_argument("--viewer-dir", default="")
    args = ap.parse_args()

    viewer_url = args.viewer          # index() 用到,路由那边可能会改写
    live = Live(args.user)
    await live.start("about:blank")

    async def index(_r):
        return web.Response(text=PAGE.replace("__VIEWER__", viewer_url),
                            content_type="text/html")

    async def demo(_r):
        return web.Response(text=(HERE / "demo.html").read_text(encoding="utf-8"),
                            content_type="text/html")

    async def trace(_r):
        if not live.trace:
            return web.Response(status=404, text="还没有动作")
        return web.Response(body=live.trace, content_type="application/zip")

    async def channel(request):
        ws = web.WebSocketResponse(heartbeat=None, max_msg_size=0)
        await ws.prepare(request)
        live.viewers.add(ws)
        if live.last_frame:
            await ws.send_str(json.dumps({"c": "frame", "data": live.last_frame}))
        if live.version:
            await ws.send_str(json.dumps({"c": "trace", "v": live.version,
                                          "n": len(live.actions), "last": ""}))
        try:
            async for msg in ws:
                if msg.type is WSMsgType.TEXT:
                    try:
                        await live.handle(json.loads(msg.data))
                    except Exception as e:
                        print("input 出错:", e)
        finally:
            live.viewers.discard(ws)
        return ws

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/demo", demo)
    app.router.add_get("/trace.zip", trace)
    app.router.add_get("/ws", channel)
    app.router.add_get("/favicon.ico", lambda _r: web.Response(status=204))
    viewer_url = args.viewer
    if args.viewer_dir:
        d = Path(args.viewer_dir).expanduser().resolve()
        if not (d / "index.html").exists():
            raise SystemExit(f"--viewer-dir 里没有 index.html:{d}")
        app.router.add_static("/viewer/", d)
        viewer_url = "/viewer/index.html"

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, args.bind, args.port).start()
    url = args.url.replace("SELF", f"http://127.0.0.1:{args.port}")
    await live.handle({"t": "nav", "url": url})
    print(f"\n  打开  http://127.0.0.1:{args.port}/   (也监听 {args.bind})\n"
          f"  上半屏能点能打字,下半屏是 trace,做一个动作就多一条\n"
          f"  viewer:{viewer_url}\n")

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
        live.stop()
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
