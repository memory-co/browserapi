"""sessiond 的 HTTP 壳 —— docs/v1/api/。

**这一层不写业务逻辑。** 它只做序列化和鉴权 —— 多写一行判断,就是漂移的开始
(works/02 §2)。每个端点几乎都是一句"调 core 的某个方法,把结果 dump 成 JSON"。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from typing import Any, Awaitable, Callable

from aiohttp import WSMsgType, web

from webmuxd.core import locate
from webmuxd.errors import BadRequest, ReadOnly, WebmuxdError
from webmuxd.serve.session import Session

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
    if TOKEN or VIEW_TOKEN:
        given = (request.headers.get("Authorization", "")
                 .removeprefix("Bearer ").strip()) or request.query.get("t", "")
        if VIEW_TOKEN and given == VIEW_TOKEN:
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


def build(session: Session) -> web.Application:
    app = web.Application(middlewares=[errors, auth])
    app["session"] = session
    r = app.router

    r.add_get("/api/status", h_status)
    r.add_get("/api/viewport", h_viewport)
    r.add_post("/api/reset", h_reset)

    r.add_get("/api/tabs", h_tabs)
    r.add_post("/api/tabs", h_tab_new)
    r.add_post("/api/tabs/reorder", h_reorder)
    r.add_get("/api/tabs/{id}", h_tab_one)
    r.add_delete("/api/tabs/{id}", h_tab_close)
    r.add_post("/api/tabs/{id}/activate", h_tab_activate)
    r.add_post("/api/tabs/{id}/dialog", h_dialog)
    r.add_get("/api/tabs/{id}/history", h_history)
    for verb in ("goto", "back", "forward", "reload", "stop"):
        r.add_post(f"/api/tabs/{{id}}/{verb}", _nav_handler(verb))

    r.add_post("/api/act", h_act)
    r.add_get("/api/observe", h_observe)
    r.add_get("/api/observe/{obs}/screenshot", h_obs_shot)
    r.add_get("/api/screenshot", h_screenshot)
    r.add_get("/api/text", h_text)

    r.add_get("/api/log", h_log)
    r.add_get("/api/log/bundle", h_bundle)
    r.add_get("/api/log/{seq}/shot", h_log_shot)

    r.add_get("/api/events", h_events)
    r.add_get("/healthz", lambda _r: web.Response(text="ok"))
    return app


def _s(request: web.Request) -> Session:
    return request.app["session"]


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
    s = _s(request)
    obs = await s.observe(annotate=False, text="none", max_elements=0)
    vp = obs.page.get("viewport", {})
    return _json({"screen": vp, "page": vp, "crop_top": 0})


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
    tab = await s.tabs.open(body.get("url") or "about:blank",
                            activate=body.get("active", True))
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
    tab = s.tabs.get(tab_id)
    if not tab.dialog:
        raise BadRequest("这个 tab 上没有待回应的弹窗", code="bad_request")
    await s.executor_for(tab_id)
    await s.cdp.send("Page.handleJavaScriptDialog",
                     {"accept": bool(body.get("accept")),
                      "promptText": body.get("text", "")},
                     session_id=s._sessions[tab_id])
    s.tabs.update(tab_id, dialog=None)
    return _json({"ok": True})


# ---------------------------------------------------------------- act/observe

async def h_act(request: web.Request) -> web.Response:
    body = await _body(request)
    actions = body.get("actions")
    if not isinstance(actions, list) or not actions:
        raise BadRequest("actions 要是个非空数组", code="bad_request")
    return _json(await _s(request).act(
        tab=body.get("tab"), actions=actions, settle=body.get("settle"),
        note=body.get("note"), user=body.get("user", "api")))


def _obs_kwargs(q) -> dict[str, Any]:
    return {
        "annotate": q.get("annotate", "true") != "false",
        "viewport_only": q.get("viewport_only") == "true",
        "max_elements": int(q.get("max_elements", locate.MAX_ELEMENTS)),
        "text": q.get("text", "digest"),
    }


async def h_observe(request: web.Request) -> web.Response:
    s = _s(request)
    obs = await s.observe(tab=request.query.get("tab"), **_obs_kwargs(request.query))
    request.app.setdefault("shots", {})[obs.id] = (obs.screenshot, obs.plain_screenshot)
    return _json(obs.to_json(shot_url=f"/api/observe/{obs.id}/screenshot"))


async def h_obs_shot(request: web.Request) -> web.Response:
    pair = request.app.get("shots", {}).get(request.match_info["obs"])
    if not pair:
        raise BadRequest("这次观测的截图已经不在了", code="bad_request")
    marked, plain = pair
    want_plain = request.query.get("annotate") == "false"
    return web.Response(body=plain if want_plain else marked,
                        content_type="image/webp")


async def h_screenshot(request: web.Request) -> web.Response:
    from webmuxd.core.observe import _capture
    s = _s(request)
    tab_id = s.resolve_tab(request.query.get("tab"))
    await s.bring_to_front(tab_id)
    await s.executor_for(tab_id)
    data = await _capture(s.cdp, s._sessions[tab_id],
                          full_page=request.query.get("full_page") == "true")
    return web.Response(body=data, content_type="image/webp")


async def h_text(request: web.Request) -> web.Response:
    s = _s(request)
    obs = await s.observe(tab=request.query.get("tab"), annotate=False,
                          text="full", max_elements=0)
    return web.Response(text=obs.text, content_type="text/plain")


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
