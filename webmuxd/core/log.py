"""操作日志 —— docs/v1/works/03-log.md 和 docs/v1/api/log.md。

**这是 tmux 的 scrollback,不是归档系统。**

一个 `log.jsonl` 装三类记录,不分 tab 也不分类型 —— 一行一条 JSON,
要哪部分就筛哪部分,jsonl 本来就是给这么用的。
曾经想过按 tab 分文件,但在一万行的量级上筛一遍的成本可以忽略,
而分文件要额外维护一套目录生命周期。

`seq` **和事件流共用一个计数器**,所以拿一条日志的 seq 就能在事件流里
找到它前后发生了什么(works/06 §5)。
"""

from __future__ import annotations

import io
import json
import os
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable, Iterator

#: 满多少条切一刀。**只留上一刀** —— 在线记录永远在 LIMIT ~ 2×LIMIT 之间。
LOG_LIMIT = int(os.environ.get("WEBMUXD_LOG_LIMIT", "5000"))

#: 三类,没有第四类。页面自己的变化(标题变了、loading 变了)**不进日志** ——
#: 没有人"做"它们,那只是同步通知(works/03 §1.2)。
KINDS = ("action", "tab", "session")


class Seq:
    """全局单调的序号。日志和事件流**共用同一个** —— 两边对得齐靠它。"""

    def __init__(self, start: int = 0) -> None:
        self._n = start
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._n += 1
            return self._n

    @property
    def current(self) -> int:
        return self._n


