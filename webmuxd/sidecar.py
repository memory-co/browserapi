"""**页面里的那一段** —— 装、以及它和服务端之间那个唯一的口子。

源码在 [`webmuxjs/sidecar/`](../webmuxjs/sidecar/),和观看页(`webmuxjs/client/`)
平级。**这儿只管装,不管写** —— 这一分工是有原因的:

原来那几段 JS 是 Python 里的字符串字面量,散在 `probe.py` 和 `cursor.py` 里,
各自 `addBinding` + `addScriptToEvaluateOnNewDocument` + `evaluate` 走一遍。
四份一样的仪式,就是四次犯同一个错的机会 —— 而那个错犯过两次,
两次的表现都是"什么都没发生,也没有错"(见 `enable()` 的 docstring)。
更要紧的是:**那是全项目唯一一块没有类型检查、没有单元测试的代码,
而它跑在别人的页面里** —— 密码明文那次就是从那儿漏出去的。

搬进 `webmuxjs/` 之后它和观看页共用一套工具链:`tsc` 管类型、`vitest` 管行为、
`vite` 打成一个 IIFE。**装的和测的是同一份产物**,不是同一份产物的两次抄写。

它是**探针,不是垫片**:只看不改。唯一的例外是 `window.open` 的 features ——
那不是改页面行为,是把 popup 收进 tab 表(f §5)。

> 一条硬规矩:**探针不许读表单控件的 `value`。** 密码框上那就是明文。
> 落地在 `webmuxjs/sidecar/src/label.ts`,盯着它的测试在
> `tests/pixels_on_a_wire/`(读的是**建出来那份**,不是源码)。
"""

from __future__ import annotations

import contextlib
from pathlib import Path

from webmuxd.cdp import CDP, CDPError

#: 页面往回说话的那个函数名。**全项目只开这一个 binding。**
#:
#: 必须和 `webmuxjs/sidecar/src/wire.ts` 里的 `BINDING` 一个字不差 ——
#: 不一样的话页面照样调、binding 照样在,**服务端一条都收不到,还不报错**。
#: 所以 `tests/the_layout_holds/` 里有一条盯着这两个字符串。
BINDING = "__webmuxd"

#: 建出来那份的落地处 —— **构建产物,不在 git 里**,和 `_client/` 一个道理
#: ([j §4.3](../docs/v2/works/j-layout.md#43-构建怎么接进-wheel))。
_BUILT = Path(__file__).resolve().parent / "_sidecar" / "sidecar.js"

#: 开发时的退路:还没往包里拷过,就直接读 `npm run build` 的产物。
#: **只是退路,不是等价物** —— 装出来的包里只有 `_BUILT` 那一份。
_DEV = (Path(__file__).resolve().parents[1] / "webmuxjs" / "sidecar"
        / "dist" / "sidecar.js")

_cache: str | None = None


def source() -> str:
    """要注进页面的那一整段。**找不到就报,并说该跑哪一行。**

    不静默返回空串:空串注进去不会报错,而后果是光标永远是箭头、
    人的操作不进流水、前台漂了没人知道 —— 三样功能一起没了,一条错都没有。
    """
    global _cache
    if _cache is not None:
        return _cache
    for p in (_BUILT, _DEV):
        if p.exists():
            _cache = p.read_text(encoding="utf-8")
            return _cache
    raise RuntimeError(
        "页面里那段还没构建:"
        f"{_BUILT} 和 {_DEV} 都不在 —— "
        "在 webmuxjs/sidecar/ 里跑 `npm install && npm run build`")


async def enable(cdp: CDP, session_id: str) -> None:
    """**Runtime 域要先开,而且只这一处开。**

    页面里的东西全靠 `Runtime.addBinding` 往回报,而 `Runtime.bindingCalled`
    **只在这个域开着的时候才推**。不开的话:`addBinding` 照样成功、
    页面里那个函数照样在、页面照样调它 —— **而服务端一条都收不到,还不报错**
    ([issue](../docs/v2/issues/dom-binding-不活过导航.md))。

    这个洞的两半分别咬过一次:DOM 那条画面整个不工作,光标同步在
    JPG/VNC 下整个不工作 —— 两次的表现都是"什么都没发生,也没有错"。
    所以它在**一处**、在装任何东西**之前**。
    """
    with contextlib.suppress(Exception):
        await cdp.send("Runtime.enable", {}, session_id=session_id)
    with contextlib.suppress(Exception):
        await cdp.send("Runtime.addBinding", {"name": BINDING},
                       session_id=session_id)


async def install(cdp: CDP, session_id: str) -> None:
    """装到这个 target 上,**每次导航自动重装**。

    两句缺一不可:`addScriptToEvaluateOnNewDocument` 保证它跑在页面自己的
    第一行脚本**之前**(之后的每个文档);`Runtime.evaluate` 补当前这一个
    —— 已经加载完的那一页不会再触发前者。
    """
    js = source()
    try:
        await cdp.send("Page.addScriptToEvaluateOnNewDocument",
                       {"source": js}, session_id=session_id)
        await cdp.send("Runtime.evaluate", {"expression": js},
                       session_id=session_id)
    except CDPError:
        # 装不上不该让这个 tab 整个用不了 —— 后果是几样观测缺失,
        # 而那几样各自都有别的迹象。**但不该悄悄地缺**:调用方
        # (`sessions.executor_for`)会把它记成一条 diag。
        raise
