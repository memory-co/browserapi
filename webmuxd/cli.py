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
import time
import sys
from pathlib import Path
from typing import Any

from webmuxd import Webmuxd
from webmuxd import models
from webmuxd import processes
from webmuxd import sessions as rt
from webmuxd.api import Session, Tab
from webmuxd.exceptions import WebmuxdError

# 退出码 → 错误码(cli/README §6)。4/5/6 可重试,7 该告警。
EXIT = {
    "bad_request": 2, "blocked_url": 2,
    "session_not_found": 3, "tab_gone": 3, "session_exists": 3,
    "not_found": 4, "not_clickable": 4,
    # **页面打不开是自成一类的下一步** —— 不是"找不到那个元素"(改定位),
    # 而是"那个地址拿不到"(改地址、换 https、看网络)。
    "nav_failed": 8,
    "timeout": 5,
    "busy": 6, "busy_human": 6,
    "chrome_gone": 7, "session_dead": 7, "runtime_unavailable": 7,
    "port_in_use": 7,
}


def main(argv: list[str] | None = None) -> int:
    p = _parser()
    # **位置参数被 `-t` 劈成两段时,argparse 配不上。**
    #
    # `webmuxd get value -t demo @e13` —— "value" 在 `-t` 前面、"@e13" 在后面,
    # argparse 只肯把一个 `nargs="+"` 配给其中**连着的一段**,剩下那个就成了
    # "unrecognized arguments: @e13"。而 `get <种类> <目标>` 这个顺序是照
    # agent-browser 来的,不该为了绕开这个限制去改它。
    #
    # 所以自己收尾:剩下的**不是选项的**那些,接回 `rest` 去。
    # **打错的词在解析之前就接住。**
    #
    # 不把它们注册成子命令,是因为那样它们会跑进 `--help` 的列表,
    # 也会跑进 argparse 那句 "choose from …" —— **看上去像是能用的命令**。
    # 它们不是命令,是路标。
    word = _first_word(list(argv) if argv is not None else sys.argv[1:])
    if word in _WRONG_WORD:
        print(f"✗ bad_request: {_WRONG_WORD[word]}", file=sys.stderr)
        return EXIT["bad_request"]

    args, extra = p.parse_known_args(argv)
    if extra:
        # 打错词的那几个一概不管后面跟了什么 —— `webmuxd start --port 7900`
        # 要的是"它搬去哪了",不是"--port 不认识"。
        stray = [x for x in extra if x.startswith("-")]
        if stray or not hasattr(args, "rest"):
            p.error(f"不认识的参数:{' '.join(extra)}")
        args.rest = list(args.rest) + extra
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


def _manager(args: argparse.Namespace, base: str) -> Webmuxd:
    return Webmuxd(base, token=os.environ.get("WEBMUXD_TOKEN"),
                   user=args.user or os.environ.get("WEBMUXD_USER") or "cli",
                   name=args.socket_name)


def _server(args: argparse.Namespace) -> Webmuxd:
    """连上那个 server。**没起就报错并说该跑哪一行** —— 不偷偷起一个。

    tmux 能按需自启是因为它用 socket,没有端口要挑;我们有,
    而那条规矩是"端口由你给"([h §6](../docs/v2/works/h-runtime.md#6-端口由你给))。
    """
    base = args.host or Registry(name=args.socket_name).base()
    if not base:
        raise WebmuxdError(
            "没有在跑的 server —— 先 `webmuxd server start --port 7900`",
            code="session_not_found")
    return _manager(args, base)


def _session(args: argparse.Namespace) -> Session:
    sid, _tab = _split_target(args.target)
    web = _server(args)
    rows = web.list()
    if sid is None:
        if len(rows) != 1:
            # **不猜** —— 点错浏览器的代价比敲错终端大(cli/README §2)
            if rows:
                why = f"有 {len(rows)} 个 session,得用 -t 指定"
            else:
                why = "这个 server 上还没有 session —— `webmuxd new --id demo`"
                # **`stop` 是让页面停止加载,不是停 server。**
                # server 那一族收进二级之后这条歧义小多了,但一个刚起完
                # server 的人还是可能顺手打 `stop` —— 那就把路指对。
                if getattr(args, "cmd", "") == "stop":
                    why += "\n  要停的是整个 server 的话:`webmuxd server stop`"
            raise WebmuxdError(why, code="session_not_found")
        sid = rows[0]["id"]
    return web.session(id=sid)


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

