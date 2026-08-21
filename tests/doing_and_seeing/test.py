"""动作执行 —— 对着 docs/v1/api/act.md §2 §3 校,跑在真 Chromium 上。"""

import asyncio

import pytest

from webmuxd.act import (
    MASK, Executor, PageDigest, describe_change,
)
from webmuxd.exceptions import BadRequest

FORM = (
    "data:text/html;charset=utf-8,"
    "<h1>结算</h1>"
    "<label for=phone>手机号</label><input id=phone>"
    "<label for=pw>密码</label><input id=pw type=password>"
    "<button id=go onclick=\"document.getElementById('out').textContent='订单已提交'\">"
    "提交订单</button>"
    "<button id=cancel>取消订单</button>"
    "<select id=city><option value=sh>上海</option><option value=bj>北京</option></select>"
    "<input id=agree type=checkbox>"
    "<div id=out></div>"
)


@pytest.fixture
async def ex(cdp, page):
    _tid, sid = page
    e = Executor(cdp, sid)
    await e.start()
    await cdp.send("Page.navigate", {"url": FORM}, session_id=sid)
    await asyncio.sleep(0.6)
    yield e
    e.stop()


async def _value(cdp, sid, css, prop="value"):
    r = await cdp.send("Runtime.evaluate",
                       {"expression": f"document.querySelector({css!r}).{prop}",
                        "returnByValue": True}, session_id=sid)
    return r["result"].get("value")


# ------------------------------------------------------- after.changed 是人话

def test_new_alert_becomes_a_sentence():
    """「出现『订单已提交』」比「DOM 变了 34 个节点」有用一百倍(§2.1)。"""
    before = PageDigest(lines=("结算",), alerts=())
    after = PageDigest(lines=("结算",), alerts=("订单已提交",))
    assert describe_change(before, after) == "出现『订单已提交』"


def test_new_text_block_becomes_a_sentence():
    before = PageDigest(lines=("结算", "共 2 件商品"))
    after = PageDigest(lines=("结算", "共 2 件商品", "订单已取消"))
    assert describe_change(before, after) == "出现『订单已取消』"


def test_disappearing_form_is_noticed():
    assert describe_change(PageDigest(lines=("a",), forms=1),
                           PageDigest(lines=("a",), forms=0)) == "表单消失了"


def test_nothing_changed_says_nothing():
    """**算不出来就闭嘴。**「页面变了」这种话等于没说。"""
    d = PageDigest(lines=("结算",), forms=1)
    assert describe_change(d, d) is None


def test_long_text_is_clipped():
    after = PageDigest(lines=("x" * 200,))
    out = describe_change(PageDigest(), after)
    assert out and len(out) < 50


# ------------------------------------------------------------------ 串行

@pytest.mark.asyncio
async def test_actions_run_in_order_and_stop_at_the_first_error(ex, cdp, page):
    """**遇错即停** —— 失败之后页面已经不是你以为的样子,继续跑只会错得更远。"""
    _tid, sid = page
    rs = await ex.run([
        {"type": "type", "label": "手机号", "text": "13800000000"},
        {"type": "click", "text": "根本不存在的按钮"},
        {"type": "type", "label": "密码", "text": "不该被执行"},
    ])
    assert len(rs) == 2, "失败之后还继续跑了"
    assert rs[0].ok and not rs[1].ok
    assert rs[1].error == "not_found"
    assert rs[1].candidates, "失败那条得带候选,模型才有得纠正"
    assert await _value(cdp, sid, "#pw") == "", "第三个动作被执行了"


@pytest.mark.asyncio
async def test_click_reports_what_it_actually_hit(ex):
    """`target` 是你说要点什么,`hit` 是实际命中了什么 —— 分开摆,
    一眼看出是认错了元素还是页面变了。"""
    (r,) = await ex.run([{"type": "click", "text": "提交订单"}])
    assert r.ok
    assert r.target == {"text": "提交订单"}
    assert r.hit and r.hit["name"] == "提交订单" and r.hit["role"] == "button"


@pytest.mark.asyncio
async def test_click_actually_clicks(ex, cdp, page):
    _tid, sid = page
    await ex.run([{"type": "click", "text": "提交订单"}])
    assert await _value(cdp, sid, "#out", "textContent") == "订单已提交"


@pytest.mark.asyncio
async def test_after_changed_shows_up_on_a_real_click(ex):
    (r,) = await ex.run([{"type": "click", "text": "提交订单"}])
    assert r.after.get("changed") == "出现『订单已提交』", r.after


# ------------------------------------------------------------------ 输入

@pytest.mark.asyncio
async def test_type_by_label(ex, cdp, page):
    _tid, sid = page
    (r,) = await ex.run([{"type": "type", "label": "手机号", "text": "13800000000"}])
    assert r.ok
    assert await _value(cdp, sid, "#phone") == "13800000000"


@pytest.mark.asyncio
async def test_type_with_clear_replaces(ex, cdp, page):
    _tid, sid = page
    await ex.run([{"type": "type", "label": "手机号", "text": "111"}])
    await ex.run([{"type": "type", "label": "手机号", "text": "222", "clear": True}])
    assert await _value(cdp, sid, "#phone") == "222"


