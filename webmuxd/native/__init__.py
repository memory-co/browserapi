"""没有桌面之后 —— 把六类原生 UI 用 CDP 收回来。

docs/v2/works/06-no-desktop.md。**这是 v2 唯一的真实工作量。**

v1 里这批东西是"看不见但仍然阻塞",还有桌面兜底;v2 里它们**根本不会渲染**,
所以 CDP 拦截是唯一路径 —— 没有二义性,行为可测。

| 类 | 谁管 | 排期 |
| --- | --- | --- |
| JS 对话框 | [`dialogs`](dialogs.py) | **必须** —— 不做任何 `confirm` 都让页面永久卡住 |
| 下载 | [`downloads`](downloads.py) | **必须** —— 不做点了下载什么都不发生 |
| 文件选择 | [`files`](files.py) | **必须** —— 不做上传类流程完全走不通 |
| Basic 认证 | [`auth`](auth.py) | 应该 —— **默认不开**,理由见那个文件 |
| 权限 | [`permissions`](permissions.py) | 应该 —— 默认拒绝本来就是安全的默认 |
| PDF / 内置查看器 | 走下载 | headless 没有内置查看器 |

三条共同的规矩在 [`base`](base.py):不替用户决定、有超时且超时不静默、
内置页面要能画它们。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from webmuxd.native.auth import BasicAuth
from webmuxd.native.dialogs import Dialogs
from webmuxd.native.downloads import Downloads
from webmuxd.native.files import FileChooser
from webmuxd.native.permissions import Permissions

if TYPE_CHECKING:                                    # pragma: no cover
    from webmuxd.serve.session import Session

__all__ = ["Natives", "Dialogs", "Downloads", "FileChooser", "BasicAuth",
           "Permissions"]


class Natives:
    """一个 session 一份。`Session` 只跟它打交道,不认识下面五个。"""

    def __init__(self, session: "Session") -> None:
        self.dialogs = Dialogs(session)
        self.downloads = Downloads(session)
        self.files = FileChooser(session)
        self.auth = BasicAuth(session)
        self.permissions = Permissions(session)

    async def attach(self) -> None:
        self.dialogs.attach()
        self.files.attach()
        self.auth.attach()
        await self.downloads.attach()
        await self.permissions.attach()

    async def attach_target(self, session_id: str) -> None:
        """每接一个新 target 都要走一遍的那些(Page 域的开关不是浏览器级的)。"""
        await self.files.enable_for(session_id)
        await self.auth.enable_for(session_id)

    def pending_json(self) -> dict[str, Any]:
        """**挡着页面的东西一次给全** —— 内置页面和上层 UI 都靠它开局对齐。"""
        return {"dialogs": self.dialogs.list_json(),
                "file_choosers": self.files.list_json(),
                "downloads": self.downloads.list_json(),
                "permissions": self.permissions.list_json(),
                "auth": {"on": self.auth.on,
                         "origins": sorted(k or "*" for k in self.auth.creds)}}
