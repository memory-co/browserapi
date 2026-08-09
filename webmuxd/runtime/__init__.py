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
    """默认 runtime。**docker 探到了就是 container**,否则退到本机跑。

    这不是配置,是从"这台机器有什么"推出来的 —— 记录里只有事实,
    没有"你想用哪个"这种键。
    """
    from webmuxd import env
    if env.get("docker"):
        return "container"
    rec = env.load()
    if rec is not None:
        return "process"                 # 探过了,没探到 docker
    return DEFAULT


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
    if env.get("docker"):
        # container 那条信记录(**docker 在不在是机器的事实**);
        # 另外两条本来就是现探的,便宜
        return {"container": True, "process": ProcessRuntime().available()[0],
                "remote": True}
    out = {}
    for name, make in _MAKERS.items():
        try:
            out[name] = make().available()[0]
        except Exception:
            out[name] = False
    return out


__all__ = ["get", "detect", "default", "DEFAULT", "Handle", "Runtime",
           "ContainerRuntime", "ProcessRuntime", "RemoteRuntime"]
