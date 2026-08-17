"""光标同步 —— docs/v2/works/03-input.md §5。

远端页面里光标是什么形状,本地就跟着变。没有这个,画面上一切都是箭头,
**人会分不清哪里能点**。

**CDP 里没有「光标变了」这种事件** —— 光标是纯渲染层的东西,screencast 的帧里
也不含光标。所以只能往页面注入探针,`elementFromPoint` + `getComputedStyle`,
**值变了才上报**,基本不占带宽。

复用 `core/shim.BINDING` 那一个 binding,**不新开第二个**([03 §6](../../docs/v2/works/03-input.md)):
探针改变了页面环境这件事要如实承认,那就更没理由多加一个。
"""

from __future__ import annotations

from webmuxd.core.cdp import CDP, CDPError
from webmuxd.core.shim import BINDING

#: CSS 规范里的 cursor 关键字。**白名单,不是黑名单。**
#:
#: 这个值会被直接写进客户端的 `style.cursor`,而**远端页面是不可信的**。
#: `cursor` 支持 `url(...)` 自定义光标 —— 原样透传等于让被隔离的页面指使客户端
#: 去拉任意 URL,隔离性当场破掉。
ALLOWED = frozenset("""
auto default none context-menu help pointer progress wait cell crosshair text
vertical-text alias copy move no-drop not-allowed grab grabbing all-scroll
col-resize row-resize n-resize e-resize s-resize w-resize ne-resize nw-resize
se-resize sw-resize ew-resize ns-resize nesw-resize nwse-resize zoom-in zoom-out
""".split())


def sanitize(value: str) -> str:
    """不在白名单里一律降级成 `default`。"""
    v = (value or "").strip().lower()
    return v if v in ALLOWED else "default"


CURSOR_JS = """
(() => {
  if (window.__webmuxdCursorShim) return;
  let last = '', pending = false, lx = 0, ly = 0;

  // `cursor: auto` 的语义是"文字上 I 型,其它地方箭头",光读计算样式
  // 区分不出来 —— 两种情况读出来都是 auto。所以要做命中测试。
  const overText = (x, y) => {
    const f = document.caretRangeFromPoint;
    if (!f) return false;
    let r;
    try { r = document.caretRangeFromPoint(x, y); } catch (e) { return false; }
    if (!r || !r.startContainer || r.startContainer.nodeType !== 3) return false;
    // caretRangeFromPoint 会"吸附"到最近的文字,**不校验就会让空白处也报 I 型**
    const range = document.createRange();
    range.selectNodeContents(r.startContainer);
    for (const rect of range.getClientRects()) {
      if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom)
        return true;
    }
    return false;
  };

  const read = () => {
    pending = false;
    let el;
    try { el = document.elementFromPoint(lx, ly); } catch (e) { return; }
    if (!el) return;
    let c = 'default';
    try { c = getComputedStyle(el).cursor || 'auto'; } catch (e) {}
    if (c === 'auto') c = overText(lx, ly) ? 'text' : 'default';
    if (c === last) return;                 // **值变了才上报**
    last = c;
    try { __webmuxd(JSON.stringify({ kind: 'cursor', cursor: c })); } catch (e) {}
  };

  const tick = (e) => {
    if (e) { lx = e.clientX; ly = e.clientY; }
    if (pending) return;
    pending = true;
    requestAnimationFrame(read);            // rAF 节流
  };

  addEventListener('pointermove', tick, true);
  addEventListener('pointerdown', tick, true);
  addEventListener('scroll', () => tick(null), true);
  window.__webmuxdCursorShim = true;
})();
""".replace("__webmuxd", BINDING)


async def install(cdp: CDP, session_id: str) -> None:
    """装到这个 target 上,每次导航自动重装。"""
    try:
        await cdp.send("Runtime.addBinding", {"name": BINDING},
                       session_id=session_id)
        await cdp.send("Page.addScriptToEvaluateOnNewDocument",
                       {"source": CURSOR_JS}, session_id=session_id)
        await cdp.send("Runtime.evaluate", {"expression": CURSOR_JS},
                       session_id=session_id)
    except CDPError:
        pass
