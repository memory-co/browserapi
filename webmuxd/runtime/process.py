"""本机起一个 —— **v2 唯一的本地跑法**(docs/v2/works/07-runtime.md §5)。

v1 的 `process` 有两个尴尬:**要本机装 chromium**,以及没有 Xvnc 就只有 API
没有画面。v2 把两个都消掉了 —— 画面来自 CDP,浏览器来自 `webmuxd install`。
于是它从"开发和 CI 凑合用的那个"变成了**默认**。

    <install 下来的 chrome> --headless=new --remote-debugging-port=<free> --user-data-dir=<profile>

两个进程,秒起。它们是 server 的子进程,`kill-server` 跟着死。

**剩下的差别写在明处:没有网络和文件系统隔离**,页面跑在你自己机器上。
这一条不能因为默认了就说得轻一点 —— 要隔离,把 webmuxd 装进容器,
或者用 `remote` 连一个别处的浏览器(§2、§6)。
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
from typing import Any

from webmuxd import browser
from webmuxd.runtime.base import (
    Handle, free_port, require_ports, spawn_sessiond, unavailable, wait_http,
    wait_port,
)

#: 起浏览器的固定参数。**沙箱默认不关** —— 和 v1 一样的姿态,需要时
#: `WEBMUXD_NO_SANDBOX=1`(内核禁用非特权 user namespace 时才需要)。
BASE_ARGS = (
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
    "--disable-session-crashed-bubble",
    # 后台 target 不产帧是**我们要的**(works/05 §2),所以不去关渲染器节流
)


def resolve_browser(explicit: str | None = None) -> str:
    """用哪个浏览器。**传进来的赢**,其次记录,再其次系统里那个。

    找不到就抛,并说该跑 `webmuxd install` —— 不静默降级,
    那等于让你以为在跑钉死的那一版(works/07 §4.1)。
    """
    for cand in (explicit, os.environ.get("WEBMUXD_BROWSER")):
        if cand:
            if os.path.exists(cand):
                return cand
            raise unavailable("process", f"指定的浏览器不在:{cand}",
                              "确认路径,或者跑 `webmuxd install` 下一个")
    from webmuxd import env
    rec = (env.get("default_browser") or {})
    p = rec.get("path") if isinstance(rec, dict) else None
    if p and os.path.exists(p):
        return p
    got = browser.find()
    if got:
        return got
    got = browser.find_system()
    if got:
        return got
    raise unavailable("process", "本机没有浏览器",
                      "跑 `webmuxd install` 下一个钉死版本的,"
                      "或者 session(browser=…) 指一个")


class ProcessRuntime:
    name = "process"

    def available(self) -> tuple[bool, str]:
        try:
            resolve_browser()
            return True, ""
        except Exception as e:
            return False, str(e)

    def start(self, id: str, *, port: int, url: str = "about:blank",
              window_size: str = "", browser_path: str | None = None,
              proxy: str | None = None, data_dir: str | None = None,
              token: str | None = None, bind: str = "127.0.0.1",
              **_opts: Any) -> Handle:
        exe = resolve_browser(browser_path)
        require_ports(port)

        work = data_dir or tempfile.mkdtemp(prefix=f"webmuxd-{id}-")
        os.makedirs(work, exist_ok=True)
        cdp_port = free_port()
        notes: list[str] = []

        # 以前镜像替用户扛掉的那些,现在落到裸机上 —— **明说,不静默**
        missing = browser.missing_libs(exe)
        if missing:
            raise unavailable("process", f"浏览器缺共享库:{', '.join(missing[:6])}",
                              "跑 `webmuxd install --with-deps`(要 root),"
                              "或者自己 apt install 上面这些")
        if not browser.has_cjk_font():
            notes.append(f"{browser.FONT_HINT[1]} —— `{browser.FONT_HINT[0]}`")

        args = [exe, *BASE_ARGS,
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={os.path.join(work, 'profile')}"]
        # **root 下沙箱起不来,这不是选择题。**
        #
        # Chromium 硬拒绝:`Running as root without --no-sandbox is not supported`
        # (crbug 638180)。所以 root + 沙箱**没有能跑的配置** —— 报错让人自己去
        # 查,等于把一个无解的选择丢回去。
        #
        # 而且我们自己推荐的隔离路子(把 webmuxd 装进容器,[works/07 §2])
        # 默认就是 root。所以这儿自动加上,**但要说出来**:
        # 关掉的是安全特性,不能悄悄关。
        as_root = hasattr(os, "geteuid") and os.geteuid() == 0
        if as_root or os.environ.get("WEBMUXD_NO_SANDBOX"):
            args.append("--no-sandbox")
        if as_root and not os.environ.get("WEBMUXD_NO_SANDBOX"):
            notes.append("你是 root —— Chromium 在 root 下必须 --no-sandbox 才起得来"
                         "(crbug 638180),已经替你加上了。**沙箱是关着的**;"
                         "想要它就换个非 root 用户跑")
        if window_size:
            args.append(f"--window-size={window_size.replace('x', ',')}")
        if proxy:
            args.append(f"--proxy-server={proxy}")
        args.append(url)

        # **浏览器的 stderr 不能扔。** 它起不来的原因就写在里面(root 没关沙箱、
        # 缺共享库、profile 目录不能写……),扔掉之后我们只能让人"手工跑一遍看
        # 报什么" —— 那等于把排查工作原样退回去。0.5.2 之前就是这样。
        log_path = os.path.join(work, "chrome.log")
        procs: dict[str, subprocess.Popen] = {}
        with open(log_path, "wb") as log:
            procs["browser"] = subprocess.Popen(
                args, stdout=subprocess.DEVNULL, stderr=log,
                start_new_session=True)
        if not wait_port(cdp_port, 30):
            why = _tail(log_path)
            _kill_all(procs)
            raise unavailable(
                self.name,
                "浏览器起来了但 CDP 没监听" + (f":{why}" if why else ""),
                f"完整日志在 {log_path};手工跑一遍:{' '.join(args[:3])} …")

        procs["sessiond"] = spawn_sessiond(
            f"http://127.0.0.1:{cdp_port}", port=port, bind=bind,
            data=os.path.join(work, "data"), token=token)
        if bind not in ("127.0.0.1", "localhost", "::1"):
            notes.append(f"画面口绑在 {bind} —— **这台机器网络能到的人,"
                         f"拿到 token 就能操作这个浏览器**")
        if not wait_http(f"http://127.0.0.1:{port}/healthz", 30):
            _kill_all(procs)
            raise unavailable(self.name, "sessiond 没起来",
                              "手工跑一遍 python -m webmuxd.serve 看报什么")

        return Handle(self.name, id, port,
                      {"cdp_port": cdp_port, "work": work, "browser": exe,
                       "bind": bind,
                       "pids": {k: p.pid for k, p in procs.items()},
                       "notes": notes, "_procs": procs})

    def stop(self, handle: Handle) -> None:
        procs = handle.detail.get("_procs") or {}
        if procs:
            _kill_all(procs)
            return
        for pid in (handle.detail.get("pids") or {}).values():
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)

    def alive(self, handle: Handle) -> bool:
        procs = handle.detail.get("_procs") or {}
        p = procs.get("sessiond")
        if p is not None:
            return p.poll() is None
        pid = (handle.detail.get("pids") or {}).get("sessiond")
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _tail(path: str, lines: int = 4) -> str:
    """把浏览器最后几行 stderr 拿出来,**去掉那些没用的前缀**。

    Chromium 的每一行都长这样:
    `[206402:206402:0818/205945.649553:ERROR:.../zygote_host_impl_linux.cc:102] 真正的话`
    —— 前面那一坨对使用者没有任何意义,留着只会把真正那句话挤出屏幕。
    """
    import re
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\[[\d:./]+:(ERROR|WARNING|INFO|FATAL):[^\]]*\]\s*", "", line).strip()
        if line and not line.startswith("["):
            out.append(line)
    return "\n     ".join(out[-lines:])


def _kill_all(procs: dict) -> None:
    for p in procs.values():
        with contextlib.suppress(Exception):
            p.send_signal(signal.SIGTERM)
    for p in procs.values():
        try:
            p.wait(timeout=5)
        except Exception:
            with contextlib.suppress(Exception):
                p.kill()


def _which(names: tuple[str, ...]) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None
