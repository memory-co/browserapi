"""**那个口** —— 一个 server,全部 session 都在它下面(docs/v2/api/)。

**这一层不写业务逻辑。** 它只做序列化和鉴权 —— 多写一行判断,就是漂移的开始
(works/02 §2)。每个端点几乎都是一句"调 core 的某个方法,把结果 dump 成 JSON"。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from aiohttp import WSMsgType, web

from webmuxd import xpra as relay
from webmuxd.exceptions import (BadRequest, ReadOnly, SessionNotFound,
                                WebmuxdError)
from webmuxd import capture, locate
from webmuxd import models
from webmuxd import input as input_leg
from webmuxd.frames import HEADER_SIZE, UPSTREAM
from webmuxd.screen import Viewer
from webmuxd.sessions import Server, Session

#: 设了就要 `Authorization: Bearer <token>`,没设就不鉴权(api/README §1)。
TOKEN = os.environ.get("WEBMUXD_TOKEN") or ""

#: 只读 token:能看能读,**所有写操作 403**。
VIEW_TOKEN = os.environ.get("WEBMUXD_VIEW_TOKEN") or ""

_WRITE_METHODS = {"POST", "DELETE", "PUT", "PATCH"}


def _err(e: WebmuxdError) -> web.Response:
    """错误信封 —— 三边共用同一个形状(api/README §4)。"""
    status = e.http_status or {
        "not_found": 404, "tab_gone": 404, "not_clickable": 409, "timeout": 408,
        "nav_failed": 502, "busy": 409, "busy_human": 409, "read_only": 403,
        "chrome_gone": 503, "blocked_url": 400, "bad_request": 400,
        "session_not_found": 404, "session_exists": 409, "port_in_use": 409,
        "runtime_unavailable": 503, "session_dead": 410,
    }.get(e.code or "", 500)
    body: dict[str, Any] = {"code": e.code or "internal", "message": e.message}
    if e.details:
        body["details"] = e.details
    return web.json_response({"error": body}, status=status, dumps=_dumps)


def _dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False)


def _json(payload: Any, status: int = 200) -> web.Response:
    return web.json_response(payload, status=status, dumps=_dumps)


@web.middleware
async def auth(request: web.Request, handler: Callable[..., Awaitable]) -> web.Response:
    # 浏览器自己会去要 favicon,而且**不带我们的 query**。它回的是 204 空响应,
    # 没有任何可保护的东西 —— 挡它只会在日志里留下一条看着吓人的 403。
    if request.path == "/favicon.ico":
        request["writable"] = False
        return await handler(request)
    given = (request.headers.get("Authorization", "")
             .removeprefix("Bearer ").strip()) or request.query.get("t", "")

    # 一次性观看 token(`POST /api/live-token` 签的)—— 只读的写操作 403
    if given:
        sid = request.match_info.get("sid") if request.match_info else None
        known, read_only = (request.app["server"].get(sid).check_token(given)
                            if sid and sid in request.app["server"]
                            else (False, True))
        if known:
            if read_only and request.method in _WRITE_METHODS:
                return _err(ReadOnly("这是只读链接", code="read_only"))
            request["writable"] = not read_only
            return await handler(request)

    request["writable"] = True
    if TOKEN or VIEW_TOKEN:
        if VIEW_TOKEN and given == VIEW_TOKEN:
            # **画面那一半的只读,v2 才第一次是真的**(works/04 §3):
            # HTTP 靠方法判,而 WS 上的输入靠这个标记 —— 服务端丢弃,
            # 不是前端把按钮变灰。
            request["writable"] = False
            if request.method in _WRITE_METHODS:
                return _err(ReadOnly("这是只读链接", code="read_only"))
        elif not TOKEN or given != TOKEN:
            return _err(ReadOnly("token 不对", code="read_only"))
    return await handler(request)


@web.middleware
async def errors(request: web.Request, handler: Callable[..., Awaitable]) -> web.Response:
    """**动作失败是结果,请求失败才是错误。** 这里管的是后者。"""
    try:
        return await handler(request)
    except WebmuxdError as e:
        return _err(e)
    except json.JSONDecodeError:
        return _err(BadRequest("请求体不是合法 JSON", code="bad_request"))


def build(server: Server) -> web.Application:
    """**一个 server 一个口,session 是它下面的一段路径。**

    路由全部带 `/s/{sid}/` 前缀 —— 拿 session 走 `_s(request)` 一个入口,
    所以这一层是"加前缀 + 换那一个函数",不是重写
    ([k §4](../docs/v2/works/k-one-server.md#4-路由sid-前缀))。
    """
    app = web.Application(middlewares=[errors, auth])
    app["server"] = server
    r = app.router

    r.add_get("/s/{sid}/api/status", h_status)
    r.add_get("/s/{sid}/api/viewport", h_viewport)
    r.add_post("/s/{sid}/api/reset", h_reset)

    r.add_get("/s/{sid}/api/tabs", h_tabs)
    r.add_post("/s/{sid}/api/tabs", h_tab_new)
    r.add_post("/s/{sid}/api/tabs/reorder", h_reorder)
    r.add_get("/s/{sid}/api/tabs/{id}", h_tab_one)
    r.add_delete("/s/{sid}/api/tabs/{id}", h_tab_close)
    r.add_post("/s/{sid}/api/tabs/{id}/activate", h_tab_activate)
    r.add_post("/s/{sid}/api/tabs/{id}/dialog", h_dialog)
    r.add_get("/s/{sid}/api/tabs/{id}/history", h_history)
    for verb in ("goto", "back", "forward", "reload", "stop"):
        r.add_post(f"/s/{{sid}}/api/tabs/{{id}}/{verb}", _nav_handler(verb))

    r.add_post("/s/{sid}/api/act", h_act)
    r.add_get("/s/{sid}/api/screenshot", h_screenshot)
    r.add_get("/s/{sid}/api/snapshot", h_snapshot)
    r.add_get("/s/{sid}/api/res", h_res)
    r.add_get("/s/{sid}/api/view/mode", h_mode_get)
    r.add_post("/s/{sid}/api/view/mode", h_mode_set)
    r.add_get("/s/{sid}/api/rrweb.js", h_rrweb_js)
    r.add_get("/s/{sid}/api/rrweb.css", h_rrweb_css)
    r.add_get("/s/{sid}/api/text", h_text)

    r.add_get("/s/{sid}/api/log", h_log)
    r.add_get("/s/{sid}/api/log/bundle", h_bundle)
    r.add_get("/s/{sid}/api/log/{seq}/shot", h_log_shot)

    # 没有桌面之后那六类 —— **每类一个事件 + 一个端点,不动架构**
    # (works/06 §2)。事件走 /api/events,端点在这儿。
    r.add_get("/s/{sid}/api/pending", h_pending)
    r.add_get("/s/{sid}/api/downloads", h_downloads)
    r.add_get("/s/{sid}/api/downloads/{id}", h_download_file)
    r.add_post("/s/{sid}/api/upload", h_upload)
    r.add_get("/s/{sid}/api/files", h_files)
    r.add_post("/s/{sid}/api/file-chooser/{id}", h_file_fill)
    r.add_get("/s/{sid}/api/permissions", h_perms)
    r.add_post("/s/{sid}/api/permissions", h_perm_grant)
    r.add_delete("/s/{sid}/api/permissions", h_perm_reset)
    r.add_post("/s/{sid}/api/auth", h_auth_set)
    r.add_delete("/s/{sid}/api/auth", h_auth_clear)

    # 还没做:/api/tabs/{id}/favicon、/api/live-token、/api/openapi.json
    r.add_get("/s/{sid}/api/events", h_events)
    # 画面 —— v2 新增的两条,和 API 同一个口(works/04 §1)
    # **通道 = 一个上游系统的连接**([e §6.1](../docs/v2/works/e-client.md#61-通道--一个上游系统的连接))。
    # 路径前缀本身就是模型的一部分:看到 `/channel/x` 就知道它是一条通道。
    # 旧路径留着 —— 已经写进别人的脚本里了,**说不认就不认是另一种毛病**。
    r.add_get("/s/{sid}/channel/cdp", h_view)
    r.add_get("/s/{sid}/api/view", h_view)                  # 旧名,别删
    # xpra 那条画面路。**和 API 同一个口**,而且上行过白名单(works/11 §2.2)
    r.add_get("/s/{sid}/channel/rrweb", h_rrweb)
    r.add_get("/s/{sid}/channel/xpra", h_xpra)
    r.add_get("/s/{sid}/xpra", h_xpra)                      # 旧名,别删
    r.add_get("/s/{sid}/static/{name}", h_static)
    # server 自己那一层:有哪些 session
    r.add_get("/api/sessions", h_sessions)
    r.add_post("/api/sessions", h_session_new)
    r.add_delete("/api/sessions/{sid}", h_session_close)
    r.add_get("/api/server", h_server)
    r.add_delete("/api/server", h_server_kill)

    r.add_get("/s/{sid}/", h_index)
    r.add_get("/s/{sid}", h_index)
    r.add_get("/", h_index)
    # 浏览器每开一次页面都会去要它。不接的话日志里每次多一条 404 ——
    # **日志里的噪声会盖住真的问题**,这是花一行就能消掉的那种。
    r.add_get("/favicon.ico", lambda _r: web.Response(status=204))
    r.add_get("/healthz", lambda _r: web.Response(text="ok"))
    return app


def _srv(request: web.Request) -> Server:
    return request.app["server"]


def _s(request: web.Request) -> Session:
    """**这一个函数就是"哪个 session"的全部答案。**

    35 处 handler 都走它 —— 所以从"一个进程一个 session"变成
    "一个进程 N 个 session",改的是这里,不是它们。
    """
    return _srv(request).get(request.match_info["sid"])


async def _body(request: web.Request) -> dict:
    if not request.can_read_body:
        return {}
    data = await request.json()
    if not isinstance(data, dict):
        raise BadRequest("请求体要是个对象", code="bad_request")
    return data


# ------------------------------------------------------------------ session

async def h_status(request: web.Request) -> web.Response:
    return _json(_s(request).status())


async def h_viewport(request: web.Request) -> web.Response:
    """`crop_top` = Chromium 自带 UI 的高度,**外面按它裁 iframe**
    (works/04 §2)。硬编 0 等于让上层裁错。"""
    s = _s(request)
    tab_id = s.resolve_tab(request.query.get("tab"))
    await s.executor_for(tab_id)
    r = await s.cdp.send(
        "Runtime.evaluate",
        {"expression": "JSON.stringify([window.outerWidth, window.outerHeight,"
                       " window.innerWidth, window.innerHeight])",
         "returnByValue": True}, session_id=s._sessions[tab_id])
    ow, oh, iw, ih = json.loads(r["result"]["value"])
    return _json({"screen": {"w": ow, "h": oh},
                  "page": {"w": iw, "h": ih},
                  # headless 下 outer==inner,量出来就是 0 —— 那是真的没有 UI,
                  # 不是没量到
                  "crop_top": max(0, oh - ih)})


async def h_mode_get(request: web.Request) -> web.Response:
    """现在是哪种画面、这台 session 上能切哪几种。

    **能切哪几种是起 session 时定的,不是运行时算的**
    ([c §9.3](../docs/v2/works/c-view.md#93-能切到哪几条起-session-的时候就定了))。
    """
    return _json(_s(request).view.mode_info().to_json())


async def h_mode_set(request: web.Request) -> web.Response:
    """换一种画面。切的只有这一样东西 —— 输入、光标、tab、原生 UI 一行不动。"""
    body = await _body(request)
    want = body.get("mode") or body.get("transport") or ""
    return _json(await _s(request).view.switch(str(want), why="人选的"))


async def h_res(request: web.Request) -> web.Response:
    """DOM 那条画面用的资源转发。

    **观看端不回原站拿。** 记录器只记 `src`,让观看端自己去拉的话,
    要登录的站、认 `Referer` 的 CDN 全是破图 —— 实测某视频站一页 30 张图破 25 张。
    手上有就给,没有就带着 `Referer`/UA 去上游取一份;
    **取不到才 302 回原地址** —— 退回去至少不比不转发更差
    ([c §10.2](../docs/v2/works/c-view.md#102-那条连接经过我们))。
    """
    src = _s(request).view.dom
    u = request.query.get("u", "")
    if src is None or not u.startswith(("http://", "https://")):
        raise BadRequest("这个地址不能转发", code="bad_request")
    hit = await src.fetch(u)
    if not hit:
        raise web.HTTPFound(u)
    mime, blob = hit
    return web.Response(body=blob, content_type=mime.split(";")[0].strip(),
                        headers={"Cache-Control": "max-age=300"})


async def h_rrweb_js(_request: web.Request) -> web.Response:
    """观看端要的重放器。**和页面里那份记录器是同一个包** ——
    两边版本不一致的话,事件格式对不上,表现是画面局部不更新而且不报错。"""
    from webmuxd import rrweb as dom_mod
    return web.Response(body=dom_mod.viewer_js(),
                        content_type="application/javascript",
                        headers={"Cache-Control": "max-age=86400"})


async def h_rrweb_css(_request: web.Request) -> web.Response:
    from webmuxd import rrweb as dom_mod
    return web.Response(body=dom_mod.viewer_css(), content_type="text/css",
                        headers={"Cache-Control": "max-age=86400"})


async def h_reset(request: web.Request) -> web.Response:
    s = _s(request)
    for tab_id in list(s.tabs._by_id)[1:]:
        with contextlib.suppress(WebmuxdError):
            await s.tabs.close(tab_id)
    only = s.tabs.active
    if only:
        ex = await s.executor_for(only)
        await ex.run([{"type": "goto", "url": "about:blank"}])
    await s.cdp.send("Network.clearBrowserCookies")
    s.log.append("session", event="reset")
    return _json({"ok": True})


# --------------------------------------------------------------------- tabs

async def h_tabs(request: web.Request) -> web.Response:
    return _json(_s(request).tabs.list_json())


async def h_tab_one(request: web.Request) -> web.Response:
    s = _s(request)
    tab_id = request.match_info["id"]
    tab = s.tabs.get(tab_id)
    return _json(tab.to_json(index=s.tabs.index_of(tab_id),
                             active=tab_id == s.tabs.active))


async def h_tab_new(request: web.Request) -> web.Response:
    s = _s(request)
    body = await _body(request)
    tab = await s.open_tab(body.get("url") or "about:blank",
                           activate=body.get("active", True),
                           wait=body.get("wait", "load"))
    out = tab.to_json(index=s.tabs.index_of(tab.id), active=tab.id == s.tabs.active)
    return _json(out, status=201)


async def h_tab_close(request: web.Request) -> web.Response:
    return _json(await _s(request).tabs.close(request.match_info["id"]))


async def h_tab_activate(request: web.Request) -> web.Response:
    s = _s(request)
    tab = await s.tabs.activate(request.match_info["id"])
    return _json(tab.to_json(index=s.tabs.index_of(tab.id), active=True))


async def h_reorder(request: web.Request) -> web.Response:
    s = _s(request)
    order = (await _body(request)).get("order") or []
    known = list(s.tabs._order)
    rest = [i for i in known if i not in order]
    s.tabs._order = [i for i in order if i in known] + rest
    return _json(s.tabs.list_json())


async def h_history(request: web.Request) -> web.Response:
    s = _s(request)
    tab_id = request.match_info["id"]
    await s.executor_for(tab_id)
    h = await s.cdp.send("Page.getNavigationHistory",
                         session_id=s._sessions[tab_id])
    return _json({"entries": [{"index": i, "url": e["url"], "title": e["title"]}
                              for i, e in enumerate(h["entries"])],
                  "current": h["currentIndex"]})


def _nav_handler(verb: str):
    async def handler(request: web.Request) -> web.Response:
        s = _s(request)
        tab_id = request.match_info["id"]
        body = await _body(request)
        spec: dict[str, Any] = {"type": verb, **body}
        out = await s.act(tab=tab_id, actions=[spec],
                          user=body.get("user", "api"))
        first = out["results"][0]
        if not first.get("ok"):
            raise WebmuxdError(first.get("message", ""), code=first.get("error"),
                               details={"candidates": first.get("candidates", [])})
        tab = s.tabs.get(tab_id)
        return _json(tab.to_json(index=s.tabs.index_of(tab_id),
                                 active=tab_id == s.tabs.active))
    return handler


async def h_dialog(request: web.Request) -> web.Response:
    s = _s(request)
    tab_id = request.match_info["id"]
    body = await _body(request)
    if not s.tabs.get(tab_id).dialog:
        raise BadRequest("这个 tab 上没有待回应的弹窗", code="bad_request")
    # **不替用户决定** —— accept 没有默认值,调用方必须说(works/06 §2)
    if "accept" not in body:
        raise BadRequest("要说 accept:true 还是 false", code="bad_request")
    return _json(await s.native.dialogs.respond(
        tab_id, accept=bool(body["accept"]), text=body.get("text", ""),
        by=body.get("user", "api")))


# --------------------------------------------------------------- act / 读一眼

async def h_act(request: web.Request) -> web.Response:
    body = await _body(request)
    actions = body.get("actions")
    if not isinstance(actions, list) or not actions:
        raise BadRequest("actions 要是个非空数组", code="bad_request")
    return _json(await _s(request).act(
        tab=body.get("tab"), actions=actions, settle=body.get("settle"),
        note=body.get("note"), user=body.get("user", "api")))


async def h_snapshot(request: web.Request) -> web.Response:
    """这一页上有什么,**每样带一个 `@e1`**。

    这个口子回来过。当初砍 `/api/observe` 的理由是"那是一套关于 agent
    该怎么用浏览器的意见" —— 但那套意见此刻仍然在跑,每次 `click "登录"`
    都在用它([locate.snapshot](../webmuxd/locate.py))。
    **藏起来没有让它变小,只是让它没法被人调。**

    所以这一版把旋钮交出去:`interactive` / `selector` / `viewport` / `max`。
    """
    q = request.query
    snap = await _s(request).snapshot(
        q.get("tab"),
        interactive_only=q.get("interactive") in ("1", "true"),
        selector=q.get("selector") or None,
        viewport_only=q.get("viewport") in ("1", "true"),
        max_elements=int(q.get("max") or locate.MAX_ELEMENTS))
    return _json(snap.to_json())


async def h_screenshot(request: web.Request) -> web.Response:
    """那一刻的页面。

    **"读"这一面是三样:正文、一张图、和一份带 `@e1` 的结构**
    (`/api/text` / 这个 / `/api/snapshot`)。
    """
    s = _s(request)
    sid = await s._reading_session(request.query.get("tab"))
    data = await capture.screenshot(
        s.cdp, sid, full_page=request.query.get("full_page") == "true")
    return web.Response(body=data, content_type="image/webp")


async def h_text(request: web.Request) -> web.Response:
    s = _s(request)
    sid = await s._reading_session(request.query.get("tab"))
    return web.Response(text=await capture.text(s.cdp, sid),
                        content_type="text/plain")


# ---------------------------------------------------------------------- log

async def h_log(request: web.Request) -> web.Response:
    q = request.query
    entries = _s(request).log.read(
        limit=int(q.get("limit", 100)),
        after=int(q["after"]) if "after" in q else None,
        only=q.get("only"), user=q.get("user"), tab=q.get("tab"),
        kind=q.get("kind"))
    return _json({"entries": entries})


async def h_bundle(request: web.Request) -> web.Response:
    data = _s(request).log.bundle(tab=request.query.get("tab"))
    return web.Response(body=data, content_type="application/zip",
                        headers={"Content-Disposition": 'attachment; filename="bundle.zip"'})


async def h_log_shot(request: web.Request) -> web.Response:
    p = _s(request).log.shot_path(int(request.match_info["seq"]))
    if not p.exists():
        raise BadRequest("这一步没有截图", code="bad_request")
    return web.Response(body=p.read_bytes(), content_type="image/webp")


# -------------------------------------------------------------------- events

async def h_events(request: web.Request) -> web.WebSocketResponse:
    """内部机制,不是产品面 —— 写脚本的碰不到它(works/06 §5)。"""
    s = _s(request)
    ws = web.WebSocketResponse(heartbeat=15)
    await ws.prepare(request)

    after = int(request.query["after"]) if "after" in request.query else None
    prefixes = [p.rstrip("*") for p in (request.query.get("types") or "").split(",") if p]
    q, backlog = s.subscribe(after)

    def wanted(e: dict) -> bool:
        return not prefixes or any(e["type"].startswith(p) for p in prefixes)

    try:
        for e in backlog:
            if wanted(e):
                await ws.send_str(_dumps(e))
        pump = asyncio.create_task(_pump(ws, q, wanted))
        async for msg in ws:
            if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
        pump.cancel()
    finally:
        s.unsubscribe(q)
    return ws


async def _pump(ws: web.WebSocketResponse, q: asyncio.Queue,
                wanted: Callable[[dict], bool]) -> None:
    with contextlib.suppress(asyncio.CancelledError, ConnectionResetError):
        while True:
            e = await q.get()
            if wanted(e):
                await ws.send_str(_dumps(e))


# --------------------------------------------------------------------- 画面

#: 浏览器端那份的落地处 —— **构建产物,不在 git 里**
#: ([j §4.3](../docs/v2/works/j-layout.md#43-构建怎么接进-wheel))。
_BUILT = Path(__file__).resolve().parent / "_client"

#: 开发时的退路:还没往包里拷过,就直接读 `npm run build` 的产物。
#: **只是退路,不是等价物** —— 装出来的包里只有 `_BUILT` 那一份。
_DEV = Path(__file__).resolve().parents[1] / "webmuxjs" / "client" / "dist"


def client_dir() -> Path:
    """浏览器端那份在哪。**找不到就报,并说该跑哪一行** —— 不静默给个 404。"""
    for d in (_BUILT, _DEV):
        if (d / "index.html").exists():
            return d
    raise RuntimeError(
        "浏览器端那份还没构建:"
        f"{_BUILT} 和 {_DEV} 都没有 index.html —— "
        "在 webmuxjs/client/ 里跑 `npm install && npm run build`")


#: 观看页会去取的静态文件。**按后缀放行,不是目录服务** ——
#: 构建产物的文件名由 Vite 定,写死一张名字白名单会在改构建配置那天悄悄坏掉。
_STATIC_SUFFIX = frozenset({".js", ".css", ".map", ".woff2"})


async def h_index(request: web.Request) -> web.Response:
    """内置页 —— `/` 是那张 session 列表,`/s/<id>/` 是那个 session 的画面。

    **它不是"界面"**:画面 + 一条 tab 条 + 一个地址栏,加上一张
    "有哪些 session"的清单。没有登录页、没有设置面板、**没有仪表盘** ——
    `tmux ls` 就是一行一个,没有 CPU 曲线
    ([k §3](../docs/v2/works/k-one-server.md#3-那个口上看到什么))。

    **同一个文件。** 走哪条由地址决定,客户端自己认
    —— 服务端这儿没有第二份 HTML。
    """
    sid = request.match_info.get("sid")
    if sid and sid not in _srv(request):
        raise SessionNotFound(f"没有叫 {sid!r} 的 session",
                              code="session_not_found",
                              details={"have": sorted(_srv(request)._sessions)})
    return web.FileResponse(client_dir() / "index.html",
                            headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ server

async def h_sessions(request: web.Request) -> web.Response:
    """有哪些 session。**列表页和 `webmuxd ls` 用的是同一份。**"""
    return _json(_srv(request).list_json())


async def h_session_new(request: web.Request) -> web.Response:
    body = await _body(request)
    sid = str(body.get("id") or "").strip()
    if not sid:
        raise BadRequest("要给 session 起个名字", code="bad_request",
                         details={"how": 'POST /api/sessions {"id": "demo"}'})
    opts = {k: v for k, v in body.items() if k != "id"}
    info = await _srv(request).create(sid, **opts)
    return _json({"id": sid, "url": info.path(), "runtime": info.kind,
                  "notes": info.detail.get("notes") or []})


async def h_session_close(request: web.Request) -> web.Response:
    sid = request.match_info["sid"]
    await _srv(request).close(sid)
    return _json({"closed": sid})


async def h_server(request: web.Request) -> web.Response:
    srv = _srv(request)
    return _json({"ok": True, "sessions": len(srv),
                  "uptime_s": int(time.time() - srv.started_at),
                  "api": {"version": "1.0", "schema": "v1"}})


async def h_server_kill(request: web.Request) -> web.Response:
    """`kill-server` —— **一个都不许留**,然后自己也走。"""
    srv = _srv(request)
    n = len(srv)
    await srv.close_all()
    asyncio.get_running_loop().call_later(0.2, lambda: os.kill(os.getpid(),
                                                               signal.SIGTERM))
    return _json({"killed": n})


async def h_static(request: web.Request) -> web.FileResponse:
    """观看页要的那几个构建产物。

    **不是一个静态目录服务** —— 这个进程能读到的东西比一个 web 服务器该暴露的
    多得多。两道:名字里不许有路径分隔符和 `..`,后缀要在白名单里;
    然后还要落在 `client_dir()` 里面。
    """
    name = request.match_info["name"]
    d = client_dir()
    target = (d / name).resolve()
    if ("/" in name or "\\" in name or ".." in name
            or Path(name).suffix not in _STATIC_SUFFIX
            or d.resolve() not in target.parents
            or not target.is_file()):
        raise BadRequest(f"没有这个文件:{name}", code="not_found")
    return web.FileResponse(target, headers={"Cache-Control": "no-store"})


async def h_rrweb(request: web.Request) -> web.WebSocketResponse:
    """DOM 那条画面 —— rrweb 事件流,**只下行**。

    **这条通道不承载输入。** 不是"我们没实现",是结构上做死的:
    这个 handler 里没有任何一条路把收到的东西送出去 —— 上行的字节读完就丢。
    输入永远只走 `/channel/cdp`
    ([b §1](../docs/v2/works/b-input.md#1-收口在哪))。

    通道名跟的是**上游**(rrweb),不是使用者看到的那个词(DOM)——
    `/channel/x` 说的是"这条连接接的是哪个上游系统"
    ([e §6.1](../docs/v2/works/e-client.md#61-通道--一个上游系统的连接))。
    """
    s = _s(request)
    src = s.view.dom
    if src is None:
        raise BadRequest("这个 session 不是 DOM 模式,没有这条画面路",
                         code="not_found",
                         details={"how": "起的时候加 --transport dom,"
                                         "或者在界面上切到 DOM"})
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=0)
    await ws.prepare(request)

    async def send(msg: dict) -> None:
        if not ws.closed:
            await ws.send_str(_dumps(msg))

    # **新来的要从最近一张全量快照接上,不能从半路接。**
    # 增量链从中间开始重放出来的是一棵错的 DOM,而且不报错
    # ([c §5.5](../docs/v2/works/c-view.md#55-背压不能沿用丢旧保新))。
    for e in src.snapshot_for_new_viewer():
        with contextlib.suppress(Exception):
            await ws.send_str(_dumps({"type": "dom", "e": e}))
    src.listeners.add(send)
    try:
        async for msg in ws:
            # **读完就丢。** 这条通道上没有"上行"这回事 ——
            # 不是过滤,是根本没有接收端。
            if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                break
    finally:
        src.listeners.discard(send)
    return ws


async def h_xpra(request: web.Request) -> web.WebSocketResponse:
    """xpra 那条画面连接 —— 代理到上游,**上行过白名单**(view/relay.py)。

    走我们的口而不是直连 xpra,是为了 [a](../docs/v2/works/a-architecture.md)
    那条"一个口",以及 token 要在我们这儿校验一次 —— xpra 自己的鉴权
    是进程级的,不认我们的只读 token。
    """
    upstream = _srv(request).info(request.match_info["sid"]).detail.get("xpra_ws") or ""
    if not upstream:
        raise BadRequest("这个 session 不是 xpra 模式,没有这条画面路",
                         code="not_found",
                         details={"how": "起的时候加 --transport xpra"})
    return await relay.pump(request, upstream)


async def h_view(request: web.Request) -> web.WebSocketResponse:
    """帧下行 + ack / 输入上行 —— docs/v2/works/02 · 03。"""
    s = _s(request)
    ws = web.WebSocketResponse(heartbeat=20, max_msg_size=0)
    await ws.prepare(request)

    writable = bool(request.get("writable", True))
    v = Viewer(ws.send_bytes, lambda d: ws.send_str(_dumps(d)),
               writable=writable, name=request.query.get("as") or "")
    # **权限只在连接建立时说一次。** 鼠标移动一秒几十个事件,逐个回 403
    # 等于自己 DoS 自己(works/04 §3)。
    # `stats()` 里已经带了 `transport` —— 别再显式传一遍(会是 TypeError)。
    stats = {k: val for k, val in s.view.stats().items()
             if k not in ("viewers", "transport")}
    await v.send(models.Hello(writable=writable, protocol=HEADER_SIZE,
                              transport=s.view.mode, extra=stats).to_json())
    await s.view.add_viewer(v)
    try:
        async for msg in ws:
            if msg.type is not WSMsgType.TEXT:
                if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
                continue
            try:
                m = json.loads(msg.data)
            except ValueError:
                continue
            await _view_msg(s, v, m)
    finally:
        await s.view.remove_viewer(v)
    return ws


async def _view_msg(s: Session, v: Viewer, m: dict) -> None:
    kind = m.get("type")
    if kind not in UPSTREAM:
        return                                  # 白名单,不是黑名单
    if kind == "ack":
        fid = m.get("frameId")
        await s.view.on_viewer_ack(v, int(fid) if isinstance(fid, (int, float)) else None)
        return
    if not v.writable:
        return                                  # **服务端丢弃**,静默
    if kind == "resize":
        await s.view.resize(m.get("w") or 0, m.get("h") or 0)
    elif kind == "tab":
        tab_id = str(m.get("id") or "")
        if tab_id in s.tabs:
            await s.tabs.activate(tab_id)
    elif kind == "mode":
        # 切不了就把原因发回去。**不静默留在原来那种** ——
        # 使用者以为换了、画质却没变,比报错难查得多。
        try:
            await s.view.switch(str(m.get("mode") or ""), why="人选的")
        except WebmuxdError as e:
            await v.send(models.ModeError(
                e.message, (e.details or {}).get("hint", "")).to_json())
    else:
        await input_leg.deliver(s, s.view.target_session, m)


# ------------------------------------------------------- 没有桌面之后(works/06)

async def h_pending(request: web.Request) -> web.Response:
    """**挡着页面的东西一次给全。** UI 一连上先拉这个对齐,之后靠事件增量。"""
    return _json(_s(request).native.pending_json())


async def h_downloads(request: web.Request) -> web.Response:
    return _json({"downloads": _s(request).native.downloads.list_json()})


async def h_download_file(request: web.Request) -> web.Response:
    p = _s(request).native.downloads.path_of(request.match_info["id"])
    if p is None:
        raise BadRequest("没有这个下载,或者它还没完成", code="not_found")
    return web.FileResponse(p)


async def h_upload(request: web.Request) -> web.Response:
    """把文件放进 session 的 files 目录,回填文件选择框时按名字引用它。

    收两种:`multipart/form-data`,或者裸 body + `?name=`。
    """
    files = _s(request).native.files
    saved = []
    if request.content_type.startswith("multipart/"):
        reader = await request.multipart()
        while (part := await reader.next()) is not None:
            name = part.filename or part.name or "upload"
            saved.append(files.save(name, await part.read(decode=False)))
    else:
        name = request.query.get("name") or "upload"
        saved.append(files.save(name, await request.read()))
    return _json({"files": saved}, status=201)


async def h_files(request: web.Request) -> web.Response:
    return _json({"files": _s(request).native.files.list_files()})


async def h_file_fill(request: web.Request) -> web.Response:
    body = await _body(request)
    names = body.get("files")
    if names is not None and not isinstance(names, list):
        raise BadRequest("files 要是个数组(空数组 = 取消)", code="bad_request")
    return _json(await _s(request).native.files.fill(
        request.match_info["id"], names or [], by=body.get("user", "api")))


async def h_perms(request: web.Request) -> web.Response:
    return _json(_s(request).native.permissions.list_json())


async def h_perm_grant(request: web.Request) -> web.Response:
    body = await _body(request)
    names = body.get("names")
    if not isinstance(names, list) or not names:
        raise BadRequest("names 要是个非空数组", code="bad_request")
    return _json(await _s(request).native.permissions.grant(
        names, origin=body.get("origin", ""), by=body.get("user", "api")))


async def h_perm_reset(request: web.Request) -> web.Response:
    return _json(await _s(request).native.permissions.reset(
        by=request.query.get("user", "api")))


async def h_auth_set(request: web.Request) -> web.Response:
    body = await _body(request)
    if not body.get("user") or body.get("password") is None:
        raise BadRequest("要给 user 和 password", code="bad_request")
    return _json(await _s(request).native.auth.set(
        origin=body.get("origin", ""), user=body["user"],
        password=body["password"]))


async def h_auth_clear(request: web.Request) -> web.Response:
    return _json(await _s(request).native.auth.clear())


# --------------------------------------------------------------------------
# server 的进程入口 —— **一个 server 一个口**([k](../docs/v2/works/k-one-server.md))
# --------------------------------------------------------------------------

async def _run(args: argparse.Namespace) -> None:
    server = Server(data_root=args.data, bind=args.bind)
    runner = web.AppRunner(build(server))
    await runner.setup()
    site = web.TCPSite(runner, args.bind, args.port)
    await site.start()
    logging.info("server 起来了:http://%s:%d/  (还没有 session ——"
                 " `webmuxd new --id demo`)", args.bind, args.port)
    if args.bind not in ("127.0.0.1", "localhost", "::1"):
        logging.warning("绑在 %s —— **这台机器网络能到的人,拿到 token 就能"
                        "操作这里的浏览器**", args.bind)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    try:
        await stop.wait()
    finally:
        # **一个都不许留** —— 留下的是没人管的 chrome
        await server.close_all()
        await runner.cleanup()


def main() -> None:
    p = argparse.ArgumentParser(prog="webmuxd-server")
    # **默认只绑回环。**
    #
    # v1 这儿是 `0.0.0.0`,那时候它跑在容器里 —— 那个 `0.0.0.0` 是**容器内的**,
    # 外面还有 `docker -p` 那一层决定暴不暴露。v2 没有容器了,
    # `0.0.0.0` 就是真的 0.0.0.0([h](../docs/v2/works/h-runtime.md))
    # —— 前提变了,默认值必须跟着变。
    #
    # 而且 `/s/<id>/` 是**能直接操作浏览器**的画面口,不是 v1 那个纯 API 口。
    p.add_argument("--bind", "--host", dest="bind", default="127.0.0.1",
                   help="绑哪个地址。默认只绑本机;填 0.0.0.0 就是对外开放")
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("WEBMUXD_PORT", "7900")))
    p.add_argument("--data", default=os.environ.get("WEBMUXD_DATA", "/data"))
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
