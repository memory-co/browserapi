"""页面层 shim —— docs/v1/works/07-popup-windows.md §2 D。

**popup 一律转成 tab,没有开关,没有例外。**

杠杆是规范里那条(MDN):`windowFeatures` 省略或为空,开出来的就是普通 tab。
所以不需要任何"转换"动作 —— 把触发 popup 的 features 吃掉就行。

为什么是这条路,而不是拦 `Page.windowOpen` 之后重开:
**那会双向断掉 opener**,页面手里的 WindowProxy 废掉、新 tab 的 `window.opener`
也没了 —— OAuth 和支付回调会直接坏。这条路是页面**自己**调原生 `open`,
所以 opener 关系完整。

**装在主世界**,不是独立世界 —— 要覆盖的正是页面看到的那个 `window.open`。
"""

from __future__ import annotations

from webmuxd.core.cdp import CDP, CDPError

#: 只留这三个 —— 它们不触发 popup,但改变返回值语义,吃掉会改变行为
#: (`noopener` 必须还返回 `null`)。
KEEP = ("noopener", "noreferrer", "attributionsrc")

POPUP_TO_TAB_JS = """
(() => {
  if (window.__webmuxdOpenShim) return;
  const nativeOpen = window.open;
  const KEEP = /^\\s*(noopener|noreferrer|attributionsrc)\\s*$/i;
  window.open = function (url, name, features) {
    const keep = String(features || "").split(",").filter(f => KEEP.test(f)).join(",");
    return nativeOpen.call(this, url, name, keep);
  };
  // 别让页面一眼看穿(有极少数站点靠 toString 判原生)
  try {
    window.open.toString = () => nativeOpen.toString();
  } catch (e) {}
  window.__webmuxdOpenShim = true;
})();
"""


async def install(cdp: CDP, session_id: str) -> None:
    """装到这个 target 上,**每次导航自动重装**。

    `addScriptToEvaluateOnNewDocument` 保证它在页面自己的第一行脚本之前跑;
    再对当前文档 evaluate 一次,因为已经加载完的那一页不会再触发它。
    """
    try:
        await cdp.send("Page.addScriptToEvaluateOnNewDocument",
                       {"source": POPUP_TO_TAB_JS}, session_id=session_id)
        await cdp.send("Runtime.evaluate",
                       {"expression": POPUP_TO_TAB_JS}, session_id=session_id)
    except CDPError:
        # 装不上不该让这个 tab 用不了 —— 后果只是 popup 还是窗口
        pass


# ---------------------------------------------------------------------------
# 人在动没在动 —— works/06 §3.2
# ---------------------------------------------------------------------------

#: 页面调它把输入报回来。`Runtime.addBinding` 会把这个调用变成
#: `Runtime.bindingCalled` 事件送到 sessiond。
BINDING = "__webmuxd"

HUMAN_INPUT_JS = """
(() => {
  if (window.__webmuxdInputShim) return;
  const send = (kind, e) => {
    try {
      __webmuxd(JSON.stringify({
        kind, x: e.clientX | 0, y: e.clientY | 0,
        role: (e.target && (e.target.getAttribute('role') ||
               e.target.tagName || '')).toLowerCase(),
        name: (e.target && (e.target.innerText || e.target.value || ''))
              .toString().trim().slice(0, 40),
        at: Date.now()
      }));
    } catch (err) {}
  };
  // **捕获阶段** —— 页面 stopPropagation 也拦不住我们
  addEventListener('pointerdown', e => send('pointerdown', e), true);
  addEventListener('keydown', e => send('keydown', e), true);
  window.__webmuxdInputShim = true;
})();
"""


async def install_input_watch(cdp: CDP, session_id: str) -> None:
    """让页面把输入报回来。

    **CDP 派发的输入在页面里 `isTrusted === true`** —— 和真人点的一模一样,
    页面脚本分不出。所以这里只负责"有输入",谁干的由上层用
    "我刚派发了什么" 做相关性(works/06 §3.2)。
    """
    try:
        await cdp.send("Runtime.addBinding", {"name": BINDING},
                       session_id=session_id)
        await cdp.send("Page.addScriptToEvaluateOnNewDocument",
                       {"source": HUMAN_INPUT_JS}, session_id=session_id)
        await cdp.send("Runtime.evaluate", {"expression": HUMAN_INPUT_JS},
                       session_id=session_id)
    except CDPError:
        pass
