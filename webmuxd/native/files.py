"""文件选择框 —— docs/v2/works/06-no-desktop.md §5 排第三。

**不做的话上传类流程完全走不通**:页面点了 `<input type=file>`,
Chromium 等着一个原生选择框,而 headless 里根本没有那个框。

两段:

1. `Page.setInterceptFileChooserDialog` 把框拦下来 → `Page.fileChooserOpened`
   带着 `backendNodeId`,我们抛事件出去
2. 外面把文件传上来(`POST /api/upload`),再回填 `DOM.setFileInputFiles`

**超时的默认动作是取消**(填空列表)—— 和别的几类一样,"没人回答"就是"别做"。
"""

from __future__ import annotations

import contextlib
import os
import re
from pathlib import Path
from typing import Any

from webmuxd.native.base import Interceptor, Pending

FILE_TIMEOUT = 180.0                    # 人要去翻文件,给宽一点

_SAFE = re.compile(r"[^\w.\-() 一-鿿]+")


def safe_name(name: str) -> str:
    """名字来自调用方,**不可信**:去掉路径分隔符和奇怪字符,只留一个文件名。"""
    base = os.path.basename(name or "").strip() or "upload"
    base = _SAFE.sub("_", base).lstrip(".") or "upload"
    return base[:180]


class FileChooser(Interceptor):
    kind = "file"

    def __init__(self, session, *, timeout: float = FILE_TIMEOUT) -> None:
        super().__init__(session, timeout=timeout)
        self.files_dir = Path(session.files_dir)
        self.files_dir.mkdir(parents=True, exist_ok=True)

    def attach(self) -> None:
        self.session.cdp.on("Page.fileChooserOpened", self._opened)

    async def enable_for(self, session_id: str) -> None:
        """每个 target 都要开一次 —— 它是 Page 域的开关,不是浏览器级的。"""
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Page.setInterceptFileChooserDialog",
                                        {"enabled": True}, session_id=session_id)

    # ------------------------------------------------------------------ 进

    def _opened(self, params: dict, sid: str | None) -> None:
        tab_id = self.session._tab_of_session(sid)
        self.open(self._next_id("file"), tab_id, {
            "mode": params.get("mode", "selectSingle"),      # 还是 selectMultiple
            "node": params.get("backendNodeId"),
            "session": sid,
        }, on_timeout=self._on_timeout)

    # ------------------------------------------------------------------ 出

    async def fill(self, id: str, names: list[str], *, by: str = "api") -> dict[str, Any]:
        """回填。`names` 是 `POST /api/upload` 传上来的那些文件名。

        空列表 = 取消,这也是超时时走的那条。
        """
        p = self.pending.get(id)
        if p is None:
            return {"ok": False, "error": "没有这个待办"}
        paths = []
        for n in names or ():
            fp = self.files_dir / safe_name(n)
            if fp.exists():
                paths.append(str(fp))
        await self._set(p, paths)
        self.close(id, action="cancel" if not paths else "fill", by=by)
        return {"ok": True, "id": id, "files": [os.path.basename(x) for x in paths]}

    async def _set(self, p: Pending, paths: list[str]) -> None:
        with contextlib.suppress(Exception):
            await self.session.cdp.send(
                "DOM.setFileInputFiles",
                {"files": paths, "backendNodeId": p.info.get("node")},
                session_id=p.info.get("session"))

    async def _on_timeout(self, p: Pending) -> None:
        await self._set(p, [])          # 空列表就是取消

    # ------------------------------------------------------------------ 收文件

    def save(self, name: str, data: bytes) -> str:
        fp = self.files_dir / safe_name(name)
        fp.write_bytes(data)
        return fp.name

    def list_files(self) -> list[dict]:
        return [{"name": f.name, "bytes": f.stat().st_size}
                for f in sorted(self.files_dir.iterdir()) if f.is_file()]
