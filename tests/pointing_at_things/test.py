"""定位引擎 —— 对着 docs/v1/api/act.md §1.1 和 §4 校。

文档说元素筛选是「整个系统最容易出质量问题的地方」,所以这里测得细一点:
匹配的**分档**语义、多义时**绝不挑一个**、以及失败时必须给候选。
"""

import asyncio

import pytest

from webmuxd.locate import (
    FILTER_VERSION, Element, Snapshot, match_by_text, resolve, snapshot,
)
from webmuxd.exceptions import BadRequest, NotClickable, NotFound

# 注意 href 里不能出现裸 `#` —— 那是 URL 的片段分隔符,
# 会把后面整段 HTML 截掉,页面上就只剩第一个按钮了。踩过。
PAGE = (
    "data:text/html;charset=utf-8,"
    "<button>提交订单</button>"
    "<button>提交并支付</button>"
    "<a href='https://example.com/fb'>提交反馈</a>"
    "<label for=phone>手机号</label><input id=phone>"
    "<label for=pw>密码</label><input id=pw type=password>"
    "<button disabled>已停用</button>"
    "<button style='position:absolute;top:5000px'>很下面的按钮</button>"
)


def _el(n, role, name, **kw):
    return Element(id=n, role=role, name=name, **kw)


# --------------------------------------------------------------- 匹配分档

def test_exact_beats_substring():
    """精确匹配优先 —— 而且**只要有精确命中就停在那一档**,
    否则"精确 1 个"会被子串的 5 个稀释掉。"""
    els = [_el(1, "button", "提交"), _el(2, "button", "提交订单"),
           _el(3, "button", "提交并支付")]
    assert [e.id for e in match_by_text(els, "提交")] == [1]


def test_falls_back_to_substring():
    els = [_el(1, "button", "提交订单"), _el(2, "button", "提交并支付"),
           _el(3, "link", "返回")]
    assert [e.id for e in match_by_text(els, "提交")] == [1, 2]


def test_falls_back_to_case_insensitive_last():
    els = [_el(1, "button", "Submit Order"), _el(2, "button", "Cancel")]
    assert [e.id for e in match_by_text(els, "submit")] == [1]
    # 但有大小写精确的时候就不该走到这一档
    els2 = [_el(1, "button", "submit"), _el(2, "button", "Submit Order")]
    assert [e.id for e in match_by_text(els2, "submit")] == [1]


def test_whitespace_is_normalised():
    els = [_el(1, "button", "  提交   订单 ")]
    assert match_by_text(els, "提交 订单")


# ------------------------------------------------------- 多义:绝不挑一个

def test_ambiguous_raises_with_all_candidates():
    """**绝不随便挑一个** —— 点错浏览器比敲错终端贵(api/act.md §4)。"""
    snap = Snapshot([_el(1, "button", "提交订单"), _el(2, "button", "提交并支付")])
    with pytest.raises(NotFound) as ei:
        resolve({"text": "提交"}, snap)
    assert len(ei.value.candidates) == 2, "多义时候选得给全,不是给 3 个里的前几个"
    assert "nth" in str(ei.value), "得告诉调用方怎么消歧"


def test_nth_disambiguates():
    snap = Snapshot([_el(1, "button", "提交订单"), _el(2, "button", "提交并支付")])
    assert resolve({"text": "提交", "nth": 1}, snap).id == 2


def test_nth_out_of_range_says_how_many_there_were():
    snap = Snapshot([_el(1, "button", "提交订单")])
    with pytest.raises(NotFound) as ei:
        resolve({"text": "提交", "nth": 5}, snap)
    assert "只有 1 个" in str(ei.value)


# ------------------------------------------------------------- 失败要给候选

def test_miss_gives_nearest_candidates():
    """找不到时把最像的塞回来 —— 模型据此自我纠正,人据此看出
    是页面变了还是识别错了(api/act.md §2)。"""
    snap = Snapshot([_el(1, "button", "提交订单"), _el(2, "link", "订单"),
                     _el(3, "button", "完全无关")])
    with pytest.raises(NotFound) as ei:
        # 「提交付款」和三个都不构成子串关系,是真的 miss ——
        # 但它和「提交订单」共享字符,候选排序应该把那个排前面
        resolve({"text": "提交付款"}, snap)
    names = [c["name"] for c in ei.value.candidates]
    assert names[0] == "提交订单", f"候选没按相似度排:{names}"


def test_total_miss_still_shows_what_is_on_the_page():
    """查询和页面上任何东西都不沾边时,**也要给候选**。

    空候选等于什么都没告诉调用方;给几个真实存在的名字,
    至少能看出"页面不是我以为的那个"。"""
    snap = Snapshot([_el(1, "button", "提交订单"), _el(2, "link", "帮助")])
    with pytest.raises(NotFound) as ei:
        resolve({"text": "结算"}, snap)
    assert len(ei.value.candidates) == 2


