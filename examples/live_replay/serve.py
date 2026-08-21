"""你用 CDP 流开浏览器,下半屏实时跟着重放。

    python3 examples/live_replay/serve.py --port 8090            # 默认 rrweb
    python3 examples/live_replay/serve.py --port 8090 --replay trace

上半屏是**能操作的画面**(`Page.startScreencast` 出的帧 + `Input.*` 送回去的
鼠标键盘)。下半屏两种可选:

| `--replay` | 下半屏是什么 | 节奏 |
| --- | --- | --- |
| **`rrweb`**(默认) | rrweb 的 `Replayer` 跑在 live 模式 | **按 DOM 变化连续流**,页面动它就动 |
| `trace` | Playwright Trace Viewer | **一条动作一跳** —— 每条都要重拼整包再 post 进去 |

`trace` 那条不顺是结构决定的:trace 是给事后复盘的产物格式,
时间轴是**动作轴**([c §16](../../docs/v2/works/c-view.md#16-playwright-trace不是来源是产物));
rrweb 本来就是流,`addEvent()` 一条一条喂就行。

两种都不改变一件事:**输入永远走 CDP。** 下半屏只是看,不承载操作
([b §1](../../docs/v2/works/b-input.md#1-收口在哪))。

> **rrweb 会往页面里注入一个五百多 KB 的记录器。** 这是它的真实代价,
> 比现在那个光标探针大得多([c §16](../../docs/v2/works/c-view.md#16-playwright-trace不是来源是产物))。
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
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiohttp import WSMsgType, web

sys.path.insert(0, str(Path(__file__).parent.parent / "trace_export"))

from to_trace import SNAPSHOT_JS, build_trace  # noqa: E402

from webmuxd.cdp import CDP  # noqa: E402
from webmuxd.processes import resolve_browser  # noqa: E402

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

#: rrweb 的记录器 —— 第一次跑会下载,之后走缓存。
VENDOR = {
    "rrweb.js": "https://cdn.jsdelivr.net/npm/rrweb@latest/dist/rrweb.umd.cjs",
    "rrweb.css": "https://cdn.jsdelivr.net/npm/rrweb@latest/dist/style.css",
}
CACHE = Path.home() / ".cache" / "webmuxd-examples"

#: 注进页面的那段:开录,每条事件经 binding 送出来。
#: `recordCanvas` 打开是为了让 canvas 也能重放 —— 关掉的话那一格是空的,
#: 正是 [c §5.5] 说的那条缺口。代价是它要一直把 canvas 转成图。
RECORD_JS = """
(() => {
  if (window.__rrwebOn) return;
  // **只在顶层的真实页面上录。**
  // 注入脚本对「每一个新文档」都生效,包括记录器自己造出来的那些 about:blank
  // iframe —— 于是被注入的 iframe 又造 iframe,实测每秒新建二十来个,
  // 主页面的全量快照直接被饿死。这两条守卫是必须的,不是优化。
  if (window.top !== window) return;
  if (!/^https?:$/.test(location.protocol)) return;
  window.__rrwebOn = 1;
  // **不吞异常。** 吞掉的表现是"下半屏一直空着",和"页面没动"分不清。
  const err = (e) => { try {
    window.__rrwebEmit(JSON.stringify({ type: 99, err: String((e && e.stack) || e) }));
  } catch (_) {} };
  try {
    rrweb.record({
      emit(e) {
        try { window.__rrwebEmit(JSON.stringify(e)); }
        catch (x) { err("emit 失败 type=" + e.type + " " + x); }
      },
      recordCanvas: true,
      sampling: { canvas: 10 },
      inlineStylesheet: true,
      inlineImages: __INLINE_IMAGES__,
      errorHandler: (e) => { err("rrweb 内部: " + e); return true; },
    });
  } catch (e) { err(e); }
})()
"""


def vendor(name: str) -> bytes:
    """下过一次就不再下。**下不到就明说** —— 静默给个空文件更难查。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / name
    if not f.exists():
        import urllib.request
        print(f"  下载 {name} …")
        with urllib.request.urlopen(VENDOR[name], timeout=60) as r:
            f.write_bytes(r.read())
    return f.read_bytes()


