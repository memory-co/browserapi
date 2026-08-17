"""没有桌面之后 —— 三条共同的规矩(docs/v2/works/06-no-desktop.md §2)。

v1 里这批原生 UI 是"看不见但仍然阻塞":裁 iframe 只是把它挪出可视区,
人把视图换一下就露出来了 —— **有兜底**。

v2 没有兜底。screencast 拍的是页面内容,浏览器自己的 UI 一个像素都不会出现在
帧里。不拦,页面就是**静止在那儿**,而人看不出为什么。

所以每一类都按同一套来:

**① 不替用户决定。** `alert` 不自动 accept,文件选择不自动填,权限不自动 grant。
一律抛事件出去等回填 —— 这些**本来就是人的决定**,替他做了,自动化脚本就会在
"以为点了确定"和"其实没点"之间产生看不见的分歧。

**② 有超时,而且超时是显式的。** 拦下来没人回填,页面就永远卡着。
每类都有默认超时和默认动作,**超时写进日志**,不静默。

**③ 内置页面要能画它们。** 这六类是协议的一部分,不是产品功能 ——
不画,人在那个页面上就会遇到"点了没反应"。
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:                                    # pragma: no cover
    from webmuxd.serve.session import Session

#: 拦下来之后等人回填多久。到点了走默认动作 —— **默认动作永远是"取消"那一侧**,
#: 因为"没人回答"最接近的意思是"别做"。
DEFAULT_TIMEOUT = 120.0


class Pending:
    """一件挡着页面、等人回填的事。"""

    __slots__ = ("id", "kind", "tab", "info", "at", "_task")

    def __init__(self, id: str, kind: str, tab: str | None, info: dict) -> None:
        self.id = id
        self.kind = kind
        self.tab = tab
        self.info = info
        self.at = time.time()
        self._task: asyncio.Task | None = None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "tab": self.tab,
                "at": self.at, **self.info}


class Interceptor:
    """一类原生 UI 的基类 —— 管住"等谁回填"和"没人回填怎么办"。"""

    kind = "native"

    def __init__(self, session: "Session", *, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.session = session
        self.timeout = timeout
        self.pending: dict[str, Pending] = {}
        self._n = 0

    # ------------------------------------------------------------------ 记账

    def _next_id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}_{self._n}"

    def open(self, id: str, tab: str | None, info: dict, *,
             on_timeout: Callable[[Pending], Awaitable[None]]) -> Pending:
        """记一件待办,发事件,并**挂一个超时**。"""
        p = Pending(id, self.kind, tab, info)
        self.pending[id] = p
        self.session.log.append(self.kind, tab=tab, state="pending", id=id, **info)
        self.session._emit(f"{self.kind}.opened", p.to_json())
        p._task = asyncio.create_task(self._expire(p, on_timeout))
        return p

    async def _expire(self, p: Pending, on_timeout) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(self.timeout)
            if self.pending.get(p.id) is not p:
                return
            # **超时不静默** —— 页面为什么动了/没动,日志里得有一行
            self.close(p.id, action="timeout", by="default")
            with contextlib.suppress(Exception):
                await on_timeout(p)

    def close(self, id: str, *, action: str, by: str = "api") -> Pending | None:
        p = self.pending.pop(id, None)
        if p is None:
            return None
        if p._task is not None:
            p._task.cancel()
        self.session.log.append(self.kind, tab=p.tab, id=id, action=action, by=by)
        self.session._emit(f"{self.kind}.closed",
                           {"id": id, "tab": p.tab, "action": action, "by": by})
        return p

    def list_json(self) -> list[dict]:
        return [p.to_json() for p in self.pending.values()]