def cmd_start(args: argparse.Namespace) -> int:
    """起那个 server。**一个 server 一个口,session 住在它下面。**"""
    reg = Registry(name=args.socket_name)
    if reg.base():
        row = reg.read() or {}
        print(f"已经在跑了  →  http://127.0.0.1:{row.get('port')}/")
        return 0

    # **端口是部署决定的,我们不替你换一个。**
    # "被占"和"没权限"分开说 —— 1024 以下要 root,报"被占了"会让人
    # 去查一个根本不存在的进程。
    processes.require_ports(args.port, host=args.bind)

    data = str(default_dir(args.socket_name) / "data")
    proc = processes.spawn_server(port=args.port, bind=args.bind, data=data,
                                  token=os.environ.get("WEBMUXD_TOKEN"))
    base = f"http://127.0.0.1:{args.port}"
    if not processes.wait_http(base + "/healthz", 30):
        proc.terminate()
        raise WebmuxdError(f"server 没起来 —— 日志在 {data}/server.log",
                           code="runtime_unavailable")
    reg.put(port=args.port, bind=args.bind, pid=proc.pid)
    _out(args, {"port": args.port, "bind": args.bind, "url": base + "/",
                "pid": proc.pid},
         f"server  →  {base}/   (还没有 session:webmuxd new --id demo)")
    if not args.json and args.bind not in ("127.0.0.1", "localhost", "::1"):
        print(f"       ⚠ 绑在 {args.bind} —— 这台机器网络能到的人,"
              "拿到 token 就能操作这里的浏览器", file=sys.stderr)
    return 0


def cmd_new(args: argparse.Namespace) -> int:
    # **命令行 > 环境变量 > 内置默认。** 没有配置文件那一档 ——
    # 参数从 lib 传(sdk/manager.md),CLI 只是把它们摆成 flag。
    url = args.url or os.environ.get("WEBMUXD_START_URL") or "about:blank"
    from webmuxd.screen import DEFAULT_H, DEFAULT_W
    window_size = args.window_size or f"{DEFAULT_W}x{DEFAULT_H}"
    w, _, h = window_size.partition("x")

    web = _server(args)
    row = web.create(args.id, runtime=args.runtime, url=url,
                     window_size=window_size, proxy=args.proxy,
                     browser_path=args.browser, cdp=args.cdp, dsf=args.dsf,
                     transport=args.transport,
                     view={"width": int(w), "height": int(h),
                           "fmt": args.img_format, "quality": args.quality,
                           "min_quality": args.min_quality})
    view_url = web.base + row["url"]
    _out(args, {**row, "view_url": view_url},
         f"{args.id}  →  {view_url}")
    if not args.json:
        for note in row.get("notes") or []:
            print(f"       ⚠ {note}", file=sys.stderr)
        print("       ⚠ 页面跑在这台机器上,**没有隔离** —— 要隔离见 "
              "docs/v2/works/h-runtime.md §2", file=sys.stderr)
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    reg = Registry(name=args.socket_name)
    base = args.host or reg.base()
    if not base:
        _out(args, {"sessions": []}, "(没有在跑的 server —— webmuxd server start --port 7900)")
        return 0
    rows = _manager(args, base).list()
    _out(args, {"sessions": rows})
    if args.json:
        return 0
    if not rows:
        print(f"(server 在 {base}/,还没有 session)")
        return 0
    for r in rows:
        print(f"{r['id']:<10} {r['runtime']:<9} {r['view_label']:<5} "
              f"{r['tabs']} 个 tab   {base}{r['url']}")
    return 0


