"""DOM 那条画面 —— 传 DOM 变更,观看端重排。

对应 [c §5](../../docs/v2/works/c-view.md#5-第三条rrweb--它不传像素)。
使用者看到的名字是 **DOM**;记录器用的是 rrweb,这个词只出现在这儿和日志里。

和另外两条的差别只有一条:**它在页面里跑。** 另外两条是从外面看 ——
一条问 Chromium 要图,一条盯着 X 显示。这一条要往页面里注入一个记录器,
所以它多两样事:

1. **注入要挡两道**(`__wm_dom` / 顶层 / http(s))。`addScriptToEvaluateOnNewDocument`
   对**每一个新文档**生效,包括记录器自己造出来的 `about:blank` iframe ——
   被注入的 iframe 又造 iframe,实测每秒新建二十来个,主页面的全量快照直接被饿死。
   **这两道守卫是必须的,不是优化。**
2. **资源要经过我们**。记录器只记 `src`,观看端自己回原站拉的话,
   要登录的站、认 `Referer` 的 CDN 全是破图 —— 实测某视频站一页 30 张图破 25 张。
   所以快照里的地址一律改写成 `/api/res?u=…`,由 sessiond 转发
   ([c §10.2](../../docs/v2/works/c-view.md#102-那条连接经过我们))。

**它是纯下行的。** 输入照旧走 `Input.*`,和另外两条一个字不差
([b §1](../../docs/v2/works/b-input.md#1-收口在哪))。
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

log = logging.getLogger("webmuxd.dom")

HERE = Path(__file__).parent
#: 记录器落在哪。**属于数据,所以是下载来的**,不进包
#: ([d §2](../../docs/v2/works/d-install.md#2-每样东西从哪来))。
RRWEB_URL = "https://cdn.jsdelivr.net/npm/rrweb@latest/dist/rrweb.umd.cjs"
RRWEB_CSS = "https://cdn.jsdelivr.net/npm/rrweb@latest/dist/style.css"
CACHE = Path.home() / ".cache" / "webmuxd" / "rrweb"

#: 事件缓冲上限。超了从最近一张全量快照往后留 —— **不能从中间截**,
#: 增量链断在中间等于重放出来的 DOM 从此是错的
#: ([c §5.5](../../docs/v2/works/c-view.md#55-背压不能沿用丢旧保新))。
MAX_EVENTS = 6000

#: 快照里这些属性是资源地址。
URL_ATTRS = ("src", "poster", "xlink:href", "data")
#: 这些标签的 `href` 才是资源;`<a href>` 不能动。
HREF_TAGS = ("link", "image", "use")

#: 注进页面的那一段。**只有这一个入口** —— 光标探针是另一件事,不掺在一起。
RECORD_JS = """
(() => {
  if (window.__wm_dom) return;
  if (window.top !== window) return;              // 只在顶层录
  if (!/^https?:$/.test(location.protocol)) return;   // about:blank 不录
  window.__wm_dom = 1;
  try {
    rrweb.record({
      emit(e) { try { window.__wm_dom_emit(JSON.stringify(e)); } catch (_) {} },
      recordCanvas: true,
      sampling: { canvas: 10 },
      inlineStylesheet: true,
    });
  } catch (e) {
    try { window.__wm_dom_emit(JSON.stringify({type: -1, err: String(e)})); }
    catch (_) {}
  }
})()
"""

BINDING = "__wm_dom_emit"


def recorder_js() -> str:
    """记录器的源码。没下过就下一次。

    **下不到就抛。** 静默给一个空文件的话,表现是"DOM 模式下画面永远不出来",
    和"页面没动"分不清。
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / "rrweb.js"
    if not f.exists():
        import urllib.request
        log.info("下载 rrweb 记录器 …")
        with urllib.request.urlopen(RRWEB_URL, timeout=60) as r:
            f.write_bytes(r.read())
    return f.read_text(encoding="utf-8")


def viewer_js() -> bytes:
    """观看端要的那份(和记录器同一个包)。"""
    return (CACHE / "rrweb.js").read_bytes()


def viewer_css() -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / "rrweb.css"
    if not f.exists():
        import urllib.request
        with urllib.request.urlopen(RRWEB_CSS, timeout=60) as r:
            f.write_bytes(r.read())
    return f.read_bytes()


def ready() -> tuple[bool, str]:
    """这条路能不能走。**下过就能走** —— 它不依赖系统里的任何东西。"""
    try:
        recorder_js()
        return True, ""
    except Exception as e:                        # noqa: BLE001
        return False, f"rrweb 记录器下不到:{e}"


