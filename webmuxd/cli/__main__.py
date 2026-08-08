"""`webmuxd` 命令行 —— docs/v1/cli/。

照着 tmux 设计。用过 tmux 的人应该不用查文档。

**CLI 是 lib 的一个用户**,和你的代码平级 —— 它自己不实现任何行为,
每条命令就是一次 lib 调用。多出来的只有两样,都是终端才需要的:
**目标解析**(`-t work:购物车` 按标题匹配)和**输出格式化**。

退出码是给脚本用的契约,**不要靠解析输出**(cli/README §6)。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from webmuxd import Webmuxd, runtime as rt
from webmuxd.cli.registry import Registry
from webmuxd.client.session import Session
from webmuxd.client.tab import Tab
from webmuxd.errors import WebmuxdError

# 退出码 → 错误码(cli/README §6)。4/5/6 可重试,7 该告警。
EXIT = {
    "bad_request": 2, "blocked_url": 2,
    "session_not_found": 3, "tab_gone": 3, "session_exists": 3,
    "not_found": 4, "not_clickable": 4,
    "timeout": 5,
    "busy": 6, "busy_human": 6,
    "chrome_gone": 7, "session_dead": 7, "runtime_unavailable": 7,
    "port_in_use": 7,
}


def main(argv: list[str] | None = None) -> int:
    p = _parser()
    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        p.print_help()
        return 2
    try:
        return args.fn(args) or 0
    except WebmuxdError as e:
        print(f"✗ {e.code}: {e.message}", file=sys.stderr)
        for c in (e.details.get("candidates") or [])[:5]:
            print(f"  候选:  {c.get('role','') :8} \"{c.get('name','')}\"",
                  file=sys.stderr)
        if e.details.get("hint"):
            print(f"  {e.details['hint']}", file=sys.stderr)
        return EXIT.get(e.code or "", 1)
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


# ---------------------------------------------------------------------------
# 目标解析 —— `session[:tab]`,**全在客户端做**,服务端只认 tab id
# ---------------------------------------------------------------------------

def _split_target(t: str | None) -> tuple[str | None, str | None]:
    t = t or os.environ.get("WEBMUXD_TARGET") or None
    if not t:
        return None, None
    sid, _, tab = t.partition(":")
    return (sid or None), (tab or None)


def _manager(args: argparse.Namespace) -> Webmuxd:
    return Webmuxd(args.host, token=os.environ.get("WEBMUXD_TOKEN"),
                   user=args.user or os.environ.get("WEBMUXD_USER") or "cli",
                   name=args.socket_name)


def _session(args: argparse.Namespace) -> Session:
    sid, _tab = _split_target(args.target)
    reg = Registry(name=args.socket_name)
    rows = reg.list()
    if sid is None:
        live = [r for r in rows if r["state"] == "ready"]
        if len(live) != 1:
            # **不猜** —— 点错浏览器的代价比敲错终端大(cli/README §2)
            raise WebmuxdError(
                f"有 {len(live)} 个 session,得用 -t 指定" if live
                else "没有在跑的 session", code="session_not_found")
        sid = live[0]["id"]

    row = reg.get(sid)
    if row is None:
        raise WebmuxdError(f"没有叫 {sid!r} 的 session", code="session_not_found")
    return _manager(args).session(id=sid, port=row["api_port"],
                                  vnc_port=row.get("vnc_port") or None)


def _tab(args: argparse.Namespace) -> Tab:
    """`work:2` / `work:t_7` / `work:购物车` —— 后两种都是本地匹配。"""
    sess = _session(args)
    _sid, key = _split_target(args.target)
    if not key:
        t = sess.active
        if t is None:
            raise WebmuxdError("这个 session 一个 tab 都没有", code="tab_gone")
        return t
    if key.isdigit():
        return sess.tab(int(key))
    if key.startswith("t_"):
        return sess.tab(key)
    return sess.tab(title=key)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

def _out(args: argparse.Namespace, payload: Any, text: str = "") -> None:
    """`--json` 吐 API 的**原始响应**,不做格式化 —— 方便和 API 混着用。"""
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    elif text:
        print(text)


def _fmt(template: str, **fields: Any) -> str:
    out = template
    for k, v in fields.items():
        out = out.replace("#{" + k + "}", "" if v is None else str(v))
    return out


# ---------------------------------------------------------------------------
# 会话
# ---------------------------------------------------------------------------

def cmd_new(args: argparse.Namespace) -> int:
    reg = Registry(name=args.socket_name)
    impl = rt.get(args.runtime)
    if reg.get(args.id) and reg.list():
        row = next((r for r in reg.list() if r["id"] == args.id), None)
        if row and row["state"] == "ready":
            # **幂等** —— 同一个 id 再建一次就是接管,不报错(像 tmux new -A -s)
            print(f"{args.id}  →  已经在跑了")
            return 0
        reg.forget(args.id)

    handle = impl.start(args.id, api_port=args.port, vnc_port=args.vnc_port or 0,
                        url=args.url, viewport=args.viewport,
                        volume=args.volume, proxy=args.proxy,
                        endpoint=args.endpoint,
                        token=os.environ.get("WEBMUXD_TOKEN"))
    reg.put(handle)
    _out(args, {"id": args.id, "api_port": handle.api_port,
                "vnc_port": handle.vnc_port},
         f"{args.id}  →  画面 {handle.vnc_url if handle.vnc_port else '(无)'}"
         f"   API {handle.api_url}")
    for note in handle.detail.get("notes") or []:
        print(f"  ⚠ {note}", file=sys.stderr)
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    rows = Registry(name=args.socket_name).list()
    _out(args, {"sessions": rows})
    if args.json:
        return 0
    if not rows:
        print("(没有 session)")
        return 0
    for r in rows:
        ports = f"{r.get('vnc_port') or '-'}/{r['api_port']}"
        tail = "" if r["state"] == "ready" else \
            f"  dead — webmuxd kill -t {r['id']} 清掉"
        print(f"{r['id']:<10} {r['runtime']:<10} {ports:<12} {r['state']}{tail}")
    return 0


def cmd_has(args: argparse.Namespace) -> int:
    """只返回退出码,给脚本用:`webmuxd has -t work || webmuxd new ...`"""
    sid, _ = _split_target(args.target)
    row = next((r for r in Registry(name=args.socket_name).list()
                if r["id"] == sid), None)
    return 0 if row and row["state"] == "ready" else 3


def cmd_kill(args: argparse.Namespace) -> int:
    sid, _ = _split_target(args.target)
    reg = Registry(name=args.socket_name)
    row = reg.get(sid)
    if row is None:
        raise WebmuxdError(f"没有叫 {sid!r} 的 session", code="session_not_found")
    handle = reg.handle(sid)
    impl = rt.get(row["runtime"])
    impl.stop(handle)
    reg.forget(sid)
    note = "(remote session,对面仍在运行)" if row["runtime"] == "remote" else ""
    _out(args, {"id": sid, "removed": True}, f"{sid} 已停掉 {note}".strip())
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    rows = Registry(name=args.socket_name).list()
    info = {"version": "0.1.0", "runtimes": rt.detect(),
            "default_runtime": rt.DEFAULT,
            "sessions": {"total": len(rows),
                         "ready": sum(1 for r in rows if r["state"] == "ready"),
                         "dead": sum(1 for r in rows if r["state"] != "ready")}}
    _out(args, info,
         "\n".join([f"版本      {info['version']}",
                    f"runtime   " + ", ".join(
                        f"{k}{'' if v else '(不可用)'}"
                        for k, v in info["runtimes"].items()),
                    f"session   {info['sessions']['ready']} 在跑,"
                    f"{info['sessions']['dead']} 死了"]))
    return 0


def cmd_attach(args: argparse.Namespace) -> int:
    sid, _ = _split_target(args.target)
    row = Registry(name=args.socket_name).get(sid)
    if not row:
        raise WebmuxdError(f"没有叫 {sid!r} 的 session", code="session_not_found")
    if not row.get("vnc_port"):
        raise WebmuxdError(f"{sid} 没有画面(起它的时候没有 VNC)",
                           code="bad_request")
    url = f"http://127.0.0.1:{row['vnc_port']}"
    print(url)
    if not args.print_only:
        import webbrowser
        webbrowser.open(url)
    return 0


# ---------------------------------------------------------------------------
# tab
# ---------------------------------------------------------------------------

def cmd_tabs(args: argparse.Namespace) -> int:
    sess = _session(args)
    tabs = sess.tabs
    _out(args, {"tabs": [t._row() for t in tabs],
                "active": sess._mirror.active})
    if args.json:
        return 0
    for t in tabs:
        row = t._row()
        if args.format:
            print(_fmt(args.format, tab_id=t.id, tab_index=row.get("index"),
                       tab_title=row.get("title"), tab_url=row.get("url"),
                       tab_active=1 if t.active else "",
                       tab_loading=1 if row.get("loading") else "",
                       session_name=sess.id, tab_count=len(tabs)))
        else:
            print(f"{row.get('index', 0)}: {row.get('title','') :<14} "
                  f"{row.get('url','')}  {'●' if t.active else ''}")
    return 0


def cmd_new_tab(args: argparse.Namespace) -> int:
    sess = _session(args)
    tab = sess.open(args.url or "about:blank", active=not args.no_switch)
    _out(args, tab._row(), f"✓ {tab.id}  {tab.title}")
    return 0


def cmd_select_tab(args: argparse.Namespace) -> int:
    t = _tab(args)
    t.activate()
    _out(args, t._row(), f"✓ 切到 {t.id}")
    return 0


def cmd_kill_tab(args: argparse.Namespace) -> int:
    t = _tab(args)
    r = t.close()
    created = (r or {}).get("created")
    _out(args, r, f"✓ 关掉 {t.id}" +
         (f";只剩它了,已新建 about:blank ({created['id']})" if created else ""))
    return 0


def _nav(verb: str):
    def run(args: argparse.Namespace) -> int:
        t = _tab(args)
        if verb == "goto":
            t.goto(args.url)
        else:
            getattr(t, verb)()
        _out(args, t._row(), f"✓ {verb}  {t.url}")
        return 0
    return run


def cmd_dialog(args: argparse.Namespace) -> int:
    t = _tab(args)
    t.answer(accept=not args.dismiss, text=args.text or "")
    _out(args, {"ok": True}, "✓ 已" + ("取消" if args.dismiss else "确定"))
    return 0


# ---------------------------------------------------------------------------
# 操作
# ---------------------------------------------------------------------------

def _locator(args: argparse.Namespace) -> dict:
    spec: dict[str, Any] = {}
    if getattr(args, "what", None):
        spec["text"] = args.what
    for src, dst in (("role", "role"), ("name", "name"), ("label", "label"),
                     ("css", "css"), ("nth", "nth")):
        v = getattr(args, src, None)
        if v is not None:
            spec[dst] = v
    if getattr(args, "at", None):
        spec["point"] = [float(x) for x in args.at.split(",")]
    return spec


def _do(args: argparse.Namespace, spec: dict) -> int:
    t = _tab(args)
    r = t.act([spec], note=args.note, user=args.user)
    res = r.results[0]
    _out(args, {"results": r.results, "log_from": r.log_from})
    if not res.get("ok"):
        raise WebmuxdError(res.get("message", ""), code=res.get("error"),
                           details={"candidates": res.get("candidates") or []})
    if not args.json:
        hit = res.get("hit") or {}
        print(f"✓ {spec['type']} → {hit.get('role','')} \"{hit.get('name','')}\""
              f"  {res.get('ms',0)}ms")
        after = res.get("after") or {}
        if after.get("changed"):
            print(f"  → {after.get('url','')}   {after['changed']}")
    return 0


def cmd_click(args): return _do(args, {"type": "click", **_locator(args)})
def cmd_key(args): return _do(args, {"type": "key", "key": args.key})


def cmd_type(args: argparse.Namespace) -> int:
    spec = {"type": "type", "text": args.text, **_locator(args)}
    spec.pop("text", None) if False else None
    # `type` 的定位不看 text —— 那是内容(api/act.md §4.1)
    if "text" in spec and getattr(args, "what", None):
        spec["label"] = spec.pop("text")
    spec["text"] = args.text
    return _do(args, spec)


def cmd_scroll(args): return _do(args, {"type": "scroll", "dy": args.dy})


def cmd_wait(args: argparse.Namespace) -> int:
    spec: dict[str, Any] = {"type": "wait_for",
                            "timeout_ms": int(args.timeout * 1000)}
    for k in ("text", "css", "url_contains"):
        v = getattr(args, k, None)
        if v:
            spec[k] = v
    return _do(args, spec)


def cmd_send(args: argparse.Namespace) -> int:
    """逃生舱 —— 直接发动作数组,CLI 没做成子命令的动作都能用它。"""
    actions = json.loads(args.actions)
    if not isinstance(actions, list):
        actions = [actions]
    t = _tab(args)
    r = t.act(actions, note=args.note, user=args.user)
    _out(args, {"results": r.results, "log_from": r.log_from})
    bad = r.failed
    if bad:
        raise WebmuxdError(bad.get("message", ""), code=bad.get("error"),
                           details={"candidates": bad.get("candidates") or []})
    if not args.json:
        print(f"✓ {len(r.results)} 个动作")
    return 0


# ---------------------------------------------------------------------------
# 看
# ---------------------------------------------------------------------------

def cmd_url(args: argparse.Namespace) -> int:
    t = _tab(args)
    _out(args, t._row(), t.url)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    st = _session(args).status()
    _out(args, st,
         f"chrome {'活着' if st['chrome']['alive'] else '没了'}  "
         f"{st['tab_count']} 个 tab  当前 {st['active_tab']}  "
         f"{'忙' if st['busy'] else '闲'}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    t = _tab(args)
    if args.shot:
        t.screenshot(args.shot)
        print(f"✓ 存到 {args.shot}")
    else:
        sys.stdout.write(t.text())
    return 0


def cmd_observe(args: argparse.Namespace) -> int:
    t = _tab(args)
    obs = t.observe()
    if args.shot:
        with open(args.shot, "wb") as fh:
            fh.write(obs.screenshot)
    _out(args, obs._d, obs.as_prompt())
    if not args.json:
        for n in obs.notes:
            print(f"  ⚠ {n}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------

def cmd_log(args: argparse.Namespace) -> int:
    sess = _session(args)
    _sid, key = _split_target(args.target)
    tab_id = _tab(args).id if key else None
    entries = sess.log(limit=args.n, tab=tab_id, kind=args.kind,
                       user=args.log_user,
                       only="failed" if args.failed else None)
    _out(args, {"entries": entries})
    if args.json:
        return 0
    for e in entries:
        at = (e.get("at") or "")[11:19]
        if e.get("note"):
            print(f"{at}  💭 {e.get('user','')}:{e['note']}")
        if e.get("kind") != "action":
            print(f"{at}  · {e.get('kind')}: {e.get('event','')} {e.get('tab','')}")
            continue
        mark = "✗" if e.get("ok") is False else ("👤" if e.get("user") == "human" else " ")
        hit = (e.get("hit") or {}).get("name")
        print(f"{at}  {mark} {e.get('action')} {json.dumps(e.get('target'), ensure_ascii=False)}"
              + (f" → {hit}" if hit else "")
              + (f"  {e.get('error')}" if e.get("error") else ""))
        after = e.get("after") or {}
        if after.get("changed"):
            print(f"          → {after.get('url','')}  {after['changed']}")
    return 0


def cmd_bundle(args: argparse.Namespace) -> int:
    data = _session(args).bundle(args.out)
    print(f"✓ {len(data)} 字节 → {args.out}")
    return 0


# ---------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="webmuxd", description="tmux + ttyd,给浏览器")
    p.add_argument("-H", "--host", default=os.environ.get("WEBMUXD_HOST"),
                   help="远端 server")
    p.add_argument("-L", "--socket-name", default="default", help="换一套独立的登记簿")
    p.add_argument("--json", action="store_true", help="吐 API 的原始响应")
    p.add_argument("--user", default=None, help="操作的署名,进日志")
    p.add_argument("--note", default=None, help="这一步的思考,进日志")
    sub = p.add_subparsers(dest="cmd")

    def add(name: str, fn, target: bool = True, **kw):
        s = sub.add_parser(name, **kw)
        if target:
            s.add_argument("-t", "--target", default=None,
                           help="session[:tab],tab 可以是 index / t_N / 标题")
        s.set_defaults(fn=fn)
        return s

    n = add("new", cmd_new, target=False, help="起一个 session")
    n.add_argument("-s", "--id", required=True)
    n.add_argument("-p", "--port", type=int, required=True, help="API 口,必填")
    n.add_argument("--vnc-port", type=int, default=0, help="画面口")
    n.add_argument("--runtime", default=rt.DEFAULT,
                   choices=["container", "process", "remote"])
    n.add_argument("-u", "--url", default="about:blank")
    n.add_argument("-v", "--viewport", default="1280x800")
    n.add_argument("--volume", default=None)
    n.add_argument("--proxy", default=None)
    n.add_argument("--endpoint", default=None)
    n.add_argument("-d", action="store_true", help="建完不 attach(默认就是)")

    add("ls", cmd_ls, target=False, help="列出 session")
    add("info", cmd_info, target=False, help="server 状态和 runtime 探测")
    add("has", cmd_has, help="只返回退出码,给脚本用")
    add("kill", cmd_kill, help="停掉一个 session")
    a = add("attach", cmd_attach, help="打开画面")
    a.add_argument("-p", "--print-only", action="store_true")

    t = add("tabs", cmd_tabs, help="列出 tab")
    t.add_argument("-F", "--format", default=None, help="#{tab_id} #{tab_url} …")
    nt = add("new-tab", cmd_new_tab, help="新建 tab")
    nt.add_argument("-u", "--url", default=None)
    nt.add_argument("-n", "--no-switch", action="store_true")
    add("select-tab", cmd_select_tab, help="切过去")
    add("kill-tab", cmd_kill_tab, help="关掉")
    g = add("goto", _nav("goto"), help="导航")
    g.add_argument("url")
    for verb in ("back", "forward", "reload", "stop"):
        add(verb, _nav(verb), help=verb)
    d = add("dialog", cmd_dialog, help="回应 alert / confirm / prompt")
    d.add_argument("--dismiss", action="store_true")
    d.add_argument("--text", default=None)

    for name, fn in (("click", cmd_click),):
        c = add(name, fn, help="点一下")
        c.add_argument("what", nargs="?", default=None, help="可见文字")
        c.add_argument("--role"), c.add_argument("--name")
        c.add_argument("--css"), c.add_argument("--at")
        c.add_argument("--nth", type=int, default=None)
    ty = add("type", cmd_type, help="输入")
    ty.add_argument("what", nargs="?", default=None, help="标签")
    ty.add_argument("text")
    ty.add_argument("--label"), ty.add_argument("--css")
    ty.add_argument("--role"), ty.add_argument("--name")
    ty.add_argument("--nth", type=int, default=None), ty.add_argument("--at")
    k = add("key", cmd_key, help="按键")
    k.add_argument("key")
    sc = add("scroll", cmd_scroll, help="滚动")
    sc.add_argument("--dy", type=float, default=400)
    w = add("wait", cmd_wait, help="等条件")
    w.add_argument("--text"), w.add_argument("--css")
    w.add_argument("--url-contains", dest="url_contains")
    w.add_argument("--timeout", type=float, default=10)
    se = add("send", cmd_send, help="逃生舱:原始动作数组")
    se.add_argument("actions")

    add("url", cmd_url, help="当前 URL")
    add("status", cmd_status, help="session 状态")
    cap = add("capture", cmd_capture, help="抓正文或截图")
    cap.add_argument("--text", action="store_true")
    cap.add_argument("--shot", default=None)
    ob = add("observe", cmd_observe, help="元素表")
    ob.add_argument("--shot", default=None)

    lg = add("log", cmd_log, help="操作日志")
    lg.add_argument("-n", type=int, default=50)
    lg.add_argument("--failed", action="store_true")
    lg.add_argument("--kind", default=None, choices=["action", "tab", "session"])
    lg.add_argument("--user", dest="log_user", default=None)
    b = add("bundle", cmd_bundle, help="打包日志和截图")
    b.add_argument("-o", "--out", default="bundle.zip")
    return p


if __name__ == "__main__":
    sys.exit(main())