def cmd_has(args: argparse.Namespace) -> int:
    """只返回退出码,给脚本用:`webmuxd has -t work || webmuxd new --id work`"""
    sid, _ = _split_target(args.target)
    base = args.host or Registry(name=args.socket_name).base()
    if not base:
        return 3
    return 0 if any(r["id"] == sid for r in _manager(args, base).list()) else 3


def cmd_kill(args: argparse.Namespace) -> int:
    sid, _ = _split_target(args.target)
    if not sid:
        raise WebmuxdError("要说关哪个:`webmuxd kill -t demo`", code="bad_request")
    web = _server(args)
    runtime = next((r["runtime"] for r in web.list() if r["id"] == sid), "")
    web.kill(sid)
    note = "(remote session,对面仍在运行)" if runtime == "remote" else ""
    _out(args, {"id": sid, "removed": True}, f"{sid} 已停掉 {note}".strip())
    return 0


def cmd_kill_server(args: argparse.Namespace) -> int:
    """**一个都不许留。** 留下的是没人管的 chrome。"""
    reg = Registry(name=args.socket_name)
    base = args.host or reg.base()
    if not base:
        reg.forget()
        _out(args, {"killed": 0}, "(没有在跑的 server)")
        return 0
    n = _manager(args, base).kill_server()
    reg.forget()
    _out(args, {"killed": n}, f"server 停了,连同 {n} 个 session")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    """停掉再起来,**端口沿用记着的那个**。

    端口是部署决定的([k](../docs/v2/works/k-one-server.md))—— 重启的时候
    替你换一个,等于让配置和实际对不上。所以从注册表里读回来;
    读不到就说清楚,不猜。

    **session 不会跟着回来。** 它们的浏览器进程随 server 一起停了 ——
    这条要说在前面,不然人以为 restart 是"原样恢复"。
    """
    reg = Registry(name=args.socket_name)
    row = reg.read() or {}
    port, bind = row.get("port"), row.get("bind", "127.0.0.1")
    if not port:
        raise WebmuxdError(
            "没有在跑的 server,不知道要用哪个口 —— `webmuxd server start --port 7900`",
            code="session_not_found")

    n = 0
    if reg.base():
        n = _manager(args, reg.base()).kill_server()
    reg.forget()

    # **等那个口真的放开再起。**
    #
    # `kill_server()` 回来的时候只是"命令送到了" —— 进程还在收尾,端口还占着。
    # 立刻 start 会撞 `port_in_use`,而那句话对着一个刚打了 restart 的人
    # 是没意义的:**他要的口就是那个,不是我们该让他去换的。**
    if not processes.wait_free(port, 10, host=bind):
        raise WebmuxdError(
            f"旧的 server 停了,但端口 {port} 10 秒还没放开 —— "
            f"看看是不是有别的东西占着(`ss -tlnp | grep {port}`)",
            code="port_in_use")

    args.port, args.bind = port, bind
    rc = cmd_start(args)
    if not args.json:
        print(f"  (顺带停掉了 {n} 个 session —— 它们不会跟着回来)")
    return rc