def test_candidates_are_never_none():
    """调用方直接 for 它 —— 不该先判 None(sdk/README §5)。"""
    with pytest.raises(NotFound) as ei:
        resolve({"text": "任何东西"}, Snapshot([]))
    assert ei.value.candidates == []


# ------------------------------------------------------------------ 其它形

def test_role_and_name_together():
    snap = Snapshot([_el(1, "button", "登录"), _el(2, "link", "登录")])
    assert resolve({"role": "button", "name": "登录"}, snap).id == 1


def test_label_only_matches_things_you_can_type_into():
    snap = Snapshot([
        _el(1, "textbox", "手机号", affords=["type", "click"]),
        _el(2, "button", "手机号", affords=["click"]),
    ])
    assert resolve({"label": "手机号"}, snap).id == 1


def test_disabled_element_is_not_clickable_not_not_found():
    """找到了但禁用 —— 这两种失败调用方的应对完全不同。"""
    snap = Snapshot([_el(1, "button", "已停用", enabled=False)])
    with pytest.raises(NotClickable):
        resolve({"text": "已停用"}, snap)


def test_element_number_needs_the_right_observation():
    """页面变了就该抛,而不是点到编号相同的另一个东西(api/act.md §4)。"""
    snap = Snapshot([_el(1, "button", "提交")])
    assert resolve({"element": 1, "observation": "obs_a"}, snap,
                   observation_id="obs_a").id == 1
    with pytest.raises(NotFound) as ei:
        resolve({"element": 1, "observation": "obs_OLD"}, snap, observation_id="obs_a")
    assert "另一次观测" in str(ei.value)


def test_nonsense_locator_is_a_usage_error():
    with pytest.raises(BadRequest):
        resolve({"wat": 1}, Snapshot([]))


# ---------------------------------------------------- 真页面上的快照(§1.1)

@pytest.mark.asyncio
async def test_snapshot_on_a_real_page(cdp, page):
    _tid, sid = page
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {"url": PAGE}, session_id=sid)
    await asyncio.sleep(0.6)

    snap = await snapshot(cdp, sid)
    names = [e.name for e in snap.elements]

    assert "提交订单" in names and "提交并支付" in names
    assert snap.filter_version == FILTER_VERSION, "筛选规则的版本要跟着快照走"

    # 规则 3:名字和 value 都空的纯装饰元素丢掉
    assert all(e.name or e.value is not None for e in snap.elements)
    # 规则 2:量不到 bbox 的不进来
    assert all(e.bbox[2] > 0 and e.bbox[3] > 0 for e in snap.elements)


@pytest.mark.asyncio
async def test_snapshot_marks_offscreen_and_disabled(cdp, page):
    """规则 4:默认给整页,但标出来哪些要滚下去才点得到。"""
    _tid, sid = page
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {"url": PAGE}, session_id=sid)
    await asyncio.sleep(0.6)

    snap = await snapshot(cdp, sid)
    by_name = {e.name: e for e in snap.elements}

    assert by_name["很下面的按钮"].in_viewport is False, "视口外的没标出来"
    assert by_name["已停用"].enabled is False
    # 视口内的排前面
    assert snap.elements[0].in_viewport is True


@pytest.mark.asyncio
async def test_viewport_only_drops_the_offscreen_ones(cdp, page):
    _tid, sid = page
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {"url": PAGE}, session_id=sid)
    await asyncio.sleep(0.6)

    snap = await snapshot(cdp, sid, viewport_only=True)
    assert "很下面的按钮" not in [e.name for e in snap.elements]


@pytest.mark.asyncio
async def test_truncation_is_announced(cdp, page):
    """截断了**必须**在 notes 里说清楚截掉了多少 —— 不说的话
    模型会把"没看见"当成"不存在"(api/act.md §1.2)。"""
    _tid, sid = page
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {"url": PAGE}, session_id=sid)
    await asyncio.sleep(0.6)

    snap = await snapshot(cdp, sid, max_elements=2)
    assert len(snap.elements) == 2
    assert any("截断" in n for n in snap.notes), f"截断了但没说:{snap.notes}"


@pytest.mark.asyncio
async def test_resolve_against_a_real_snapshot(cdp, page):
    _tid, sid = page
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {"url": PAGE}, session_id=sid)
    await asyncio.sleep(0.6)

    snap = await snapshot(cdp, sid)
    assert resolve({"text": "提交订单"}, snap).name == "提交订单"

    with pytest.raises(NotFound) as ei:
        resolve({"text": "提交"}, snap)          # 三个都含"提交"
    assert len(ei.value.candidates) >= 3, "真页面上的多义候选给少了"


@pytest.mark.asyncio
async def test_as_prompt_is_the_compact_form(cdp, page):
    """给模型的紧凑表示(api/act.md §1.3)。"""
    _tid, sid = page
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {"url": PAGE}, session_id=sid)
    await asyncio.sleep(0.6)

    text = (await snapshot(cdp, sid)).as_prompt()
    assert '[1]' in text and '"提交订单"' in text
    assert "禁用" in text and "需下滑" in text
