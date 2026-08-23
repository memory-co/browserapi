"""webmuxd —— tmux + ttyd,只是 pane 里渲染的不是 tty 字符,是浏览器像素。

三个对象,一层套一层(docs/v1/sdk/README.md §1):

    web  = Webmuxd()                                   # 管理实例,空壳
    sess = web.session(id="work", port=7900)
    tab  = sess.open("https://example.com")
"""

from webmuxd.api import (  # noqa: F401
    ActResult, Session, Tab, Webmuxd,
)
from webmuxd.exceptions import (  # noqa: F401
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

#: **版本号只有这一处。** pyproject.toml 用 `dynamic = ["version"]` 读它
#: (setuptools 静态解析这行,不 import 这个包)。
#:
#: 0.5.0 发版时踩过一次:两处各写一份,只改了 pyproject,装出来的包
#: `webmuxd info` 报的是上一版的号 —— 而且只有在**干净 venv 里装完**才看得出来。
__version__ = "0.16.0"
__all__ = ["__version__", "Webmuxd", "Session", "Tab", "ActResult"] + [
    "WebmuxdError", "ActionError", "PlatformError", "UsageError",
    "NotFound", "NotClickable", "Timeout", "NavFailed", "TabGone",
    "Busy", "BusyHuman", "ChromeGone", "SessionDead", "RuntimeUnavailable",
    "PortInUse", "BadRequest", "BlockedURL", "ReadOnly", "SessionExists",
    "SessionNotFound",
]
