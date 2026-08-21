"""**所有跨过边界的数据,在这儿定义一次。**

判据只有一条:**它会不会跨过一条边界。** 跨 HTTP、跨 WS、跨进程、跨语言的,
都在这儿;只在一个模块里活着的,不在
([j §3.1](../docs/v2/works/j-layout.md#31-modelspy所有跨边界的数据在这儿定义一次))。

三条规矩:

1. **只有数据,没有行为。** 序列化和校验可以有;一旦它开始 import `cdp.py`,
   它就不再是模型层了
2. **不 import 本项目任何东西**(除 `exceptions`)—— 保证它永远在最底下
3. **凡是出现在 HTTP / WS 上的形状,必须在这儿定义一次**,别处只 `import`

最容易混的那条区分:**数据叫 `TabInfo`,能操作的那个叫 `Tab`。**
后者带着 `.click()`、通过 HTTP 干活,住在 `api.py`;它**持有** `TabInfo`,
不重新定义一份 —— 对应 requests 里 `Session` 和 `Response` 的关系。

> 这个文件存在的理由是**一个概念一处定义**。在它之前,同一个 tab 记录
> 服务端一份、SDK 一份,同一个观测服务端一个 dataclass、SDK 一个 dict 包装类,
> 改一个字段要记得改另一边 —— 而"记得"从来不是一种机制。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from webmuxd.exceptions import NotFound

__all__ = [
    "Size", "Scroll", "PageInfo",
    "Element", "Snapshot", "Observation",
    "ActionResult", "PageDigest",
    "TabInfo",
    "ViewMode", "JPG", "VNC", "DOM", "MODES",
    "canon", "describe", "label", "needs_headed", "available_in", "mode_choices",
    "FrameHeader", "Quality",
    "SessionInfo", "Pending", "PackageFamily",
]


# ---------------------------------------------------------------------------
# 页面上的尺寸
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Size:
    w: int = 0
    h: int = 0

    def to_json(self) -> dict[str, int]:
        return {"w": self.w, "h": self.h}

    @classmethod
    def from_json(cls, d: Any) -> "Size":
        d = d or {}
        return cls(int(d.get("w") or 0), int(d.get("h") or 0))

    def __bool__(self) -> bool:
        return bool(self.w and self.h)

    def __iter__(self):
        return iter((self.w, self.h))

    def __eq__(self, other: object) -> bool:
        """**和一对数比得上。** 这东西本来就是"宽高"两个数,
        调用方写 `o.viewport == (1015, 676)` 是最自然的写法。"""
        if isinstance(other, Size):
            return (self.w, self.h) == (other.w, other.h)
        if isinstance(other, (tuple, list)):
            return (self.w, self.h) == tuple(other)
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.w, self.h))


@dataclass(frozen=True)
class Scroll:
    y: float = 0
    max_y: float = 0

    def to_json(self) -> dict[str, float]:
        return {"y": self.y, "max_y": self.max_y}

    @classmethod
    def from_json(cls, d: Any) -> "Scroll":
        d = d or {}
        return cls(d.get("y") or 0, d.get("max_y") or 0)


@dataclass
class PageInfo:
    """观测里"页面本身"那一段。

    `screen` 和 `viewport` 是**两个数**,不是一个:观看者一连上来就可能
    remote-resize 改掉桌面分辨率(Xvnc 那边 `-AcceptSetDesktopSize` 开着),
    一变响应式站点就重排、上一次观测的坐标作废。**两个都带出来**,
    调用方才能发现"地动了"。
    """

    url: str = ""
    title: str = ""
    loading: bool = False
    scroll: Scroll = field(default_factory=Scroll)
    viewport: Size = field(default_factory=Size)
    screen: Size = field(default_factory=Size)

    def to_json(self) -> dict[str, Any]:
        return {"url": self.url, "title": self.title, "loading": self.loading,
                "scroll": self.scroll.to_json(),
                "viewport": self.viewport.to_json(),
                "screen": self.screen.to_json()}

    @classmethod
    def from_json(cls, d: Any) -> "PageInfo":
        d = d or {}
        return cls(url=d.get("url", ""), title=d.get("title", ""),
                   loading=bool(d.get("loading")),
                   scroll=Scroll.from_json(d.get("scroll")),
                   viewport=Size.from_json(d.get("viewport")),
                   screen=Size.from_json(d.get("screen")))


# ---------------------------------------------------------------------------
# 元素与观测
# ---------------------------------------------------------------------------

@dataclass
class Element:
    """一个能被定位到的东西。

    `id` 是**这次观测里的编号**,不跨观测稳定 —— 所以按编号定位时要带上
    `observation` id,页面变了就抛 NotFound,而不是点到编号相同的另一个东西。
    """

    id: int
    role: str = ""
    name: str = ""
    value: str | None = None
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    in_viewport: bool = True
    enabled: bool = True
    affords: list[str] = field(default_factory=list)
    hint: str = ""

    #: 只有服务端有 —— 它是 CDP 的句柄,**不上线**。
    backend_node_id: int | None = None
    #: 只有 SDK 有 —— 这个元素是哪次观测里的。
    observation: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "role": self.role, "name": self.name, "value": self.value,
            "bbox": [round(v, 1) for v in self.bbox],
            "in_viewport": self.in_viewport, "enabled": self.enabled,
            "affords": self.affords, "hint": self.hint,
        }

    @classmethod
    def from_json(cls, d: dict, observation: str = "") -> "Element":
        return cls(
            id=d["id"], role=d.get("role", ""), name=d.get("name", ""),
            value=d.get("value"),
            bbox=tuple(d.get("bbox") or (0, 0, 0, 0)),   # type: ignore[arg-type]
            in_viewport=bool(d.get("in_viewport", True)),
            enabled=bool(d.get("enabled", True)),
            affords=d.get("affords") or [], hint=d.get("hint", ""),
            observation=observation)

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

    def brief(self) -> dict[str, Any]:
        """报错里列候选用的那几个字段。"""
        return {"id": self.id, "role": self.role, "name": self.name, "hint": self.hint}

    def __repr__(self) -> str:
        return f'<[{self.id}] {self.role} "{self.name}">'


def _not_found(what: str, elements: list[Element]) -> NotFound:
    return NotFound(what, code="not_found",
                    details={"candidates": [e.brief() for e in elements[:3]]})


@dataclass
class Snapshot:
    """一次元素快照。observe 和 act 共用同一份 ——
    **定位和给模型看的必须是同一套编号。**"""

    elements: list[Element] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    filter_version: int = 0
    viewport: Size = field(default_factory=Size)

    def __getitem__(self, n: int) -> Element:
        for el in self.elements:
            if el.id == n:
                return el
        raise _not_found(f"这次观测里没有 [{n}]", self.elements)

    def __iter__(self):
        return iter(self.elements)

    def __len__(self) -> int:
        return len(self.elements)

    def as_prompt(self) -> str:
        return "\n".join(e.as_line() for e in self.elements)


@dataclass
class Observation:
    """一次观测。

    `id` 是给按编号定位用的 —— 页面变了就该抛,而不是点到编号相同的另一个东西。

    **服务端和 SDK 是同一个类。** 差别只在两个字段谁填:服务端填
    `screenshot` / `plain_screenshot` 的字节,SDK 填 `shot_url` / `plain_url`
    的地址,由 `api.py` 那层按需去取。
    """

    id: str = ""
    tab: str | None = None
    at: str = ""
    page: PageInfo = field(default_factory=PageInfo)
    elements: list[Element] = field(default_factory=list)
    text: str = ""
    tabs: list["TabInfo"] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    filter_version: int = 0

    #: 服务端填字节;SDK 填地址,由 `api.Observation` 用到才去取。
    screenshot: bytes = b""
    plain_screenshot: bytes = b""
    shot_url: str = ""
    plain_url: str = ""

    def __getitem__(self, n: int) -> Element:
        for e in self.elements:
            if e.id == n:
                return e
        raise _not_found(f"这次观测里没有 [{n}]", self.elements)

    def __iter__(self):
        return iter(self.elements)

    def __len__(self) -> int:
        return len(self.elements)

    def find(self, *, role: str | None = None, name: str | None = None) -> Element:
        for e in self.elements:
            if (role is None or e.role == role) and (name is None or e.name == name):
                return e
        raise _not_found(f"这次观测里没有 role={role} name={name}", self.elements)

    @property
    def viewport(self) -> Size:
        """页面视口 —— **元素坐标就活在这个尺寸里**。"""
        return self.page.viewport

    @property
    def screen(self) -> Size:
        """桌面分辨率。**它会被"有人打开观看页面"改掉**(见 `PageInfo`)。"""
        return self.page.screen

    def as_prompt(self) -> str:
        """紧凑排版,**纯本地,不请求网络**。直接进 prompt。"""
        out = []
        vw, vh = self.page.viewport
        sw, sh = self.page.screen
        if vw and vh:
            head = f"视口 {vw}x{vh}"
            if sw and sh and (sw, sh) != (vw, vh):
                head += f"(桌面 {sw}x{sh})"
            out.append(head)
        out += [e.as_line() for e in self.elements]
        return "\n".join(out)

    def to_json(self, *, shot_url: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {
            "observation_id": self.id, "tab": self.tab, "at": self.at,
            "page": self.page.to_json(),
            "elements": [e.to_json() for e in self.elements],
            "tabs": [t.to_json() if isinstance(t, TabInfo) else t for t in self.tabs],
            "notes": self.notes,
            "filter_version": self.filter_version,
        }
        if self.text:
            out["text"] = self.text
        if shot_url:
            out["screenshot"] = {
                "url": shot_url, "plain_url": shot_url + "?annotate=false",
                "w": self.page.viewport.w or None,
                "h": self.page.viewport.h or None,
                "format": "webp",
            }
        return out

    @classmethod
    def from_json(cls, d: dict) -> "Observation":
        oid = d.get("observation_id", "")
        shot = d.get("screenshot") or {}
        return cls(
            id=oid, tab=d.get("tab"), at=d.get("at", ""),
            page=PageInfo.from_json(d.get("page")),
            elements=[Element.from_json(e, oid) for e in d.get("elements") or []],
            text=d.get("text", ""),
            tabs=[TabInfo.from_json(t) for t in d.get("tabs") or []],
            #: **要往 prompt 里放。** 它写的是这次观测的盲区;不给模型看,
            #: 模型会把"没看见"当成"不存在",然后自信地做错决定。
            notes=d.get("notes") or [],
            filter_version=d.get("filter_version", 0),
            shot_url=shot.get("url", ""), plain_url=shot.get("plain_url", ""))

    def __repr__(self) -> str:
        return f"<Observation {self.id} {len(self.elements)} 个元素 {self.page.url}>"


# ---------------------------------------------------------------------------
# 动作
# ---------------------------------------------------------------------------

@dataclass
class ActionResult:
    """一个动作的结果。失败的那条带 candidates —— 模型据此自我纠正。"""

    ok: bool
    ms: int
    action: str
    target: dict[str, Any] | None = None
    hit: dict[str, Any] | None = None
    after: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    message: str | None = None
    candidates: list[dict] | None = None
    opaque: bool = False
    value: Any = None                     # extract / js 这类有返回值的

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "ms": self.ms}
        for k in ("hit", "after", "error", "message", "candidates", "value"):
            v = getattr(self, k)
            if v not in (None, {}, []):
                out[k] = v
        if self.opaque:
            out["opaque"] = True
        return out


@dataclass
class PageDigest:
    """页面的一份粗略指纹,只为算出 `after.changed`。"""

    url: str = ""
    lines: tuple[str, ...] = ()
    alerts: tuple[str, ...] = ()
    forms: int = 0


# ---------------------------------------------------------------------------
# tab
# ---------------------------------------------------------------------------

@dataclass
class TabInfo:
    """一个 tab 的记录。**这是数据;能 `.click()` 的那个叫 `Tab`,在 `api.py`。**

    `index` 不在这儿 —— 顺序是 tab 表自己维护的一个列表,
    CDP 没有"把 tab 挪个位置"的命令。
    """

    id: str
    target_id: str = ""
    url: str = ""
    title: str = ""
    loading: bool = False
    security: str = "neutral"
    can_go_back: bool = False
    can_go_forward: bool = False
    favicon: str | None = None
    opener: str | None = None
    reason: str = "api"
    created_at: float = 0.0
    crashed: bool = False
    dialog: dict[str, Any] | None = None

    #: 最后一次被激活或被操作 —— LRU 挤谁看它。
    touched_at: float = 0.0

    #: 只有 SDK 那边有:服务端给的顺序和"当前是哪个"。
    index: int = 0
    active: bool = False

    def to_json(self, *, index: int | None = None,
                active: bool | None = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "index": self.index if index is None else index,
            "active": self.active if active is None else active,
            "url": self.url, "title": self.title, "loading": self.loading,
            "security": self.security,
            "can_go_back": self.can_go_back, "can_go_forward": self.can_go_forward,
            "favicon": f"/api/tabs/{self.id}/favicon" if self.favicon else None,
            "opener": self.opener, "reason": self.reason,
            "created_at": self.created_at, "crashed": self.crashed,
            "dialog": self.dialog,
        }

    @classmethod
    def from_json(cls, d: dict) -> "TabInfo":
        return cls(
            id=d.get("id", ""), url=d.get("url", ""), title=d.get("title", ""),
            loading=bool(d.get("loading")), security=d.get("security", "neutral"),
            can_go_back=bool(d.get("can_go_back")),
            can_go_forward=bool(d.get("can_go_forward")),
            favicon=d.get("favicon"), opener=d.get("opener"),
            reason=d.get("reason", "api"), created_at=d.get("created_at") or 0.0,
            crashed=bool(d.get("crashed")), dialog=d.get("dialog"),
            index=int(d.get("index") or 0), active=bool(d.get("active")))


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------

#: 三种画面模式。**这三个词只在这儿定义一次** —— CLI、API、报错、观看端界面
#: 全从这里取;`screencast` / `xpra` / `rrweb` 只是实现名,不出现在使用者面前
#: ([c §9.1](../docs/v2/works/c-view.md#91-使用者看到的是三个词))。
JPG = "jpg"
VNC = "vnc"
DOM = "dom"

#: 顺序即优先级:能用 VNC 就用 VNC,退而 JPG,再退 DOM。
#: **只在「默认选哪个」时用到** —— 运行时切换永远是人选的,不自动降级。
MODES = (VNC, JPG, DOM)


@dataclass(frozen=True)
class ViewMode:
    name: str
    label: str          #: 界面上那一个词
    blurb: str          #: 一句话体感
    when: str           #: 什么时候选它
    impl: str           #: 实现叫什么 —— 只在日志和代码里出现
    headed: bool        #: 要不要一个真实的 X 显示

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "label": self.label, "blurb": self.blurb,
                "when": self.when, "needs_headed": self.headed}


_MODE_TABLE: dict[str, ViewMode] = {
    JPG: ViewMode(JPG, "JPG", "一张一张的图,什么都显示得出来",
                  "拿不准就用它;有视频、有 canvas 的页面", "screencast", False),
    VNC: ViewMode(VNC, "VNC", "像远程桌面,连续、跟手",
                  "动画、视频、大量滚动", "xpra", True),
    DOM: ViewMode(DOM, "DOM", "传的是网页本身,字最清楚、最省流量",
                  "文字为主的页面;网络差的时候", "rrweb", False),
}

#: 旧名字继续认,但**不再回传给使用者** —— 报错和状态里一律用新词。
_MODE_ALIAS = {"screencast": JPG, "cdp": JPG, "jpeg": JPG,
               "xpra": VNC,
               "rrweb": DOM}


def canon(value: str | None) -> str | None:
    """把使用者给的词归一。**不认识就返回 None**,由调用方去报错 ——
    这里不猜、不兜底(见 `exceptions.py` 里那条"不静默降级")。"""
    if value is None:
        return None
    v = value.strip().lower()
    if v in _MODE_TABLE:
        return v
    return _MODE_ALIAS.get(v)


def describe(name: str) -> ViewMode:
    return _MODE_TABLE[name]


def label(name: str) -> str:
    m = _MODE_TABLE.get(name)
    return m.label if m else name


def needs_headed(name: str) -> bool:
    return _MODE_TABLE[name].headed


def available_in(*, headed: bool, remote: bool = False) -> tuple[str, ...]:
    """这台 session 上**能切到**的模式。

    `remote` 那条只有一个 CDP 端点,够不着对端的 X 显示 ——
    **少一个选项不是降级,是那条路上的全集**
    ([c §13](../docs/v2/works/c-view.md#13-默认走哪条))。
    """
    if remote or not headed:
        return (JPG, DOM)
    return MODES


def mode_choices() -> list[ViewMode]:
    """给 API / 界面用的那张表。**界面不该自己再写一遍这些字。**"""
    return [_MODE_TABLE[k] for k in MODES]


@dataclass(frozen=True)
class FrameHeader:
    """28 字节定长头 —— 图片裸字节前面那一截
    ([e1](../docs/v2/works/e1-wire-format.md))。"""

    cast_session_id: int
    frame_id: int
    target_id: str

    def to_json(self) -> dict[str, Any]:
        return {"cast_session_id": self.cast_session_id,
                "frame_id": self.frame_id, "target_id": self.target_id}


@dataclass(frozen=True)
class Quality:
    """一档画质。`every_nth` 是抽帧 —— 质量到底了之后才动它。"""

    quality: int
    every_nth: int


# ---------------------------------------------------------------------------
# 会话、进程、挡着页面的那些
# ---------------------------------------------------------------------------

@dataclass
class SessionInfo:
    """一个起来了的 session。

    **一个 session 一个端口**,画面和 API 落在同一个上(works/04 §1)。

    `kind` 决定 `kill-server` 之后它死不死:两种 runtime 的 sessiond 都是
    server 的子进程,跟着死;`remote` 那头的浏览器不归我们,**不动它**。
    """

    kind: str
    id: str
    port: int
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def api_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def view_url(self) -> str:
        """**和 API 同一个口。** v1 那个"没有画面就是空字符串"的分支没有了 ——
        画面是我们自己产的,只要 sessiond 活着它就在。"""
        return f"http://127.0.0.1:{self.port}/"


@dataclass
class Pending:
    """一件挡着页面、等人回填的事:对话框 / 下载 / 文件选择 / 权限 / 认证。"""

    id: str
    kind: str
    tab: str | None
    info: dict[str, Any] = field(default_factory=dict)
    at: float = 0.0

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "tab": self.tab,
                "at": self.at, **self.info}


@dataclass(frozen=True)
class PackageFamily:
    """一个发行版家族。**包名是唯一真正的差别**,流程是一样的。"""

    name: str
    #: 装包命令(不含包名)
    install: tuple[str, ...]
    #: headless chrome 缺的那些共享库
    chrome: tuple[str, ...]
    #: xpra 那条画面路要的三样
    xpra: tuple[str, ...]
    #: 中文字体 —— 没有它页面里的中文全是豆腐块
    font: tuple[str, ...]
