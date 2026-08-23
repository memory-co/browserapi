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
import json
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
    # **说了 http 就是 http。**
    #
    # 新版 Chrome 默认开着 HTTPS-First(Balanced Mode):你请求 `http://`,
    # 它先替你换成 `https://` 试,失败就停在一张 interstitial 上。
    #
    # 那张页**我们进不去** —— `certificateErrorPageController` 是空壳,
    # `document.body` 长度是 0,有头无头都一样。人在画面里看得见那两个按钮、
    # 点得动;我们的 CDP 会话里那张页是空的。于是"只有 http 的站"
    # 对 webmuxd 是**一律到不了**,不是"少一个选项"。
    #
    # 所以关掉。**这是关掉一个安全特性,所以要说出来** ——
    # `webmuxd info` 里有一行,[navigate.md](../docs/v2/cli/navigate.md) 里有一节。
    # 判据是这个项目那条老规矩:**显式传入优先**,和「端口由你给」同一条 ——
    # 调用方写了 `http://`,替它改成别的就是替它改了它说的话。
    "--disable-features=HttpsUpgrades,HttpsFirstBalancedMode",
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
def alive(pid: int) -> bool:
    """这个进程还在不在。**问的是进程,不是它答不答话。**"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                         # 在,只是不归我们管
    return True


def stop_pid(pid: int, timeout: float = 8) -> bool:
    """按 pid 停一个进程组。**先好好说,不听再动手。**

    停的是**整组**:server 底下还挂着 chrome、xpra、虚拟显示,
    只杀它自己的话那些全成孤儿(这个坑在 `xpra.stop()` 里也踩过一次)。
    """
    import contextlib
    for sig in (signal.SIGTERM, signal.SIGKILL):
        with contextlib.suppress(OSError):
            os.killpg(os.getpgid(pid), sig)
        end = time.monotonic() + (timeout if sig == signal.SIGTERM else 2)
        while time.monotonic() < end:
            if not alive(pid):
                return True
            time.sleep(0.1)
    return not alive(pid)


def forget_last_tabs(profile: str) -> None:
    """**把上次那些 tab 忘掉,但别忘掉登录态。**

    profile 目录是跟着 session 留在数据目录里的 —— 那是故意的:
    重启一次就要重新登录一遍的浏览器没人要。但 chrome 在那个目录里
    **还存了"上次开着哪些标签页"**,而且只要上次不是干净退出的
    (升级时被 kill、机器断电、`kill -9`),它下次起来就**自己把它们恢复出来**。

    表现是:人 `server stop` 再 `server start`,进去一看**上次的 tab 还在**,
    像是我们没清数据 —— 其实我们这边一条都没留,是浏览器自己捡回来的。
    实测:非正常退出之后重启,tab 表里是 `example.com` + 两个 about:blank。

    `--disable-session-crashed-bubble` 挡不住这个 —— 它只是**把那个气泡藏起来**,
    该恢复照样恢复。要真拦住,得动 profile 里那两样东西:

    - `Default/Sessions/`(和 `Sessions_Encrypted/`):上次开着哪些页,就存在这儿
    - `Preferences` 里的 `exit_type`:不是 `"Normal"` 的话 chrome 就当上次崩了

    cookie、登录态、历史都在别的文件里(`Cookies` / `Login Data` / `History`),
    **一个都不动**。
    """
    root = os.path.join(profile, "Default")
    for name in ("Sessions", "Sessions_Encrypted"):
        with contextlib.suppress(OSError):
            shutil.rmtree(os.path.join(root, name))
    prefs = os.path.join(root, "Preferences")
    try:
        with open(prefs, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return                              # 头一次起,还没有这个文件
    prof = data.setdefault("profile", {})
    if prof.get("exit_type") == "Normal" and prof.get("exited_cleanly") is True:
        return
    prof["exit_type"] = "Normal"
    prof["exited_cleanly"] = True
    with contextlib.suppress(OSError):
        with open(prefs, "w", encoding="utf-8") as f:
            json.dump(data, f)


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


def wait_free(port: int, timeout: float = 10.0, host: str = "127.0.0.1") -> bool:
    """等那个口**放开**。`wait_port` 的反面。

    停一个 server 之后立刻重起会撞上这一条:命令送到了,进程还在收尾,
    端口还占着 —— 而对一个刚打了 `restart` 的人来说,
    **他要的口就是那个**,让他去换一个是答非所问。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.socket() as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
            return True
        except OSError:
            time.sleep(0.2)
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
