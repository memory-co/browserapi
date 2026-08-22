"""端到端:HTTP 壳 + 引擎 + 真 Chromium。

对着 docs/v1/api/ 的端点总表校。这是第一次把所有东西连起来跑。
"""

import asyncio
import json
import zipfile

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from webmuxd.cdp import CDP
from webmuxd.serve import build
from webmuxd.sessions import Server


def _one(session, sid: str = "work"):
    """一个只装着这一个 session 的 server。

    **测试也走 `/s/<id>/`** —— 那是真实的地址形状,绕过它就等于不测路由
    ([k §4](../../docs/v2/works/k-one-server.md#4-路由s-id-前缀))。
    """
    import tempfile
    srv = Server(data_root=tempfile.mkdtemp(prefix="wm-srv-"))
    srv.adopt(sid, session)
    return srv
from webmuxd.sessions import Session

pytestmark = pytest.mark.asyncio

FORM = (
    "data:text/html;charset=utf-8,<title>结算</title>"
    "<button id=go onclick=\"document.getElementById('out').textContent='订单已提交'\">"
    "提交订单</button><div id=out></div>"
)


@pytest.fixture
async def client(chromium_endpoint, tmp_path):
    cdp = await CDP.connect(chromium_endpoint)
    sess = Session(cdp, data_dir=tmp_path, human_yield_ms=0)
    await sess.start()
    c = TestClient(TestServer(build(_one(sess))))
    await c.start_server()
    try:
        yield c
    finally:
        await c.close()
        await sess.close()
        await cdp.close()


async def _tab_with_form(client) -> str:
    r = await client.post("/s/work/api/tabs", json={"url": FORM})
    tab = await r.json()
    await asyncio.sleep(0.6)
    return tab["id"]


# ------------------------------------------------------------------ 端点在

async def test_status(client):
    d = await (await client.get("/s/work/api/status")).json()
    assert d["ok"] and d["chrome"]["alive"]
    assert d["api"] == {"version": "1.0", "schema": "v1"}


async def test_tabs_crud(client):
    r = await client.post("/s/work/api/tabs", json={"url": "about:blank"})
    assert r.status == 201, "新建 tab 该返回 201"
    tab = await r.json()

    listing = await (await client.get("/s/work/api/tabs")).json()
    assert tab["id"] in [t["id"] for t in listing["tabs"]]
    assert listing["active"] == tab["id"]

    one = await (await client.get(f"/s/work/api/tabs/{tab['id']}")).json()
    assert one["id"] == tab["id"]

    closed = await (await client.delete(f"/s/work/api/tabs/{tab['id']}")).json()
    assert closed["closed"] == tab["id"]


async def test_missing_tab_is_404_with_a_reason(client):
    r = await client.get("/s/work/api/tabs/t_9999")
    assert r.status == 404
    body = await r.json()
    assert body["error"]["code"] == "tab_gone"
    assert body["error"]["details"]["reason"] in ("closed", "evicted")


async def test_privileged_url_is_rejected(client):
    r = await client.post("/s/work/api/tabs", json={"url": "chrome://settings"})
    assert r.status == 400
    assert (await r.json())["error"]["code"] == "blocked_url"


# -------------------------------------------------------------------- act

async def test_act_end_to_end(client):
    tab = await _tab_with_form(client)
    r = await client.post("/s/work/api/act", json={
        "tab": tab, "actions": [{"type": "click", "text": "提交订单"}],
        "note": "购物车已确认,现在下单", "user": "claudecode"})
    assert r.status == 200
    d = await r.json()

    (res,) = d["results"]
    assert res["ok"] and res["hit"]["name"] == "提交订单"
    assert res["after"]["changed"] == "出现『订单已提交』", res["after"]
    assert "log_from" in d, "得告诉调用方这批动作在日志里从哪开始"


async def test_failed_action_comes_back_as_a_result_with_candidates(client):
    """**动作失败是结果,不是 HTTP 错误** —— 前面成功的那些不能跟着丢。"""
    tab = await _tab_with_form(client)
    r = await client.post("/s/work/api/act", json={
        "tab": tab, "actions": [{"type": "click", "text": "根本没有这个"}]})
    assert r.status == 200
    (res,) = (await r.json())["results"]
    assert not res["ok"] and res["error"] == "not_found"
    assert res["candidates"], "失败那条得带候选"


async def test_act_stops_at_the_first_error(client):
    tab = await _tab_with_form(client)
    d = await (await client.post("/s/work/api/act", json={"tab": tab, "actions": [
        {"type": "click", "text": "提交订单"},
        {"type": "click", "text": "没有这个"},
        {"type": "click", "text": "提交订单"},
    ]})).json()
    assert len(d["results"]) == 2


async def test_act_without_actions_is_a_bad_request(client):
    r = await client.post("/s/work/api/act", json={"actions": []})
    assert r.status == 400 and (await r.json())["error"]["code"] == "bad_request"


# ------------------------------------------------------------------ 读一眼

