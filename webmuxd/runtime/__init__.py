"""三种 runtime,选一次,之后所有代码都一样。"""

from __future__ import annotations

from webmuxd.runtime.base import Handle, Runtime, unavailable  # noqa: F401
from webmuxd.runtime.container import ContainerRuntime
from webmuxd.runtime.process import ProcessRuntime
from webmuxd.runtime.remote import RemoteRuntime

_MAKERS = {"container": ContainerRuntime, "process": ProcessRuntime,
           "remote": RemoteRuntime}

DEFAULT = "container"


def default() -> str:
    """默认 runtime。装过就用记录里那个(它知道 docker 通不通)。"""
    from webmuxd import env
    rec = env.load()
    return (rec or {}).get("default_runtime") or DEFAULT


def get(name: str = DEFAULT) -> Runtime:
    try:
        return _MAKERS[name]()
    except KeyError:
        raise unavailable(name, f"没有 {name!r} 这种 runtime",
                          f"只有 {', '.join(_MAKERS)}") from None


def detect() -> dict[str, bool]:
    """哪些能用。

    **有 `~/.webmuxd.json` 就读记录,没有就现探**(cli/install.md §5)——
    没装过也照常能用,`install` 省的是重复开销,不是"必须先装"。
    """
    from webmuxd import env
    rec = env.load()
    if rec:
        return {k: bool(v.get("ok"))
                for k, v in (rec.get("runtimes") or {}).items()}
    out = {}
    for name, make in _MAKERS.items():
        try:
            out[name] = make().available()[0]
        except Exception:
            out[name] = False
    return out


__all__ = ["get", "detect", "default", "DEFAULT", "Handle", "Runtime",
           "ContainerRuntime", "ProcessRuntime", "RemoteRuntime"]
