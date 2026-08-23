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
    "Size",
    "Element", "Snapshot", "Ref", "RefTable",
    "ActionResult", "PageDigest",
    "TabInfo",
    "ViewMode", "JPG", "VNC", "DOM", "MODES",
    "canon", "describe", "label", "needs_headed", "available_in", "mode_choices",
    "FrameHeader", "Quality",
    "Hello", "Cast", "Meta", "QualityChanged", "ModeInfo", "ModeError",
    "CursorChanged",
    "SessionInfo", "SessionRow", "Pending", "PackageFamily",
    "LogEntry", "LOG_KINDS", "Download", "Locator",
    "MachineFacts", "BrowserFact", "XpraFact", "RrwebFact", "FACTS_VERSION",
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


# ---------------------------------------------------------------------------
# 元素
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

    #: `@e1` —— **跨命令活着的编号**,由 [`RefTable`](#RefTable) 发。
    #: 只有走过 `snapshot` 的元素才有;`act` 内部自己抓的那份是空的。
    ref: str = ""

    #: 只有服务端有 —— 它是 CDP 的句柄,**不上线**。
    backend_node_id: int | None = None
    #: 只有 SDK 有 —— 这个元素是哪次观测里的。
    observation: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "role": self.role, "name": self.name, "value": self.value,
            "bbox": [round(v, 1) for v in self.bbox],
            "in_viewport": self.in_viewport, "enabled": self.enabled,
            "affords": self.affords, "hint": self.hint, "ref": self.ref,
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
            ref=d.get("ref", ""), observation=observation)

    def as_line(self) -> str:
        """紧凑表示的一行。**有 ref 就用 `@e1`,没有才退回 `[1]`** ——
        前者跨命令可用,后者只在这一次里成立。"""
        head = f"@{self.ref}" if self.ref else f"[{self.id}]"
        line = f"{head:5} {self.role:9} \"{self.name}\""
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
        d = {"id": self.id, "role": self.role, "name": self.name, "hint": self.hint}
        if self.ref:
            d["ref"] = self.ref
        return d

    def __repr__(self) -> str:
        return f'<[{self.id}] {self.role} "{self.name}">'


def _not_found(what: str, elements: list[Element]) -> NotFound:
    return NotFound(what, code="not_found",
                    details={"candidates": [e.brief() for e in elements[:3]]})


@dataclass
class Snapshot:
    """一次元素快照 —— **`act` 定位用的,不是一个读的口子**。

    一批动作共用同一份:同一次 `/api/act` 里的几步说的是同一个页面状态。
    但**编号不跨批**,所以没有"按编号定位"([locate.resolve](locate.py))。"""

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

    def to_json(self) -> dict[str, Any]:
        return {"elements": [e.to_json() for e in self.elements],
                "notes": self.notes, "filter_version": self.filter_version,
                "viewport": self.viewport.to_json()}

    @classmethod
    def from_json(cls, d: dict) -> "Snapshot":
        return cls(elements=[Element.from_json(e) for e in d.get("elements") or []],
                   notes=d.get("notes") or [],
                   filter_version=int(d.get("filter_version") or 0),
                   viewport=Size.from_json(d.get("viewport")))


# ---------------------------------------------------------------------------
# 跨命令的元素编号
# ---------------------------------------------------------------------------

@dataclass
class Ref:
    """`@e1` 指着的那一个节点。"""

    id: str
    #: 哪个 tab 上的。**换了 tab 就不认** —— 同一个号在两个页面上
    #: 指着两个东西,是最难查的一类错。
    tab: str
    #: CDP 的句柄。**不上线**,和 `Element.backend_node_id` 同一个东西。
    backend_node_id: int
    #: **哪一份文档**(`loaderId`)。页面一换就全作废 —— 见 `RefTable` 的说明。
    doc: str = ""
    role: str = ""
    name: str = ""


