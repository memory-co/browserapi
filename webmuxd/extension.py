"""**装进被控浏览器的那个扩展** —— 浏览器自己那一层的事归它。

源码在 [`webmuxjs/extension/`](../webmuxjs/extension/),和观看页、
[`sidecar`](sidecar.py) 平级。这儿只管**把它交给 Chromium**。

和 sidecar 的分工,判据只有一条 —— **这件事要不要碰页面**:

| | 跑在哪 | 干什么 |
| --- | --- | --- |
| [`sidecar`](sidecar.py) | **被控页面里** | 改/看页面本身:光标、人在动没在动 |
| 这儿 | **浏览器自己那一层** | 浏览器替我们做的:窗口、tab |

不用碰页面的一律往这边搬。每搬一样,"探针改变了页面环境"那条代价就小一分
([b §6](../docs/v2/works/b-input.md) · [l](../docs/v2/works/l-extension.md))。

**它是 `--load-extension` 装的,所以只有我们自己起的浏览器有。**
`remote` 那条路上的浏览器不归我们起 —— 那条路今天不管
([l §5.2](../docs/v2/works/l-extension.md))。

> **过渡期:两套并存,而且是安全的。** sidecar 里那个 `open-shim` 还在,
> 它先把 features 过滤掉、于是根本不会开出 popup;这边那条搬窗口的
> 就成了空操作。唯一两边不一致的是 `attributionsrc` —— shim 放它过去,
> 这边接得住。**所以并存期间比任何一边单独都严。**
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:                                    # pragma: no cover
    from webmuxd.cdp import CDP

#: 建出来那份的落地处 —— **构建产物,不在 git 里**,和 `_client` / `_sidecar`
#: 一个道理([j §4.3](../docs/v2/works/j-layout.md#43-构建怎么接进-wheel))。
_BUILT = Path(__file__).resolve().parent / "_extension"

#: 开发时的退路:还没往包里拷过就直接读 `npm run build` 的产物。
_DEV = Path(__file__).resolve().parents[1] / "webmuxjs" / "extension" / "dist"


def path() -> Path | None:
    """那个目录在哪。**没有就返回 `None`,不抛。**

    和 `sidecar.source()` 不一样:少了页面里那一段是三样观测一起没,
    必须吵;而少了这个扩展,今天只是 popup 那一条退回 sidecar 的老做法 ——
    **过渡期本来就两套并存**,所以它缺席不是错误。等 sidecar 那半删掉之后,
    这儿要跟着改成"没有就抛"。
    """
    for d in (_BUILT, _DEV):
        if (d / "manifest.json").exists() and (d / "sw.js").exists():
            return d
    return None


def args() -> list[str]:
    """加进 chrome 命令行的那几个。**没建出来就一个都不加。**

    `--load-extension` 只收**目录**,不收文件 —— 这是它和 sidecar
    在打包上唯一的实质差别(那边是一段源码,直接 `evaluate` 就行)。

    **不加 `--disable-extensions-except`**:那会把 Chromium 自带的组件扩展
    一起关掉,而我们没有理由碰它们。profile 是每个 session 一个新的,
    本来也不会有别人的扩展。
    """
    d = path()
    return [f"--load-extension={d}"] if d else []


#: 扩展在自己的 service worker 全局上挂的那个标记(`webmuxjs/extension/src/sw.ts`)。
#:
#: **认它不能靠文件名** —— 浏览器自带的组件扩展里也有叫 `sw.js` 的。
#: 而且 MV3 的 service worker 是**懒启动**的:读得到这个标记意味着它真的
#: 跑起来了,不只是被登记了。
MARK = "__wm_ext"


async def installed(cdp: "CDP") -> dict | None:
    """它装上了吗、跑起来了吗、装了哪几样。**读不到就是 `None`。**

    判据取自浏览器那一侧:attach 到每个 service_worker target,读那个标记。
    拿"我们传了 `--load-extension`"当判据是不行的 —— 传了不等于装上了。
    """
    import contextlib as _c
    import json as _j

    with _c.suppress(Exception):
        r = await cdp.send("Target.getTargets")
        for t in r.get("targetInfos", []):
            if t.get("type") != "service_worker":
                continue
            with _c.suppress(Exception):
                sid = (await cdp.send("Target.attachToTarget",
                                      {"targetId": t["targetId"], "flatten": True}))["sessionId"]
                got = await cdp.send(
                    "Runtime.evaluate",
                    {"expression": f"JSON.stringify(self.{MARK} || null)",
                     "returnByValue": True}, session_id=sid, timeout=5)
                await cdp.send("Target.detachFromTarget", {"sessionId": sid})
                val = (got.get("result") or {}).get("value")
                if val and val != "null":
                    return _j.loads(val)
    return None
