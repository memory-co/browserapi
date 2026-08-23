"""日志渲染 —— **CLI 和下载共用这一份。**

两处各写一遍的下场是:哪天改了显示,一处改了另一处没改,
而人拿到的两份"同一个 session 的日志"长得不一样。
"""

from __future__ import annotations

import json
from typing import Any, Iterable


def render(entries: Iterable[dict[str, Any]], *, debug: bool = False) -> str:
    """一条一行(有的两行)。**编号在最左边** —— 它和事件流共用一个计数器,
    报问题时说"第 47 条"比说"大概那个时候"有用得多。
    """
    out: list[str] = []
    for e in entries:
        n = e.get("seq", "")
        at = (e.get("at") or "")[11:23]             # HH:MM:SS.mmm
        head = f"{n:>5} {at}"
        if e.get("note"):
            out.append(f"{head}  💭 {e.get('user','')}:{e['note']}")
        if e.get("kind") == "diag":
            # **诊断:出了什么问题。** 默认只出 warn —— debug 那些量大,
            # 平时是噪音,要看得加 `--debug`。
            if e.get("level") == "debug" and not debug:
                continue
            extra = {k: v for k, v in e.items()
                     if k not in ("seq", "at", "kind", "tab", "user", "note",
                                  "level", "what")}
            out.append(f"{head}  ⚠ {e.get('what','')}"
                       + (f"  {json.dumps(extra, ensure_ascii=False)}" if extra else ""))
            continue
        if e.get("kind") != "action":
            out.append(f"{head}  · {e.get('kind')}: {e.get('event','')} {e.get('tab','')}")
            continue
        mark = "✗" if e.get("ok") is False else ("👤" if e.get("user") == "human" else " ")
        hit = (e.get("hit") or {}).get("name")
        # 键盘那几下的 `point` 永远是 `[0,0]` —— 打出来只是噪音,不打。
        target = e.get("target")
        if str(e.get("action", "")).startswith("key"):
            target = None
        out.append(f"{head}  {mark} {e.get('action')}"
                   + (f" {json.dumps(target, ensure_ascii=False)}" if target else "")
                   + (f" → {hit}" if hit else "")
                   + (f"  {e.get('error')}" if e.get("error") else ""))
        after = e.get("after") or {}
        if after.get("changed"):
            out.append(f"{'':>5} {'':>12}  → {after.get('url','')}  {after['changed']}")
    return "\n".join(out)