async def test_读的口子只有两个(client):
    """**一张图,和正文。**

    `/api/observe` 砍了 —— 那是一包"agent 该怎么用浏览器"的意见
    ([capture.py](../../webmuxd/capture.py))。这条同时守着**它别悄悄回来**。
    """
    tab = await _tab_with_form(client)

    r = await client.get(f"/s/work/api/screenshot?tab={tab}")
    assert r.status == 200 and r.content_type == "image/webp"
    assert (await r.read())[:4] == b"RIFF"

    t = await client.get(f"/s/work/api/text?tab={tab}")
    assert t.content_type == "text/plain" and "提交订单" in await t.text()

    gone = await client.get(f"/s/work/api/observe?tab={tab}")
    assert gone.status == 404, "/s/work/api/observe 又回来了"


async def test_读一眼会把后台_tab_切到前台_而且不吭声(client):
    """**这是当前行为,不是当前该有的行为。**

    要像素就得在前台(Chromium 不渲染后台 tab),所以读一眼会切 tab ——
    **它改状态,却不走那把动作锁**
    ([issue](../../docs/v2/issues/读一眼会改状态却不排队.md))。

    原来那个 `/api/observe` 至少还在 notes 里说一句;砍成裸字节之后
    连那句话都没地方放。这条测试钉住现状,**修的时候它会红**,
    红了就去看那篇 issue。
    """
    first = await _tab_with_form(client)
    await client.post("/s/work/api/tabs", json={"url": "about:blank"})   # 变成 active
    before = (await (await client.get("/s/work/api/tabs")).json())["active"]
    assert before != first

    await client.get(f"/s/work/api/screenshot?tab={first}")
    after = (await (await client.get("/s/work/api/tabs")).json())["active"]
    assert after == first, "读一眼没把 tab 切到前台,那图应该是白的"


# ------------------------------------------------------------------- log

async def test_log_records_the_action_with_note_and_user(client):
    tab = await _tab_with_form(client)
    await client.post("/s/work/api/act", json={
        "tab": tab, "actions": [{"type": "click", "text": "提交订单"}],
        "note": "购物车已确认", "user": "claudecode"})

    d = await (await client.get("/s/work/api/log?kind=action")).json()
    e = d["entries"][-1]
    assert e["user"] == "claudecode" and e["note"] == "购物车已确认"
    assert e["target"] == {"text": "提交订单"} and e["hit"]["name"] == "提交订单"


async def test_tab_lifecycle_is_persisted_not_just_evented(client):
    """事件只在内存里活 1000 条、重启就没;**生死要落盘**(api/log.md §3)。"""
    tab = await _tab_with_form(client)
    await client.delete(f"/s/work/api/tabs/{tab}")

    d = await (await client.get("/s/work/api/log?kind=tab")).json()
    events = [(e["event"], e.get("tab")) for e in d["entries"]]
    assert ("opened", tab) in events and ("closed", tab) in events


async def test_log_filters(client):
    tab = await _tab_with_form(client)
    await client.post("/s/work/api/act", json={"tab": tab, "user": "a",
                                        "actions": [{"type": "click", "text": "提交订单"}]})
    await client.post("/s/work/api/act", json={"tab": tab, "user": "b",
                                        "actions": [{"type": "click", "text": "没有"}]})

    failed = await (await client.get("/s/work/api/log?only=failed")).json()
    assert all(e["ok"] is False for e in failed["entries"])
    mine = await (await client.get("/s/work/api/log?user=a")).json()
    assert {e["user"] for e in mine["entries"]} == {"a"}


async def test_bundle_downloads(client):
    await _tab_with_form(client)
    r = await client.get("/s/work/api/log/bundle")
    assert r.status == 200
    z = zipfile.ZipFile(__import__("io").BytesIO(await r.read()))
    assert "index.html" in z.namelist()


# ----------------------------------------------------------------- events

async def test_event_stream_pushes_tab_changes(client):
    ws = await client.ws_connect("/s/work/api/events?types=tab.*")
    await client.post("/s/work/api/tabs", json={"url": "about:blank"})

    seen = []
    for _ in range(6):
        try:
            msg = await asyncio.wait_for(ws.receive(), timeout=3)
        except asyncio.TimeoutError:
            break
        if msg.type.name == "TEXT":
            seen.append(json.loads(msg.data))
        if any(e["type"] == "tab.created" for e in seen):
            break
    await ws.close()
    assert any(e["type"] == "tab.created" for e in seen), seen


async def test_seq_is_shared_between_log_and_events(client):
    """拿一条日志的 seq 就能在事件流里找到它前后发生了什么(works/06 §5)。"""
    tab = await _tab_with_form(client)
    d = await (await client.post("/s/work/api/act", json={
        "tab": tab, "actions": [{"type": "click", "text": "提交订单"}]})).json()
    log_from = d["log_from"]

    entries = (await (await client.get("/s/work/api/log")).json())["entries"]
    seqs = [e["seq"] for e in entries]
    assert log_from in seqs
    assert seqs == sorted(seqs), "seq 不是单调的"


# ------------------------------------------------------------------ 并发

async def test_only_one_action_at_a_time(client):
    """**不排队、不交错** —— 排队会让"谁先点"变得不可预测(api/README §1)。"""
    tab = await _tab_with_form(client)
    slow = {"tab": tab, "actions": [{"type": "wait_for", "ms": 800}]}
    fast = {"tab": tab, "actions": [{"type": "click", "text": "提交订单"}]}

    a = asyncio.create_task(client.post("/s/work/api/act", json=slow))
    await asyncio.sleep(0.15)
    b = await client.post("/s/work/api/act", json=fast)
    await a

    assert b.status == 409
    assert (await b.json())["error"]["code"] == "busy"