@dataclass
class RefTable:
    """一个 session 的 `@e1` 表 —— **`snapshot` 发号,`click @e1` 认号**。

    **号只增不重用。** 第二次 `snapshot` 从 `@e13` 接着发,不从 `@e1` 重来:

        snapshot  →  @e1 … @e12
        click @e5 →  页面变了
        snapshot  →  @e13 … @e20      ← 不是又一批 @e1

    重用是省事,但它把"拿着过期的号去点"从一个**报错**变成了一次
    **点错东西**。而点错浏览器比敲错终端贵 ——
    这是 [`locate`](locate.py) 开头那两条里的第二条。

    代价是号会一直涨。**这个代价是对的**:号是从 `snapshot` 的输出里
    抄来的,没人需要去猜下一个号是几。
    """

    by_id: dict[str, Ref] = field(default_factory=dict)
    next_n: int = 1

    def assign(self, elements: list[Element], tab: str, doc: str = "") -> None:
        """给一批元素发号,顺手写回 `el.ref`。`doc` 是当时那份文档的 `loaderId`。"""
        for el in elements:
            if el.backend_node_id is None:
                continue
            rid = f"e{self.next_n}"
            self.next_n += 1
            el.ref = rid
            self.by_id[rid] = Ref(rid, tab, el.backend_node_id, doc, el.role, el.name)

    def get(self, ref: str, tab: str, doc: str | None = None) -> Ref:
        """认号。**四种失败分开说**,因为要做的事不一样。"""
        rid = ref[1:] if ref.startswith("@") else ref
        got = self.by_id.get(rid)
        if got is None:
            if not self.by_id:
                raise NotFound(
                    f"@{rid} 不认识 —— 这个 session 还没 snapshot 过",
                    code="not_found", details={"ref": rid})
            raise NotFound(
                f"@{rid} 不认识 —— 现在发到 @e{self.next_n - 1},"
                f"重新 snapshot 一次",
                code="not_found", details={"ref": rid})
        if got.tab != tab:
            raise NotFound(
                f"@{rid} 是 {got.tab} 上的号,不是这个 tab 的",
                code="not_found", details={"ref": rid, "tab": got.tab})
        if doc is not None and got.doc != doc:
            # **这一条是最要紧的,而且它差点没有。**
            #
            # 原来只验"那个节点还在不在"(`DOM.getBoxModel` 拿不拿得到)。
            # 不够 —— **Chromium 会把 backendNodeId 复用给新文档里的节点**,
            # 于是导航之后拿旧号去点,`getBoxModel` 照样成功,**点中的是
            # 另一个东西,而且不报错**。实测撞到过:百度首页上的 `@e13`
            # 在搜索结果页上点成功了,点中的是结果页那个搜索框。
            #
            # 页面一换,这个 session 上所有旧号一律作废。
            raise NotFound(
                f"@{rid}(那时是 {got.role} 「{got.name}」)是上一个页面上的号"
                f" —— 页面换过了,重新 snapshot 一次",
                code="not_found", details={"ref": rid, "stale_doc": True})
        return got

    def forget(self, tab: str) -> None:
        """那个 tab 关了 —— 把它的号清掉。**`next_n` 不回退。**"""
        for rid in [k for k, v in self.by_id.items() if v.tab == tab]:
            del self.by_id[rid]


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
class SessionRow:
    """server 上那一行 session —— **列表页、`webmuxd ls`、`GET /api/sessions`
    用的是同一份**([k §3](../docs/v2/works/k-one-server.md#3-那个口上看到什么))。

    这是**跨语言**的那种:JS 那边 `api.ts` 里有个同名 interface,两边靠
    这个类对齐。`webmuxjs/server/protocol/http.md` 写的就是它。
    """

    id: str
    runtime: str = ""
    tabs: int = 0
    active_tab: str | None = None
    #: 画面走哪条 —— 实现名(`jpg`/`vnc`/`dom`)和界面上那个词
    view: str = JPG
    available: list[str] = field(default_factory=list)
    uptime_s: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        """在那个口上的位置。**只有一处拼它。**"""
        return f"/s/{self.id}/"

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "runtime": self.runtime, "url": self.url,
                "tabs": self.tabs, "active_tab": self.active_tab,
                "view": self.view, "view_label": label(self.view),
                "available": list(self.available),
                "uptime_s": self.uptime_s, "notes": list(self.notes)}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "SessionRow":
        return cls(id=d.get("id", ""), runtime=d.get("runtime", ""),
                   tabs=int(d.get("tabs") or 0), active_tab=d.get("active_tab"),
                   view=d.get("view") or JPG,
                   available=list(d.get("available") or []),
                   uptime_s=int(d.get("uptime_s") or 0),
                   notes=list(d.get("notes") or []))


