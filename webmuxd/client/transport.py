"""HTTP transport —— lib 和 sessiond 之间那一道。

**同步的。** v1 只有同步 API(sdk/README §6):要并发就多开几个 session,
这也是 tmux 的答案。用 stdlib 的 urllib,不给调用方增加依赖。

事件流那条 WS 在 `mirror.py` 里,跑在后台线程 —— 调用方碰不到它。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from webmuxd.errors import ChromeGone, WebmuxdError, from_response


class Transport:
    """一个 session(或管理面)的 base URL + token。"""

    def __init__(self, base: str, *, token: str | None = None,
                 timeout: float = 30.0) -> None:
        self.base = base.rstrip("/")
        self.token = token
        self.timeout = timeout

    # ------------------------------------------------------------------

    def get(self, path: str, **params: Any) -> Any:
        return self._call("GET", path, params=params)

    def get_bytes(self, path: str, **params: Any) -> bytes:
        return self._call("GET", path, params=params, raw=True)

    def post(self, path: str, body: dict | None = None, **params: Any) -> Any:
        return self._call("POST", path, body=body, params=params)

    def delete(self, path: str, **params: Any) -> Any:
        return self._call("DELETE", path, params=params)

    # ------------------------------------------------------------------

    def _call(self, method: str, path: str, *, body: dict | None = None,
              params: dict | None = None, raw: bool = False) -> Any:
        url = self.base + path
        clean = {k: _q(v) for k, v in (params or {}).items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)

        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode()
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = r.read()
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                parsed = json.loads(payload.decode() or "{}")
            except json.JSONDecodeError:
                parsed = {"error": {"message": payload.decode(errors="replace")[:200]}}
            raise from_response(parsed, e.code) from None
        except urllib.error.URLError as e:
            # 连不上 = 那头没了。这是平台级的事,该告警而不是重试动作。
            raise ChromeGone(f"连不上 {self.base}: {e.reason}",
                             code="chrome_gone") from None

        if raw or not ctype.startswith("application/json"):
            return payload
        out = json.loads(payload.decode() or "null")
        if isinstance(out, dict) and out.get("error"):
            raise from_response(out)
        return out

    def alive(self) -> bool:
        try:
            self.get("/api/status")
            return True
        except WebmuxdError:
            return False


def _q(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)
