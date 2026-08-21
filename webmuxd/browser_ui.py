"""**浏览器自己弹的那五类** —— 对话框 / 下载 / 文件选择 / 权限 / 认证。

没有桌面之后,这五样没人替我们点了([g](../docs/v2/works/g-native-ui.md))。
它们是"页面为什么停住"的唯一解释 —— 不接管的话,现象只剩
"observe 返回的页面一直没变"。

**放一个文件里,是因为它们是"全都要"不是"选一个"**,而且共用同一套规矩:

1. **拦下来,等人回填**,不替人做决定
2. **到点了走默认动作,而默认永远是"取消"那一侧** ——
   "没人回答"最接近的意思是"别做"
3. **进 scrollback**,让人事后看得见它挡过

([j §3.5](../docs/v2/works/j-layout.md#35-什么时候拆成两个文件))
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, TYPE_CHECKING
from urllib.parse import urlparse

from webmuxd.exceptions import BadRequest
from webmuxd.models import Pending

if TYPE_CHECKING:                                    # pragma: no cover
    from webmuxd.sessions import Session

#: 拦下来之后等人回填多久。到点了走默认动作 —— **默认动作永远是"取消"那一侧**,
#: 因为"没人回答"最接近的意思是"别做"。
DEFAULT_TIMEOUT = 120.0


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
        p = Pending(id, self.kind, tab, info, at=time.time())
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


# --------------------------------------------------------------------------
# 对话框:alert / confirm / prompt / beforeunload
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# 下载
# --------------------------------------------------------------------------



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


# --------------------------------------------------------------------------
# 文件选择
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# 权限
# --------------------------------------------------------------------------


#: CDP 认得的权限名。给错名字它会报错,所以在这儿先挡一道,
#: **报"没有这个权限名"比报一句 CDP 的原文有用**。
KNOWN = frozenset("""
accessibilityEvents audioCapture backgroundSync backgroundFetch
clipboardReadWrite clipboardSanitizedWrite displayCapture durableStorage
flash geolocation idleDetection localFonts midi midiSysex nfc notifications
paymentHandler periodicBackgroundSync protectedMediaIdentifier sensors
storageAccess speakerSelection topLevelStorageAccess videoCapture
videoCapturePanTiltZoom wakeLockScreen wakeLockSystem windowManagement
""".split())


class Permissions:
    kind = "permission"

    def __init__(self, session: "Session") -> None:
        self.session = session
        #: origin → 给过哪些。空 origin 是"所有站点"。
        self.granted: dict[str, list[str]] = {}

    async def attach(self) -> None:
        """**默认全拒。** 空列表就是"一个都不给"。"""
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Browser.grantPermissions",
                                        {"permissions": []})

    async def grant(self, names: list[str], *, origin: str = "",
                    by: str = "api") -> dict[str, Any]:
        bad = [n for n in names if n not in KNOWN]
        if bad:
            raise BadRequest(f"没有这些权限名:{', '.join(bad)}",
                             code="bad_request",
                             details={"unknown": bad, "known": sorted(KNOWN)})
        params: dict[str, Any] = {"permissions": list(names)}
        if origin:
            params["origin"] = origin
        await self.session.cdp.send("Browser.grantPermissions", params)
        self.granted[origin] = list(names)
        self.session.log.append("permission", action="grant", by=by,
                                origin=origin or "*", names=list(names))
        self.session._emit("permission.changed",
                           {"origin": origin or "*", "names": list(names)})
        return {"ok": True, "origin": origin or "*", "names": list(names)}

    async def reset(self, *, by: str = "api") -> dict[str, Any]:
        await self.session.cdp.send("Browser.resetPermissions", {})
        await self.attach()                 # 回到"全拒",不是回到浏览器默认
        self.granted.clear()
        self.session.log.append("permission", action="reset", by=by)
        self.session._emit("permission.changed", {"origin": "*", "names": []})
        return {"ok": True, "names": []}

    def list_json(self) -> dict[str, Any]:
        return {"granted": {k or "*": v for k, v in self.granted.items()},
                "default": "deny"}


# --------------------------------------------------------------------------
# HTTP 认证
# --------------------------------------------------------------------------



class BasicAuth:
    kind = "auth"

    def __init__(self, session: "Session") -> None:
        self.session = session
        #: origin → (user, password)。`""` 那把是"所有站点都用它"。
        self.creds: dict[str, tuple[str, str]] = {}
        self.on = False

    def attach(self) -> None:
        self.session.cdp.on("Fetch.authRequired", self._auth)
        self.session.cdp.on("Fetch.requestPaused", self._paused)

    # ------------------------------------------------------------------ 开关

    async def set(self, *, origin: str = "", user: str, password: str) -> dict[str, Any]:
        self.creds[origin] = (user, password)
        await self._enable()
        # **凭证不进日志** —— 和动作层那条一样,记账时看到的是掩码
        self.session.log.append("auth", event="credentials_set",
                                origin=origin or "*", user=user, password="***")
        return {"ok": True, "origin": origin or "*", "on": self.on}

    async def clear(self) -> dict[str, Any]:
        self.creds.clear()
        await self._disable()
        self.session.log.append("auth", event="credentials_cleared")
        return {"ok": True, "on": self.on}

    async def _enable(self) -> None:
        if self.on:
            return
        for tab_id in list(self.session._sessions):
            sid = self.session._sessions[tab_id]
            with contextlib.suppress(Exception):
                await self.session.cdp.send(
                    "Fetch.enable",
                    {"handleAuthRequests": True,
                     "patterns": [{"urlPattern": "*"}]},
                    session_id=sid)
        self.on = True

    async def _disable(self) -> None:
        if not self.on:
            return
        for sid in list(self.session._sessions.values()):
            with contextlib.suppress(Exception):
                await self.session.cdp.send("Fetch.disable", {}, session_id=sid)
        self.on = False

    async def enable_for(self, session_id: str) -> None:
        """新 tab 进来时接上 —— 只在已经开着的时候。"""
        if not self.on:
            return
        with contextlib.suppress(Exception):
            await self.session.cdp.send(
                "Fetch.enable",
                {"handleAuthRequests": True, "patterns": [{"urlPattern": "*"}]},
                session_id=session_id)

    # ------------------------------------------------------------------ 事件

    def _paused(self, params: dict, sid: str | None) -> None:
        """**立刻放行。** 我们要的只是 authRequired,别的请求一个都不改。"""
        import asyncio
        rid = params.get("requestId")
        if not rid:
            return
        asyncio.create_task(self._continue(rid, sid))

    async def _continue(self, rid: str, sid: str | None) -> None:
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Fetch.continueRequest",
                                        {"requestId": rid}, session_id=sid)

    def _auth(self, params: dict, sid: str | None) -> None:
        import asyncio
        asyncio.create_task(self._answer(params, sid))

    async def _answer(self, params: dict, sid: str | None) -> None:
        url = (params.get("request") or {}).get("url", "")
        origin = ""
        with contextlib.suppress(Exception):
            u = urlparse(url)
            origin = f"{u.scheme}://{u.netloc}"
        cred = self.creds.get(origin) or self.creds.get("")
        tab_id = self.session._tab_of_session(sid)

        if cred is None:
            # **不猜、不重试。** 没凭证就取消,并且**说出来** ——
            # 页面白屏时日志里得有这一行
            self.session.log.append("auth", event="no_credentials",
                                    tab=tab_id, origin=origin)
            self.session._emit("auth.required", {"tab": tab_id, "origin": origin,
                                                 "answered": False})
            body = {"response": "CancelAuth"}
        else:
            self.session.log.append("auth", event="answered", tab=tab_id,
                                    origin=origin, user=cred[0], password="***")
            self.session._emit("auth.required", {"tab": tab_id, "origin": origin,
                                                 "answered": True})
            body = {"response": "ProvideCredentials",
                    "username": cred[0], "password": cred[1]}
        with contextlib.suppress(Exception):
            await self.session.cdp.send(
                "Fetch.continueWithAuth",
                {"requestId": params.get("requestId"), "authChallengeResponse": body},
                session_id=sid)


# --------------------------------------------------------------------------
# 五类合一:Natives
# --------------------------------------------------------------------------


__all__ = ["Natives", "Dialogs", "Downloads", "FileChooser", "BasicAuth",
           "Permissions"]


class Natives:
    """一个 session 一份。`Session` 只跟它打交道,不认识下面五个。"""

    def __init__(self, session: "Session") -> None:
        self.dialogs = Dialogs(session)
        self.downloads = Downloads(session)
        self.files = FileChooser(session)
        self.auth = BasicAuth(session)
        self.permissions = Permissions(session)

    async def attach(self) -> None:
        self.dialogs.attach()
        self.files.attach()
        self.auth.attach()
        await self.downloads.attach()
        await self.permissions.attach()

    async def attach_target(self, session_id: str) -> None:
        """每接一个新 target 都要走一遍的那些(Page 域的开关不是浏览器级的)。"""
        await self.files.enable_for(session_id)
        await self.auth.enable_for(session_id)

    def pending_json(self) -> dict[str, Any]:
        """**挡着页面的东西一次给全** —— 内置页面和上层 UI 都靠它开局对齐。"""
        return {"dialogs": self.dialogs.list_json(),
                "file_choosers": self.files.list_json(),
                "downloads": self.downloads.list_json(),
                "permissions": self.permissions.list_json(),
                "auth": {"on": self.auth.on,
                         "origins": sorted(k or "*" for k in self.auth.creds)}}