@dataclass
class SessionInfo:
    """一个起来了的 session —— runtime 产出的那个把柄。

    **没有端口。** 端口在 server 上,一个 server 一个口,session 是它下面
    `/s/<id>/` 的一段路径([k](../docs/v2/works/k-one-server.md))。
    以前一个 session 一个端口,那是 kasm 留下的 —— 它的 web 口不归我们控制,
    换成我们自己产画面之后那条硬约束就没了。

    `kind` 决定 `kill-server` 之后它死不死:`process` 起的浏览器是 server 的
    子进程,跟着死;`remote` 那头的浏览器不归我们,**不动它**。
    """

    kind: str
    id: str
    detail: dict[str, Any] = field(default_factory=dict)

    def path(self) -> str:
        """这个 session 在那个口上的位置。"""
        return f"/s/{self.id}/"


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

# ---------------------------------------------------------------------------
# 这台机器上的事实 —— `~/.webmuxd.json` 那份路径表
# ---------------------------------------------------------------------------

#: 记录格式的版本。**格式变了老记录就当没有** —— 重新探,而不是猜字段。
FACTS_VERSION = 3


@dataclass(frozen=True)
class BrowserFact:
    """用哪个浏览器,以及它是哪来的。"""

    path: str
    version: str = ""
    #: `chrome-for-testing`(我们下的)/ `system`(机器上本来就有的)
    source: str = ""

    def to_json(self) -> dict[str, Any]:
        return _drop_empty({"path": self.path, "version": self.version,
                            "source": self.source})

    @classmethod
    def from_json(cls, d: Any) -> "BrowserFact | None":
        if not isinstance(d, dict) or not d.get("path"):
            return None
        return cls(str(d["path"]), str(d.get("version") or ""),
                   str(d.get("source") or ""))


@dataclass(frozen=True)
class XpraFact:
    """VNC 那条腿:xpra 在哪、**它自己的解释器**是哪个、版本多少。

    解释器单记一条不是学究气:`xpra` 是带 shebang 的脚本,用的是系统的
    Python,而 webmuxd 很可能装在一个 venv 里 —— `python3-pil` 要装进
    **它那个**里面。
    """

    bin: str = ""
    python: str = ""
    version: str = ""
    #: 传给 `--xvfb=` 的那个。**显式钉死,不读发行版配置。**
    vfb: str = "Xvfb"

    def to_json(self) -> dict[str, Any]:
        return _drop_empty({"bin": self.bin, "python": self.python,
                            "version": self.version, "vfb": self.vfb})

    @classmethod
    def from_json(cls, d: Any) -> "XpraFact | None":
        if not isinstance(d, dict) or not d.get("bin"):
            return None
        return cls(str(d["bin"]), str(d.get("python") or ""),
                   str(d.get("version") or ""), str(d.get("vfb") or "Xvfb"))


@dataclass(frozen=True)
class RrwebFact:
    """DOM 那条腿的记录器:版本 + 落在哪。"""

    version: str = ""
    js: str = ""

    def to_json(self) -> dict[str, Any]:
        return _drop_empty({"version": self.version, "js": self.js})

    @classmethod
    def from_json(cls, d: Any) -> "RrwebFact | None":
        if not isinstance(d, dict) or not d.get("js"):
            return None
        return cls(str(d.get("version") or ""), str(d["js"]))


@dataclass
class MachineFacts:
    """`~/.webmuxd.json` —— **这不是配置文件,是机器的事实**。

    `webmuxd install` 探一遍写下来,之后所有命令读它。

    **`None` = 没探到,不是"默认值"。** 这条是整份记录的语义基础:
    键在 = 探到了,键不在 = 没探到 —— 所以 `to_json()` 里
    `None` 的字段一个都不写。写一个猜的值,下次读的人分不清
    那是事实还是兜底([d](../docs/v2/works/d-install.md))。
    """

    browser: BrowserFact | None = None
    xpra: XpraFact | None = None
    rrweb: RrwebFact | None = None
    #: 传给 `--xvfb=` 的那个可执行文件(和 `xpra.vfb` 是两回事:
    #: 这个是绝对路径,那个是名字)。
    xvfb: str = ""
    #: 下下来的中文字体在哪。**今天不写这个键** —— install 不下字体。
    fonts_dir: str = ""
    version: int = FACTS_VERSION
    at: str = ""
    #: 别人写进来的键。**原样留着** —— 不是我们的东西,不该被我们吃掉。
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"version": self.version}
        if self.at:
            out["at"] = self.at
        out.update(self.extra)
        for key, val in (("default_browser", self.browser), ("xpra", self.xpra),
                         ("rrweb", self.rrweb)):
            if val is not None:
                out[key] = val.to_json()
        for key, val in (("xvfb", self.xvfb), ("fonts_dir", self.fonts_dir)):
            if val:
                out[key] = val
        return out

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "MachineFacts":
        known = {"version", "at", "default_browser", "xpra", "rrweb",
                 "xvfb", "fonts_dir"}
        return cls(
            browser=BrowserFact.from_json(d.get("default_browser")),
            xpra=XpraFact.from_json(d.get("xpra")),
            rrweb=RrwebFact.from_json(d.get("rrweb")),
            xvfb=str(d.get("xvfb") or ""),
            fonts_dir=str(d.get("fonts_dir") or ""),
            version=int(d.get("version") or 0), at=str(d.get("at") or ""),
            extra={k: v for k, v in d.items() if k not in known})


