"""把 webmuxd 的行为流写成一个 Playwright trace.zip。

**这是原型,不是 webmuxd 的功能。** 设计上它还没定([c §13.4] / [i §6]),
放在 examples/ 里是为了先把「能不能做出来」这件事验掉。

映射(c §13.4 那张表的落地):

    log.jsonl 的一条 action  →  before / input / after 三个事件
    我们在动作边界上拉的快照  →  frame-snapshot
    tab.screenshot()          →  screencast-frame + resources/<名字>

**格式是 Playwright 的内部格式**(packages/trace/src/trace.ts),没有公开规范。
已经踩到一处版本差异:1.62.1 发的字段叫 `sha1`,main 分支的类型定义已改叫
`file` —— 这里两个都写,谁读都认得。
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = 8
HERE = Path(__file__).parent
SNAPSHOT_JS = (HERE / "snapshot.js").read_text(encoding="utf-8")

#: 拉快照那几次 `js` 调用自己也会进日志。真实现里 act.py 内联调用、不落日志,
#: 原型里只能靠这个标记把它们摘掉。
MARK = "__webmuxd_snapshot__"


def _ms(e: dict | str) -> float:
    """取这条动作的毫秒时间戳。

    **优先用 `at_ms`。** `log.jsonl` 的 `at` 只到秒,同一秒里的几条动作会叠在
    一起、在时间轴上看不出先后(README「量到的问题」第一条)。
    实时录的时候我们手上就有毫秒,直接带上,不必受日志格式的限制。
    """
    if isinstance(e, dict):
        if e.get("at_ms"):
            return float(e["at_ms"])
        at = e["at"]
    else:
        at = e
    return datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).timestamp() * 1000


def _title(e: dict) -> str:
    """trace 没有「谁做的」这个字段,所以把它放进标题 —— 这是我们比 trace
    多出来的一样东西(i §3),不能在导出时丢掉。"""
    verb = e.get("action", "?")
    t = e.get("target") or {}
    what = t.get("text") or t.get("label") or t.get("url") or t.get("expression") or ""
    who = e.get("user") or "?"
    return f"[{who}] {verb} {what}".strip()


def _point(e: dict) -> dict | None:
    """`hit.bbox` 是 [x, y, w, h] —— 取中心,回放里就是那个点击光标。"""
    box = ((e.get("hit") or {}).get("bbox"))
    if not box or len(box) != 4:
        return None
    x, y, w, h = box
    return {"x": round(x + w / 2, 2), "y": round(y + h / 2, 2)}


def _snapshot_event(snap: dict, *, name: str, call_id: str,
                    page_id: str, ts: float) -> dict:
    return {"type": "frame-snapshot", "snapshot": {
        "callId": call_id,
        "snapshotName": name,
        "pageId": page_id,
        "frameId": page_id.replace("page@", "frame@"),
        "frameUrl": snap.get("url") or "about:blank",
        "timestamp": ts,
        "collectionTime": 0,
        "doctype": snap.get("doctype") or None,
        "html": snap["html"],
        "resourceOverrides": [],
        "viewport": snap.get("viewport") or {"width": 1024, "height": 768},
        "isMainFrame": True,
    }}


def write_trace(out: str | Path, *, actions: list[dict],
                snapshots: dict[int, dict], shots: dict[int, bytes],
                viewport: dict, title: str = "webmuxd session") -> Path:
    """把 `build_trace()` 的结果落到磁盘。"""
    out = Path(out)
    out.write_bytes(build_trace(actions=actions, snapshots=snapshots, shots=shots,
                                viewport=viewport, title=title))
    return out


def build_trace(*, actions: list[dict], snapshots: dict[int, dict],
                shots: dict[int, bytes], viewport: dict,
                title: str = "webmuxd session") -> bytes:
    """`actions` 是 log.jsonl 里 kind=="action" 的那些行(已按 seq 排好)。

    `snapshots[seq]` = {"before": …, "after": …},`shots[seq]` = 图片字节。
    两者都可以缺 —— 缺了就少一样东西,不影响其余部分能打开。
    """
    if not actions:
        raise ValueError("一条动作都没有,导出来的 trace 里时间轴是空的")

    base = _ms(actions[0])
    events: list[dict] = [{
        "version": VERSION, "type": "context-options", "origin": "library",
        "browserName": "chromium", "platform": "linux",
        "wallTime": base, "monotonicTime": 0.0, "title": title,
        "sdkLanguage": "python",
        "options": {"viewport": viewport, "deviceScaleFactor": 1},
    }]
    files: dict[str, bytes] = {}

    # **时间轴自己往前走。** `at` 只到秒,同一秒里的几条动作会叠在一起,
    # 播放时看不出先后 —— 所以用「上一条的结束时间」兜底,保证严格递增。
    cursor = 0.0
    for e in actions:
        seq = e["seq"]
        call_id = f"call@{seq}"
        page_id = f"page@{e.get('tab', 't_1')}"
        start = max(_ms(e) - base, cursor)
        end = start + float(e.get("ms") or 0)
        cursor = end + 1

        snap = snapshots.get(seq) or {}
        before = {"type": "before", "callId": call_id, "startTime": start,
                  "title": _title(e), "class": "Tab",
                  "method": e.get("action", "?"),
                  "params": e.get("target") or {}, "pageId": page_id}
        if "before" in snap:
            before["beforeSnapshot"] = f"before@{call_id}"
        events.append(before)
        if "before" in snap:
            events.append(_snapshot_event(snap["before"], name=f"before@{call_id}",
                                          call_id=call_id, page_id=page_id, ts=start))

        point = _point(e)
        if point:
            events.append({"type": "input", "callId": call_id, "point": point})

        if seq in shots:
            name = f"{page_id}-{int(base + end)}.png"
            files[f"resources/{name}"] = shots[seq]
            events.append({"type": "screencast-frame", "pageId": page_id,
                           "sha1": name, "file": name,   # 1.62 读 sha1,main 读 file
                           "width": viewport["width"], "height": viewport["height"],
                           "timestamp": end,
                           "frameSwapWallTime": base + end})

        after: dict[str, Any] = {"type": "after", "callId": call_id, "endTime": end}
        if "after" in snap:
            after["afterSnapshot"] = f"after@{call_id}"
        if not e.get("ok", True):
            after["error"] = {"message": e.get("message") or e.get("error") or "失败",
                              "name": e.get("error") or "Error", "stack": ""}
        events.append(after)
        if "after" in snap:
            events.append(_snapshot_event(snap["after"], name=f"after@{call_id}",
                                          call_id=call_id, page_id=page_id, ts=end))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("trace.trace",
                   "\n".join(json.dumps(e, ensure_ascii=False) for e in events))
        z.writestr("trace.network", "")     # 网络还没接,但这个条目必须在
        for name, blob in files.items():
            z.writestr(name, blob)
    return buf.getvalue()


def actions_from_log(entries: list[dict]) -> list[dict]:
    """从 `sess.log()` 的结果里挑出动作,并摘掉原型自己拉快照那几次。"""
    return [e for e in entries
            if e.get("kind") == "action"
            and MARK not in json.dumps(e.get("target") or {}, ensure_ascii=False)]
