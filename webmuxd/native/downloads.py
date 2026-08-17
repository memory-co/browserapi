"""下载 —— docs/v2/works/06-no-desktop.md §5 排第二。

**不做的话点了下载什么都不发生**,文件在那台机器上没人知道。
v1 里还有个下载气泡挂在工具栏上,v2 连那个都没有。

和别的几类不一样:下载**不需要人回填**,它需要的是"东西落到哪儿、怎么取走"。
所以这里没有超时和默认动作,只有事件和一个取文件的端点。

`Browser.setDownloadBehavior` 用 `allowAndName`:文件按 GUID 落盘,
我们再按 `suggestedFilename` 改名 —— **重名不覆盖**,加序号。
覆盖掉上一次的下载是那种"你以为拿到了新的"的错。
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:                                    # pragma: no cover
    from webmuxd.serve.session import Session


class Downloads:
    kind = "download"

    def __init__(self, session: "Session") -> None:
        self.session = session
        self.dir = Path(session.downloads_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.items: dict[str, dict[str, Any]] = {}

    async def attach(self) -> None:
        self.session.cdp.on("Browser.downloadWillBegin", self._begin)
        self.session.cdp.on("Browser.downloadProgress", self._progress)
        # **浏览器级,不是每个 target 一遍** —— 下载归浏览器管
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Browser.setDownloadBehavior", {
                "behavior": "allowAndName",
                "downloadPath": str(self.dir),
                "eventsEnabled": True})

    # ------------------------------------------------------------------ 事件

    def _begin(self, params: dict, _sid: str | None) -> None:
        guid = params.get("guid", "")
        name = os.path.basename(params.get("suggestedFilename") or "") or guid
        item = {"id": guid, "file": name, "url": params.get("url", ""),
                "bytes": 0, "total": 0, "state": "pending", "path": None}
        self.items[guid] = item
        self.session.log.append("download", state="pending", id=guid,
                                file=name, url=item["url"])
        self.session._emit("download.began", dict(item))

    def _progress(self, params: dict, _sid: str | None) -> None:
        guid = params.get("guid", "")
        item = self.items.get(guid)
        if item is None:
            return
        item["bytes"] = int(params.get("receivedBytes") or 0)
        item["total"] = int(params.get("totalBytes") or 0)
        state = params.get("state", "inProgress")
        if state == "inProgress":
            item["state"] = "running"
            return
        item["state"] = "done" if state == "completed" else "canceled"
        if item["state"] == "done":
            item["path"] = str(self._rename(guid, item["file"]))
        self.session.log.append("download", state=item["state"], id=guid,
                                file=item["file"], bytes=item["bytes"])
        self.session._emit("download.done", dict(item))

    def _rename(self, guid: str, name: str) -> Path:
        """`allowAndName` 落的是 GUID 文件名,改回人看得懂的那个。"""
        src = self.dir / guid
        if not src.exists():
            return src
        dst = self.dir / name
        stem, ext = os.path.splitext(name)
        n = 1
        while dst.exists():                     # **重名不覆盖**
            dst = self.dir / f"{stem} ({n}){ext}"
            n += 1
        with contextlib.suppress(OSError):
            src.rename(dst)
        return dst

    # ------------------------------------------------------------------ 取

    def list_json(self) -> list[dict]:
        return sorted(self.items.values(), key=lambda i: i["id"])

    def path_of(self, id: str) -> Path | None:
        item = self.items.get(id)
        if not item or item["state"] != "done" or not item["path"]:
            return None
        p = Path(item["path"])
        # 只放行下载目录里的东西 —— 名字来自页面,**不可信**
        try:
            p.resolve().relative_to(self.dir.resolve())
        except ValueError:
            return None
        return p if p.exists() else None
