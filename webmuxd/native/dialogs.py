"""JS 对话框 —— `alert` / `confirm` / `prompt` / `beforeunload`。

docs/v2/works/06-no-desktop.md §5 排第一:**不做的话任何 `confirm` 都会让页面
永久卡住,而且看不出来**。现象是"observe 返回的页面一直没变",看不出是网络慢
还是有个 confirm 挡着。

v1 已经拦下来了(`Page.javascriptDialogOpening` → `tab.dialog`),v2 补的是
另外三样:**事件、超时、日志**。

超时的默认动作是 **dismiss**,四种都一样:
"没人回答"最接近的意思是"别做" —— `confirm` 当没点确定,`beforeunload` 留在原页。
"""

from __future__ import annotations

import contextlib
from typing import Any

from webmuxd.native.base import Interceptor, Pending

#: 对话框比别的更该早点放手 —— 它**完全挡死**整个页面,连 JS 都停了。
DIALOG_TIMEOUT = 60.0


class Dialogs(Interceptor):
    kind = "dialog"

    def __init__(self, session, *, timeout: float = DIALOG_TIMEOUT) -> None:
        super().__init__(session, timeout=timeout)

    def attach(self) -> None:
        self.session.cdp.on("Page.javascriptDialogOpening", self._opening)
        self.session.cdp.on("Page.javascriptDialogClosed", self._closed)

    # ------------------------------------------------------------------ 进

    def _opening(self, params: dict, sid: str | None) -> None:
        tab_id = self.session._tab_of_session(sid)
        info = {"subtype": params.get("type"),
                "text": params.get("message", ""),
                "default": params.get("defaultPrompt") or "",
                "url": params.get("url", "")}
        p = self.open(self._next_id("dlg"), tab_id, info,
                      on_timeout=self._on_timeout)
        # tab 上的状态 —— **弹窗挡住了页面,所以它不只是一条通知**
        if tab_id:
            self.session.tabs.update(tab_id, dialog={
                "id": p.id, "kind": info["subtype"], "message": info["text"],
                "default": info["default"]})

    def _closed(self, _params: dict, sid: str | None) -> None:
        """页面自己把它关了(比如 `Page.reload` 冲掉)—— 清账,别留个假的待办。"""
        tab_id = self.session._tab_of_session(sid)
        for pid, p in list(self.pending.items()):
            if p.tab == tab_id:
                self.close(pid, action="gone", by="page")
        if tab_id:
            self.session.tabs.update(tab_id, dialog=None)

    # ------------------------------------------------------------------ 出

    async def respond(self, tab_id: str, *, accept: bool, text: str = "",
                      by: str = "api") -> dict[str, Any]:
        """回填。**不替用户决定**,所以 `accept` 没有默认值,调用方必须说。"""
        pid = next((k for k, p in self.pending.items() if p.tab == tab_id), None)
        sid = await self.session.cdp_session_for(tab_id)
        await self.session.cdp.send(
            "Page.handleJavaScriptDialog",
            {"accept": bool(accept), "promptText": text}, session_id=sid)
        self.session.tabs.update(tab_id, dialog=None)
        if pid:
            self.close(pid, action="accept" if accept else "dismiss", by=by)
        return {"ok": True, "id": pid, "accepted": bool(accept)}

    async def _on_timeout(self, p: Pending) -> None:
        if not p.tab:
            return
        with contextlib.suppress(Exception):
            sid = await self.session.cdp_session_for(p.tab)
            await self.session.cdp.send("Page.handleJavaScriptDialog",
                                        {"accept": False}, session_id=sid)
            self.session.tabs.update(p.tab, dialog=None)