@pytest.mark.asyncio
async def test_select_and_check(ex, cdp, page):
    _tid, sid = page
    rs = await ex.run([
        {"type": "select", "role": "combobox", "value": "bj"},
        {"type": "check", "role": "checkbox", "checked": True},
    ])
    assert all(r.ok for r in rs), [r.to_json() for r in rs]
    assert await _value(cdp, sid, "#city") == "bj"
    assert await _value(cdp, sid, "#agree", "checked") is True


@pytest.mark.asyncio
async def test_select_a_missing_option_fails_loudly(ex):
    (r,) = await ex.run([{"type": "select", "role": "combobox", "value": "没有这个"}])
    assert not r.ok and r.error == "not_found"


# ------------------------------------------------------------------ 导航

@pytest.mark.asyncio
async def test_back_with_no_history_is_an_error_not_a_noop(ex):
    """**不静默无操作** —— 脚本里"后退成功"和"没得后退"是两回事,
    你 UI 上按钮的禁用状态也要对得上(api/tabs.md §3)。"""
    await ex.run([{"type": "back"}])              # 退回 about:blank —— 这一步是合法的
    (r,) = await ex.run([{"type": "back"}])       # 再退就没得退了
    assert not r.ok and r.error == "bad_request"
    assert "没得后退" in (r.message or "")


@pytest.mark.asyncio
async def test_goto_refuses_privileged_pages(ex):
    (r,) = await ex.run([{"type": "goto", "url": "chrome://settings"}])
    assert not r.ok and r.error == "blocked_url"


# ------------------------------------------------------------- 等待与逃生舱

@pytest.mark.asyncio
async def test_wait_for_text_that_arrives(ex):
    rs = await ex.run([
        {"type": "js", "expression":
            "setTimeout(()=>{document.getElementById('out').textContent='慢慢来'},200)"},
        {"type": "wait_for", "text": "慢慢来", "timeout_ms": 3000},
    ])
    assert all(r.ok for r in rs), [r.to_json() for r in rs]


@pytest.mark.asyncio
async def test_wait_for_that_never_arrives_times_out(ex):
    (r,) = await ex.run([{"type": "wait_for", "text": "永远不会有", "timeout_ms": 400}])
    assert not r.ok and r.error == "timeout"


@pytest.mark.asyncio
async def test_js_and_point_are_marked_opaque(ex):
    """`js` 和坐标点击在日志里标黄 —— 回看时它们看不出到底干了什么(§4)。"""
    (r,) = await ex.run([{"type": "js", "expression": "1+1"}])
    assert r.ok and r.value == 2 and r.opaque

    (r2,) = await ex.run([{"type": "click", "point": [5, 5]}])
    assert r2.opaque, "坐标点击没标黄"


@pytest.mark.asyncio
async def test_css_escape_hatch_works_and_reports_itself(ex, cdp, page):
    _tid, sid = page
    (r,) = await ex.run([{"type": "click", "css": "#go"}])
    assert r.ok and r.hit == {"css": "#go"}
    assert await _value(cdp, sid, "#out", "textContent") == "订单已提交"


@pytest.mark.asyncio
async def test_unknown_action_is_a_usage_error(ex):
    (r,) = await ex.run([{"type": "没有这个动作"}])
    assert not r.ok and r.error == "bad_request"


# -------------------------------------------------------------------- 凭证

class _Vault:
    async def resolve(self, ref):
        assert ref == "secret://vault/shop/pwd"
        return "hunter2"


@pytest.mark.asyncio
async def test_secret_is_used_but_never_echoed(cdp, page):
    """明文只在 sessiond 内部出现一次 —— **日志里一律打码**(§3.1)。"""
    _tid, sid = page
    e = Executor(cdp, sid, secrets=_Vault())
    await e.start()
    await cdp.send("Page.navigate", {"url": FORM}, session_id=sid)
    await asyncio.sleep(0.6)

    (r,) = await e.run([{"type": "type", "label": "密码",
                         "text_ref": "secret://vault/shop/pwd"}])
    assert r.ok
    assert await _value(cdp, sid, "#pw") == "hunter2", "密码没真的输进去"

    dumped = str(r.to_json()) + str(r.target)
    assert "hunter2" not in dumped, "明文漏进了结果/日志"
    assert r.target and r.target.get("text") == MASK
    e.stop()


@pytest.mark.asyncio
async def test_secret_without_a_backend_is_a_usage_error(ex):
    (r,) = await ex.run([{"type": "type", "label": "密码",
                          "text_ref": "secret://x"}])
    assert not r.ok and r.error == "bad_request"


# -------------------------------------------------------------------- settle

@pytest.mark.asyncio
async def test_settle_none_returns_immediately(ex):
    import time
    began = time.monotonic()
    await ex.run([{"type": "js", "expression": "1"}], settle={"strategy": "none"})
    assert time.monotonic() - began < 1.0


@pytest.mark.asyncio
async def test_unknown_settle_strategy_is_rejected(ex):
    with pytest.raises(BadRequest):
        await ex._settler.settle({"strategy": "随便等等"})
