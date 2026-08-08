"""三种 runtime,选一次,之后所有代码都一样。"""

from __future__ import annotations

from webmuxd.runtime.base import Handle, Runtime, unavailable  # noqa: F401
from webmuxd.runtime.container import ContainerRuntime
from webmuxd.runtime.process import ProcessRuntime
from webmuxd.runtime.remote import RemoteRuntime

_MAKERS = {"container": ContainerRuntime, "process": ProcessRuntime,
           "remote": RemoteRuntime}

DEFAULT = "container"


def get(name: str = DEFAULT) -> Runtime:
    try:
        return _MAKERS[name]()
    except KeyError:
        raise unavailable(name, f"没有 {name!r} 这种 runtime",
                          f"只有 {', '.join(_MAKERS)}") from None


def detect() -> dict[str, bool]:
    """探测哪些能用 —— CLI 靠它给出**准确的**报错提示,而不是猜。"""
    out = {}
    for name, make in _MAKERS.items():
        try:
            out[name] = make().available()[0]
        except Exception:
            out[name] = False
    return out


__all__ = ["get", "detect", "DEFAULT", "Handle", "Runtime",
           "ContainerRuntime", "ProcessRuntime", "RemoteRuntime"]
