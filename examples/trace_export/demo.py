"""跑一个真 session,把它导成 trace.zip。

    python3 examples/trace_export/demo.py            # 写到 ./webmuxd-trace.zip
    npx playwright show-trace webmuxd-trace.zip      # 打开看

做的事:起一个 session → 在一个表单页上点几下(**其中一条故意点不存在的东西**,
用来看失败在回放里长什么样)→ 每条动作的前后各拉一张 DOM 快照、动作后截一张图
→ 全部写成 trace。

**快照是在我们自己的动作边界上拉的** —— 这正是 Playwright 给不出的那一样
(它只认自己的 API 调用,而我们的输入是裸 CDP)。见 c §13.2 / §13.4。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))

from to_trace import MARK, SNAPSHOT_JS, actions_from_log, write_trace  # noqa: E402

from webmuxd import Webmuxd  # noqa: E402

#: **必须 quote。** 裸写 data: URL 时,CSS 里一个 `#334` 就把它从 fragment 处截断了。
_HTML = (
    "<meta charset=utf-8><style>body{font:16px sans-serif;padding:40px}"
    "h1{color:#334}button{padding:6px 14px;margin-right:8px}"
    "input{padding:4px;margin:4px 0}#out{margin-top:16px;color:#a00}</style>"
    "<h1>结算</h1>"
    "<label for=phone>手机号</label><br><input id=phone size=30><br>"
    "<label for=addr>收货地址</label><br><input id=addr size=30><br><br>"
    "<button id=go onclick=\"document.getElementById('out').textContent='订单已提交'\">"
    "提交订单</button><button id=cancel>取消订单</button>"
    "<div id=out></div>"
)
FORM = "data:text/html;charset=utf-8," + quote(_HTML)


def snap(tab) -> dict | None:
    """在动作边界上拉一张全量 DOM 快照。"""
    try:
        raw = tab.js(f"/*{MARK}*/ " + SNAPSHOT_JS)
        return json.loads(raw) if raw else None
    except Exception as exc:                      # 快照失败不该带塌整个导出
        print(f"  ! 快照没拉到:{exc}")
        return None


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "webmuxd-trace.zip")
    web = Webmuxd(user="claudecode")
    sess = web.session(id="trace-demo")
    snapshots: dict[int, dict] = {}
    shots: dict[int, bytes] = {}
    try:
        tab = sess.open(FORM)
        print(f"session 起来了:{sess.view_url}")
        # **session 活得比进程久** —— 同一个 id 再跑一次,日志里还有上一次的。
        # 先记下水位,最后只导这一轮的。
        seen = sess.log(limit=1)
        mark = seen[-1]["seq"] if seen else 0

        def do(label, fn):
            """一次动作 = 前快照 → 动作 → 后快照 + 一张图。**边界由我们定义。**"""
            before = snap(tab)
            r = fn()
            seq = r.log_from
            after = snap(tab)
            if seq is not None:
                snapshots[seq] = {k: v for k, v in
                                  (("before", before), ("after", after)) if v}
                try:
                    shots[seq] = tab.screenshot()
                except Exception:
                    pass
            print(f"  {label}: seq={seq} ok={r.ok}")

        do("填手机号", lambda: tab.type("手机号", "13800000000"))
        do("填地址", lambda: tab.type("收货地址", "上海市杨浦区"))
        do("点提交", lambda: tab.click("提交订单"))
        # **故意失败一条** —— 回放里应该显示成红的。
        # 走 act() 而不是 click():快捷方法失败就抛,这里要的是它落进日志。
        do("点一个不存在的",
           lambda: tab.act([{"type": "click", "text": "根本没有这个按钮"}]))
        do("点取消", lambda: tab.click("取消订单"))

        entries = sess.log(limit=500, after=mark)
        actions = actions_from_log(entries)
        vp = sess.viewport()
        write_trace(out, actions=actions, snapshots=snapshots, shots=shots,
                    viewport={"width": vp.get("width", 1024),
                              "height": vp.get("height", 768)},
                    title="webmuxd · trace-demo")
        print(f"\n写好了:{out}  ({out.stat().st_size} 字节,"
              f"{len(actions)} 条动作,{len(snapshots)} 张快照,{len(shots)} 张图)")
        print(f"打开:npx playwright show-trace {out}")
        return 0
    finally:
        sess.kill()


if __name__ == "__main__":
    raise SystemExit(main())
