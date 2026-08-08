"""`Session` —— 一个 kasm 容器(docs/v1/sdk/session.md)。

一块 VNC 屏、一个 Chromium、一份日志。从 `Webmuxd.session(id=...)` 那儿拿。

**页面动作不挂在这儿**,挂在 `Tab` 上 —— `sess.click(...)` 这种方法**故意不给**:
一个 session 有多个 tab,"在哪个 tab 上点"不该靠隐式的当前值。
"""

from __future__ import annotations

from typing import Any

from webmuxd.client.mirror import Mirror
from webmuxd.client.tab import Tab
from webmuxd.client.transport import Transport
from webmuxd.errors import TabGone


class Session:
    def __init__(self, id: str, api_url: str, *, vnc_url: str = "",
                 token: str | None = None, user: str = "api",
                 owned: bool = False, manager: Any = None) -> None:
        self.id = id
        self.api_url = api_url.rstrip("/")
        self.vnc_url = vnc_url
        self.user = user
        self._t = Transport(self.api_url, token=token)
        self._manager = manager
        #: `with` 只关**这次真的建起来的** —— 接管到别人的,拿到手不等于有权杀
        self._owned = owned
        self._last_seen: dict[str, dict] = {}

        ws = self.api_url.replace("http://", "ws://").replace("https://", "wss://")
        self._mirror = Mirror(ws + "/api/events", token=token,
                              refetch=lambda: self._t.get("/api/tabs"))
        self._mirror.load(self._t.get("/api/tabs"))
        self._mirror.start()

    def __repr__(self) -> str:
        return f"<Session {self.id} {self.api_url} {len(self.tabs)} 个 tab>"

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc: object) -> None:
        if self._owned:
            self.kill()
        else:
            self.detach()

    # ------------------------------------------------------------ tab 表

    @property
    def tabs(self) -> list[Tab]:
        """**读内存,不发请求**(sdk/README §3)。"""
        return [Tab(self, t["id"]) for t in self._mirror.tabs()]

    @property
    def active(self) -> Tab | None:
        a = self._mirror.active
        return Tab(self, a) if a else None

    def tab(self, key: Any = None, *, title: str | None = None) -> Tab:
        """按 id / index / 标题拿一个。**按标题和 index 是本地匹配**,线上只认 id。"""
        rows = self._mirror.tabs()
        if title is not None:
            hits = [t for t in rows if t.get("title") == title] or \
                   [t for t in rows if title in (t.get("title") or "")]
            if len(hits) != 1:
                from webmuxd.errors import NotFound
                raise NotFound(
                    f"标题「{title}」匹配到 {len(hits)} 个 tab" if hits
                    else f"没有标题含「{title}」的 tab",
                    code="not_found",
                    details={"candidates": [{"id": t["id"], "name": t.get("title", "")}
                                            for t in rows]})
            return Tab(self, hits[0]["id"])
        if isinstance(key, int):
            try:
                return Tab(self, rows[key]["id"])
            except IndexError:
                raise TabGone(f"没有第 {key} 个 tab", code="tab_gone",
                              details={"reason": "closed"}) from None
        if isinstance(key, str):
            if self._mirror.get(key) is None:
                raise TabGone(f"{key} 不在了", code="tab_gone",
                              details={"reason": "closed"})
            return Tab(self, key)
        raise TypeError("tab() 要 id、index 或 title=")

    def open(self, url: str = "about:blank", *, active: bool = True,
             user: str | None = None) -> Tab:
        """新建 tab + 导航 + 返回句柄 —— **一次请求**,线上本来就是一步。"""
        d = self._t.post("/api/tabs", {"url": url, "active": active,
                                       "user": user or self.user})
        # **拿响应回灌内存**,不等 WS 那条 tab.created 追上来 ——
        # 和动作响应回灌是同一条原则(sdk/README §3),否则 `sess.open(url)`
        # 之后立刻读 `tab.title` 就是个竞态。
        self._mirror.seed(d)
        return Tab(self, d["id"])

    def reorder(self, order: list[str]) -> None:
        """少给的自动排在后面 —— lib 帮你补齐再发。"""
        self._t.post("/api/tabs/reorder", {"order": order})

    def sync(self) -> None:
        """手动重新拉全量。收到 `gap` 时 lib 自己会做,这个是给你兜底的。"""
        self._mirror.load(self._t.get("/api/tabs"))

    @property
    def stale(self) -> bool:
        """WS 断了 → True,内存不保证新鲜(属性读会退化成直接 GET)。"""
        return self._mirror.stale

    # -------------------------------------------------------------- 日志

    def log(self, *, limit: int = 100, after: int | None = None,
            only: str | None = None, user: str | None = None,
            tab: str | None = None, kind: str | None = None) -> list[dict]:
        return self._t.get("/api/log", limit=limit, after=after, only=only,
                           user=user, tab=tab, kind=kind)["entries"]

    def bundle(self, path: str | None = None, *, tab: str | None = None) -> bytes:
        data = self._t.get_bytes("/api/log/bundle", tab=tab)
        if path:
            with open(path, "wb") as fh:
                fh.write(data)
        return data

    # -------------------------------------------------------------- 杂项

    def status(self) -> dict:
        return self._t.get("/api/status")

    def viewport(self) -> dict:
        return self._t.get("/api/viewport")

    def reset(self) -> None:
        self._t.post("/api/reset")
        self.sync()

    def share(self, *, writable: bool = False, ttl: float = 3600) -> dict:
        """**默认只读**,和 API、CLI、ttyd 的默认一致 ——
        lib 不做"代码里方便所以更宽松"这种事。"""
        return self._t.post("/api/live-token",
                            {"read_only": not writable, "ttl_s": int(ttl)})

    def upload_file(self, path: str) -> str:
        with open(path, "rb") as fh:
            return self._t.post("/api/upload", {"name": path, "data": fh.read().hex()})["file_id"]

    def download(self, name: str, to: str | None = None) -> bytes:
        data = self._t.get_bytes(f"/api/download/{name}")
        if to:
            with open(to, "wb") as fh:
                fh.write(data)
        return data

    def detach(self) -> None:
        """断开但**不动那个 session** —— 关掉网页就是 detach,容器照跑。"""
        self._mirror.stop()

    def kill(self) -> None:
        self._mirror.stop()
        if self._manager is not None:
            self._manager._forget(self.id)