def _drop_empty(d: dict[str, Any]) -> dict[str, Any]:
    """**空的不写。** 键在 = 探到了。"""
    return {k: v for k, v in d.items() if v}

# ---------------------------------------------------------------------------
# 下行消息 —— **观看端收到的那六种**
# ---------------------------------------------------------------------------
#
# 这一组是**跨语言**的:JS 那边 `protocol/messages.ts` 里有一一对应的
# interface,而 `webmuxjs/server/protocol/frames.md` §4 写的就是它们。
#
# 上行那张白名单在 `frames.py`(它是**安全边界**,和这些不是一回事):
# 上行是"观看者能表达什么",这里是"我们会告诉观看者什么"。


@dataclass
class Hello:
    """连上来第一条 —— **权限只在这时候说一次**。

    鼠标移动一秒几十个事件,逐个回 403 等于自己 DoS 自己。
    """

    writable: bool
    transport: str
    protocol: int = 28
    w: int = 0
    h: int = 0
    #: 画面那一摊的现状,原样带上(`Screencaster.stats()`)。
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {"type": "hello", "writable": self.writable,
                "protocol": self.protocol, "transport": self.transport,
                **({"w": self.w, "h": self.h} if self.w else {}), **self.extra}


@dataclass
class Cast:
    """开始/重开一轮 —— 尺寸变了、切了 tab、重新 startScreencast。"""

    tab: str | None
    w: int
    h: int
    format: str = "jpeg"
    quality: int = 80
    dsf: float | None = None

    def to_json(self) -> dict[str, Any]:
        out = {"type": "cast", "tab": self.tab, "w": self.w, "h": self.h,
               "format": self.format, "quality": self.quality}
        if self.dsf is not None:
            out["dsf"] = self.dsf
        return out


@dataclass
class Meta:
    """**帧的真实尺寸和 CSS 尺寸不是一回事。**

    `dsf=2` 时 CDP 报 1024×768 而图是 2048×1536 —— 观看端算"有效缩放"
    只信解码出来的那个,这条只是把两边都说出来。
    """

    frame_w: int
    frame_h: int
    css_w: int
    css_h: int

    def to_json(self) -> dict[str, Any]:
        return {"type": "meta", "frame_w": self.frame_w, "frame_h": self.frame_h,
                "css_w": self.css_w, "css_h": self.css_h}


@dataclass
class QualityChanged:
    """降质/抽帧 —— **先降画质再抽帧**([c1](../docs/v2/works/c1-quality.md))。"""

    quality: int
    every_nth: int

    def to_json(self) -> dict[str, Any]:
        return {"type": "quality", "quality": self.quality,
                "every_nth": self.every_nth}


@dataclass
class ModeInfo:
    """现在是哪种画面、能切哪几种。**界面不该自己再写一遍这些字。**

    `why` / `was` 只在真的切过之后才有 —— **切了必须说出来**
    ([c §9.5](../docs/v2/works/c-view.md#95-切了必须说出来)):
    画面变了而人不知道为什么,比画面差本身更糟。
    """

    mode: str
    available: list[str] = field(default_factory=list)
    why: str = ""
    was: str = ""

    @property
    def label(self) -> str:
        return label(self.mode)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mode": self.mode, "label": self.label,
            "available": [m.to_json() for m in mode_choices()
                          if m.name in self.available]}
        if self.why:
            out["why"] = self.why
        if self.was:
            out["was"] = self.was
        return out

    def as_message(self) -> dict[str, Any]:
        return {"type": "mode", **self.to_json()}


