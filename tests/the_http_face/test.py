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
    c = TestClient(TestServer(build(sess)))
    await c.start_server()
    try:
        yield c
    finally:
        await c.close()
        await sess.close()
        await cdp.close()


async def _tab_with_form(client) -> str:
    r = await client.post("/api/tabs", json={"url": FORM})
    tab = await r.json()
    await asyncio.sleep(0.6)
    return tab["id"]


# ------------------------------------------------------------------ 端点在

async def test_status(client):
    d = await (await client.get("/api/status")).json()
    assert d["ok"] and d["chrome"]["alive"]
    assert d["api"] == {"version": "1.0", "schema": "v1"}


async def test_tabs_crud(client):
    r = await client.post("/api/tabs", json={"url": "about:blank"})
    assert r.status == 201, "新建 tab 该返回 201"
    tab = await r.json()

    listing = await (await client.get("/api/tabs")).json()
    assert tab["id"] in [t["id"] for t in listing["tabs"]]
    assert listing["active"] == tab["id"]

    one = await (await client.get(f"/api/tabs/{tab['id']}")).json()
    assert one["id"] == tab["id"]

    closed = await (await client.delete(f"/api/tabs/{tab['id']}")).json()
    assert closed["closed"] == tab["id"]


async def test_missing_tab_is_404_with_a_reason(client):
    r = await client.get("/api/tabs/t_9999")
    assert r.status == 404
    body = await r.json()
    assert body["error"]["code"] == "tab_gone"
    assert body["error"]["details"]["reason"] in ("closed", "evicted")


async def test_privileged_url_is_rejected(client):
    r = await client.post("/api/tabs", json={"url": "chrome://settings"})
    assert r.status == 400
    assert (await r.json())["error"]["code"] == "blocked_url"


# -------------------------------------------------------------------- act

async def test_act_end_to_end(client):
    tab = await _tab_with_form(client)
    r = await client.post("/api/act", json={
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
    r = await client.post("/api/act", json={
        "tab": tab, "actions": [{"type": "click", "text": "根本没有这个"}]})
    assert r.status == 200
    (res,) = (await r.json())["results"]
    assert not res["ok"] and res["error"] == "not_found"
    assert res["candidates"], "失败那条得带候选"


async def test_act_stops_at_the_first_error(client):
    tab = await _tab_with_form(client)
    d = await (await client.post("/api/act", json={"tab": tab, "actions": [
        {"type": "click", "text": "提交订单"},
        {"type": "click", "text": "没有这个"},
        {"type": "click", "text": "提交订单"},
    ]})).json()
    assert len(d["results"]) == 2


async def test_act_without_actions_is_a_bad_request(client):
    r = await client.post("/api/act", json={"actions": []})
    assert r.status == 400 and (await r.json())["error"]["code"] == "bad_request"


# ---------------------------------------------------------------- observe

async def test_observe_returns_everything_at_once(client):
    tab = await _tab_with_form(client)
    d = await (await client.get(f"/api/observe?tab={tab}")).json()

    assert d["observation_id"].startswith("obs_")
    assert d["page"]["title"] == "结算"
    assert d["elements"][0]["name"] == "提交订单"
    assert d["screenshot"]["format"] == "webp"
    assert "tabs" in d and "notes" in d

    shot = await client.get(d["screenshot"]["url"])
    assert shot.status == 200 and shot.content_type == "image/webp"
    # **只有一张。** `?annotate=false` 那个版本没有了 —— 标注不再进页面,
    # 于是"干净版"和它就是同一张(issues/标注层会被人看见.md)
    same = await client.get(d["screenshot"]["url"] + "?annotate=false")
    assert await same.read() == await shot.read()


async def test_screenshot_and_text(client):
    tab = await _tab_with_form(client)
    r = await client.get(f"/api/screenshot?tab={tab}")
    assert r.status == 200 and (await r.read())[:4] == b"RIFF"

    t = await client.get(f"/api/text?tab={tab}")
    assert "提交订单" in await t.text()


async def test_observing_a_background_tab_says_it_switched(client):
    """要像素就得在前台 —— 而且**得说出来**,因为画面跳了
    (sdk/tab/read.md §3)。"""
    first = await _tab_with_form(client)
    await client.post("/api/tabs", json={"url": "about:blank"})   # 变成 active
    d = await (await client.get(f"/api/observe?tab={first}")).json()
    assert any("前台" in n for n in d["notes"]), d["notes"]


# ------------------------------------------------------------------- log

async def test_log_records_the_action_with_note_and_user(client):
    tab = await _tab_with_form(client)
    await client.post("/api/act", json={
        "tab": tab, "actions": [{"type": "click", "text": "提交订单"}],
        "note": "购物车已确认", "user": "claudecode"})

    d = await (await client.get("/api/log?kind=action")).json()
    e = d["entries"][-1]
    assert e["user"] == "claudecode" and e["note"] == "购物车已确认"
    assert e["target"] == {"text": "提交订单"} and e["hit"]["name"] == "提交订单"


async def test_tab_lifecycle_is_persisted_not_just_evented(client):
    """事件只在内存里活 1000 条、重启就没;**生死要落盘**(api/log.md §3)。"""
    tab = await _tab_with_form(client)
    await client.delete(f"/api/tabs/{tab}")

    d = await (await client.get("/api/log?kind=tab")).json()
    events = [(e["event"], e.get("tab")) for e in d["entries"]]
    assert ("opened", tab) in events and ("closed", tab) in events


async def test_log_filters(client):
    tab = await _tab_with_form(client)
    await client.post("/api/act", json={"tab": tab, "user": "a",
                                        "actions": [{"type": "click", "text": "提交订单"}]})
    await client.post("/api/act", json={"tab": tab, "user": "b",
                                        "actions": [{"type": "click", "text": "没有"}]})

    failed = await (await client.get("/api/log?only=failed")).json()
    assert all(e["ok"] is False for e in failed["entries"])
    mine = await (await client.get("/api/log?user=a")).json()
    assert {e["user"] for e in mine["entries"]} == {"a"}


async def test_bundle_downloads(client):
    await _tab_with_form(client)
    r = await client.get("/api/log/bundle")
    assert r.status == 200
    z = zipfile.ZipFile(__import__("io").BytesIO(await r.read()))
    assert "index.html" in z.namelist()


# ----------------------------------------------------------------- events

async def test_event_stream_pushes_tab_changes(client):
    ws = await client.ws_connect("/api/events?types=tab.*")
    await client.post("/api/tabs", json={"url": "about:blank"})

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
    d = await (await client.post("/api/act", json={
        "tab": tab, "actions": [{"type": "click", "text": "提交订单"}]})).json()
    log_from = d["log_from"]

    entries = (await (await client.get("/api/log")).json())["entries"]
    seqs = [e["seq"] for e in entries]
    assert log_from in seqs
    assert seqs == sorted(seqs), "seq 不是单调的"


# ------------------------------------------------------------------ 并发

async def test_only_one_action_at_a_time(client):
    """**不排队、不交错** —— 排队会让"谁先点"变得不可预测(api/README §1)。"""
    tab = await _tab_with_form(client)
    slow = {"tab": tab, "actions": [{"type": "wait_for", "ms": 800}]}
    fast = {"tab": tab, "actions": [{"type": "click", "text": "提交订单"}]}

    a = asyncio.create_task(client.post("/api/act", json=slow))
    await asyncio.sleep(0.15)
    b = await client.post("/api/act", json=fast)
    await a

    assert b.status == 409
    assert (await b.json())["error"]["code"] == "busy"
