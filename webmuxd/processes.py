"""**所有进程都归它** —— 起、等、看活、收干净。

浏览器、xpra、Xvfb、sessiond,不管哪一种,这四件事是同一套。
以前 `runtime/process.py` 和 `xpra.py` 各写了一份,于是超时、清理、
"起不来时打哪段日志"三处都不一样 —— 合成一份就是这个文件
([j §3.2](../docs/v2/works/j-layout.md#32-processespy所有进程都归它))。

**它不认识 `xpra.py`,也不认识 `sessions.py`。**
"要 VNC 就先起一套 xpra"是**会话的编排**,在 `sessions.py`;
这儿只提供机制,不做那个决定。

拿哪个浏览器也不在这儿定 —— 装完之后"浏览器在哪"就是配置里的一行,
读它的是 `config.py`。
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

from webmuxd import config
from webmuxd.exceptions import PortInUse, unavailable

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
    rec = config.browser()
    if rec and os.path.exists(rec.path):
        return rec.path
    got = config.find()
    if got:
        return got
    got = config.find_system()
    if got:
        return got
    raise unavailable("process", "本机没有浏览器",
                      "跑 `webmuxd install` 下一个钉死版本的,"
                      "或者 session(browser=…) 指一个")


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


# ---------------------------------------------------------------------------

def port_free(port: int, host: str = "127.0.0.1") -> bool:
    return _bind_error(port, host) is None


def _bind_error(port: int, host: str) -> OSError | None:
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return None
        except OSError as e:
            return e


def require_ports(*ports: int, host: str = "127.0.0.1") -> None:
    """**端口是部署决定的,我们不替你换一个。** 被占了就说被占了。

    **"被占"和"没权限"要分开说** —— 1024 以下要 root,而报"被占了"会让人
    去查根本不存在的那个进程。提示指错方向比没有提示更糟。
    """
    import errno
    for p in ports:
        e = _bind_error(p, host)
        if e is None:
            continue
        if e.errno == errno.EACCES:
            raise PortInUse(f"端口 {p} 要 root 才能绑(1024 以下都要)",
                            code="port_in_use",
                            details={"port": p, "reason": "privileged"})
        raise PortInUse(f"端口 {p} 被占了", code="port_in_use",
                        details={"port": p, "reason": "in_use"})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


#: **等一个进程监听的时候,要盯着那个进程本身。**
#:
#: 不盯的下场:浏览器因为 root 没关沙箱、缺共享库、profile 写不了而**立刻退出**,
#: 我们照样干等满 30 秒(有头那条是 60 秒),然后告诉人
#: 「浏览器起来了但 CDP 没监听」—— **它没起来,它已经死了。**
#: 一句话把人往错的方向指,后面日志再全也白搭。
def _died(proc: subprocess.Popen | None) -> bool:
    return proc is not None and proc.poll() is not None


def wait_http(url: str, timeout: float = 30.0,
              proc: subprocess.Popen | None = None) -> bool:
    import urllib.error
    import urllib.request
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except urllib.error.HTTPError:
            return True                  # 有响应就算起来了(401 也算)
        except Exception:
            if _died(proc):
                return False             # 人都没了,别等了
            time.sleep(0.25)
    return False


def wait_port(port: int, timeout: float = 30.0, host: str = "127.0.0.1",
              proc: subprocess.Popen | None = None) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), 0.5):
                return True
        except OSError:
            if _died(proc):
                return False
            time.sleep(0.2)
    return False


# --------------------------------------------------------------------------
# sessiond —— 两种 runtime 共用这一段:**都是"拿一个 CDP 端点起一个 sessiond"**,
# 区别只在那个端点是我们起的还是你给的。
# --------------------------------------------------------------------------

def spawn_server(*, port: int, data: str, bind: str = "127.0.0.1",
                 token: str | None = None) -> subprocess.Popen:
    """起那个 server 进程,**不等它** —— 等在调用方那儿。

    `start_new_session` 脱离调用者的进程组:`webmuxd start` 是一次性的命令,
    不脱离的话它一退出就把刚起的 server 带走了。

    **它的输出不能扔。** 和浏览器那条是同一个教训:扔掉之后它崩了、
    降质了、报警了,外面一概看不见。落到 data 目录旁边。
    """
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)}
    if token:
        env["WEBMUXD_TOKEN"] = token
    os.makedirs(data, exist_ok=True)
    log_file = open(os.path.join(data, "server.log"), "ab", buffering=0)
    return subprocess.Popen(
        [sys.executable, "-m", "webmuxd.serve",
         "--bind", bind, "--port", str(port), "--data", data],
        env=env, stdout=log_file, stderr=log_file, start_new_session=True)
