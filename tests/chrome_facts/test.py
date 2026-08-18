"""把 works/06 §7 和 works/07 §5 的「待实测」变成真的测量。

这些不是普通单测 —— 每一条都对应一句设计文档里写着"还没验"的话。
测不过就是设计要改,不是测试要改。
"""

import asyncio

import pytest

from webmuxd.core.cdp import CDP

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# works/06 §7 之一:重新 setDiscoverTargets 会不会把已存在的 target 各补一条
#   —— 这是"不会漏"这个结论的地基。不成立的话,重连后必须用 getTargets 重建全表。
# ---------------------------------------------------------------------------

async def test_discover_targets_re_announces_existing(chromium_endpoint):
    a = await CDP.connect(chromium_endpoint)
    try:
        before = {t["targetId"] for t in (await a.send("Target.getTargets"))["targetInfos"]
                  if t["type"] == "page"}
        made = [(await a.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
                for _ in range(3)]

        # 新连一条,只开 discover,数它主动推给我们几条
        b = await CDP.connect(chromium_endpoint)
        seen: list[str] = []
        b.on("Target.targetCreated",
             lambda p, _s: seen.append(p["targetInfo"]["targetId"])
             if p["targetInfo"]["type"] == "page" else None)
        await b.send("Target.setDiscoverTargets", {"discover": True})
        await asyncio.sleep(0.5)
        await b.close()

        assert set(made) <= set(seen), (
            "setDiscoverTargets 没有把已存在的 target 补齐 —— "
            "works/06 §2『会不会漏』的地基不成立,重连后必须走 getTargets 重建全表"
        )
        assert before <= set(seen)
    finally:
        for tid in made:
            await a.send("Target.closeTarget", {"targetId": tid})
        await a.close()


# ---------------------------------------------------------------------------
# works/06 §7 之二:openerId 在三种开 tab 的方式下分别给不给
#   —— reason 的判据全靠它。noopener 那条尤其关键:如果它没有 openerId,
#      就会和人按 Ctrl+T 长得一样,必须靠 url 兜底(works/06 §2)。
# ---------------------------------------------------------------------------

async def _open_via(cdp, sid, script) -> dict:
    """在页面里执行 script 开一个新 target,返回它的 targetInfo。

    按「出现了没见过的 target id」判,不按 url —— 容器里没网,
    新 target 一开始的 url 可能是空的或 about:blank,按 url 判会漏。
    """
    known = {t["targetId"] for t in (await cdp.send("Target.getTargets"))["targetInfos"]}
    fut: asyncio.Future = asyncio.get_running_loop().create_future()

    def on_created(p, _s):
        ti = p["targetInfo"]
        if ti["type"] == "page" and ti["targetId"] not in known and not fut.done():
            fut.set_result(ti)

    off = cdp.on("Target.targetCreated", on_created)
    try:
        await cdp.send("Runtime.evaluate",
                       {"expression": script, "userGesture": True}, session_id=sid)
        return await asyncio.wait_for(fut, 5)
    finally:
        off()


async def test_opener_id_presence_per_open_style(cdp, page):
    """实测结论(2026-08-08,Chromium 124):**四种方式全都带 openerId**。

    这推翻了 works/06 早先的假设。`noopener` 切断的是页面侧的 `window.opener`
    (JS 层),而 `targetInfo.openerId` 是**浏览器层**的血缘记录 —— 两回事。
    所以 `reason` 的判据比原先想的简单:有 openerId = 页面开的,没有 = 人开的。
    """
    tid, sid = page
    await cdp.send("Target.setDiscoverTargets", {"discover": True})
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {
        "url": "data:text/html,"
               "<a id=a href='https://example.com/1' target=_blank>a</a>"
               "<a id=b href='https://example.com/2' target=_blank rel=noopener>b</a>"
    }, session_id=sid)
    await asyncio.sleep(0.4)

    cases = {
        "window_open":      "window.open('https://example.com/a','_blank')",
        "window_open+noopener": "window.open('https://example.com/b','_blank','noopener')",
        "a target=_blank":  "document.getElementById('a').click()",
        "a rel=noopener":   "document.getElementById('b').click()",
    }
    results = {}
    for label, script in cases.items():
        ti = await _open_via(cdp, sid, script)
        results[label] = ti.get("openerId")
        await cdp.send("Target.closeTarget", {"targetId": ti["targetId"]})

    print("\n[实测] openerId 是否存在:")
    for k, v in results.items():
        print(f"    {k:24} {bool(v)}")

    assert all(results.values()), (
        f"有开 tab 的方式不带 openerId: "
        f"{[k for k, v in results.items() if not v]} —— reason 判不出来源"
    )