@dataclass
class ModeError:
    """切不动 —— **说清为什么、以及怎么才能有**,不静默留在原来那种。"""

    message: str
    hint: str = ""

    def to_json(self) -> dict[str, Any]:
        out = {"type": "mode_error", "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out


@dataclass
class CursorChanged:
    """光标。**值已经过白名单** —— 页面能把它设成任意字符串。"""

    cursor: str

    def to_json(self) -> dict[str, Any]:
        return {"type": "cursor", "cursor": self.cursor}

# ---------------------------------------------------------------------------
# scrollback 里的一行,和那些挡着页面的东西
# ---------------------------------------------------------------------------

#: 日志有哪几类。v1 是三类;v2 多出来的四类是**没有桌面之后**那批原生 UI ——
#: 它们是"页面为什么停住"的唯一解释,不进 scrollback 的话,
#: 现象就只剩"页面一直没变,而且不知道为什么"。
LOG_KINDS = ("action", "tab", "session", "dialog", "download", "file",
             "permission", "auth")


@dataclass
class LogEntry:
    """`log.jsonl` 里的一行 —— **人和 agent 进同一条流,每条标明是谁做的**
    ([i §4](../docs/v2/works/i-agent-surface.md))。

    **`fields` 是刻意留的。** 一条 `action` 和一条 `download` 共同的只有
    上面那几样,剩下的按类不同 —— 把它们全列成字段,等于让这个类跟着
    每一个动词一起长。跨模块要读的是共同那几样,`fields` 是那一类自己的事。
    """

    seq: int
    kind: str
    at: str = ""
    tab: str | None = None
    #: **谁做的** —— `api` / `cli` / `human` / 调用方自己签的名
    user: str = ""
    #: 这一步的思考,调用方写进来的
    note: str = ""
    fields: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"seq": self.seq, "at": self.at, "kind": self.kind}
        for k, v in (("tab", self.tab), ("user", self.user), ("note", self.note)):
            if v:
                out[k] = v
        out.update(self.fields)
        return out

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "LogEntry":
        known = {"seq", "at", "kind", "tab", "user", "note"}
        return cls(seq=int(d.get("seq") or 0), kind=str(d.get("kind") or ""),
                   at=str(d.get("at") or ""), tab=d.get("tab"),
                   user=str(d.get("user") or ""), note=str(d.get("note") or ""),
                   fields={k: v for k, v in d.items() if k not in known})


@dataclass
class Download:
    """一个下载。**它是"页面为什么停住"的一种** —— headless 里没人替你点保存。"""

    id: str
    file: str = ""
    url: str = ""
    bytes: int = 0
    total: int = 0
    #: `pending` / `done` / `canceled`
    state: str = "pending"
    path: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "file": self.file, "url": self.url,
                "bytes": self.bytes, "total": self.total,
                "state": self.state, "path": self.path}


@dataclass(frozen=True)
class Locator:
    """**怎么找到那个元素。**

    以前这个形状在三处各拼一份(`act.py` / `api.py` / `cli.py`),
    而它是**跨 HTTP 的**:SDK 拼出来、服务端解开。三份意味着加一种写法
    要记得改三个地方 —— 而"记得"从来不是一种机制。

    **`ref` 和 `nth` 不是一回事**:`nth` 是"这几个同名的里第几个",
    只在这一次匹配里成立;`ref` 是 [`RefTable`](#RefTable) 发的号,
    跨命令活着,而且**过期了会明确报错,不会指向另一个元素**。
    """

    #: 上一次 `snapshot` 里的编号,写作 `@e1`。**最准的一种** ——
    #: 它指着那一个具体的 DOM 节点,不靠名字去猜。
    ref: str = ""
    #: 可见文字,最常用
    text: str = ""
    role: str = ""
    name: str = ""
    #: 表单标签找输入框
    label: str = ""
    #: 选择器,逃生舱
    css: str = ""
    #: 坐标,最后手段
    point: tuple[float, float] | None = None
    #: 多于一个时要第几个
    nth: int | None = None

    #: 这几个键就是全部。**加一种写法要改这一处,不是三处。**
    KEYS = ("ref", "text", "role", "name", "label", "css", "point", "nth")

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in ("ref", "text", "role", "name", "label", "css"):
            if getattr(self, k):
                out[k] = getattr(self, k)
        if self.point is not None:
            out["point"] = list(self.point)
        if self.nth is not None:
            out["nth"] = self.nth
        return out

    def __bool__(self) -> bool:
        return bool(self.to_json())

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Locator":
        pt = d.get("point")
        return cls(text=str(d.get("text") or ""), role=str(d.get("role") or ""),
                   name=str(d.get("name") or ""), label=str(d.get("label") or ""),
                   css=str(d.get("css") or ""),
                   point=(float(pt[0]), float(pt[1])) if pt else None,
                   nth=int(d["nth"]) if d.get("nth") is not None else None)