def cmd_install(args: argparse.Namespace) -> int:
    from webmuxd.install import install
    install(force=args.force, with_deps=args.with_deps, mirror=args.mirror)
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    from webmuxd import config
    reg = Registry(name=args.socket_name)
    base = args.host or reg.base()
    rows = _manager(args, base).list() if base else []
    rec = config.load()
    # **xpra 那条路能不能走,现探。** 和 runtime 一样的姿态:
    # 键在=探到了,键不在=没探到 —— 不猜、不缓存。
    from webmuxd import xpra as xpra_mod
    xpra_ok, xpra_why = xpra_mod.available()
    info = {"version": __import__("webmuxd").__version__, "runtimes": rt.detect(),
            "default_runtime": rt.default(),
            "default_transport": models.VNC if xpra_ok else None,
            # **报的是使用者看得见的那三个词。** JPG / DOM 不依赖系统里的东西,
            # 永远可用;VNC 要一个真实的 X 显示([c §9.3])。
            "transports": {models.JPG: True, models.VNC: xpra_ok, models.DOM: True},
            "views": [m.to_json() for m in models.mode_choices()],
            "xpra_why": "" if xpra_ok else xpra_why,
            "env_record": {"at": rec.at} if rec else None,
            # **关掉的安全特性要报出来。** 关可以,悄悄关不行。
            "off": ["HttpsUpgrades", "HttpsFirstBalancedMode"],
            "server": base or None,
            "sessions": {"total": len(rows)}}
    _out(args, info,
         "\n".join([f"版本      {info['version']}",
                    f"runtime   " + ", ".join(
                        f"{k}{'' if v else '(不可用)'}"
                        for k, v in info["runtimes"].items()),
                    # **使用者看到的是那三个词**,不是实现名
                    # ([c §9.1](../docs/v2/works/c-view.md#91-使用者看到的是三个词))
                    (f"画面      {models.label(models.VNC)}(默认),"
                     f"{models.label(models.JPG)},{models.label(models.DOM)}"
                     if xpra_ok else
                     f"画面      {models.label(models.JPG)},"
                     f"{models.label(models.DOM)} —— "
                     f"**默认的 {models.label(models.VNC)} 用不了**:{xpra_why}"),
                    (f"server    {base}/  ({len(rows)} 个 session)" if base
                     else "server    没在跑 —— `webmuxd server start --port 7900`"),
                    "安全      已关 HTTPS-First —— `http://` 就按 http 走,"
                    "不替你升级(docs/v2/cli/navigate.md)",
                    (f"记录      {rec.at}(webmuxd install 探的)" if rec
                     else "记录      没有 —— 每次都现探,"
                          "跑 `webmuxd install` 可以省掉")]))
    return 0


def cmd_attach(args: argparse.Namespace) -> int:
    sid, _ = _split_target(args.target)
    web = _server(args)
    if sid and not any(r["id"] == sid for r in web.list()):
        raise WebmuxdError(f"没有叫 {sid!r} 的 session", code="session_not_found")
    # **画面一定在** —— 它是我们自己产的,只要 server 活着就有。
    # 不给 id 就开那张列表页。
    url = web.base + (f"/s/{sid}/" if sid else "/")
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
    """命令行那几个 flag → 一个定位描述。

    **形状在 [`models.Locator`](models.py)** —— 这儿只管把 flag 摆进去,
    加一种写法改那一处,不改这三处(SDK / CLI / 执行层)。
    """
    at = getattr(args, "at", None)
    what = (getattr(args, "what", None) or "").strip()
    # **`@` 打头是上一次 snapshot 的号**,别的都是可见文字。
    # 一个真叫「@提醒」的按钮怎么点?写 `--name "@提醒"`。
    ref = what if what.startswith("@") else ""
    return models.Locator(
        ref=ref,
        text="" if ref else what,
        role=getattr(args, "role", None) or "",
        name=getattr(args, "name", None) or "",
        label=getattr(args, "label", None) or "",
        css=getattr(args, "css", None) or "",
        point=tuple(float(x) for x in at.split(",")) if at else None,
        nth=getattr(args, "nth", None),
    ).to_json()


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
    spec: dict[str, Any] = {"type": "type", **_locator(args)}
    # **`type` 的定位不看 text** —— 那个键装的是要输入的内容
    # (api/act.md §4.1)。所以位置参数在这儿的意思是"标签"。
    if "text" in spec:
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


def cmd_fill(args: argparse.Namespace) -> int:
    """**清空再填** —— `clear` + `type` 一条命令。

    对上 agent-browser 的 `fill <sel> <text>`。填表单十次有九次要的是这个,
    而拆成两条的话中间那一步失败了状态是半截的。
    """
    spec: dict[str, Any] = {"type": "type", "clear": True, **_locator(args)}
    if "text" in spec:                       # 位置参数在这儿是标签,不是内容
        spec["label"] = spec.pop("text")
    spec["text"] = args.text
    return _do(args, spec)


#: `get` 的每一样对应 `extract` 的一个 mode。**这儿不做第二套语义。**
_GET_MODES = ("text", "html", "value", "attr", "count", "box", "table")