# ---------------------------------------------------------------------------
# works/06 §7 之三:flatten 拿到的 session 上,Page / Security 事件推不推得全
#   —— tab 条要画的 url/title/loading/锁 全靠它们。
# ---------------------------------------------------------------------------

async def test_page_and_security_events_arrive_on_flat_session(cdp, page):
    tid, sid = page
    got: set[str] = set()
    cdp.on_any(lambda m, p, s: got.add(m) if s == sid else None)

    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Security.enable", session_id=sid)
    await cdp.send("Page.navigate",
                   {"url": "data:text/html,<title>hi</title><p>x"}, session_id=sid)
    await asyncio.sleep(1.0)

    assert "Page.frameNavigated" in got, f"没收到 frameNavigated,只有 {sorted(got)}"
    assert any(m.startswith("Page.frameStartedLoading") or m == "Page.loadEventFired"
               for m in got), f"没有 loading 类事件,只有 {sorted(got)}"
    print(f"\n[实测] flat session 上收到 {len(got)} 类事件: {sorted(got)[:8]}…")


# ---------------------------------------------------------------------------
# works/07 §5:吃掉 windowFeatures 之后,window.open 真的开成 tab 而不是窗口
#   —— 这是"popup 一律转成 tab"这个结论的全部依据。
# ---------------------------------------------------------------------------

SHIM = """
const nativeOpen = window.open;
window.open = function (url, name, features) {
  const keep = String(features || "").split(",")
    .filter(f => /^\\s*(noopener|noreferrer|attributionsrc)\\s*$/i.test(f)).join(",");
  return nativeOpen.call(this, url, name, keep);
};
"""


async def _window_count(cdp) -> int:
    infos = (await cdp.send("Target.getTargets"))["targetInfos"]
    pages = [t for t in infos if t["type"] == "page"]
    wins = set()
    for t in pages:
        try:
            r = await cdp.send("Browser.getWindowForTarget", {"targetId": t["targetId"]})
            wins.add(r["windowId"])
        except Exception:
            pass
    return len(wins)


@pytest.mark.skip(
    reason="headless 下测不了:带 windowFeatures 的 window.open 根本不产生 target,"
           "headless 也没有真正的窗口概念。这条要在 headful 的浏览器上验 —— "
           "works/07 §5 已按此标注。"
)
async def test_stripping_window_features_makes_a_tab_not_a_window(cdp, page):
    tid, sid = page
    await cdp.send("Page.enable", session_id=sid)
    await cdp.send("Page.navigate", {"url": "data:text/html,<h1>shim</h1>"}, session_id=sid)
    await asyncio.sleep(0.3)

    base_windows = await _window_count(cdp)

    # 不装 shim:带尺寸参数 → 应该是一个新窗口
    ti = await _open_via(cdp, sid, "window.open('https://example.com/p','_blank','width=320,height=320')")
    popup_windows = await _window_count(cdp)
    await cdp.send("Target.closeTarget", {"targetId": ti["targetId"]})
    await asyncio.sleep(0.2)

    # 装 shim:同样的调用 → 应该只多一个 tab,窗口数不变
    await cdp.send("Runtime.evaluate", {"expression": SHIM}, session_id=sid)
    ti2 = await _open_via(cdp, sid, "window.open('https://example.com/q','_blank','width=320,height=320')")
    shimmed_windows = await _window_count(cdp)

    # shim 之后返回值仍是个真 WindowProxy(opener 关系还在)
    r = await cdp.send("Runtime.evaluate", {
        "expression": "typeof window.open('https://example.com/n','_blank','width=300') === 'object'",
        "userGesture": True}, session_id=sid)
    await cdp.send("Target.closeTarget", {"targetId": ti2["targetId"]})

    print(f"\n[实测] 窗口数 基线={base_windows} 未shim={popup_windows} shim后={shimmed_windows}")
    assert shimmed_windows <= base_windows + 1, (
        f"装了 shim 还是开出了窗口(基线 {base_windows} → {shimmed_windows})—— "
        "works/07 §4『popup 一律转成 tab』的依据不成立"
    )
    assert r["result"]["value"] is True, "shim 之后 window.open 不再返回 WindowProxy"
