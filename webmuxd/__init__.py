"""webmuxd —— tmux + ttyd,只是 pane 里渲染的不是 tty 字符,是浏览器像素。

三个对象,一层套一层(docs/v1/sdk/README.md §1):

    web  = Webmuxd()                                   # 管理实例,空壳
    sess = web.session(id="work", api_port=7900, view_port=8090)
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

__version__ = "0.4.4"
__all__ = ["__version__", "Webmuxd", "Session", "Tab", "ActResult",
           "Observation", "Element"] + [
    "WebmuxdError", "ActionError", "PlatformError", "UsageError",
    "NotFound", "NotClickable", "Timeout", "NavFailed", "TabGone",
    "Busy", "BusyHuman", "ChromeGone", "SessionDead", "RuntimeUnavailable",
    "PortInUse", "BadRequest", "BlockedURL", "ReadOnly", "SessionExists",
    "SessionNotFound",
]
