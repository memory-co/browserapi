"""权限 —— 定位 / 通知 / 摄像头 / 剪贴板。

docs/v2/works/06-no-desktop.md §2 里这一类和别的不一样:**CDP 没有"页面请求了
权限"这种事件**,所以拦不下来,也就没有"抛事件等回填"这回事。

能做的是**定策略**:

    Browser.grantPermissions {permissions: []}   →  一律拒绝(默认)
    Browser.grantPermissions {origin, permissions: [...]}  →  显式给

headless 里不弹框、默认就是拒绝,所以**不做也不会卡住页面** ——
§5 里它排在"应该"那一档,理由就是这个。做它是为了另一半:
**要用的时候能给**,而不是"这个功能在 webmuxd 里没有"。
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:                                    # pragma: no cover
    from webmuxd.serve.session import Session

#: CDP 认得的权限名。给错名字它会报错,所以在这儿先挡一道,
#: **报"没有这个权限名"比报一句 CDP 的原文有用**。
KNOWN = frozenset("""
accessibilityEvents audioCapture backgroundSync backgroundFetch
clipboardReadWrite clipboardSanitizedWrite displayCapture durableStorage
flash geolocation idleDetection localFonts midi midiSysex nfc notifications
paymentHandler periodicBackgroundSync protectedMediaIdentifier sensors
storageAccess speakerSelection topLevelStorageAccess videoCapture
videoCapturePanTiltZoom wakeLockScreen wakeLockSystem windowManagement
""".split())


class Permissions:
    kind = "permission"

    def __init__(self, session: "Session") -> None:
        self.session = session
        #: origin → 给过哪些。空 origin 是"所有站点"。
        self.granted: dict[str, list[str]] = {}

    async def attach(self) -> None:
        """**默认全拒。** 空列表就是"一个都不给"。"""
        with contextlib.suppress(Exception):
            await self.session.cdp.send("Browser.grantPermissions",
                                        {"permissions": []})

    async def grant(self, names: list[str], *, origin: str = "",
                    by: str = "api") -> dict[str, Any]:
        bad = [n for n in names if n not in KNOWN]
        if bad:
            from webmuxd.errors import BadRequest
            raise BadRequest(f"没有这些权限名:{', '.join(bad)}",
                             code="bad_request",
                             details={"unknown": bad, "known": sorted(KNOWN)})
        params: dict[str, Any] = {"permissions": list(names)}
        if origin:
            params["origin"] = origin
        await self.session.cdp.send("Browser.grantPermissions", params)
        self.granted[origin] = list(names)
        self.session.log.append("permission", action="grant", by=by,
                                origin=origin or "*", names=list(names))
        self.session._emit("permission.changed",
                           {"origin": origin or "*", "names": list(names)})
        return {"ok": True, "origin": origin or "*", "names": list(names)}

    async def reset(self, *, by: str = "api") -> dict[str, Any]:
        await self.session.cdp.send("Browser.resetPermissions", {})
        await self.attach()                 # 回到"全拒",不是回到浏览器默认
        self.granted.clear()
        self.session.log.append("permission", action="reset", by=by)
        self.session._emit("permission.changed", {"origin": "*", "names": []})
        return {"ok": True, "names": []}

    def list_json(self) -> dict[str, Any]:
        return {"granted": {k or "*": v for k, v in self.granted.items()},
                "default": "deny"}