class Log:
    """一个 session 的操作日志。

        log = Log(Path("/data"))
        seq = log.append("action", tab="t_3", action="click", ok=True, ...)
        for e in log.read(limit=50, kind="tab"): ...
    """

    def __init__(self, root: str | Path, *, limit: int = LOG_LIMIT,
                 seq: Seq | None = None) -> None:
        self.root = Path(root)
        self.shots = self.root / "shots"
        self.root.mkdir(parents=True, exist_ok=True)
        self.shots.mkdir(exist_ok=True)
        self._limit = max(1, limit)
        self.seq = seq or Seq(self._recover_seq())
        self._lines = self._count(self._current)
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- 路径

    @property
    def _current(self) -> Path:
        return self.root / "log.jsonl"

    @property
    def _previous(self) -> Path:
        return self.root / "log.1.jsonl"

    def shot_path(self, seq: int) -> Path:
        """截图按 seq 命名 —— 所以切掉一刀时,知道该连哪批图一起删。"""
        return self.shots / f"{seq:06d}.webp"

    # ---------------------------------------------------------------- 写

    def append(self, kind: str, **fields: Any) -> int:
        """写一条,返回它的 seq。

        `at` 不传就用当前时间。**明文不该走到这儿** ——
        凭证在执行层就已经换成掩码了(api/act.md §3.1)。
        """
        if kind not in KINDS:
            raise ValueError(f"没有 {kind!r} 这一类日志,只有 {KINDS}")
        with self._lock:
            seq = self.seq.next()
            entry = {"seq": seq, "at": fields.pop("at", None) or _now(), "kind": kind}
            entry.update({k: v for k, v in fields.items() if v is not None})
            with self._current.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._lines += 1
            if self._lines >= self._limit:
                self._rotate()
            return seq

    def _rotate(self) -> None:
        """切一刀:当前文件改名,开新的,**只留上一刀**。

        被覆盖掉那一刀里的截图一起删 —— 留着图没有对应的记录,
        既占地方又没法解释。
        """
        if self._previous.exists():
            self._drop_shots_of(self._previous)
            self._previous.unlink()
        if self._current.exists():
            self._current.rename(self._previous)
        self._lines = 0

    def _drop_shots_of(self, path: Path) -> None:
        for entry in _iter_jsonl(path):
            seq = entry.get("seq")
            if seq is None:
                continue
            p = self.shot_path(int(seq))
            if p.exists():
                p.unlink()

    # ---------------------------------------------------------------- 读

    def read(
        self,
        *,
        limit: int = 100,
        after: int | None = None,
        only: str | None = None,
        user: str | None = None,
        tab: str | None = None,
        kind: str | None = None,
    ) -> list[dict[str, Any]]:
        """按 seq 顺序给最近的若干条。

        所有筛选都是**过滤**,不是读不同的文件 —— 磁盘上就一个 jsonl
        (works/03 §1.1)。
        """
        if kind is not None and kind not in KINDS:
            raise ValueError(f"没有 {kind!r} 这一类日志")

        def keep(e: dict) -> bool:
            if after is not None and e.get("seq", 0) <= after:
                return False
            if kind is not None and e.get("kind") != kind:
                return False
            if tab is not None and e.get("tab") != tab:
                return False
            if user is not None and e.get("user") != user:
                return False
            if only == "failed" and e.get("ok", True):
                return False
            return True

        out = [e for e in self._all() if keep(e)]
        return out[-limit:] if limit and limit > 0 else out

    def _all(self) -> Iterator[dict[str, Any]]:
        yield from _iter_jsonl(self._previous)
        yield from _iter_jsonl(self._current)

    def count(self) -> int:
        return sum(1 for _ in self._all())

    # ---------------------------------------------------------------- 打包

    def bundle(self, *, tab: str | None = None) -> bytes:
        """日志 + 截图 + 一个离线 HTML,zip 成一份。

        **解开双击就能看,不依赖容器还活着** —— 用来把"它当时干了什么"发给别人。
        """
        entries = self.read(limit=0, tab=tab)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("log.jsonl", "\n".join(
                json.dumps(e, ensure_ascii=False) for e in entries))
            for e in entries:
                p = self.shot_path(int(e["seq"]))
                if p.exists():
                    z.write(p, f"shots/{p.name}")
            z.writestr("index.html", _offline_html(entries))
        return buf.getvalue()

    # ------------------------------------------------------------ 起来时

    def _recover_seq(self) -> int:
        """重启之后接着往下发号 —— seq 不能倒退,否则和历史记录撞车。"""
        top = 0
        for path in (self._previous, self._current):
            for entry in _iter_jsonl(path):
                top = max(top, int(entry.get("seq", 0)))
        return top

    @staticmethod
    def _count(path: Path) -> int:
        return sum(1 for _ in _iter_jsonl(path))


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue          # 半行(写到一半被杀)不该让整份日志读不出来


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def _offline_html(entries: Iterable[dict[str, Any]]) -> str:
    """极简的离线回看页。没有构建系统,没有依赖 —— 双击就开。"""
    rows = []
    for e in entries:
        kind = e.get("kind")
        who = e.get("user") or ""
        note = e.get("note")
        shot = f'<img loading=lazy src="shots/{int(e["seq"]):06d}.webp">' \
            if (e.get("shot") or kind == "action") else ""
        if kind == "action":
            head = f'{e.get("action","")} {json.dumps(e.get("target",""), ensure_ascii=False)}'
            hit = e.get("hit") or {}
            body = f'命中 {hit.get("role","")} 「{hit.get("name","")}」' if hit else ""
            after = (e.get("after") or {}).get("changed") or ""
        else:
            head = f'{kind}: {e.get("event","")} {e.get("tab","")}'
            body = e.get("final_url") or e.get("url") or ""
            after = e.get("reason") or ""
        cls = "bad" if e.get("ok") is False else ("opaque" if e.get("opaque") else "")
        rows.append(
            f'<tr class="{cls}"><td>{e.get("seq")}</td><td>{e.get("at","")}</td>'
            f'<td>{who}</td><td>{_esc(note) if note else ""}</td>'
            f'<td>{_esc(head)}<br><small>{_esc(body)}</small></td>'
            f'<td>{_esc(after)}</td><td>{shot}</td></tr>')
    return f"""<!doctype html><meta charset=utf-8><title>webmuxd 操作日志</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;margin:2rem;max-width:1200px}}
 table{{border-collapse:collapse;width:100%}}
 td{{border-top:1px solid #ddd;padding:.4rem;vertical-align:top}}
 tr.bad td{{background:#fff0f0}} tr.opaque td{{background:#fffbe6}}
 img{{max-width:280px;border:1px solid #ccc}} small{{color:#666}}
</style>
<h1>操作日志 <small>{len(rows)} 条</small></h1>
<table><tr><th>seq<th>时间<th>谁<th>💭<th>做了什么<th>结果<th>截图</tr>
{''.join(rows)}
</table>"""


def _esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
