"""没有桌面之后 —— 对着 docs/v2/works/06-no-desktop.md 校,跑在真 Chromium 上。

v1 里这批原生 UI 是"看不见但仍然阻塞",人换个视图就露出来了。v2 里它们
**根本不会渲染** —— 不拦,页面就静止在那儿,而人看不出为什么。

所以这个场景验的是三件事,逐类过一遍:**拦得下来、回填得进去、超时不静默**。
"""

import asyncio
import contextlib

import pytest
from aiohttp import web as aioweb
from aiohttp.test_utils import TestClient, TestServer

from webmuxd.core.cdp import CDP
from webmuxd.serve.app import build
from webmuxd.serve.session import Session

FILE_BODY = b"webmuxd v2 native ui"


@pytest.fixture
async def target():
    """一个真的 HTTP 靶子 —— 下载要 `Content-Disposition`,认证要 401。"""
    async def dl(_r):
        return aioweb.Response(body=FILE_BODY, headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": 'attachment; filename="报表.bin"'})

    async def page(_r):
        return aioweb.Response(content_type="text/html", text="""
            <body><input id=f type=file>
            <button id=b onclick="window.r = confirm('删掉吗?')">问</button>
            </body>""")

    async def secret(request):
        if not request.headers.get("Authorization"):
            return aioweb.Response(status=401, text="nope",
                                   headers={"WWW-Authenticate": 'Basic realm="x"'})
        return aioweb.Response(text="进来了 " + request.headers["Authorization"][:20])

    app = aioweb.Application()
    app.router.add_get("/dl", dl)
    app.router.add_get("/page", page)
    app.router.add_get("/secret", secret)
    server = TestServer(app)
    await server.start_server()
    yield f"http://127.0.0.1:{server.port}"
    await server.close()


@pytest.fixture
async def live(chromium_endpoint, tmp_path):
    conn = await CDP.connect(chromium_endpoint)
    session = Session(conn, data_dir=tmp_path, human_yield_ms=0)
    await session.start()
    client = TestClient(TestServer(build(session)))
    await client.start_server()
    probe = await CDP.connect(chromium_endpoint)
    try:
        yield session, client, probe
    finally:
        await probe.close()
        with contextlib.suppress(Exception):
            await client.close()
        await session.close()
        await conn.close()


async def _sid(probe, tab):
    r = await probe.send("Target.attachToTarget",
                         {"targetId": tab.target_id, "flatten": True})
    return r["sessionId"]


async def _wait(cond, timeout=15):
    async with asyncio.timeout(timeout):
        while True:
            got = cond()
            if got:
                return got
            await asyncio.sleep(0.05)


# ------------------------------------------------------------------ 对话框

async def test_confirm_挡住页面_回填之后才继续(live, target):
    session, client, probe = live
    tab = await session.open_tab(target + "/page")
    sid = await _sid(probe, tab)

    # confirm 会把 JS 停在那儿 —— 所以这条 evaluate 不能 await
    asyncio.create_task(probe.send(
        "Runtime.evaluate", {"expression": "b.click()", "userGesture": True},
        session_id=sid, timeout=30))

    p = await _wait(lambda: session.native.dialogs.list_json())
    assert p[0]["subtype"] == "confirm" and p[0]["text"] == "删掉吗?"
    # tab 上也要看得见 —— 弹窗挡住了页面,它不只是一条通知
    assert session.tabs.get(tab.id).dialog["message"] == "删掉吗?"

    r = await client.post(f"/api/tabs/{tab.id}/dialog", json={"accept": True})
    assert r.status == 200

    got = await _wait(lambda: session.native.dialogs.pending == {} or None)
    assert got is not None
    v = await probe.send("Runtime.evaluate",
                         {"expression": "window.r", "returnByValue": True},
                         session_id=sid)
    assert v["result"]["value"] is True
    assert session.tabs.get(tab.id).dialog is None


async def test_不给_accept_就是_400_不替你决定(live, target):
    session, client, probe = live
    tab = await session.open_tab(target + "/page")
    sid = await _sid(probe, tab)
    asyncio.create_task(probe.send(
        "Runtime.evaluate", {"expression": "b.click()", "userGesture": True},
        session_id=sid, timeout=30))
    await _wait(lambda: session.native.dialogs.list_json())

    r = await client.post(f"/api/tabs/{tab.id}/dialog", json={})
    assert r.status == 400, "**不替用户决定** —— accept 没有默认值"
    await client.post(f"/api/tabs/{tab.id}/dialog", json={"accept": False})


async def test_超时走_dismiss_而且写进日志(live, target):
    session, client, probe = live
    session.native.dialogs.timeout = 0.5          # 把超时压短
    tab = await session.open_tab(target + "/page")
    sid = await _sid(probe, tab)
    asyncio.create_task(probe.send(
        "Runtime.evaluate", {"expression": "b.click()", "userGesture": True},
        session_id=sid, timeout=30))
    await _wait(lambda: session.native.dialogs.list_json())

    await _wait(lambda: session.native.dialogs.pending == {} or None, timeout=10)
    v = await probe.send("Runtime.evaluate",
                         {"expression": "window.r", "returnByValue": True},
                         session_id=sid)
    assert v["result"]["value"] is False, "超时该 dismiss —— 没人回答就是别做"

    # **超时不静默**:页面为什么动了,日志里得有这一行
    rows = [e for e in session.log.read(limit=50, kind="dialog")]
    assert any(e.get("action") == "timeout" for e in rows), rows


# -------------------------------------------------------------------- 下载

async def test_下载落到_session_目录_而且取得回来(live, target):
    session, client, probe = live
    tab = await session.open_tab(target + "/page")
    sid = await _sid(probe, tab)
    await probe.send("Runtime.evaluate",
                     {"expression": f"location.href={target + '/dl'!r}"},
                     session_id=sid)

    done = await _wait(lambda: [d for d in session.native.downloads.list_json()
                                if d["state"] == "done"], timeout=20)
    item = done[0]
    assert item["file"] == "报表.bin"

    r = await client.get("/api/downloads")
    assert r.status == 200 and (await r.json())["downloads"][0]["file"] == "报表.bin"
    r = await client.get(f"/api/downloads/{item['id']}")
    assert r.status == 200 and await r.read() == FILE_BODY

    rows = list(session.log.read(limit=50, kind="download"))
    assert any(e.get("state") == "done" for e in rows)


# ---------------------------------------------------------------- 文件选择

async def test_文件选择拦得下来_填得进去(live, target):
    session, client, probe = live
    tab = await session.open_tab(target + "/page")
    sid = await _sid(probe, tab)

    r = await client.post("/api/upload?name=票据.txt", data=b"hello")
    assert r.status == 201 and (await r.json())["files"] == ["票据.txt"]

    await probe.send("Runtime.evaluate",
                     {"expression": "f.click()", "userGesture": True},
                     session_id=sid)
    pend = await _wait(lambda: session.native.files.list_json())
    assert pend[0]["mode"] in ("selectSingle", "selectMultiple")

    r = await client.post(f"/api/file-chooser/{pend[0]['id']}",
                          json={"files": ["票据.txt"]})
    assert r.status == 200

    await asyncio.sleep(0.3)
    v = await probe.send("Runtime.evaluate",
                         {"expression": "f.files[0] && f.files[0].name",
                          "returnByValue": True}, session_id=sid)
    assert v["result"]["value"] == "票据.txt"


async def test_上传的名字过一道_不带路径出去(live):
    session, client, _ = live
    r = await client.post("/api/upload?name=../../etc/passwd", data=b"x")
    saved = (await r.json())["files"][0]
    assert "/" not in saved and ".." not in saved


# -------------------------------------------------------------------- 权限

async def test_默认全拒_显式才给(live):
    session, client, _ = live
    r = await client.get("/api/permissions")
    assert (await r.json())["default"] == "deny"

    r = await client.post("/api/permissions", json={"names": ["geolocation"]})
    assert r.status == 200 and (await r.json())["names"] == ["geolocation"]
    assert "geolocation" in (await (await client.get("/api/permissions")).json())["granted"]["*"]

    assert (await client.delete("/api/permissions")).status == 200
    assert (await (await client.get("/api/permissions")).json())["granted"] == {}


async def test_不认识的权限名要说出来_而不是原样丢给_cdp(live):
    _, client, _ = live
    r = await client.post("/api/permissions", json={"names": ["随便编的"]})
    assert r.status == 400
    body = await r.json()
    assert "随便编的" in body["error"]["details"]["unknown"]
    assert "geolocation" in body["error"]["details"]["known"]


# ---------------------------------------------------------------- Basic 认证

async def test_认证默认不开_撞上_401_再设凭证重进(live, target):
    """真实流程就是这个顺序:**先撞上,再设,再进** —— 而不是预先给每个请求上税。"""
    session, client, probe = live
    assert session.native.auth.on is False, "默认不开 —— 拦 auth 要给每个请求上税"

    tab = await session.open_tab("about:blank")
    sid = await _sid(probe, tab)

    # 没开拦截时,401 是**看得见的失败**(服务器那个 body),不是页面静止
    await client.post(f"/api/tabs/{tab.id}/goto", json={"url": target + "/secret"})
    await asyncio.sleep(0.3)
    v = await probe.send("Runtime.evaluate",
                         {"expression": "document.body.innerText",
                          "returnByValue": True}, session_id=sid)
    assert "进来了" not in (v["result"]["value"] or "")

    r = await client.post("/api/auth", json={"user": "u", "password": "p"})
    assert r.status == 200 and session.native.auth.on is True

    await client.post(f"/api/tabs/{tab.id}/reload", json={})
    await asyncio.sleep(0.8)
    v = await probe.send("Runtime.evaluate",
                         {"expression": "document.body.innerText",
                          "returnByValue": True}, session_id=sid)
    assert "进来了" in (v["result"]["value"] or "")

    rows = list(session.log.read(limit=50, kind="auth"))
    assert any(e.get("event") == "answered" for e in rows)
    # **凭证不进日志** —— 和动作层那条同一个规矩
    assert all(e.get("password") in (None, "***") for e in rows)

    assert (await client.delete("/api/auth")).status == 200
    assert session.native.auth.on is False


# ------------------------------------------------------------------ 一次给全

async def test_挡着页面的东西一次给全(live, target):
    session, client, probe = live
    tab = await session.open_tab(target + "/page")
    sid = await _sid(probe, tab)
    asyncio.create_task(probe.send(
        "Runtime.evaluate", {"expression": "b.click()", "userGesture": True},
        session_id=sid, timeout=30))
    await _wait(lambda: session.native.dialogs.list_json())

    body = await (await client.get("/api/pending")).json()
    assert body["dialogs"] and body["dialogs"][0]["subtype"] == "confirm"
    assert set(body) == {"dialogs", "file_choosers", "downloads",
                         "permissions", "auth"}
    await client.post(f"/api/tabs/{tab.id}/dialog", json={"accept": False})
