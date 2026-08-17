"""两种 runtime —— **本机起一个,或者你给一个 CDP 端点。**

docs/v2/works/07-runtime.md §1:契约塌成一个 CDP 端点之后,线以下只剩这两种,
而且它们的区别只是"那个端点是我起的还是你给的"。

**容器不在里面**(§2):tmuxd 不会 `docker run` 一个 tmux。要隔离就把 webmuxd
整个放进容器里跑 —— 那是部署决定,不是我们的参数。
"""

from __future__ import annotations

from webmuxd.runtime.base import Handle, Runtime, unavailable  # noqa: F401
from webmuxd.runtime.process import ProcessRuntime
from webmuxd.runtime.remote import RemoteRuntime

_MAKERS = {"process": ProcessRuntime, "remote": RemoteRuntime}

#: **本机起一个就是默认。** v1 选 container 的三个理由里,"用户不用装浏览器"
#: 被 `webmuxd install` 接走了,"有画面"被 CDP 接走了,只剩隔离 ——
#: 而隔离不是我们的活(works/07 §5)。
DEFAULT = "process"


def default() -> str:
    return DEFAULT


def get(name: str = DEFAULT) -> Runtime:
    try:
        return _MAKERS[name]()
    except KeyError:
        raise unavailable(name, f"没有 {name!r} 这种 runtime",
                          f"只有 {', '.join(_MAKERS)}"
                          "(容器那条 v2 去掉了,见 docs/v2/works/07 §2)") from None


def detect() -> dict[str, bool]:
    """哪些能用。`remote` 永远能用(端点是你给的),`process` 看有没有浏览器。"""
    out = {}
    for name, make in _MAKERS.items():
        try:
            out[name] = make().available()[0]
        except Exception:
            out[name] = False
    return out


__all__ = ["get", "detect", "default", "DEFAULT", "Handle", "Runtime",
           "ProcessRuntime", "RemoteRuntime"]
