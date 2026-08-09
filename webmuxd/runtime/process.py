"""`process` runtime —— 直接在本机拉起来,不要 docker。

**秒起,但没有隔离** —— 页面跑在你自己机器上。开发和 CI 用它;
生产用 `container`。

它是 server 的子进程,所以 **`kill-server` 之后跟着死** ——
这点和 tmux 的 pane 一样(works/05 §3.2)。
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from typing import Any

from webmuxd import env
from webmuxd.runtime.base import (
    Handle, require_ports, unavailable, wait_http, wait_port,
)

CHROMIUM_NAMES = ("chromium-browser", "chromium", "chromium-freeworld")
#: VNC 那半边。没有它就只有 API,**画面是空的** —— 这件事要说出来,不能装作没有。
VNC_NAMES = ("Xvnc", "Xtigervnc", "Xvfb")


class ProcessRuntime:
    name = "process"

    def available(self) -> tuple[bool, str]:
        # 现探。**`install` 不记 chromium** —— 它只回答 docker 和镜像那两个
        # 问题(cli/install.md §2),而 `shutil.which` 本来就不值得记
        if not _which(CHROMIUM_NAMES):
            return False, ("本机没有 chromium。装一个,或者改用 runtime=container "
                           "(那样浏览器在镜像里)")
        return True, ""

    def _chromium(self) -> str | None:
        p = os.environ.get("WEBMUXD_CHROMIUM")
        if p:
            if os.path.exists(p):
                return p
            raise unavailable(self.name, env.stale_hint(f"chromium 在 {p}"),
                              "跑 `webmuxd install` 重新探")
        return _which(CHROMIUM_NAMES)

    def start(self, id: str, *, api_port: int, vnc_port: int,
              url: str = "about:blank", viewport: str = "1280x800",
              proxy: str | None = None, data_dir: str | None = None,
              **_opts: Any) -> Handle:
        ok, why = self.available()
        if not ok:
            raise unavailable(self.name, why, "改用 runtime=container")
        require_ports(api_port)

        chromium = self._chromium()
        vnc = _which(VNC_NAMES)
        work = data_dir or tempfile.mkdtemp(prefix=f"webmuxd-{id}-")
        os.makedirs(work, exist_ok=True)
        cdp_port = _free_port()
        notes: list[str] = []

        procs: dict[str, subprocess.Popen] = {}
        display = None
        if vnc and vnc.endswith(("Xvnc", "Xtigervnc")):
            display = _free_display()
            procs["vnc"] = subprocess.Popen(
                [vnc, display, "-geometry", viewport, "-rfbport", str(vnc_port),
                 "-SecurityTypes", "None", "-AlwaysShared"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
            wait_port(vnc_port, 10)
        else:
            # **说出来**:没有 VNC 就没有画面,只有 API。装作有画面比没画面更糟。
            notes.append("本机没有 Xvnc,这个 session 只有 API 没有画面 —— "
                         "人看不了,`vnc_url` 是空的")

        args = [chromium, "--no-sandbox", "--disable-gpu",
                f"--remote-debugging-port={cdp_port}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={os.path.join(work, 'profile')}",
                "--disable-infobars", "--disable-session-crashed-bubble",
                f"--window-size={viewport.replace('x', ',')}"]
        if proxy:
            args.append(f"--proxy-server={proxy}")
        if display is None:
            args.append("--headless=new")
        args.append(url)

        child_env = dict(os.environ)
        if display:
            child_env["DISPLAY"] = display
        # `start_new_session` —— 脱离调用者的进程组。CLI 是一次性的命令,
        # 不脱离的话 `webmuxd new` 一退出就把刚起的浏览器带走了。
        procs["chromium"] = subprocess.Popen(args, env=child_env,
                                             stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL,
                                             start_new_session=True)
        if not wait_port(cdp_port, 30):
            _kill_all(procs)
            raise unavailable(self.name, "chromium 起来了但 CDP 没监听",
                              "看看 --user-data-dir 那个目录能不能写")

        procs["sessiond"] = subprocess.Popen(
            [sys.executable, "-m", "webmuxd.serve",
             "--cdp", f"http://127.0.0.1:{cdp_port}",
             "--host", "127.0.0.1", "--port", str(api_port),
             "--data", os.path.join(work, "data")],
            env={**child_env, "PYTHONPATH": os.pathsep.join(sys.path)},
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        if not wait_http(f"http://127.0.0.1:{api_port}/healthz", 30):
            _kill_all(procs)
            raise unavailable(self.name, "sessiond 没起来",
                              "手工跑一遍 python -m webmuxd.serve 看报什么")

        return Handle(self.name, id, api_port, vnc_port if display else 0,
                      {"display": display, "cdp_port": cdp_port, "work": work,
                       "pids": {k: p.pid for k, p in procs.items()},
                       "notes": notes, "_procs": procs})

    def stop(self, handle: Handle) -> None:
        procs = handle.detail.get("_procs") or {}
        if procs:
            _kill_all(procs)
            return
        # 跨进程:只有 pid,按 pid 杀
        for pid in (handle.detail.get("pids") or {}).values():
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)

    def alive(self, handle: Handle) -> bool:
        procs = handle.detail.get("_procs") or {}
        p = procs.get("sessiond")
        if p is not None:
            return p.poll() is None
        # 别的进程起的(CLI 上一次调用)—— 只能看 pid 还在不在
        pid = (handle.detail.get("pids") or {}).get("sessiond")
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _kill_all(procs: dict) -> None:
    for p in procs.values():
        try:
            p.send_signal(signal.SIGTERM)
        except Exception:
            pass
    for p in procs.values():
        try:
            p.wait(timeout=5)
        except Exception:
            with_kill = getattr(p, "kill", None)
            if with_kill:
                with_kill()


def _which(names: tuple[str, ...]) -> str | None:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _free_display() -> str:
    for n in range(7, 100):
        if not os.path.exists(f"/tmp/.X11-unix/X{n}"):
            return f":{n}"
    raise unavailable("process", "找不到空闲的 X display", "清一清 /tmp/.X11-unix")
