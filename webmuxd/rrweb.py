"""DOM 那条画面 —— 传 DOM 变更,观看端重排。

对应 [c §5](../docs/v2/works/c-view.md#5-第三条rrweb--它不传像素)。
使用者看到的名字是 **DOM**;记录器用的是 rrweb,这个词只出现在这儿和日志里。

和另外两条的差别只有一条:**它在页面里跑。** 另外两条是从外面看 ——
一条问 Chromium 要图,一条盯着 X 显示。这一条要往页面里注入一个记录器,
所以它多两样事:

1. **注入要挡两道**(`__wm_dom` / 顶层 / http(s))。`addScriptToEvaluateOnNewDocument`
   对**每一个新文档**生效,包括记录器自己造出来的 `about:blank` iframe ——
   被注入的 iframe 又造 iframe,实测每秒新建二十来个,主页面的全量快照直接被饿死。
   **这两道守卫是必须的,不是优化。**
2. **资源要经过我们**。记录器只记 `src`,观看端自己回原站拉的话,
   要登录的站、认 `Referer` 的 CDN 全是破图 —— 实测某视频站一页 30 张图破 25 张。
   所以快照里的地址一律改写成 `/api/res?u=…`,由 sessiond 转发
   ([c §10.2](../docs/v2/works/c-view.md#102-那条连接经过我们))。

**它是纯下行的。** 输入照旧走 `Input.*`,和另外两条一个字不差
([b §1](../docs/v2/works/b-input.md#1-收口在哪))。
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import quote

log = logging.getLogger("webmuxd.dom")

HERE = Path(__file__).parent

#: 记录器的版本。**钉死,不用 `@latest`。**
#: `@latest` 意味着两台机器、两个时间点拿到的可能不是同一份 ——
#: 而记录器和观看端的重放器必须是同一版,对不上的表现是"画面局部不更新"
#: 且不报错。这正是 [c §8.1](../docs/v2/works/c-view.md#81-虚拟显示钉死-xvfb)
#: 那条"同一条命令在两台机器上结果不同"要防的事。
RRWEB_VERSION = "2.1.1"
_BASE = f"https://cdn.jsdelivr.net/npm/rrweb@{RRWEB_VERSION}/dist"
RRWEB_URL = f"{_BASE}/rrweb.umd.cjs"
RRWEB_CSS = f"{_BASE}/style.css"

#: 记录器落在哪。**属于数据,所以是下载来的**,不进包
#: ([d §2](../docs/v2/works/d-install.md#2-每样东西从哪来))——
#: 而"下载"这件事归 `webmuxd install`,不归运行时。
CACHE = Path.home() / ".cache" / "webmuxd" / f"rrweb-{RRWEB_VERSION}"

#: 事件缓冲上限。超了从最近一张全量快照往后留 —— **不能从中间截**,
#: 增量链断在中间等于重放出来的 DOM 从此是错的
#: ([c §5.5](../docs/v2/works/c-view.md#55-背压不能沿用丢旧保新))。
#: **每多少条事件让页面重新出一张全量快照。**
#:
#: rrweb 内置的机制(`checkoutEveryNth`):到点了它自己发一条 Meta + 一张全量快照,
#: 而 Meta 那条在我们这儿的语义就是"从这里重来" —— 之前的全部可以扔。
#: 于是缓冲永远只有"最后一张快照 + 之后的增量",**不需要去历史里找切割点**。
#:
#: 2000 是拿"一张快照多贵"换"缓冲多大"。快照是整棵 DOM 序列化,不便宜;
#: 而一个安静的页面根本不会触发 —— rrweb 只在有事件出来的时候数数。
CHECKOUT_EVERY = 2000

#: **兜底的硬上限。** 快照要是不来(页面卡住、记录器被页面自己的脚本弄坏),
#: 缓冲不能无限涨。到了就整个丢掉重来并**吵一声** ——
#: 重放不一致是难看,server 被一个 tab 拖垮是灾难。
MAX_EVENTS = CHECKOUT_EVERY * 4

#: 快照里这些属性是资源地址。
URL_ATTRS = ("src", "poster", "xlink:href", "data")
#: 这些标签的 `href` 才是资源;`<a href>` 不能动。
HREF_TAGS = ("link", "image", "use")

#: 注进页面的那一段。**只有这一个入口** —— 光标探针是另一件事,不掺在一起。
RECORD_JS = """
(() => {
  if (window.__wm_dom) return;
  if (window.top !== window) return;              // 只在顶层录
  if (!/^https?:$/.test(location.protocol)) return;   // about:blank 不录
  window.__wm_dom = 1;

  // **binding 不活过导航,而这段脚本比服务端补 binding 早。**
  //
  // 实测(docs/v2/issues/dom-binding-不活过导航.md):`Runtime.addBinding`
  // 装的是当前那个执行上下文里的一个函数,一导航就没了;而 document-start
  // 的脚本在新上下文一建好就跑 —— 服务端还来不及补。
  //
  // 以前这儿是 `try { emit(...) } catch (_) {}`:事件被**静默丢掉**,
  // 表现是"DOM 模式画面永远不出来,一条错都没有"。现在攒着等。
  var pend = [], lost = 0, timer = null;

  function flush() {
    var send = window.__wm_dom_emit;
    if (typeof send !== "function") return false;
    if (lost) {
      lost = 0;
      send(JSON.stringify({type: -1, err: "binding 迟迟不来,缓冲丢了一次"}));
    }
    while (pend.length) send(pend.shift());
    return true;
  }

  function emit(s) {
    pend.push(s);
    if (flush()) { if (timer) { clearInterval(timer); timer = null; } return; }
    // **满了就整个丢,不从中间截。** 增量链断在中间,重放出来的 DOM
    // 从此是错的 —— 那比"画面停住"难查得多(c §5.5)。
    if (pend.length > 5000) { pend.length = 0; lost = 1; }
    if (!timer) timer = setInterval(flush, 50);
  }

  // **开关留出来。** 只有"当前那个 tab"该录 —— 后台 tab 录了有两笔损失:
  //
  // 1. **白烧**:页面里序列化、我们这边收,而没有任何人在看它;
  // 2. **是错的**:整个 session 共用一条增量链,后台 tab 的 mutation
  //    会混进当前 tab 的链里(实测:当前页一动不动,6 秒混进来 6 条),
  //    客户端拿它们去改当前那棵树,改出来的是一棵没人见过的树。
  //
  // 停了再开是安全的:rrweb 一开始录就会先出一张**全新的全量快照**,
  // 那正好就是"从快照往下"。停录期间的变化会丢 —— 不要紧,
  // 我们从来不重放历史,DOM 是实时看的那一条腿。
  var stop = null;
  window.__wm_dom_rec = function (on) {
    if (on && !stop) { stop = start(); return 1; }
    if (!on && stop) { try { stop(); } catch (e) {} stop = null; return 0; }
    return stop ? 1 : 0;
  };

  function start() {
  try {
    return rrweb.record({
      emit: function (e) { emit(JSON.stringify(e)); },
      recordCanvas: true,
      // **不录鼠标。** 录了的话重放端会照着画一个自己的指针出来
      // (rrweb 那个 `.replayer-mouse`,20x20,跟着录下来的轨迹走)——
      // 而人自己的光标本来就在那儿,于是**画面上有两个指针**。
      //
      // 从源头关,不是在观看端遮:鼠标是增量事件里最密的一路,
      // 不录就不传,顺带省了那份带宽。
      //
      // `mouseInteraction: false` 连点击和 focus/blur 一起关掉 ——
      // 那些事件我们一样不需要(输入走 `Input.*`,和重放没关系),
      // 而 focus 那几条正是把观看端键盘焦点夺走的那一类。
      sampling: { canvas: 10, mousemove: false, mouseInteraction: false },
      inlineStylesheet: true,
      // **每 __CHECKOUT__ 条重新出一张全量快照。** 服务端那边靠它把缓冲砍干净 ——
      // 见 `CHECKOUT_EVERY`。没有它的话缓冲只能靠"在历史里找一张旧快照",
      // 而一个只在开头有过一次快照的页面(开着不动、之后全是增量)
      // **永远找不到** —— 实测缓冲一路涨,每条新事件都要把三千多条 JSON
      // 重新解析一遍,单核打满,整个 server 的事件循环被堵死。
      checkoutEveryNth: __CHECKOUT__,
    });
  } catch (e) {
    emit(JSON.stringify({type: -1, err: String(e)}));
    return null;
  }
  }
  window.__wm_dom_rec(1);            // 装上就先录着,服务端随后按需关
})()
"""
# **那个数只写一处。** 页面那边和服务端那边说的得是同一个 —— 分开写两遍,
# 改了一处忘了另一处的话,缓冲的行为和注释就对不上了。
RECORD_JS = RECORD_JS.replace("__CHECKOUT__", str(CHECKOUT_EVERY))

BINDING = "__wm_dom_emit"


def paths() -> dict[str, Path]:
    return {"js": CACHE / "rrweb.js", "css": CACHE / "rrweb.css"}


def download(force: bool = False) -> dict[str, str]:
    """下载记录器。**这是 `webmuxd install` 干的活,不是运行时。**

    起 session 的时候现下有两个问题:第一次起会卡在网络上,
    而离线或者 CDN 被挡的机器要到那一刻才知道 —— 而 install 存在的意义
    正是"**一次探清楚,之后不再猜**"([d](../docs/v2/works/d-install.md))。
    """
    import urllib.request
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for name, url in (("js", RRWEB_URL), ("css", RRWEB_CSS)):
        f = paths()[name]
        if force or not f.exists() or f.stat().st_size == 0:
            with urllib.request.urlopen(url, timeout=60) as r:
                body = r.read()
            if len(body) < 1024:
                raise RuntimeError(f"{url} 只回了 {len(body)} 字节,不像是那个文件")
            f.write_bytes(body)
        out[name] = str(f)
    return out


def ready() -> tuple[bool, str]:
    """**探,不下。** 键在=探到了,键不在=没探到 —— 和别的探测一个姿态。"""
    js = paths()["js"]
    if js.exists() and js.stat().st_size > 1024:
        return True, ""
    return False, f"rrweb 记录器还没下(要 {RRWEB_VERSION})"


def _read(name: str) -> bytes:
    f = paths()[name]
    if not f.exists():
        # **不在这儿偷偷下。** 起 session 时卡在网络上、或者离线机器
        # 到这一刻才发现,都比在 install 阶段说清楚差得多。
        raise FileNotFoundError(
            f"DOM 那条画面要的 rrweb {RRWEB_VERSION} 还没下 —— "
            f"跑一下 `webmuxd install`")
    return f.read_bytes()


def recorder_js() -> str:
    return _read("js").decode("utf-8")


def viewer_js() -> bytes:
    """观看端要的那份。**和页面里那份记录器是同一个文件** ——
    两边版本对不上的表现是"画面局部不更新"且不报错,所以只有这一份。"""
    return _read("js")


def viewer_css() -> bytes:
    return _read("css")


def _umd_shield(umd: str) -> str:
    """把 UMD 那一坨包起来跑,**跑的时候先把 `define` / `module` / `exports` 藏掉**。

    rrweb 那个包是 UMD:它先看页面上有没有模块系统,有就把自己交给模块系统,
    **不设全局**。而我们下一段代码要的正是全局那个 `rrweb`。

    起 session 就选 DOM 的时候撞不上 —— 那是 document-start,页面一行都还没跑,
    自然没有 `define`。**中途切过去才会**:那时页面早加载完了。
    百度首页实测 `typeof define === "function"`(它自带 AMD 加载器),
    于是 UMD 走了 AMD 分支,`window.rrweb` 从头到尾是 undefined,
    紧接着记录器报 `ReferenceError: rrweb is not defined`。

    这个错**是喊出来的**(进了服务端日志),但人看到的是:点了 DOM 按钮之后
    **一片空白** —— JPG 那张图藏起来了,DOM 那个 div 里什么都没有。

    藏完要还回去:那是页面自己的加载器,弄坏了页面就废了。UMD 是同步执行的,
    所以 `finally` 里还原是准的。
    """
    return ("(function(){var __d=window.define,__m=window.module,__e=window.exports;"
            "window.define=undefined;window.module=undefined;window.exports=undefined;"
            "try{\n" + umd + "\n}finally{"
            "window.define=__d;window.module=__m;window.exports=__e;}})();")


class DomSource:
    """一个 session 的 DOM 画面。

    `push` 由上层给 —— 它负责把事件发给所有观看者。
    """

    def __init__(self, push: Callable[[dict], Awaitable[None]] | None = None) -> None:
        #: 兼容留着,现在不用 —— 事件走自己的通道,不搭在 `/channel/cdp` 上。
        self.push = push
        #: 接在 `/channel/rrweb` 上的那些观看者。
        #: **一条数据只该有一条路** —— 同时往两条通道发的话,
        #: 客户端会重放两遍,而增量链重放两遍出来的是一棵错的 DOM。
        self.listeners: set[Callable[[dict], Awaitable[None]]] = set()
        self.events: list[str] = []
        #: url -> (mime, 字节)。页面加载过的资源留一份,重放时从这儿出。
        self.res: dict[str, tuple[str, bytes]] = {}
        self.page_url = ""
        #: 写诊断用。**上层塞进来** —— DomSource 自己拿不到 session。
        self.log: Any = None
        self.armed: set[str] = set()
        #: 想让哪个 tab 录。**认这个,不认"现在谁在录"** ——
        #: 后者会被"装上就自己开录"那一下弄乱(见下)。
        self._want: str | None = None
        #: 我们认为**正在录**的那些 tab。
        #:
        #: 记的是"一组"而不是"当前那一个" —— 因为**装上就自己开录了**
        #: (`RECORD_JS` 最后那行 `__wm_dom_rec(1)`)。第一版记的是单个
        #: `_recording`,初值 `None`,于是"它不在录"这个假设从一开始就是错的,
        #: 该停的全被跳过 —— 混流照旧,而且一点声音都没有。
        self._rec: set[str] = set()
        self.bytes = {"events": 0, "res": 0}
        self._pending: dict[str, dict] = {}
        self._cdp: Any = None
        self._sid = ""

    # ------------------------------------------------------------ 装上去

    async def arm(self, cdp: Any, session_id: str) -> None:
        """把记录器挂到这个 target 上。**每个 tab 都要挂,同一个只挂一次。**

        必须在导航之前 —— `addScriptToEvaluateOnNewDocument` 只对之后的文档生效。
        """
        if session_id in self.armed:
            log.info("这个 tab 已经装过了 sid=%s", session_id[:8])
            return
        first = not self.armed
        self._cdp, self._sid = cdp, session_id
        src = _umd_shield(recorder_js()) + "\n;\n" + RECORD_JS
        #   ↑ 那个分号是必须的:UMD 最后一行是 `}))`,后面直接跟 `(() => …)()`
        #     会被解析成"调用上一个表达式的结果",报的是
        #     `(intermediate value)(...) is not a function`,和 rrweb 无关。
        # **Runtime 域要先开。** `bindingCalled` 和 `executionContextCreated`
        # 都只在开着的时候才推 —— 不开的话 addBinding 照样成功、页面里那个函数
        # 照样在,但**页面发出来的东西一条都到不了服务端**,而且不报错。
        await cdp.send("Runtime.enable", {}, session_id=session_id)
        await cdp.send("Runtime.addBinding", {"name": BINDING}, session_id=session_id)
        # **Page 域要先开。** 不开的话 `addScriptToEvaluateOnNewDocument`
        # 有可能被接受却不生效 —— 表现是 binding 在、记录器不在,不报错。
        with contextlib.suppress(Exception):
            await cdp.send("Page.enable", session_id=session_id)
        r = await cdp.send("Page.addScriptToEvaluateOnNewDocument",
                           {"source": src}, session_id=session_id)
        log.debug("注入登记好了 id=%s(%d KB)", r.get("identifier"), len(src) // 1024)
        # **还要给当前这一页补一次。**
        #
        # `addScriptToEvaluateOnNewDocument` 只对**之后**创建的文档生效。
        # 而 attach 常常发生在导航之后 —— 实测登记那一刻 `location.href`
        # 已经是目标页了,于是脚本永远等不到"下一个文档",一条事件都发不出来,
        # **而且全程不报错**(docs/v2/issues/dom-注入登记了但不执行.md)。
        #
        # 不 await:这一下要五秒多(552 KB 的源码要过一遍解析),
        # 挂在 attach 路径上会把开 tab 拖慢五秒。脚本自己有
        # `if (window.__wm_dom) return`,补两次也没事。
        asyncio.create_task(self._inject_now(cdp, session_id, src))
        if first:
            # 事件回调是连接级的,**只挂一次** —— 每个 tab 挂一遍的话,
            # 同一条事件会被处理 N 次,缓冲里全是重复。
            for ev, fn in (("Runtime.bindingCalled", self._on_binding),
                           # **每次导航都要补 binding** —— 它不活过导航
                           ("Runtime.executionContextCreated", self._on_context),
                           ("Network.responseReceived", self._on_resp),
                           ("Network.loadingFinished", self._on_done)):
                cdp.on(ev, fn)
        self.armed.add(session_id)
        self._rec.add(session_id)          # 装上就自己开录了,见 RECORD_JS 末尾
        log.info("DOM 记录器装上了(%d 个 tab)", len(self.armed))

    async def _inject_now(self, cdp: Any, session_id: str, src: str) -> None:
        """给已经加载完的那一页补一次注入。**失败要说出来** ——
        静默失败的表现是"DOM 模式画面永远不出来",和"页面没动"分不清。"""
        try:
            # **binding 要先在。** 它不一定活过导航 —— 实测记录器跑起来了、
            # 而 `window.__wm_dom_emit` 是 undefined,于是 emit 抛进
            # try/catch,事件被静默丢掉:画面永远不出来,一条错都没有。
            # 重复 addBinding 是幂等的,补一次不亏。
            await cdp.send("Runtime.addBinding", {"name": BINDING},
                           session_id=session_id)
            r = await cdp.send("Runtime.evaluate",
                               {"expression": src, "returnByValue": False},
                               session_id=session_id)
        except Exception as e:                    # noqa: BLE001
            log.warning("当前页补注入失败(等下次导航):%s", e)
            self._diag("warn", "记录器补不进当前这一页 —— 要等下次导航",
                       err=str(e)[:200])
            return
        if r.get("exceptionDetails"):
            log.warning("当前页补注入抛了:%s",
                        json.dumps(r["exceptionDetails"], ensure_ascii=False)[:300])
        else:
            log.info("当前页补上记录器了")

    def _on_context(self, _params: dict, sid: str | None) -> None:
        """新文档 = 新执行上下文 = **binding 没了**,补一次。

        `Runtime.addBinding` 装的是当前上下文里的一个函数,导航之后就没了。
        实测:导航前 `typeof window.__wm_dom_emit === "function"`,
        导航后 `undefined` —— 而记录器照跑,只是 emit 全抛进了黑洞
        ([issue](../docs/v2/issues/dom-binding-不活过导航.md))。

        补这一下**必然比页面里那段脚本晚**(它是 document-start 的),
        所以页面那边会先攒着 —— 两边配合才补得上这个洞。
        """
        if sid is None or sid not in self.armed or self._cdp is None:
            return
        asyncio.create_task(self._readd(sid))

    async def _readd(self, sid: str) -> None:
        with contextlib.suppress(Exception):
            await self._cdp.send("Runtime.addBinding", {"name": BINDING},
                                 session_id=sid)

    def note_url(self, url: str) -> None:
        """当前页地址 —— 取资源时要拿它当 `Referer`,不然很多 CDN 直接 403。"""
        if url:
            self.page_url = url

    # -------------------------------------------------------- 页面传出来

    def _on_binding(self, params: dict, _sid: str | None) -> None:
        if params.get("name") != BINDING:
            return
        payload = params.get("payload") or ""
        try:
            kind = json.loads(payload).get("type")
        except ValueError:
            return
        if kind == -1:                            # 页面里抛的,别吞
            log.warning("DOM 记录器出错:%s", payload[:300])
            self._diag("warn", "DOM 记录器在页面里抛了", err=payload[:200])
            return
        payload = self._rewrite(payload)
        if kind == 4:                             # Meta:新的一页,从这里重来
            self.events = [payload]
        else:
            self.events.append(payload)
            if len(self.events) > MAX_EVENTS:
                # **走到这儿说明该来的快照没来。**
                # 正常路径是 `checkoutEveryNth` 让页面重新出一张全量快照,
                # 上面那条 `kind == 4` 就把缓冲清了 —— 根本到不了这里。
                log.warning("DOM 事件缓冲超了 %d 条而快照没来 —— 整个丢掉重来,"
                            "重放会缺一段(页面卡住了?)", MAX_EVENTS)
                self._diag("warn", "DOM 事件缓冲超了而快照没来 —— 丢掉重来,"
                                   "重放会缺一段", cap=MAX_EVENTS)
                self.events = []
                self.bytes["events"] = 0
        self.bytes["events"] += len(payload)
        msg = {"type": "dom", "e": payload}
        for fn in list(self.listeners):
            asyncio.create_task(fn(msg))

    # ------------------------------------------------- 资源:一律经过我们

    def _rw(self, url: str) -> str:
        if not url or not url.startswith(("http://", "https://")):
            return url                            # data: / blob: / 相对地址不动
        # **相对地址,前面没有斜杠。**
        #
        # 转发那条路由是 `/s/{sid}/api/res`,而这儿原来写的是根路径
        # `/api/res` —— 于是**每一个**资源都 404。实测一个百度首页 25 个
        # 资源请求,**0 成功、25 个 404**:CSS、字体、图片全没了。
        #
        # 而它看起来只是"页面有点丑":重放出来的是一棵**没有样式的**真 DOM,
        # 结构对、文字全、节点数也对 —— **按节点数或文字判的断言全是绿的**。
        #
        # 不写死 `/s/{sid}` 是因为 `Session` 上根本没有 id(它在注册表里)。
        # 相对地址靠重放文档自己的 base 解析,而那就是观看页 `…/s/{sid}/`。
        return f"api/res?u={quote(url, safe='')}"

    def _rw_css(self, css: str) -> str:
        return re.sub(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)",
                      lambda m: f"url({self._rw(m.group(1))})", css)

    def _rw_node(self, n: Any) -> None:
        """**按结构走,不用正则扫整串** —— 正则会误伤正文里长得像地址的文字。"""
        if isinstance(n, list):
            for x in n:
                self._rw_node(x)
            return
        if not isinstance(n, dict):
            return
        a = n.get("attributes")
        if isinstance(a, dict):
            tag = (n.get("tagName") or "").lower()
            for k in URL_ATTRS:
                if isinstance(a.get(k), str):
                    a[k] = self._rw(a[k])
            if tag in HREF_TAGS and isinstance(a.get("href"), str):
                a["href"] = self._rw(a["href"])
            if isinstance(a.get("srcset"), str):
                a["srcset"] = ", ".join(
                    " ".join([self._rw(p.split(" ")[0])] + p.split(" ")[1:])
                    for p in (x.strip() for x in a["srcset"].split(",")) if p)
            for k in ("style", "_cssText"):
                if isinstance(a.get(k), str):
                    a[k] = self._rw_css(a[k])
        for k in ("childNodes", "adds", "node", "texts", "removes"):
            v = n.get(k)
            if isinstance(v, (list, dict)):
                self._rw_node(v)

    def _rewrite(self, payload: str) -> str:
        try:
            e = json.loads(payload)
        except ValueError:
            return payload
        self._rw_node(e.get("data"))
        return json.dumps(e, ensure_ascii=False)

    def _on_resp(self, params: dict, _sid: str | None) -> None:
        if params.get("type") in ("Image", "Media", "Font", "Stylesheet", "Other"):
            r = params.get("response") or {}
            self._pending[params["requestId"]] = {"url": r.get("url", ""),
                                                  "mime": r.get("mimeType", "")}

    def _on_done(self, params: dict, _sid: str | None) -> None:
        info = self._pending.pop(params.get("requestId", ""), None)
        if info and info["url"] and info["url"] not in self.res:
            asyncio.create_task(self._grab(params["requestId"], info))

    async def _grab(self, rid: str, info: dict) -> None:
        """趁浏览器还留着的时候把响应体收下来。收不到不算错 —— `fetch` 会兜底。"""
        try:
            r = await self._cdp.send("Network.getResponseBody",
                                     {"requestId": rid}, session_id=self._sid)
        except Exception:                         # noqa: BLE001
            return
        body = r.get("body") or ""
        raw = base64.b64decode(body) if r.get("base64Encoded") else body.encode()
        if len(raw) <= 8 * 1024 * 1024:
            self.res[info["url"]] = (info["mime"] or "application/octet-stream", raw)
            self.bytes["res"] += len(raw)

    async def fetch(self, url: str) -> tuple[str, bytes] | None:
        """手上没有就去上游取一份。**带 `Referer` 和 UA** ——
        不带的话很多 CDN 直接 403,而那正是"让观看端自己回原站拿"靠不住的原因。
        """
        hit = self.res.get(url)
        if hit:
            return hit
        try:
            import aiohttp
            headers = {"User-Agent": UA}
            if self.page_url:
                headers["Referer"] = self.page_url
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.get(url, headers=headers) as r:
                    if r.status >= 400:
                        return None
                    body = await r.read()
                    if len(body) > 8 * 1024 * 1024:
                        return None
                    mime = r.headers.get("Content-Type", "application/octet-stream")
        except Exception:                         # noqa: BLE001
            return None
        self.res[url] = (mime, body)
        self.bytes["res"] += len(body)
        return self.res[url]

    # ------------------------------------------------------------- 状态

    def snapshot_for_new_viewer(self) -> list[str]:
        """新来的观看者要从最近一张全量快照接上,不能从半路接。"""
        return list(self.events)

    def _diag(self, level: str, what: str, **fields: Any) -> None:
        """记进这个 session 自己那条流(有的话)。"""
        if self.log is not None:
            with contextlib.suppress(Exception):
                self.log.diag(level, what, **fields)

    async def only_record(self, cdp: Any, session_id: str | None) -> None:
        """**只让这一个 tab 录,别的全停;而且让它重新出一张全量快照。**

        为什么只录一个:整个 session 共用一条增量链,同时录两个 tab 是**错的**,
        不只是费 —— 后台 tab 的 mutation 会混进当前 tab 的链里
        (实测:当前页一动不动,6 秒混进来 6 条),客户端拿它们去改当前那棵树。

        为什么要重开:换 tab = 换一条链,旧链上的增量对新页面是废的,所以缓冲要清。
        **而清了就必须补一张新快照** —— 不然这一刻连上来的观看端拿到的是空的,
        画面永远出不来(第一版就漏了这一步:静态页切回去之后,缓冲空着,
        而页面再没有新事件,于是那条腿静悄悄地死了)。

        重开是安全的:rrweb 一开始录就先出一张全新的全量快照,那正好是
        "从快照往下"。停录期间的变化会丢 —— 不要紧,我们从来不重放历史。
        """
        if session_id == self._want:
            return                                # 已经是这个状态了
        self._want = session_id
        for sid in list(self._rec):               # 全停,包括目标那个
            with contextlib.suppress(Exception):
                await cdp.send("Runtime.evaluate",
                               {"expression": "window.__wm_dom_rec && window.__wm_dom_rec(0)"},
                               session_id=sid)
        self._rec.clear()
        # **先清缓冲再开录** —— 反过来的话新那张快照会被后清的那一下抹掉。
        self.events = []
        self.bytes["events"] = 0
        if session_id is not None:
            with contextlib.suppress(Exception):
                await cdp.send("Runtime.evaluate",
                               {"expression": "window.__wm_dom_rec && window.__wm_dom_rec(1)"},
                               session_id=session_id)
            self._rec.add(session_id)

    def stats(self) -> dict:
        return {"events": len(self.events), "bytes": dict(self.bytes),
                "resources": len(self.res), "listeners": len(self.listeners),
                "armed": len(self.armed), "recording": len(self._rec)}


UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
