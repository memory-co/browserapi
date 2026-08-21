"""观测 —— 对着 docs/v1/api/act.md §1 校,跑在真 Chromium 上。"""

import asyncio

import pytest

from webmuxd.observe import DIGEST_CHARS, observe

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
    assert obs.page.title == "结算"
    assert obs.page.viewport.w > 0
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


async def test_observation_reads_the_shape_the_api_actually_sends():
    """**回归测试。** 分辨率这个功能第一次是坏的发出去的(0.3.0):

    `_page_info` 拿到扁平的 `w/h/screenW/screenH` 之后会**重排成嵌套结构**,
    而我两头都按扁平写 —— 服务端把 `screen*` 丢了,客户端又按扁平去读。
    单元测试当时是绿的,因为它测的是我自己写的形状,不是 API 真正发出来的那个。

    所以这条**照抄真实响应的形状**。
    """
    from webmuxd import Observation

    real = {                       # 从 GET /api/observe 实际抓的
        "observation_id": "obs_x", "tab": "t_1", "elements": [],
        "page": {"url": "https://example.com/", "title": "Example Domain",
                 "loading": False,
                 "scroll": {"y": 0, "max_y": 0},
                 "viewport": {"w": 1015, "h": 676},
                 "screen": {"w": 1024, "h": 768}},
    }
    o = Observation.of(None, real)
    assert o.viewport == (1015, 676)
    assert o.screen == (1024, 768)
    # 两者不同才显示 —— 相同的时候那一行是噪音
    assert o.as_prompt().splitlines()[0] == "视口 1015x676(桌面 1024x768)"


async def test_page_info_keeps_the_screen_size_through_the_reshape():
    """服务端那半:重排的时候**别把 screen 丢了**。"""
    import json as _json

    from webmuxd import observe as mod

    class FakeCDP:
        async def send(self, method, params=None, session_id=None):
            return {"result": {"value": _json.dumps({
                "url": "u", "title": "t", "loading": False,
                "scrollY": 0, "maxY": 0, "w": 1015, "h": 676,
                "screenW": 1024, "screenH": 768})}}

    page = await mod._page_info(FakeCDP(), "sid")
    assert page.viewport == (1015, 676)
    assert page.screen == (1024, 768)
