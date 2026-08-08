"""异常树 —— docs/v1/sdk/README.md §5。

**异常是原生表达,错误码是它的序列化。** `.candidates` 在这儿是属性,
到了 HTTP 只能塞进 `details`。

三个基类就是给调用方的分诊表:

    ActionError    这一步没做成,你能自愈 —— 换个写法或重试
    PlatformError  这个 session 出事了 —— 该告警,别盲目重试
    UsageError     你代码写错了 —— 重试多少次都一样
"""

from __future__ import annotations

from typing import Any


class WebmuxdError(Exception):
    """所有 webmuxd 异常的根。

    每个实例都带 `.code` / `.message` / `.details` / `.http_status`,原样来自响应体 ——
    **新加的错误码即使还没建类,也会以基类形式抛出来,不会变成 KeyError**
    (sdk/README §5)。
    """

    #: 线上错误码。基类没有,子类各自声明。
    code: str | None = None

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or type(self).code
        self.details: dict[str, Any] = details or {}
        self.http_status = http_status

    def __str__(self) -> str:
        return f"{self.code}: {self.message}" if self.code else self.message

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"{type(self).__name__}({self.message!r}, code={self.code!r})"


class ActionError(WebmuxdError):
    """这一步没做成,但 session 是好的。换个写法或重试。"""


class PlatformError(WebmuxdError):
    """这个 session 出事了。该告警,别盲目重试。"""


class UsageError(WebmuxdError):
    """调用方写错了。重试多少次都一样。"""


# --------------------------------------------------------------------------
# ActionError —— 可自愈
# --------------------------------------------------------------------------

class NotFound(ActionError):
    """定位不到元素。**带候选** —— 把它喂回模型就能自我纠正。"""

    code = "not_found"

    @property
    def candidates(self) -> list[dict[str, Any]]:
        """最像的几个,`{role, name, hint}`。定位失败时永远给,不会是 None。"""
        return self.details.get("candidates", [])


class NotClickable(ActionError):
    """找到了,但被遮挡或禁用。等一下重试,或先滚动。"""

    code = "not_clickable"


class Timeout(ActionError):
    """settle 或 wait_for 超时。"""

    code = "timeout"


class NavFailed(ActionError):
    """页面打不开。"""

    code = "nav_failed"

    @property
    def net_error(self) -> str | None:
        """如 `ERR_NAME_NOT_RESOLVED`。"""
        return self.details.get("net_error")


class TabGone(ActionError):
    """tab 没了。

    `.reason` 分得清是**你关的**还是**被挤掉的** —— 后者不是任何人的意图,
    是超了 `WEBMUXD_TAB_MAX` 被 LRU 挤出去的(api/tabs.md §3)。
    """

    code = "tab_gone"

    @property
    def reason(self) -> str | None:
        """`closed` | `evicted` | `crashed`。"""
        return self.details.get("reason")

    @property
    def final_url(self) -> str | None:
        """被挤掉时它停在哪 —— 想恢复就拿这个重开。"""
        return self.details.get("final_url")


class _Retryable(ActionError):
    @property
    def retry_after_ms(self) -> int | None:
        return self.details.get("retry_after_ms")


class Busy(_Retryable):
    """已有动作在跑。一个 session 同时只跑一个动作,不排队、不交错。"""

    code = "busy"

    @property
    def dialog(self) -> dict[str, Any] | None:
        """被弹窗挡住时,告诉你是哪个弹窗(api/tabs.md §3)。"""
        return self.details.get("dialog")


class BusyHuman(_Retryable):
    """人正在 VNC 里操作,API 让路中。**lib 不自动等** —— 要等你自己等。"""

    code = "busy_human"


# --------------------------------------------------------------------------
# PlatformError —— 该告警
# --------------------------------------------------------------------------

class ChromeGone(PlatformError):
    """Chromium 崩了(会自动重拉)。tab 全丢,之前的句柄全废。"""

    code = "chrome_gone"


class SessionDead(PlatformError):
    """记录还在但探活失败。"""

    code = "session_dead"


class RuntimeUnavailable(PlatformError):
    """这个 runtime 起不来。**不静默降级** —— 那等于把页面偷偷挪到别处跑。"""

    code = "runtime_unavailable"

    @property
    def hint(self) -> str | None:
        """如"改用 runtime=process,但那样没有隔离"。"""
        return self.details.get("hint")


class PortInUse(PlatformError):
    """你给的端口被占了。

    端口是**部署决定**的,我们不自动换一个 —— 换了你的配置就和实际对不上
    (sdk/manager.md §1)。
    """

    code = "port_in_use"


# --------------------------------------------------------------------------
# UsageError —— 改代码
# --------------------------------------------------------------------------

class BadRequest(UsageError):
    code = "bad_request"


class BlockedURL(UsageError):
    """特权页面(`chrome://` 那一类)。

    不是做不到,是不该做:那些设置该在容器启动参数里配,不该让代码跑去点
    (api/tabs.md §3)。
    """

    code = "blocked_url"


class ReadOnly(UsageError):
    """用的是只读 token。"""

    code = "read_only"


class SessionExists(UsageError):
    code = "session_exists"


class SessionNotFound(UsageError):
    code = "session_not_found"


# --------------------------------------------------------------------------
# 线上 → 异常
# --------------------------------------------------------------------------

_BY_CODE: dict[str, type[WebmuxdError]] = {
    cls.code: cls
    for cls in (
        NotFound, NotClickable, Timeout, NavFailed, TabGone, Busy, BusyHuman,
        ChromeGone, SessionDead, RuntimeUnavailable, PortInUse,
        BadRequest, BlockedURL, ReadOnly, SessionExists, SessionNotFound,
    )
}

# 认不出的码,按 HTTP 状态落到哪个基类。5xx 是平台的事,4xx 是调用方的事。
_FALLBACK_BY_STATUS: tuple[tuple[range, type[WebmuxdError]], ...] = (
    (range(400, 409), UsageError),
    (range(409, 500), ActionError),   # 409/408 这类是"再试试"
    (range(500, 600), PlatformError),
)


def error_class(code: str | None, http_status: int | None = None) -> type[WebmuxdError]:
    """码 → 类。**认不出也不抛 KeyError**,退到一个语义最近的基类。"""
    if code and code in _BY_CODE:
        return _BY_CODE[code]
    if http_status is not None:
        for span, cls in _FALLBACK_BY_STATUS:
            if http_status in span:
                return cls
    return WebmuxdError


def from_response(body: Any, http_status: int | None = None) -> WebmuxdError:
    """把 `{"error": {code, message, details}}` 变成异常实例。

    响应体不成形状时也要给出个像样的异常 —— 调用方拿到的不该是 `TypeError`。
    """
    err: dict[str, Any] = {}
    if isinstance(body, dict):
        raw = body.get("error")
        if isinstance(raw, dict):
            err = raw
        elif isinstance(raw, str):
            err = {"code": raw}

    code = err.get("code")
    message = err.get("message") or (f"HTTP {http_status}" if http_status else "unknown error")
    details = err.get("details")
    if not isinstance(details, dict):
        details = {}

    cls = error_class(code, http_status)
    return cls(message, code=code, details=details, http_status=http_status)


def raise_for_response(body: Any, http_status: int | None = None) -> None:
    """有 error 就抛,没有就返回。"""
    if isinstance(body, dict) and body.get("error"):
        raise from_response(body, http_status)
