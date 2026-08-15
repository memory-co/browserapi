"""session 登记簿 —— docs/v1/works/05-server-session-runtime.md §6。

CLI 是一次性的命令,`webmuxd new` 和 `webmuxd ls` 是两个进程,
所以得有个地方记着"起过哪些"。

**文件只是线索,`alive()` 才是真相。** 每次列都现场探活,不读缓存 ——
容器可能被 `docker rm` 掉了、进程可能被 OOM 杀了,而文件不会自己更新。

> 这是没有常驻 server 时的做法。works/05 里那个"按需自启的 server"
> 还没做,所以 `process` 起的 session **不跟着 CLI 进程死**(它们被
> `start_new_session` 脱开了),要靠 `webmuxd kill` 清。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

from webmuxd import runtime as rt
from webmuxd.runtime.base import Handle


def default_dir(name: str = "default") -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / "webmuxd" / name


class Registry:
    def __init__(self, path: str | Path | None = None, *, name: str = "default") -> None:
        self.dir = Path(path) if path else default_dir(name)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "sessions.json"

    # ---------------------------------------------------------------- 读写

    def _read(self) -> dict[str, dict]:
        try:
            return json.loads(self.file.read_text() or "{}")
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict[str, dict]) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        tmp.replace(self.file)              # 原子替换,别让半个文件被读到

    def put(self, handle: Handle, **extra: Any) -> None:
        data = self._read()
        detail = {k: v for k, v in handle.detail.items() if not k.startswith("_")}
        data[handle.id] = {"id": handle.id, "runtime": handle.kind,
                           "api_port": handle.api_port, "view_port": handle.view_port,
                           "detail": detail, **extra}
        self._write(data)

    def forget(self, id: str) -> None:
        data = self._read()
        if data.pop(id, None) is not None:
            self._write(data)

    def get(self, id: str) -> dict | None:
        return self._read().get(id)

    def handle(self, id: str) -> Handle | None:
        row = self.get(id)
        if not row:
            return None
        return Handle(row["runtime"], row["id"], row["api_port"],
                      row.get("view_port", 0), dict(row.get("detail") or {}))

    # ---------------------------------------------------------------- 探活

    def list(self) -> list[dict]:
        """**每次都现场探活。** 死掉的照样列出来,标 `dead` ——
        看不到它你就不知道该清理什么。"""
        out = []
        for row in self._read().values():
            h = Handle(row["runtime"], row["id"], row["api_port"],
                       row.get("view_port", 0), dict(row.get("detail") or {}))
            try:
                alive = rt.get(row["runtime"]).alive(h)
            except Exception:
                alive = False
            out.append({**row, "state": "ready" if alive else "dead"})
        return sorted(out, key=lambda r: r["id"])

    def __iter__(self) -> Iterator[dict]:
        return iter(self.list())