def cmd_get(args: argparse.Namespace) -> int:
    """问一个元素的一个值。

    **在它之前,"确认一下"只有一个办法:把整页再抓一遍** ——
    而抓整页会发一批新号
    ([issue](../docs/v2/issues/每次确认都要抓一整页-于是号在膨胀.md))。

        webmuxd get value -t demo @e13        # 框里现在是什么
        webmuxd get count -t demo --css h3    # 有几条结果
        webmuxd get text  -t demo "登录"       # 那个东西上的字
    """
    kind, args.what, args.attr = _unpack(args.rest, [*_GET_MODES, "url", "title"], "get")
    if kind in ("url", "title"):             # 这两样不落到元素上
        t = _tab(args)
        _out(args, t._row(), t.url if kind == "url" else t.title)
        return 0
    spec: dict[str, Any] = {"type": "count" if kind == "count" else "extract",
                            **_locator(args)}
    if kind == "attr":
        if not args.attr:
            raise WebmuxdError("get attr 要给属性名:`get attr <目标> href`",
                               code="bad_request")
        spec["attr"] = args.attr
    if kind != "count":
        spec["mode"] = kind
    return _do_value(args, spec)


def cmd_is(args: argparse.Namespace) -> int:
    """问一个元素的状态。**答案在退出码里**(`0` 是,`1` 否)——
    和 `has` 一样,给脚本用的是码不是字。

        webmuxd is visible -t demo @e13 && echo 看得见
    """
    kind, args.what, _ = _unpack(args.rest, ["visible", "enabled", "checked"], "is")
    spec = {"type": "extract", "mode": kind, **_locator(args)}
    return _do_value(args, spec, boolean=True)


def _unpack(rest: list[str], kinds: list[str],
            cmd: str) -> tuple[str, str | None, str | None]:
    """`[种类, 目标?, 属性名?]` → 三个值。**种类不认识就当场说清有哪些。**"""
    kind = rest[0]
    if kind not in kinds:
        raise WebmuxdError(f"{cmd} 不认识 {kind!r} —— 有的是:{', '.join(kinds)}",
                           code="bad_request")
    return kind, (rest[1] if len(rest) > 1 else None), (rest[2] if len(rest) > 2 else None)


def _do_value(args: argparse.Namespace, spec: dict, *, boolean: bool = False) -> int:
    """跑一个"取值"的动作,**把值本身打到 stdout** —— 好让 `$(...)` 直接用。"""
    r = _tab(args).act([spec], note=args.note, user=args.user)
    res = r.results[0]
    _out(args, {"results": r.results, "log_from": r.log_from})
    if not res.get("ok"):
        raise WebmuxdError(res.get("message", ""), code=res.get("error"),
                           details={"candidates": res.get("candidates") or []})
    value = res.get("value")
    if not args.json:
        if isinstance(value, bool):
            # **`true` / `false`,不是 Python 的 `True` / `False`** ——
            # 这一行是给 shell 和别的语言看的,不是给 Python 看的。
            print("true" if value else "false")
        elif isinstance(value, (dict, list)):
            print(json.dumps(value, ensure_ascii=False))
        else:
            print("" if value is None else value)
    # **`is` 的答案是退出码。** 不是错误,所以不走 EXIT 那张表。
    return (0 if value else 1) if boolean else 0


#: **打错的词 → 该用哪个。**
#:
#: 这几个不是命令,是**别人会打的词**。打错了拿到 argparse 那一大坨
#: "invalid choice(choose from 34 个)"没有帮助 —— 它把答案埋在一行里。
#:
#: `stop` 不在这儿,因为它是个真命令(让页面停止加载)——
#: 那一种在 `_session()` 里当场说清。
_WRONG_WORD = {
    # 0.11.0 搬走的那三个 —— **搬了就得说搬到哪儿了**,不是让人自己去 help 里找
    "start":       "server 那一族收成二级了:`webmuxd server start --port 7900`",
    "restart":     "→ `webmuxd server restart`(端口沿用记着的那个)",
    "kill-server": "→ `webmuxd server stop`",
    # 别人会打、但我们没有的词
    "stop-server": "→ `webmuxd server stop`",
    "shutdown":    "→ `webmuxd server stop`",
    "quit":        "停整个 server 是 `webmuxd server stop`;只停一个 session 是 `webmuxd kill -t <id>`",
    "exit":        "停整个 server 是 `webmuxd server stop`;只停一个 session 是 `webmuxd kill -t <id>`",
    "list":        "列 session 是 `webmuxd ls`",
    "ps":          "列 session 是 `webmuxd ls`",
    "open":        "起 session 是 `webmuxd new --id <id>`,导航是 `webmuxd goto -t <id> <url>`",
}


