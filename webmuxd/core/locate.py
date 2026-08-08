"""元素快照与定位 —— docs/v1/api/act.md §1.1 和 §4。

文档自己说了:元素筛选这套规则是**整个系统最容易出质量问题的地方**。
所以两件事在这儿是硬的:

1. **筛选规则有版本号**(`FILTER_VERSION`),每条日志记它。
   规则一升级,历史日志里的元素编号就对不上了 —— 不记版本就没法回看。
2. **文字匹配定死,不猜**:精确 → 子串 → 大小写不敏感,
   **仍然多于一个就报 not_found 并列出全部候选,绝不随便挑一个**。
   随便挑的代价是点错东西,而点错浏览器比敲错终端贵。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from webmuxd.core.cdp import CDP, CDPError
from webmuxd.errors import BadRequest, NotClickable, NotFound

#: 筛选规则的版本。**改了规则就要 +1** —— 日志里记着它,
#: 否则规则一变,历史观测里的 `[12]` 就指向了别的东西(api/act.md §1.1)。
FILTER_VERSION = 1

#: 默认最多给多少个元素。超了必须在 notes 里说清楚截掉了多少。
MAX_ELEMENTS = 150

#: 可交互的 role —— 第一档筛选(api/act.md §1.1 规则 1)。
INTERACTIVE_ROLES = frozenset({
    "button", "link", "textbox", "searchbox", "checkbox", "radio", "combobox",
    "listbox", "option", "menuitem", "menuitemcheckbox", "menuitemradio",
    "tab", "slider", "spinbutton", "switch", "textarea", "colorwell", "date",
    "datetime", "file upload button", "InputTime", "menulistpopup",
})

#: 这些 role 即使有名字也不该进元素表 —— 纯结构。
STRUCTURAL_ROLES = frozenset({
    "RootWebArea", "generic", "none", "presentation", "paragraph", "LineBreak",
    "StaticText", "InlineTextBox", "list", "listitem", "Iframe",
})


@dataclass
class Element:
    """一个能被定位到的东西。

    `id` 是**这次观测里的编号**,不跨观测稳定 —— 所以按编号定位时要带上
    `observation` id,页面变了就抛 NotFound,而不是点到编号相同的另一个东西。
    """

    id: int
    role: str
    name: str
    value: str | None = None
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    in_viewport: bool = True
    enabled: bool = True
    affords: list[str] = field(default_factory=list)
    hint: str = ""
    backend_node_id: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "role": self.role, "name": self.name, "value": self.value,
            "bbox": [round(v, 1) for v in self.bbox],
            "in_viewport": self.in_viewport, "enabled": self.enabled,
            "affords": self.affords, "hint": self.hint,
        }

    def as_line(self) -> str:
        """紧凑表示的一行(api/act.md §1.3)。"""
        line = f"[{self.id}] {self.role:8} \"{self.name}\""
        if self.value is not None:
            line += f" = \"{self.value}\""
        flags = []
        if not self.in_viewport:
            flags.append("需下滑")
        if not self.enabled:
            flags.append("禁用")
        return line + (f"        ({'、'.join(flags)})" if flags else "")


@dataclass
class Snapshot:
    """一次元素快照。observe 和 act 共用同一份 —— 定位和给模型看的必须是同一套编号。"""

    elements: list[Element]
    notes: list[str] = field(default_factory=list)
    filter_version: int = FILTER_VERSION
    viewport: tuple[float, float] = (0, 0)

    def __getitem__(self, n: int) -> Element:
        for el in self.elements:
            if el.id == n:
                return el
        raise NotFound(f"这次观测里没有 [{n}]", code="not_found",
                       details={"candidates": [e.to_json() for e in self.elements[:3]]})

    def as_prompt(self) -> str:
        return "\n".join(e.as_line() for e in self.elements)


# ---------------------------------------------------------------------------
# 抓快照
# ---------------------------------------------------------------------------

async def snapshot(cdp: CDP, session_id: str, *, max_elements: int = MAX_ELEMENTS,
                   viewport_only: bool = False) -> Snapshot:
    """抓可访问性树 → 筛出能交互又看得见的 → 量 bbox。

    **不能把整棵 AX 树倒给模型**(几千节点,又贵又吵),所以有 §1.1 那套规则。
    """
    await cdp.send("Accessibility.enable", session_id=session_id)
    tree = await cdp.send("Accessibility.getFullAXTree", session_id=session_id)
    metrics = await cdp.send("Page.getLayoutMetrics", session_id=session_id)
    vp = metrics.get("cssVisualViewport") or metrics.get("layoutViewport") or {}
    vw = float(vp.get("clientWidth") or vp.get("width") or 0)
    vh = float(vp.get("clientHeight") or vp.get("height") or 0)

    notes: list[str] = []
    raw: list[dict] = []
    for node in tree.get("nodes", []):
        if node.get("ignored"):
            continue
        role = (node.get("role") or {}).get("value") or ""
        if role in STRUCTURAL_ROLES:
            continue
        name = ((node.get("name") or {}).get("value") or "").strip()
        value = (node.get("value") or {}).get("value")
        props = {p["name"]: p.get("value", {}).get("value")
                 for p in node.get("properties", [])}

        is_control = role in INTERACTIVE_ROLES
        if not (is_control or props.get("focusable")):
            continue
        # 规则 3「名字和 value 都空的纯装饰元素丢掉」**只适用于靠 focusable
        # 混进来的东西**(没名字的可点击 div 那类)。真正的表单控件即使没标签
        # 也是有意义的 —— 一个裸 checkbox 你照样得能勾它。
        if not is_control and not name and value in (None, ""):
            continue
        if node.get("backendDOMNodeId") is None:
            continue
        raw.append({"role": role, "name": name, "value": value,
                    "backend": node["backendDOMNodeId"],
                    "disabled": bool(props.get("disabled"))})

    boxes = await _boxes(cdp, session_id, [r["backend"] for r in raw])

    elements: list[Element] = []
    for r in raw:
        box = boxes.get(r["backend"])
        if not box:
            continue                      # 量不到 bbox = 看不见(规则 2)
        x, y, w, h = box
        if w <= 0 or h <= 0:
            continue
        in_vp = (vh <= 0) or (y + h > 0 and y < vh)
        if viewport_only and not in_vp:
            continue
        elements.append(Element(
            id=0, role=r["role"], name=r["name"],
            value=r["value"] if r["value"] not in (None, "") else (
                "" if r["role"] in ("textbox", "searchbox", "textarea") else None),
            bbox=(x, y, w, h), in_viewport=in_vp, enabled=not r["disabled"],
            affords=_affords(r["role"]), hint=f"{r['role']}#{r['backend']}",
            backend_node_id=r["backend"]))

    # 默认给整页,但视口内的排前面 —— 让模型知道"这个要滚下去才点得到"(规则 4)
    elements.sort(key=lambda e: (not e.in_viewport, e.bbox[1], e.bbox[0]))
    if len(elements) > max_elements:
        notes.append(f"元素被截断:实际 {len(elements)} 个,返回前 {max_elements} 个")
        elements = elements[:max_elements]
    for n, el in enumerate(elements, start=1):
        el.id = n

    return Snapshot(elements=elements, notes=notes, viewport=(vw, vh))


def _affords(role: str) -> list[str]:
    if role in ("textbox", "searchbox", "textarea", "spinbutton"):
        return ["type", "click", "clear"]
    if role in ("checkbox", "radio", "switch"):
        return ["check", "click"]
    if role in ("combobox", "listbox"):
        return ["select", "click"]
    return ["click", "hover"]


async def _boxes(cdp: CDP, session_id: str,
                 backends: list[int]) -> dict[int, tuple[float, float, float, float]]:
    """批量量 bbox。并发发出去 —— 一个个来的话 150 个元素要等半天。"""

    async def one(bid: int):
        try:
            r = await cdp.send("DOM.getBoxModel", {"backendNodeId": bid},
                               session_id=session_id, timeout=5)
        except CDPError:
            return bid, None              # 量不到就是看不见,不是错误
        q = r.get("model", {}).get("border") or []
        if len(q) < 8:
            return bid, None
        xs, ys = q[0::2], q[1::2]
        return bid, (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    out: dict[int, tuple[float, float, float, float]] = {}
    for bid, box in await asyncio.gather(*(one(b) for b in backends)):
        if box:
            out[bid] = box
    return out


# ---------------------------------------------------------------------------
# 定位
# ---------------------------------------------------------------------------

#: 定位的六种写法(api/act.md §4)。
LOCATOR_KEYS = ("text", "role", "name", "label", "element", "observation", "css",
                "point", "nth")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def match_by_text(elements: list[Element], text: str) -> list[Element]:
    """**匹配语义定死,不猜**(api/act.md §4):

        精确匹配优先 → 没有则子串匹配 → 大小写不敏感

    每一档**只要有命中就停在那一档** —— 不把三档的结果混在一起,
    否则"精确匹配到 1 个"会被子串匹配到的 5 个稀释掉。
    """
    want = _norm(text)
    if not want:
        return []
    names = [(el, _norm(el.name)) for el in elements]

    exact = [el for el, n in names if n == want]
    if exact:
        return exact
    sub = [el for el, n in names if want in n]
    if sub:
        return sub
    lo = want.lower()
    return [el for el, n in names if lo in n.lower()]


def resolve(spec: dict[str, Any], snap: Snapshot,
            *, observation_id: str | None = None) -> Element:
    """把一个定位描述变成唯一一个元素,或者抛 NotFound(带候选)。"""
    if not isinstance(spec, dict) or not any(k in spec for k in LOCATOR_KEYS):
        raise BadRequest(f"看不懂的定位:{spec!r}", code="bad_request")

    # 按编号定位:必须带上是哪次观测的编号
    if "element" in spec:
        obs = spec.get("observation")
        if observation_id is not None and obs is not None and obs != observation_id:
            raise NotFound(
                "这个编号来自另一次观测,页面可能已经变了 —— 重新 observe 一次",
                code="not_found", details={"candidates": [], "stale_observation": obs})
        return snap[int(spec["element"])]

    # css / point 是逃生舱,交给调用方直接执行,这里只做形状检查
    if "css" in spec or "point" in spec:
        raise _Escape(spec)

    if "text" in spec:
        hits = match_by_text(snap.elements, str(spec["text"]))
        what = f"「{spec['text']}」"
    elif "label" in spec:
        # 表单标签找输入框:名字对上,且是能输入的
        hits = [e for e in match_by_text(snap.elements, str(spec["label"]))
                if "type" in e.affords]
        what = f"标签「{spec['label']}」"
    elif "role" in spec or "name" in spec:
        role, name = spec.get("role"), spec.get("name")
        hits = list(snap.elements)
        if role:
            hits = [e for e in hits if e.role == role]
        if name:
            hits = match_by_text(hits, str(name))
        what = f"{role or ''} 「{name or ''}」".strip()
    else:
        raise BadRequest(f"看不懂的定位:{spec!r}", code="bad_request")

    if not hits:
        raise NotFound(f"找不到{what}", code="not_found",
                       details={"candidates": _candidates(snap, spec)})

    nth = spec.get("nth")
    if nth is not None:
        try:
            return hits[int(nth)]
        except (IndexError, ValueError):
            raise NotFound(f"{what} 只有 {len(hits)} 个,要不到第 {nth} 个",
                           code="not_found",
                           details={"candidates": [e.to_json() for e in hits]}) from None

    if len(hits) > 1:
        # **绝不随便挑一个。** 要第几个就加 nth。
        raise NotFound(
            f"{what} 匹配到 {len(hits)} 个,不确定是哪个 —— 加 nth 或换个说法",
            code="not_found", details={"candidates": [e.to_json() for e in hits]})

    el = hits[0]
    if not el.enabled:
        raise NotClickable(f"{what} 找到了,但它是禁用的", code="not_clickable",
                           details={"hit": el.to_json()})
    return el


class _Escape(Exception):
    """css / point 这类逃生舱,不走元素表 —— 由 act 那边直接执行。"""

    def __init__(self, spec: dict[str, Any]) -> None:
        super().__init__("escape hatch")
        self.spec = spec


def _candidates(snap: Snapshot, spec: dict[str, Any], limit: int = 3) -> list[dict]:
    """定位失败时把最像的几个塞回来。

    **这是刻意设计的**:模型有机会自我纠正,排查时也能一眼看出
    是页面变了还是识别错了(api/act.md §2)。
    """
    want = _norm(str(spec.get("text") or spec.get("name") or spec.get("label") or ""))
    if not want:
        return [e.to_json() for e in snap.elements[:limit]]

    def score(el: Element) -> float:
        n = _norm(el.name)
        if not n:
            return 0.0
        lo_n, lo_w = n.lower(), want.lower()
        if lo_w in lo_n or lo_n in lo_w:
            return 0.9 + min(len(lo_w), len(lo_n)) / max(len(lo_w), len(lo_n)) / 10
        common = len(set(lo_w) & set(lo_n))
        return common / max(len(set(lo_w)), 1) * 0.5

    # **哪怕一个都不像,也要给几个。** 空候选等于什么都没告诉调用方;
    # 给几个页面上真实存在的名字,至少能看出"页面不是我以为的那个"。
    ranked = sorted(snap.elements, key=score, reverse=True)
    return [e.to_json() for e in ranked[:limit]]
