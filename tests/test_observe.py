"""观测 —— 对着 docs/v1/api/act.md §1 校,跑在真 Chromium 上。"""

import asyncio

import pytest

from webmuxd.core.observe import DIGEST_CHARS, observe

pytestmark = pytest.mark.asyncio

PAGE = (
    "data:text/html;charset=utf-8,"
    "<title>结算</title>"
    "<button>提交订单</button><button>取消订单</button>"
    "<label for=c>优惠码</label><input id=c>"
    "<p>" + "正文内容。" * 50 + "</p>"
)


async def _goto(cdp, sid, url=PAGE):
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {"url": url}, session_id=sid)
    await asyncio.sleep(0.6)


async def test_one_call_gets_everything(cdp, page):
    """**一次调用拿到能直接喂给模型的全部东西**,调用方零解析(§1)。"""
    _tid, sid = page
    await _goto(cdp, sid)
    obs = await observe(cdp, sid, tab="t_1")

    assert obs.id.startswith("obs_")
    assert obs.page["title"] == "结算"
    assert obs.page["viewport"]["w"] > 0
    assert [e.name for e in obs.elements][:2] == ["提交订单", "取消订单"]
    assert obs.screenshot and obs.plain_screenshot
    assert "正文内容" in obs.text
    assert obs.filter_version >= 1, "筛选规则的版本要跟着观测走"


async def test_annotated_and_plain_are_different_images(cdp, page):
    """标注版画了编号框,干净版没有 —— 两张图不该是同一份字节。"""
    _tid, sid = page
    await _goto(cdp, sid)
    obs = await observe(cdp, sid)
    assert obs.screenshot != obs.plain_screenshot, "标注层没画上去"
    assert obs.screenshot[:4] == b"RIFF", "不是 webp"


async def test_the_marking_layer_never_survives_the_shot(cdp, page):
    """标注层是临时的 —— 留在页面上会污染后面所有观测和人看到的画面。"""
    _tid, sid = page
    await _goto(cdp, sid)
    await observe(cdp, sid)

    r = await cdp.send("Runtime.evaluate",
                       {"expression": "!!document.getElementById('__webmuxd_marks')",
                        "returnByValue": True}, session_id=sid)
    assert r["result"]["value"] is False, "标注层留在页面上了"


async def test_marking_does_not_leak_into_the_next_snapshot(cdp, page):
    """标注层自己不能被下一次快照当成页面内容。"""
    _tid, sid = page
    await _goto(cdp, sid)
    first = await observe(cdp, sid)
    second = await observe(cdp, sid)
    assert [e.name for e in first.elements] == [e.name for e in second.elements]


async def test_annotate_false_skips_the_layer(cdp, page):
    _tid, sid = page
    await _goto(cdp, sid)
    obs = await observe(cdp, sid, annotate=False)
    assert obs.screenshot == obs.plain_screenshot


async def test_digest_is_capped_and_says_so(cdp, page):
    """截断了就要说 —— 不说的话模型把"没看见"当成"不存在"(§1.2)。"""
    _tid, sid = page
    await _goto(cdp, sid)
    obs = await observe(cdp, sid, text="digest")
    if len(obs.text) >= DIGEST_CHARS:
        assert any("正文" in n for n in obs.notes)

    full = await observe(cdp, sid, text="full")
    assert len(full.text) >= len(obs.text)

    none = await observe(cdp, sid, text="none")
    assert none.text == ""


async def test_cross_origin_iframe_is_reported_as_a_blind_spot(cdp, page):
    """跨域 iframe 读不到 —— **必须说**,否则模型以为那块地方什么都没有。"""
    _tid, sid = page
    await _goto(cdp, sid, "data:text/html;charset=utf-8,"
                          "<h1>宿主</h1><iframe src='https://example.com/'></iframe>")
    await asyncio.sleep(0.8)
    obs = await observe(cdp, sid)
    assert any("iframe" in n for n in obs.notes), f"跨域盲区没报:{obs.notes}"


async def test_truncation_note_travels_with_the_observation(cdp, page):
    _tid, sid = page
    await _goto(cdp, sid)
    obs = await observe(cdp, sid, max_elements=1)
    assert len(obs.elements) == 1
    assert any("截断" in n for n in obs.notes)


async def test_as_prompt_is_what_goes_into_the_model(cdp, page):
    _tid, sid = page
    await _goto(cdp, sid)
    text = (await observe(cdp, sid)).as_prompt()
    assert '[1] button   "提交订单"' in text
    assert '"优惠码"' in text


async def test_to_json_shape_matches_the_spec(cdp, page):
    _tid, sid = page
    await _goto(cdp, sid)
    obs = await observe(cdp, sid, tab="t_3")
    d = obs.to_json(shot_url="/api/observe/x/screenshot")

    for key in ("observation_id", "tab", "at", "page", "elements", "tabs", "notes"):
        assert key in d, f"响应里缺 {key}"
    assert d["screenshot"]["format"] == "webp"
    assert d["screenshot"]["plain_url"].endswith("annotate=false")
    assert d["elements"][0]["role"] == "button"