#: 那几个全局开关里,**带值的**是这些 —— 找"第一个词"的时候要连值一起跳过。
_TAKES_VALUE = {"-H", "--host", "-L", "--socket-name", "--user", "--note"}


def _first_word(argv: list[str]) -> str | None:
    """命令是哪个词。`webmuxd --user bob start` 里是 `start`,不是 `bob`。"""
    it = iter(argv)
    for tok in it:
        if tok in _TAKES_VALUE:
            next(it, None)
            continue
        if tok.startswith("-"):
            continue
        return tok
    return None


def cmd_snapshot(args: argparse.Namespace) -> int:
    """这一页上有什么。**每一样带一个 `@e1`,下一条命令直接拿去用。**"""
    snap = _tab(args).snapshot(interactive=args.interactive,
                               selector=args.selector,
                               viewport=args.viewport,
                               max_elements=args.max)
    _out(args, snap.to_json())
    if args.json:
        return 0
    for el in snap.elements:
        print(el.as_line())
    for n in snap.notes:
        print(f"! {n}")
    if not snap.elements:
        # **空不是成功。** 但也不是失败 —— 页面可能真的还没加载完。
        # 说清楚下一步试什么,比回一个空行有用。
        print("(什么都没抓到 —— 页面可能还在加载,先 `webmuxd wait`;"
              "或者去掉 -i 看看结构)")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    t = _tab(args)
    if args.shot:
        t.screenshot(args.shot)
        print(f"✓ 存到 {args.shot}")
    else:
        sys.stdout.write(t.text())
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

    # ---------------------------------------------------------------- server
    #
    # **只有起/停/重启收成二级,别的都平铺。**
    #
    # 平铺是对的 —— `click` / `goto` / `snapshot` 一天打几十遍,`webmuxd do click`
    # 只是让每一次都更长。tmux 和 agent-browser 也都这样:**热的动词平铺,
    # 成组的收进二级**(agent-browser 的二级全是冷的:get / is / mouse / set /
    # network / storage …)。
    #
    # 但 server 这一族非收不可,因为它撞了名字:
    # **`start` 是我们自己发明的**(tmux 没有,它的 server 隐式起;我们因为端口
    # 必须显式给才加了它)。发明了 `start` 就欠一个 `stop` —— 而 `stop` 被
    # 页面那个"停止加载"占着。于是一个刚 `start` 完的人打 `stop`,拿到的是
    # "这个 server 上还没有 session",方向完全反了。
    #
    # 收进二级之后这条歧义自己没了:**server 的东西全在 `server` 底下**,
    # 所以 bare `stop` 不可能是 server 的。
    srv = sub.add_parser("server", help="起 / 停 / 重启这个 server")
    srvsub = srv.add_subparsers(dest="sub")

    def sadd(name, fn, **kw):
        x = srvsub.add_parser(name, **kw)
        x.set_defaults(fn=fn, cmd="server")
        return x

    srv.set_defaults(fn=lambda a: (srv.print_help(), 2)[1], cmd="server")

    st = sadd("start", cmd_start, help="起 server(一个口,承载全部 session)")
    st.add_argument("--port", "-p", type=int,
                    default=int(os.environ.get("WEBMUXD_PORT", "7900")),
                    help="这个口:人打开它看画面,代码连它调 API")
    st.add_argument("--bind", default="127.0.0.1",
                    help="绑哪个地址。默认只绑本机;填 0.0.0.0 就是对外开放 —— "
                         "拿到 token 的人就能操作这里的浏览器")

    n = add("new", cmd_new, target=False, help="起一个 session")
    n.add_argument("--id", "-s", required=True)
    # **一件事一个名字,三层通用**:CLI 用 --x,lib 用 x=,镜像用 WEBMUXD_X。
    n.add_argument("--runtime", default=None, choices=["process", "remote"],
                   help="process(默认)= 本机起一个浏览器;"
                        "remote = 你给一个 CDP 端点,浏览器不归我们")
    n.add_argument("--browser", default=None,
                   help="用哪个浏览器二进制。不给就用 `webmuxd install` 下的那个")
    n.add_argument("--cdp", default=None,
                   help="runtime=remote 时对面那个 CDP 端点")
    n.add_argument("--url", "-u", default=None)
    n.add_argument("--window-size", "-v", "--viewport", default=None,
                   dest="window_size", help="画面尺寸,例 1280x800")
    n.add_argument("--proxy", default=None)
    # **绑哪个地址**,和全局那个 `-H/--host`(连哪台机器)不是一回事 ——
    # 所以这儿叫 `--bind`,不复用 `--host`。
    # 清晰度三个独立的旋钮 —— **调错那个不会有任何效果**
    # ([e1](../docs/v2/works/e1-wire-format.md))
    n.add_argument("--quality", type=int, default=80,
                   help="画质 1-100(png 无损,对它无效)。它同时是自适应升质的上限")
    n.add_argument("--format", default="jpeg", choices=["jpeg", "png", "webp"],
                   dest="img_format", help="帧编码。扁平 UI 页面 png 有时反而更小")
    n.add_argument("--min-quality", type=int, default=25, dest="min_quality",
                   help="自适应最多降到多少。默认 25 —— 再低就是马赛克,"
                        "到底了改抽帧,那才是链路真撑不住时该退的方向")
    # **默认关。** 不给就是 1(不加 --force-device-scale-factor);
    # 光写 `--dsf` 就是 2(Retina 那种最常见的情况);要 1.5 就 `--dsf 1.5`。
    n.add_argument("--dsf", type=float, nargs="?", const=2.0, default=1.0,
                   help="渲染倍率。**默认关**,只在观看端是高 DPI 屏时才开 —— "
                        "光写 --dsf 就是 2。普通屏上开了反而更糊,还多花 2.6 倍带宽")
    # **画面用哪种。默认 VNC**([c §13])—— 它按 damage 区域编码,
    # 滚动时 `scroll` 包零字节搬像素。`webmuxd install` 会把它装上。
    # 起不来就报错,**不自己换一种**;退路是显式说一声。
    #
    # 旧名字(screencast / xpra / rrweb)继续认,但不列在 choices 里 ——
    # **一件事一个词**,列出来就等于承认有两套叫法。
    n.add_argument("--transport", default=None, metavar="{jpg,vnc,dom}",
                   help="画面用哪种。不给就是 vnc。"
                        "jpg=什么都显示得出来;vnc=连续、跟手;"
                        "dom=字最清楚、最省流量(但没有视频)")
    n.add_argument("-d", action="store_true", help="建完不 attach(默认就是)")

    ins = add("install", cmd_install, target=False,
              help="探一遍环境、装该装的、把结果记下来")
    ins.add_argument("--force", action="store_true", help="重下一遍")
    ins.add_argument("--with-deps", action="store_true",
                     help="顺便装系统依赖(要 root,只支持 Debian/Ubuntu)")
    ins.add_argument("--mirror", default=None,
                     help="换下载源。国内:https://cdn.npmmirror.com/binaries/chrome-for-testing")
    sadd("stop", cmd_kill_server, help="停掉 server 和全部 session")
    sadd("restart", cmd_restart, help="停掉再起来,端口沿用记着的那个")

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
        c.add_argument("what", nargs="?", default=None,
                       help="可见文字,或 snapshot 给的 @e1")
        c.add_argument("--role"), c.add_argument("--name")
        c.add_argument("--css"), c.add_argument("--at")
        c.add_argument("--nth", type=int, default=None)
    ty = add("type", cmd_type, help="输入")
    ty.add_argument("what", nargs="?", default=None,
                    help="标签,或 snapshot 给的 @e1")
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
    fi = add("fill", cmd_fill, help="清空再填(= clear + type)")
    fi.add_argument("what", nargs="?", default=None,
                    help="标签,或 snapshot 给的 @e1")
    fi.add_argument("text")
    fi.add_argument("--label"), fi.add_argument("--css")
    fi.add_argument("--role"), fi.add_argument("--name")
    fi.add_argument("--nth", type=int, default=None), fi.add_argument("--at")

    # **位置参数收成一个列表,自己拆。**
    # `webmuxd get value -t demo @e13` 里那个 `-t demo` 把位置参数劈成两段,
    # 而 argparse 一碰到两个 `nargs="?"` 被劈开就配不上了(报
    # "unrecognized arguments: @e13")。收成 `+` 之后怎么摆都认。
    g = add("get", cmd_get, help="问一个值(text/value/count/…)")
    g.add_argument("rest", nargs="+", metavar="种类 [目标] [属性名]")
    g.add_argument("--css"), g.add_argument("--role"), g.add_argument("--name")
    g.add_argument("--label"), g.add_argument("--at")
    g.add_argument("--nth", type=int, default=None)

    i = add("is", cmd_is, help="问一个状态,答案在退出码里")
    i.add_argument("rest", nargs="+", metavar="visible|enabled|checked [目标]")
    i.add_argument("--css"), i.add_argument("--role"), i.add_argument("--name")
    i.add_argument("--label"), i.add_argument("--at")
    i.add_argument("--nth", type=int, default=None)

    sn = add("snapshot", cmd_snapshot, help="这一页上有什么(带 @e1)")
    sn.add_argument("-i", "--interactive", action="store_true",
                    help="只要能点能填的")
    sn.add_argument("-s", "--selector", default=None, help="只看这棵子树")
    sn.add_argument("--viewport", action="store_true", help="只要视口内的")
    sn.add_argument("--max", type=int, default=150, help="最多几个")
    cap = add("capture", cmd_capture, help="抓正文或截图")
    cap.add_argument("--text", action="store_true")
    cap.add_argument("--shot", default=None)
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