#: 动作做完之后等这么久再拍「后」快照 —— 页面要有时间反应。
SETTLE = 0.45
#: 连续打字算一条动作,停这么久就收口。
TYPE_IDLE = 0.9


#: 快照/变更里这些属性是资源地址,要改写成走我们。
URL_ATTRS = ("src", "poster", "xlink:href", "data")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
#: 这些标签的 href 才是资源(link 的样式表);<a href> 不能动。
HREF_TAGS = ("link", "image", "use")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Live:
    def __init__(self, user: str, mode: str = "rrweb", *,
                 inline_images: bool = False, proxy_res: bool = True) -> None:
        self.user = user
        self.mode = mode
        self.inline_images = inline_images
        self.proxy_res = proxy_res
        #: rrweb 的事件缓冲。**只留最近一段可重放的** ——
        #: 一个 Meta(4) 之后跟着 FullSnapshot(2) 才构得出 Replayer,
        #: 所以见到 Meta 就从它重新开始攒,后来的观看者才追得上。
        self.rr: list[str] = []
        #: 两条各花了多少 —— 判断代价要看这个,不是事件条数
        self.bytes = {"rr": 0, "frame": 0, "res": 0}
        #: url -> (mime, 字节)。**这就是那个"代理"** —— 页面加载过的资源
        #: 我们这儿留一份,重放时从这儿出,不回原站。
        self.res: dict[str, tuple[str, bytes]] = {}
        #: 上游取资源时带的 Referer —— 很多 CDN(B 站就是)不带就 403
        self.page_url = ""
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
        for m in ("Page.enable", "Runtime.enable", "Network.enable"):
            await self.cdp.send(m, session_id=self.sid)
        if self.proxy_res:
            self._arm_network()
        self.cdp.on("Page.screencastFrame", self._on_frame)
        self.cdp.on("Page.frameNavigated", self._on_nav)
        if self.mode == "rrweb":
            await self._arm_rrweb()
        await self.cdp.send("Page.startScreencast",
                            {"format": "jpeg", "quality": 75,
                             "maxWidth": W, "maxHeight": H, "everyNthFrame": 1},
                            session_id=self.sid)

    # ------------------------------------------------- 把地址改到我们身上

    def _rw(self, url: str) -> str:
        """**所有 http(s) 资源一律改到我们身上,不管当时兜住没有。**

        第一版只改"已经收到的",在真实站点上等于没改:全量快照在页面刚加载时
        就发出去了,而图片是随后几秒才陆续到的 —— 实测 B 站那一页 30 张图,
        走代理的 0 张、破图 25 张。

        现在 `/res` 是**按需**的:手上有就给,没有就自己去上游取一份。
        竞态因此不存在了。
        """
        if not url or not url.startswith(("http://", "https://")):
            return url                      # data: / blob: / 相对地址都不动
        return f"/res?u={quote(url, safe='')}"

    def _rw_css(self, css: str) -> str:
        return re.sub(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)",
                      lambda m: f"url({self._rw(m.group(1))})", css)

    def _rw_node(self, n: Any) -> None:
        """递归改写 rrweb 序列化出来的节点树。**按结构走,不用正则扫整串** ——
        正则会误伤正文里长得像地址的文字。"""
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
        for k in ("childNodes", "adds", "attributes", "node", "texts", "removes"):
            v = n.get(k)
            if isinstance(v, (list, dict)) and k != "attributes":
                self._rw_node(v)

    def _rewrite(self, payload: str) -> str:
        """事件里凡是我们兜住了的地址,一律改成走 `/res`。"""
        try:
            e = json.loads(payload)
        except Exception:
            return payload
        self._rw_node(e.get("data"))
        return json.dumps(e, ensure_ascii=False)

    # ------------------------------------------------------ 资源:自己兜住

    def _arm_network(self) -> None:
        """**从 CDP 收响应体,不从页面里取。**

        `inlineImages` 是把图画进 canvas 再取字节,跨域没 CORS 头就污染画布 ——
        实测那张跨域图内联不了,只能退回原地址。而 `Network.getResponseBody`
        走的是浏览器已经收到的字节,**不受同源策略管**,跨域一样拿得到。

        另一半好处是:观看端不必够得着原站。资源从我们这儿出。
        """
        self._pending: dict[str, dict] = {}
        self.cdp.on("Network.responseReceived", self._on_resp)
        self.cdp.on("Network.loadingFinished", self._on_done)

    def _on_resp(self, params: dict, _sid: str | None) -> None:
        r = params.get("response") or {}
        if params.get("type") in ("Image", "Media", "Font", "Stylesheet", "Other"):
            self._pending[params["requestId"]] = {
                "url": r.get("url", ""), "mime": r.get("mimeType", "")}

    def _on_done(self, params: dict, _sid: str | None) -> None:
        info = self._pending.pop(params.get("requestId", ""), None)
        if info and info["url"]:
            asyncio.create_task(self._grab(params["requestId"], info))

    async def fetch_res(self, url: str) -> tuple[str, bytes] | None:
        """手上没有就去上游取。**带上 Referer 和 UA** ——
        实测不带的话 B 站的图直接 403,而那正是"回原站自己拿"靠不住的原因。"""
        hit = self.res.get(url)
        if hit:
            return hit
        try:
            import aiohttp
            headers = {"User-Agent": UA}
            if self.page_url:
                headers["Referer"] = self.page_url
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
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

    async def _grab(self, rid: str, info: dict) -> None:
        try:
            r = await self.cdp.send("Network.getResponseBody",
                                    {"requestId": rid}, session_id=self.sid)
        except Exception:
            return                       # 已经被浏览器丢了,不是错误
        body = r.get("body") or ""
        raw = base64.b64decode(body) if r.get("base64Encoded") else body.encode()
        if len(raw) > 8 * 1024 * 1024:   # 别把内存吃光
            return
        self.res[info["url"]] = (info["mime"] or "application/octet-stream", raw)
        self.bytes["res"] += len(raw)

    async def _arm_rrweb(self) -> None:
        """**只走 new-document 这条路,不做一次性的大 evaluate。**

        记录器有五百多 KB。把它塞进 `Runtime.evaluate` 等回包会挂住;
        而 `addScriptToEvaluateOnNewDocument` 是"以后每一页开头都跑一遍",
        不需要等结果 —— 换页之后还继续录,靠的也是它。
        **代价:它对「已经打开着的那一页」不生效**,要等下一次导航。
        这里无所谓 —— 服务起来之后马上就会导航到目标页。
        真做的话该在这里补一次注入(拆成 record-only 的小包就不会挂)。
        """
        # 那个分号是必须的:UMD 最后一行是 `}))`,后面直接跟 `(() => …)()`
        # 会被解析成"调用上一个表达式的结果",报的是
        # `(intermediate value)(...) is not a function`,和 rrweb 本身没关系。
        src = (vendor("rrweb.js").decode("utf-8") + "\n;\n"
               + RECORD_JS.replace("__INLINE_IMAGES__",
                                   "true" if self.inline_images else "false"))
        await self.cdp.send("Runtime.addBinding", {"name": "__rrwebEmit"},
                            session_id=self.sid)
        await self.cdp.send("Page.addScriptToEvaluateOnNewDocument",
                            {"source": src}, session_id=self.sid)
        self.cdp.on("Runtime.bindingCalled", self._on_rr)

    def _on_rr(self, params: dict, _sid: str | None) -> None:
        if params.get("name") != "__rrwebEmit":
            return
        payload = params.get("payload") or ""
        try:
            t = json.loads(payload).get("type")
        except Exception as e:
            print("！事件解不开:", len(payload), "字节", e)
            return
        if t == 99:                     # 页面里抛的,直接打出来
            print("！rrweb 在页面里出错:", payload[:400])
            return
        if t == 4:                      # Meta:新的一页,从这里重新攒
            self.rr = [payload]
        else:
            self.rr.append(payload)
            if len(self.rr) > 8000:     # 别无限长
                self.rr = self.rr[-4000:]
        if self.proxy_res:
            payload = self._rewrite(payload)
            self.rr[-1] = payload
        self.bytes["rr"] += len(payload)
        self._push({"c": "rr", "e": payload, "b": self.bytes})

    # ------------------------------------------------------------ 画面下行

    def _on_frame(self, params: dict, _sid: str | None) -> None:
        asyncio.create_task(self.cdp.send(
            "Page.screencastFrameAck", {"sessionId": params["sessionId"]},
            session_id=self.sid))
        self.last_frame = params["data"]
        self.bytes["frame"] += len(params["data"]) * 3 // 4
        self._push({"c": "frame", "data": params["data"], "b": self.bytes})

    def _on_nav(self, params: dict, _sid: str | None) -> None:
        f = params.get("frame") or {}
        if f.get("parentId"):
            return                                   # 只认主 frame
        self.page_url = f.get("url", "") or self.page_url
        if self.mode == "trace":
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
            if m["type"] == "mousePressed" and self.mode == "trace":
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
            if self.mode == "trace":
                await self._typed(m["text"])
            await self.cdp.send("Input.insertText", {"text": m["text"]},
                                session_id=self.sid)
        elif k == "key":
            if m["key"] in ("Enter", "Tab") and self.mode == "trace":
                await self._flush_typing()
            for t in ("keyDown", "keyUp"):
                await self.cdp.send("Input.dispatchKeyEvent", {
                    "type": t, "key": m["key"], "code": m.get("code", ""),
                    "windowsVirtualKeyCode": m.get("vk", 0)}, session_id=self.sid)
        elif k == "nav":
            if self.mode == "trace":
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
    ap.add_argument("--replay", choices=("rrweb", "trace"), default="rrweb",
                    help="下半屏用哪个重放器")
    #: 把 <img> 转成 data URL 一起传。**代价是体积** —— 开关在这儿就是为了量它。
    ap.add_argument("--inline-images", action="store_true")
    #: 关掉之后重放端会回原地址拿资源 —— 留着是为了能对比
    ap.add_argument("--no-proxy-res", action="store_true")
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
    live = Live(args.user, args.replay, inline_images=args.inline_images,
                proxy_res=not args.no_proxy_res)
    if args.replay == "rrweb":
        vendor("rrweb.js"); vendor("rrweb.css")     # 先备好再起,免得第一页漏录
    await live.start("about:blank")

    async def index(_r):
        return web.Response(
            text=(PAGE.replace("__VIEWER__", viewer_url)
                      .replace("__MODE__", args.replay)),
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
    app.router.add_get("/pattern.png", lambda _r: web.FileResponse(HERE / "pattern.png"))
    app.router.add_get("/flower.mp4", lambda _r: web.FileResponse(HERE / "flower.mp4"))

    async def res(request):
        """资源全从这儿出。**重放端不必够得着原站,也不必有它的 Referer。**

        手上有就给;没有就去上游取一份再给。**取不到就 302 回原地址** ——
        退回去至少和不做代理一样,不会把"本来能拿到"变成"破图"。
        """
        u = request.query.get("u", "")
        if not u.startswith(("http://", "https://")):
            return web.Response(status=400)
        hit = await live.fetch_res(u)
        if not hit:
            raise web.HTTPFound(u)
        mime, blob = hit
        return web.Response(body=blob, content_type=mime.split(";")[0].strip(),
                            headers={"Cache-Control": "max-age=300"})

    app.router.add_get("/res", res)
    app.router.add_get("/trace.zip", trace)
    app.router.add_get("/ws", channel)
    app.router.add_get("/favicon.ico", lambda _r: web.Response(status=204))

    async def rrweb_events(_r):
        """新观看者要先把攒着的补上,否则它从半路接不上。"""
        return web.json_response({"events": live.rr})

    async def vendor_file(request):
        name = request.match_info["name"]
        if name not in VENDOR:
            return web.Response(status=404)
        return web.Response(body=vendor(name),
                            content_type="text/css" if name.endswith(".css")
                            else "application/javascript")

    app.router.add_get("/rr/events", rrweb_events)
    app.router.add_get("/vendor/{name}", vendor_file)
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
    if not args.no_proxy_res:
        print("  资源代理:开 —— 重放端只找我们要,不回原站")
    how = ("rrweb —— 按 DOM 变化连续流,页面动它就动"
           if args.replay == "rrweb" else
           "Playwright Trace —— 一条动作一跳")
    print(f"\n  打开  http://127.0.0.1:{args.port}/   (也监听 {args.bind})\n"
          f"  上半屏能点能打字;下半屏:{how}\n")

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
