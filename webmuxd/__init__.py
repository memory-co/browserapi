"""webmuxd —— tmux + ttyd,只是 pane 里渲染的不是 tty 字符,是浏览器像素。

三个对象,一层套一层(docs/v1/sdk/README.md §1):

    web  = Webmuxd()                                   # 管理实例,空壳
    sess = web.session(id="work", port=7900)
    tab  = sess.open("https://example.com")
"""

from webmuxd.client import (  # noqa: F401
    Webmuxd, Session, Tab, ActResult, Observation, Element,
)
from webmuxd.errors import (  # noqa: F401
    WebmuxdError,
    ActionError,
    PlatformError,
    UsageError,
    NotFound,
    NotClickable,
    Timeout,
    NavFailed,
    TabGone,
    Busy,
    BusyHuman,
    ChromeGone,
    SessionDead,
    RuntimeUnavailable,
    PortInUse,
    BadRequest,
    BlockedURL,
    ReadOnly,
    SessionExists,
    SessionNotFound,
)

#: **和 pyproject.toml 保持一致。** 0.5.0 发版前忘了改这里,装出来的包
#: `webmuxd info` 会报上一版的号 —— 两处都得动。
__version__ = "0.5.0"
__all__ = ["__version__", "Webmuxd", "Session", "Tab", "ActResult",
           "Observation", "Element"] + [
    "WebmuxdError", "ActionError", "PlatformError", "UsageError",
    "NotFound", "NotClickable", "Timeout", "NavFailed", "TabGone",
    "Busy", "BusyHuman", "ChromeGone", "SessionDead", "RuntimeUnavailable",
    "PortInUse", "BadRequest", "BlockedURL", "ReadOnly", "SessionExists",
    "SessionNotFound",
]
