"""`Observation` —— 一次观测的对象化(docs/v1/sdk/tab/read.md)。

线上是一坨 JSON,这边是个**能下标、能 find、能直接进 prompt** 的东西。
这个落差就是"主体在 lib"的具体样子(works/02 §1)。
"""

from __future__ import annotations

from typing import Any, Iterator


class Element:
    """观测里的一个元素。`tab.click(el)` 会自动带上 observation id ——
    页面变了就抛 NotFound,而不是点到编号相同的另一个东西。"""

    __slots__ = ("id", "role", "name", "value", "bbox", "in_viewport",
                 "enabled", "affords", "hint", "observation")

    def __init__(self, d: dict, observation: str) -> None:
        self.id = d["id"]
        self.role = d.get("role", "")
        self.name = d.get("name", "")
        self.value = d.get("value")
        self.bbox = tuple(d.get("bbox") or (0, 0, 0, 0))
        self.in_viewport = bool(d.get("in_viewport", True))
        self.enabled = bool(d.get("enabled", True))
        self.affords = d.get("affords") or []
        self.hint = d.get("hint", "")
        self.observation = observation

    def __repr__(self) -> str:
        return f'<[{self.id}] {self.role} "{self.name}">'


class Page:
    __slots__ = ("url", "title", "loading", "scroll", "viewport")

    def __init__(self, d: dict) -> None:
        self.url = d.get("url", "")
        self.title = d.get("title", "")
        self.loading = bool(d.get("loading"))
        self.scroll = d.get("scroll") or {}
        self.viewport = d.get("viewport") or {}


class Observation:
    def __init__(self, session: Any, d: dict) -> None:
        self._s = session
        self._d = d
        self.id: str = d.get("observation_id", "")
        self.tab: str | None = d.get("tab")
        self.at: str = d.get("at", "")
        self.page = Page(d.get("page") or {})
        self.elements = [Element(e, self.id) for e in d.get("elements") or []]
        self.tabs: list[dict] = d.get("tabs") or []
        #: **要往 prompt 里放。** 它写的是这次观测的盲区;不给模型看,
        #: 模型会把"没看见"当成"不存在",然后自信地做错决定。
        self.notes: list[str] = d.get("notes") or []
        self.text: str = d.get("text", "")
        self.filter_version: int = d.get("filter_version", 0)
        self._shot: bytes | None = None
        self._plain: bytes | None = None

    def __getitem__(self, n: int) -> Element:
        for e in self.elements:
            if e.id == n:
                return e
        from webmuxd.errors import NotFound
        raise NotFound(f"这次观测里没有 [{n}]", code="not_found",
                       details={"candidates": [vars_of(e) for e in self.elements[:3]]})

    def __iter__(self) -> Iterator[Element]:
        return iter(self.elements)

    def __len__(self) -> int:
        return len(self.elements)

    def find(self, *, role: str | None = None, name: str | None = None) -> Element:
        for e in self.elements:
            if (role is None or e.role == role) and (name is None or e.name == name):
                return e
        from webmuxd.errors import NotFound
        raise NotFound(f"这次观测里没有 role={role} name={name}", code="not_found",
                       details={"candidates": [vars_of(e) for e in self.elements[:3]]})

    def as_prompt(self) -> str:
        """紧凑排版,**纯客户端,不请求网络**。直接进 prompt。"""
        out = []
        for e in self.elements:
            line = f'[{e.id}] {e.role:8} "{e.name}"'
            if e.value is not None:
                line += f' = "{e.value}"'
            flags = ([] if e.in_viewport else ["需下滑"]) + ([] if e.enabled else ["禁用"])
            out.append(line + (f"        ({'、'.join(flags)})" if flags else ""))
        return "\n".join(out)

    @property
    def screenshot(self) -> bytes:
        """标注版 —— 图上已经画好 [12] [13] 编号(Set-of-Mark)。"""
        if self._shot is None:
            self._shot = self._s._t.get_bytes(self._d["screenshot"]["url"])
        return self._shot

    @property
    def plain_screenshot(self) -> bytes:
        if self._plain is None:
            self._plain = self._s._t.get_bytes(self._d["screenshot"]["url"],
                                               annotate=False)
        return self._plain

    def __repr__(self) -> str:
        return f"<Observation {self.id} {len(self.elements)} 个元素 {self.page.url}>"


def vars_of(e: Element) -> dict:
    return {"id": e.id, "role": e.role, "name": e.name, "hint": e.hint}
