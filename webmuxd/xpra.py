"""xpra 那条画面路的**服务端一头** —— docs/v2/works/11 · 12。

    Xvfb :N  +  xpra start-desktop :N  +  chrome --kiosk --display=:N

三个进程,但只有一个归我们管:**xpra 自己会拉起 Xvfb 和 chrome**
(`--start-child`),所以我们 Popen 一个、杀一个。

三条来自实测的硬规矩([12](../docs/v2/works/12-xpra-client.md)):

**① `start-desktop`,不是 `start`。** seamless 模式下 `<select>` 下拉是一个独立的
`new-override-redirect` 窗口,客户端得自己做多窗口合成;desktop 模式下 X 把它
合成进同一个窗口,客户端只面对一块画布(§6)。代价是多一个 `python3-pil` 依赖。

**② `--kiosk`,于是没有 bar 要裁。** `outerHeight - innerHeight` 实测:
普通启动 143、去掉警告条 88、加上 kiosk **0**。原计划那套"客户端裁掉 crop_top"
连同"鼠标 y 要加回去"那个坑一起不存在了(§10)。

**③ `--sharing=yes`。** 每个观看者一条自己的上游连接,各自的 damage 流和背压 ——
和 [viewer.py](view/viewer.py) 那个"慢的那个只掉自己的帧"是同一个形状。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from webmuxd.runtime.base import unavailable

#: 起 xpra 时固定关掉的一堆。**我们只要像素**([11 §5](../docs/v2/works/11-xpra.md))——
#: 剪贴板、音频、通知、文件传输、打印全走我们自己的 API,不走 xpra。
OFF = (
    "--notifications=no", "--pulseaudio=no", "--speaker=off", "--microphone=no",
    "--printing=no", "--file-transfer=no", "--mdns=no", "--dbus=no",
    "--dbus-launch=", "--webcam=no", "--clipboard=no", "--bell=no",
)

#: chrome 在 xpra 下的固定参数。**和 headless 那条的差别全在这儿**:
#: 有头、kiosk、而且要把两条提示条按下去 —— 不然它们占 55 像素还一直在。
KIOSK_ARGS = (
    "--kiosk",
    # `--test-type` 按下 "You are using an unsupported command-line flag" 那条;
    # Chrome for Testing 自己还有一条 "only for automated testing"。
    # **这两条不按下去,画面顶上就一直挂着 55 像素的黄条**(12 §10)。
    "--test-type", "--disable-infobars",
    "--no-first-run", "--no-default-browser-check",
    "--disable-session-crashed-bubble",
)


@dataclass
class XpraSession:
    proc: subprocess.Popen
    display: str
    ws_port: int
    cdp_port: int
    socket_dir: str
    log_path: str
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ws_url(self) -> str:
        return f"ws://127.0.0.1:{self.ws_port}/"


def xpra_python(exe: str | None = None) -> str | None:
    """**跑 xpra 的是哪个 python。**

    这不是学究气:`xpra` 是个带 shebang 的脚本,用的是系统的解释器,
    而 webmuxd 很可能装在一个 venv 里。拿我们自己的 `import PIL` 去判断,
    **两个方向都会错** —— venv 里没有而系统有(拦下一个本来能跑的模式),
    或者反过来(说能跑,起的时候才炸)。

    读不出 shebang(比如它是个二进制)就返回 `None`,由调用方决定 ——
    **不知道就说不知道,不要拿一个猜的答案去挡人**。
    """
    exe = exe or shutil.which("xpra")
    if not exe:
        return None
    try:
        with open(exe, "rb") as f:
            first = f.readline(256)
    except OSError:
        return None
    if not first.startswith(b"#!"):
        return None
    parts = first[2:].decode("utf-8", "replace").strip().split()
    if not parts:
        return None
    # `#!/usr/bin/env python3` 这种形式,真正的解释器在第二个词
    return parts[1] if parts[0].endswith("env") and len(parts) > 1 else parts[0]


def available() -> tuple[bool, str]:
    """**探到才叫有。** 缺一样都起不来,而且报错要指名道姓。"""
    missing = []
    exe = shutil.which("xpra")
    if not exe:
        missing.append("xpra")
    if not shutil.which("Xvfb"):
        missing.append("Xvfb(xorg 的虚拟显示,包名一般是 xvfb)")

    # `start-desktop` 要 PIL,`start` 不要 —— 而我们只用 start-desktop(§6)。
    # 实测过:不装就是 `xpra-server is not installed: No module named 'PIL'`,
    # 而那句话**完全不指方向**。
    py = xpra_python(exe) if exe else None
    if py:
        try:
            ok = subprocess.run([py, "-c", "import PIL"], capture_output=True,
                                timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = True                 # 探不动就别挡路,让真错误自己出来
        if not ok:
            missing.append(f"PIL(start-desktop 要它;{py} 上装:"
                           f"apt install python3-pil)")
    if missing:
        return False, "缺:" + "、".join(missing)
    return True, ""


def free_display(start: int = 80, end: int = 200) -> str:
    """找一个没人用的 `:N`。

    **看 socket 文件,不看进程。** X 的显示号就是 `/tmp/.X11-unix/X<N>`,
    这是唯一一处不会撒谎的地方。
    """
    for n in range(start, end):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}") and \
                not os.path.exists(f"/tmp/.X{n}-lock"):
            return f":{n}"
    raise unavailable("xpra", f"{start}-{end} 之间没有空的 X 显示号",
                      "有一堆没清干净的 X session,`ls /tmp/.X11-unix/`")


def build_chrome_argv(exe: str, *, cdp_port: int, profile: str, url: str,
                      width: int, height: int, proxy: str | None = None,
                      no_sandbox: bool = False) -> list[str]:
    """xpra 模式下的 chrome 命令行。**和 headless 那条共享的部分很少**,
    所以不复用 `process.BASE_ARGS` —— 硬凑只会让两边都看不懂。"""
    argv = [exe, *KIOSK_ARGS,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={profile}",
            # 窗口尺寸给满,kiosk 下它就是整个显示
            "--window-position=0,0", f"--window-size={width},{height}"]
    if no_sandbox:
        argv.append("--no-sandbox")
    if proxy:
        argv.append(f"--proxy-server={proxy}")
    argv.append(url)
    return argv


def _quote(argv: list[str]) -> str:
    """`--start-child=` 是一个字符串,xpra 自己拆。**空格要转义**,
    不然 `--window-size=1024,768 url` 会被拆成两个参数。"""
    import shlex
    return " ".join(shlex.quote(a) for a in argv)


def start(*, display: str, ws_port: int, cdp_port: int, chrome_argv: list[str],
          width: int, height: int, work: str) -> XpraSession:
    """起一个 xpra desktop session,**不等它** —— 等在调用方。"""
    ok, why = available()
    if not ok:
        raise unavailable(
            "xpra", f"起不来 xpra:{why}",
            "Debian/Ubuntu:apt install xpra xvfb python3-pil;"
            "或者去掉 --transport xpra 用默认的 screencast")

    socket_dir = os.path.join("/tmp", f"webmuxd-xpra{display.lstrip(':')}")
    os.makedirs(socket_dir, exist_ok=True)
    os.makedirs(work, exist_ok=True)
    log_path = os.path.join(work, "xpra.log")

    argv = [
        "xpra", "start-desktop", display,
        f"--socket-dir={socket_dir}",
        f"--bind-ws=127.0.0.1:{ws_port}",
        "--html=off",                    # 它自带的客户端我们不要,我们自己写
        "--daemon=no",                   # **要它当我们的子进程活着**
        f"--resize-display={width}x{height}",
        "--sharing=yes",                 # 一个观看者一条上游连接
        "--exit-with-children=yes",      # chrome 没了 xpra 也就没意义了
        *OFF,
        f"--start-child={_quote(chrome_argv)}",
    ]
    with open(log_path, "ab", buffering=0) as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=log,
                                start_new_session=True)
    return XpraSession(proc=proc, display=display, ws_port=ws_port,
                       cdp_port=cdp_port, socket_dir=socket_dir,
                       log_path=log_path,
                       detail={"display": display, "xpra_ws_port": ws_port})


def stop(sess: XpraSession, timeout: float = 8) -> None:
    """停掉。**先用 `xpra stop` 好好说**,它会把 chrome 和 Xvfb 一起收干净;
    不听再 SIGTERM。

    > 这台机器上验过一件事:`pkill xpra` 会让整个 shell 拿到退出码 144。
    > **不要用 pkill。**
    """
    import contextlib
    with contextlib.suppress(Exception):
        subprocess.run(["xpra", "stop", sess.display,
                        f"--socket-dir={sess.socket_dir}"],
                       capture_output=True, timeout=timeout)
    with contextlib.suppress(Exception):
        sess.proc.wait(timeout=3)
    if sess.proc.poll() is None:
        with contextlib.suppress(Exception):
            sess.proc.terminate()
            sess.proc.wait(timeout=3)
    if sess.proc.poll() is None:
        with contextlib.suppress(Exception):
            sess.proc.kill()


def tail(path: str, lines: int = 6) -> str:
    """xpra 起不来的原因就写在它的日志里。和 [process.py](runtime/process.py)
    那条是同一个教训:**扔掉日志等于把排查工作原样退回给人**。"""
    try:
        with open(path, "rb") as f:
            text = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    keep = [ln.strip() for ln in text.splitlines()
            if ln.strip() and not ln.startswith("  ")]
    return "\n     ".join(keep[-lines:])
