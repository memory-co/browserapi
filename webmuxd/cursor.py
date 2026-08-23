"""光标同步的**服务端那一半** —— docs/v2/works/b-input.md §5。

算形状的那段在页面里跑(`webmuxjs/sidecar/src/cursor.ts`)——
CDP 里没有「光标变了」这种事件,screencast 的帧里也不含光标,
所以只能在页面里 `elementFromPoint` + `getComputedStyle`,**值变了才上报**。

留在这儿的只有一样,而它必须留在这儿:**那份白名单。**
它是信任边界 —— 页面报上来的值会被直接写进观看端的 `style.cursor`,
而**远端页面是不可信的**。这道闸放在页面里就等于没有。
"""

from __future__ import annotations

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