# --------------------------------------------------------------------------
# server 在哪 —— **登记的只剩这一件事**([k](../docs/v2/works/k-one-server.md))
# --------------------------------------------------------------------------

def default_dir(name: str = "default") -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / "webmuxd" / name


class Registry:
    """记着"这套 server 在哪个口上"。

    以前这儿是一张 session 表,`ls` 要读表再逐个探活 —— 因为没有常驻进程,
    **这个文件在冒充 server**。现在有真的了,它只剩一行:端口、绑在哪、pid。

    `-L name` / `-S path` 照抄 tmux:**换 socket = 换一套独立的 server**。
    """

    def __init__(self, path: str | Path | None = None, *, name: str = "default") -> None:
        self.dir = Path(path) if path else default_dir(name)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "server.json"

    def read(self) -> dict | None:
        """**读不懂就当没有。** 和环境记录那条一个姿态 —— 上一版留下的
        `sessions.json` 我们根本不看,它的存在不该让任何一条命令崩。
        """
        try:
            row = json.loads(self.file.read_text() or "{}")
        except (OSError, json.JSONDecodeError):
            return None
        return row if isinstance(row, dict) and isinstance(row.get("port"), int) else None

    def put(self, *, port: int, bind: str, pid: int) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"port": port, "bind": bind, "pid": pid,
             "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            ensure_ascii=False, indent=1))
        tmp.replace(self.file)              # 原子替换,别让半个文件被读到

    def forget(self) -> None:
        self.file.unlink(missing_ok=True)

    def base(self) -> str | None:
        """server 的地址 —— **探得到才算**。

        文件会撒谎(进程被 OOM 杀了它不知道),所以按记录去连、连不上就当没有。
        和"记录会撒谎"那条老规矩([d](../docs/v2/works/d-install.md))一致。
        """
        row = self.read()
        if not row:
            return None
        url = f"http://127.0.0.1:{row['port']}"
        return url if processes.wait_http(url + "/healthz", 2) else None