class DomSource:
    """一个 session 的 DOM 画面。

    `push` 由上层给 —— 它负责把事件发给所有观看者。
    """

    def __init__(self, push: Callable[[dict], Awaitable[None]] | None = None) -> None:
        self.push = push
        self.events: list[str] = []
        #: url -> (mime, 字节)。页面加载过的资源留一份,重放时从这儿出。
        self.res: dict[str, tuple[str, bytes]] = {}
        self.page_url = ""
        self.armed: set[str] = set()
        self.bytes = {"events": 0, "res": 0}
        self._pending: dict[str, dict] = {}
        self._cdp: Any = None
        self._sid = ""

    # ------------------------------------------------------------ 装上去

    async def arm(self, cdp: Any, session_id: str) -> None:
        """把记录器挂到这个 target 上。**每个 tab 都要挂,同一个只挂一次。**

        必须在导航之前 —— `addScriptToEvaluateOnNewDocument` 只对之后的文档生效。
        """
        if session_id in self.armed:
            return
        first = not self.armed
        self._cdp, self._sid = cdp, session_id
        src = recorder_js() + "\n;\n" + RECORD_JS
        #   ↑ 那个分号是必须的:UMD 最后一行是 `}))`,后面直接跟 `(() => …)()`
        #     会被解析成"调用上一个表达式的结果",报的是
        #     `(intermediate value)(...) is not a function`,和 rrweb 无关。
        await cdp.send("Runtime.addBinding", {"name": BINDING}, session_id=session_id)
        await cdp.send("Page.addScriptToEvaluateOnNewDocument",
                       {"source": src}, session_id=session_id)
        if first:
            # 事件回调是连接级的,**只挂一次** —— 每个 tab 挂一遍的话,
            # 同一条事件会被处理 N 次,缓冲里全是重复。
            for ev, fn in (("Runtime.bindingCalled", self._on_binding),
                           ("Network.responseReceived", self._on_resp),
                           ("Network.loadingFinished", self._on_done)):
                cdp.on(ev, fn)
        self.armed.add(session_id)
        log.info("DOM 记录器装上了(%d 个 tab)", len(self.armed))

    def note_url(self, url: str) -> None:
        """当前页地址 —— 取资源时要拿它当 `Referer`,不然很多 CDN 直接 403。"""
        if url:
            self.page_url = url

    # -------------------------------------------------------- 页面传出来

    def _on_binding(self, params: dict, _sid: str | None) -> None:
        if params.get("name") != BINDING:
            return
        payload = params.get("payload") or ""
        try:
            kind = json.loads(payload).get("type")
        except ValueError:
            return
        if kind == -1:                            # 页面里抛的,别吞
            log.warning("DOM 记录器出错:%s", payload[:300])
            return
        payload = self._rewrite(payload)
        if kind == 4:                             # Meta:新的一页,从这里重来
            self.events = [payload]
        else:
            self.events.append(payload)
            if len(self.events) > MAX_EVENTS:
                self._trim()
        self.bytes["events"] += len(payload)
        if self.push:
            asyncio.create_task(self.push({"type": "dom", "e": payload}))

    def _trim(self) -> None:
        """砍历史时**必须从一张全量快照砍起**。

        从中间砍等于把增量链断在半路 —— 重放出来的 DOM 从此和真页面不一致,
        **而且不报错**。找不到可切的点就宁可留着。
        """
        for i in range(len(self.events) // 2, len(self.events)):
            try:
                if json.loads(self.events[i]).get("type") == 4:
                    self.events = self.events[i:]
                    return
            except ValueError:
                continue
        log.debug("事件缓冲超了但没有可切的全量快照,先留着")

    # ------------------------------------------------- 资源:一律经过我们

    def _rw(self, url: str) -> str:
        if not url or not url.startswith(("http://", "https://")):
            return url                            # data: / blob: / 相对地址不动
        return f"/api/res?u={quote(url, safe='')}"

    def _rw_css(self, css: str) -> str:
        return re.sub(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)",
                      lambda m: f"url({self._rw(m.group(1))})", css)

    def _rw_node(self, n: Any) -> None:
        """**按结构走,不用正则扫整串** —— 正则会误伤正文里长得像地址的文字。"""
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
        except ValueError:
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
        """趁浏览器还留着的时候把响应体收下来。收不到不算错 —— `fetch` 会兜底。"""
        try:
            r = await self._cdp.send("Network.getResponseBody",
                                     {"requestId": rid}, session_id=self._sid)
        except Exception:                         # noqa: BLE001
            return
        body = r.get("body") or ""
        raw = base64.b64decode(body) if r.get("base64Encoded") else body.encode()
        if len(raw) <= 8 * 1024 * 1024:
            self.res[info["url"]] = (info["mime"] or "application/octet-stream", raw)
            self.bytes["res"] += len(raw)

    async def fetch(self, url: str) -> tuple[str, bytes] | None:
        """手上没有就去上游取一份。**带 `Referer` 和 UA** ——
        不带的话很多 CDN 直接 403,而那正是"让观看端自己回原站拿"靠不住的原因。
        """
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
        except Exception:                         # noqa: BLE001
            return None
        self.res[url] = (mime, body)
        self.bytes["res"] += len(body)
        return self.res[url]

    # ------------------------------------------------------------- 状态

    def snapshot_for_new_viewer(self) -> list[str]:
        """新来的观看者要从最近一张全量快照接上,不能从半路接。"""
        return list(self.events)

    def stats(self) -> dict:
        return {"events": len(self.events), "bytes": dict(self.bytes),
                "resources": len(self.res)}


UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
