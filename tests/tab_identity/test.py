"""tab 表 —— 对着 docs/v1/api/tabs.md 和 works/06 校,跑在真 Chromium 上。"""

import asyncio
import time

import pytest

from webmuxd.tabs import TabTable, is_blocked
from webmuxd.exceptions import BadRequest, TabGone




@pytest.fixture
async def table(cdp):
    events: list[tuple[str, dict]] = []
    t = TabTable(cdp, emit=lambda ty, p: events.append((ty, p)))
    await t.start()
    await asyncio.sleep(0.3)          # 让已存在的 target 都进来
    t.events = events                 # type: ignore[attr-defined]
    yield t
    for tab_id in list(t._by_id):
        try:
            await t.close(tab_id)
        except Exception:
            pass


def _types(t) -> list[str]:
    return [ty for ty, _ in t.events]


async def _until(pred, timeout: float = 3.0):
    """等一个条件成立,**别用固定的 sleep**。

    挤 tab 要等 `Target.closeTarget` 走一个来回,机器忙的时候 0.1 秒不够 ——
    那样测出来的是"这台机器今天快不快",不是"逻辑对不对"。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.01)
    return pred()



async def _reset_to_one(t):
    """把表清到只剩一个 tab,返回它。

    注意不能"全关掉" —— 关掉最后一个会触发「永远至少留一个」,
    自动补一个 about:blank 出来。这个残留 tab 会在后面被当成 LRU 受害者,
    我第一版测试就是栽在这儿(是测试错了,不是实现错了)。
    """
    ids = list(t._by_id)
    for tab_id in ids[1:]:
        await t.close(tab_id)
    if not t._by_id:
        await t.open("about:blank")
    keeper = next(iter(t._by_id))
    await t.activate(keeper)
    return keeper


# --------------------------------------------------------------------- id

@pytest.mark.asyncio
async def test_ids_are_ours_and_never_reused(table):
    """t_N 关掉之后不复用 —— 历史日志里的 t_7 得永远指同一个东西
    (works/06 §1)。"""
    a = await table.open("about:blank")
    b = await table.open("about:blank")
    assert a.id != b.id
    assert a.target_id != a.id, "对外的 id 不能就是 CDP 的 targetId"

    await table.close(a.id)
    c = await table.open("about:blank")
    assert c.id != a.id, "关掉的号被复用了"

    with pytest.raises(TabGone):
        table.get(a.id)


@pytest.mark.asyncio
async def test_gone_tab_says_whether_it_was_closed_or_evicted(table):
    a = await table.open("about:blank")
    await table.close(a.id)
    with pytest.raises(TabGone) as ei:
        table.get(a.id)
    assert ei.value.reason == "closed"


# ----------------------------------------------------------------- reason

@pytest.mark.asyncio
async def test_page_opened_tab_is_reason_page(table, cdp):
    """有 openerId = 页面开的。实测四种开法(含 noopener)全都带它,
    所以这个判据不需要 url 兜底(works/06 §2)。"""
    opener = await table.open("data:text/html,<h1>o</h1>")
    a = await cdp.send("Target.attachToTarget",
                       {"targetId": opener.target_id, "flatten": True})
    before = set(table._by_id)
    await cdp.send("Runtime.evaluate",
                   {"expression": "window.open('https://example.com/x','_blank','noopener')",
                    "userGesture": True}, session_id=a["sessionId"])
    for _ in range(200):
        if set(table._by_id) - before:
            break
        await asyncio.sleep(0.01)

    new_id = (set(table._by_id) - before).pop()
    tab = table.get(new_id)
    assert tab.reason == "page", f"noopener 开的被判成了 {tab.reason}"
    assert tab.opener == opener.id, "血缘关系丢了"


@pytest.mark.asyncio
async def test_api_opened_tab_is_reason_api(table):
    tab = await table.open("about:blank")
    assert tab.reason == "api"


# ----------------------------------------------------------------- active

@pytest.mark.asyncio
async def test_active_is_ours_not_observed(table):
    """改自己的字段,再把 Chromium 拽过来对齐(api/tabs.md §5)。"""
    a = await table.open("about:blank")
    b = await table.open("about:blank")
    assert table.active == b.id, "新建的没切过去"

    await table.activate(a.id)
    assert table.active == a.id, "activate 之后记录立刻就该是新的,不该慢半拍"
    assert ("tab.activated", {"id": a.id, "previous": b.id}) in table.events


@pytest.mark.asyncio
async def test_closing_active_moves_focus_not_leaves_a_hole(table):
    a = await table.open("about:blank")
    b = await table.open("about:blank")
    await table.close(b.id)
    assert table.active == a.id, "关掉当前 tab 之后没人接手"


# ------------------------------------------------------------ 至少留一个

@pytest.mark.asyncio
async def test_closing_the_last_tab_creates_a_blank_one(table):
    """Chromium 关掉最后一个 tab 会连窗口一起关,所以先补一个
    (api/tabs.md §3)。"""
    for tab_id in list(table._by_id):
        if tab_id != next(iter(table._by_id)):
            await table.close(tab_id)
    assert len(table) == 1
    only = next(iter(table._by_id))

    r = await table.close(only)
    assert r["created"] is not None, "关掉最后一个之后没补上"
    assert len(table) == 1
    assert table.active == r["created"]["id"]


# --------------------------------------------------------------- 上限 LRU

@pytest.mark.asyncio
async def test_eviction_takes_the_least_recently_used(cdp):
    """LRU 而不是 FIFO —— 先开的不等于最没用的(works/03 §5.1)。"""
    events: list[tuple[str, dict]] = []
    t = TabTable(cdp, emit=lambda ty, p: events.append((ty, p)), tab_max=4)
    await t.start()
    await asyncio.sleep(0.3)
    keeper = await _reset_to_one(t)

    a = await t.open("data:text/html,a")
    b = await t.open("data:text/html,b")
    c = await t.open("data:text/html,c")       # 现在 4 个:keeper a b c
    t.touch(a.id)
    await asyncio.sleep(0.02)
    t.touch(b.id)
    await asyncio.sleep(0.02)
    t.touch(c.id)                              # keeper 最旧
    events.clear()

    d = await t.open("data:text/html,d")       # 第五个 → 挤掉最旧的 keeper
    await _until(lambda: any(ty == "tab.closed" for ty, _ in events))

    evicted = [p for ty, p in events if ty == "tab.closed" and p["reason"] == "evicted"]
    assert len(evicted) == 1, f"挤多了或没挤:{evicted}"
    assert evicted[0]["id"] == keeper, "挤掉的不是最不活跃的那个"
    assert evicted[0]["final_url"] is not None, "被挤掉的得留下 final_url,不然没法恢复"
    assert all(x.id in t for x in (a, b, c, d))


@pytest.mark.asyncio
async def test_eviction_never_takes_the_active_or_a_busy_tab(cdp):
    """当前激活的永远不挤,正在跑动作的也不挤 —— 哪怕它们是最旧的
    (api/tabs.md §3)。所以受害者只能是那个既不激活也不忙的。"""
    events: list[tuple[str, dict]] = []
    t = TabTable(cdp, emit=lambda ty, p: events.append((ty, p)), tab_max=3)
    await t.start()
    await asyncio.sleep(0.3)
    keeper = await _reset_to_one(t)

    old_busy = await t.open("data:text/html,busy")
    middle = await t.open("data:text/html,middle")
    t.mark_busy(old_busy.id)                   # 最旧的那个在忙
    events.clear()

    fresh = await t.open("data:text/html,fresh")   # 超了 → 只能挤 keeper 或 middle
    await _until(lambda: any(ty == "tab.closed" for ty, _ in events))

    assert old_busy.id in t, "挤掉了正在跑动作的 tab —— 那个动作会变成一半"
    assert fresh.id in t and t.active == fresh.id, "挤掉了刚建的或当前激活的"
    evicted = [p["id"] for ty, p in events if ty == "tab.closed" and p["reason"] == "evicted"]
    assert evicted == [keeper], f"受害者应该是最旧的非忙非激活那个,实际 {evicted}"


@pytest.mark.asyncio
async def test_挤掉时事件先到也不能丢掉_evicted(cdp):
    """**这条是一个真的竞态的回归测试。**

    `await Target.closeTarget` 中间会让出控制权,而 Chromium 的
    `targetDestroyed` 事件**经常比这个响应先到**。先到的话表已经被清干净了,
    后面那句 `self._order.remove(victim)` 会 `ValueError`,
    于是 `reason="evicted"` 那条事件**再也发不出去** —— 表现有两种:
    被挤掉的 tab 报成 `closed`,或者一个事件都没有。

    这里把"事件先到"变成确定的:在 `closeTarget` 真正发出去之前,
    先手工喂一条 `targetDestroyed` 进去。
    """
    events: list[tuple[str, dict]] = []
    t = TabTable(cdp, emit=lambda ty, p: events.append((ty, p)), tab_max=1)
    await t.start()
    await asyncio.sleep(0.3)
    keeper = await _reset_to_one(t)
    keeper_target = t.get(keeper).target_id

    real_send = t._cdp.send

    async def send_but_event_first(method, params=None, **kw):
        if method == "Target.closeTarget":
            # 事件抢在响应前面 —— 这就是线上偶发的那个顺序
            t._on_destroyed({"targetId": params["targetId"]}, None)
        return await real_send(method, params, **kw)

    t._cdp.send = send_but_event_first
    events.clear()
    try:
        await t.open("data:text/html,b")          # 超了 → keeper 被挤
        await _until(lambda: keeper not in t)
    finally:
        t._cdp.send = real_send

    closed = [p for ty, p in events if ty == "tab.closed" and p["id"] == keeper]
    assert len(closed) == 1, f"事件丢了或者发了两遍:{closed}"
    assert closed[0]["reason"] == "evicted", "事件先到时被报成了 closed"
    with pytest.raises(TabGone) as ei:
        t.get(keeper)
    assert ei.value.reason == "evicted"
    assert keeper_target not in t._evicting, "标记没清干净"


@pytest.mark.asyncio
async def test_evicted_tab_reports_evicted_not_closed(cdp):
    """被挤掉不是你关的 —— 异常里必须分得清(api/tabs.md §3)。"""
    t = TabTable(cdp, tab_max=1)
    await t.start()
    await asyncio.sleep(0.3)
    keeper = await _reset_to_one(t)

    b = await t.open("data:text/html,b")   # b 变 active → keeper 被挤
    await _until(lambda: keeper not in t)

    with pytest.raises(TabGone) as ei:
        t.get(keeper)
    assert ei.value.reason == "evicted"
    assert ei.value.final_url is not None, "得能拿 final_url 重开"
    assert b.id in t


# --------------------------------------------------------------- 特权页面

@pytest.mark.parametrize("url", [
    "chrome://settings", "devtools://x", "view-source:https://a.com",
    "chrome-extension://abc", "CHROME://Settings",
])
def test_privileged_urls_are_blocked(url):
    assert is_blocked(url)


@pytest.mark.parametrize("url", ["about:blank", "https://a.com", "data:text/html,x"])
def test_ordinary_urls_are_not(url):
    assert not is_blocked(url)


@pytest.mark.asyncio
async def test_open_refuses_privileged(table):
    with pytest.raises(BadRequest) as ei:
        await table.open("chrome://settings")
    assert ei.value.code == "blocked_url"


# ----------------------------------------------------------------- 事件

@pytest.mark.asyncio
async def test_updated_carries_only_what_changed(table):
    tab = await table.open("about:blank")
    table.events.clear()
    table.update(tab.id, title="新标题", url=tab.url)   # url 没变
    changed = [p for ty, p in table.events if ty == "tab.updated"]
    assert changed and changed[0]["changed"] == {"title": "新标题"}, \
        "整条替换会让外面的 tab 条闪、丢滚动位置"


@pytest.mark.asyncio
async def test_no_event_when_nothing_changed(table):
    tab = await table.open("about:blank")
    table.events.clear()
    table.update(tab.id, title=tab.title)
    assert "tab.updated" not in _types(table)


@pytest.mark.asyncio
async def test_workers_do_not_land_in_the_tab_table(table, cdp):
    """targetCreated 推的是所有 target;不按 type 过滤的话
    service worker 会跑进 tab 条(works/06 §2)。"""
    before = len(table)
    table._on_created({"targetInfo": {"targetId": "x1", "type": "service_worker"}}, None)
    table._on_created({"targetInfo": {"targetId": "x2", "type": "iframe"}}, None)
    await asyncio.sleep(0.05)
    assert len(table) == before
