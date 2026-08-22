"""**VNC 那条画面** —— 起一套 xpra,再按它那个 8 字节头协议转下来。

    Xvfb :N  +  xpra start-desktop :N  +  chrome --kiosk --display=:N

三个进程,但只有一个归我们管:**xpra 自己会拉起 Xvfb 和 chrome**
(`--start-child`),所以我们 Popen 一个、杀一个。

三条来自实测的硬规矩([e](../docs/v2/works/e-client.md)):

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

import asyncio
import contextlib
import logging
import os
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from typing import Any, Callable

import aiohttp
from aiohttp import WSMsgType, web

from webmuxd import models
from webmuxd.exceptions import unavailable

#: **虚拟显示由我们指定,不看发行版的配置。**
#:
#: xpra 用哪个 vfb 写在它自己的 `/etc/xpra/conf.d/55_server_x11.conf` 里,
#: **是打包方定的**:Debian 那边默认 `Xvfb`,RHEL 那边默认 `xpra_Xdummy`
#: (Xorg + dummy 驱动)。于是同一条命令在两台机器上跑的是两个不同的 X server,
#: 而 Xdummy 要装 Xorg —— 云主机上基本没有,报错是:
#:
#:     failed to locate Xorg binary to run
#:     Xvfb command has terminated! xpra cannot continue
#:
#: 更坏的是这**绕过了我们的探测**:`shutil.which("Xvfb")` 明明探到了,
#: xpra 转头去用 Xdummy,然后挂在别处。**探的东西和用的东西必须是同一个。**
#:
#: 所以钉死 Xvfb。屏幕开大是给 RandR 留余地,真实尺寸由 `--resize-display` 定。
XVFB = ("Xvfb -screen 0 8192x4096x24 +extension GLX +extension RANDR "
        "+extension RENDER +extension Composite -extension DOUBLE-BUFFER "
        "-nolisten tcp -noreset -auth $XAUTHORITY")

#: 起 xpra 时固定关掉的一堆。**我们只要像素**([c](../docs/v2/works/c-view.md))——
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
    # **软件 GL,显式指定。**
    #
    # 这台 Xvfb 上没有 GLX/DRI,而有头的 Chrome 不像 headless 那样会自己退到
    # SwiftShader —— 实测它直接把 WebGL 整个关掉(`SystemInfo.getInfo` 报
    # `webgl: disabled_off`)。**headless 那条有 WebGL,xpra 这条没有**,
    # 换默认的时候差点把这个功能弄丢。
    #
    # 而且 `--disable-gpu` **救不回来**:有头下它关得更彻底,WebGL 照样是 false。
    # 实测能用的只有下面这一组([c](../docs/v2/works/c-view.md))。
    "--use-gl=angle", "--use-angle=swiftshader",
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


def probe() -> models.XpraFact:
    """探出这台机器上 VNC 那条腿([d §1](../docs/v2/works/d-install.md#1-产出一份路径表))。

    **空 = 没探到。** 探不到的一律留空 —— 写一个猜的值,
    下次读的人分不清那是事实还是兜底。形状在
    [`models.XpraFact`](models.py):**记录里那一段就是它**,
    不是"探一个 dict 再由别人拼成记录"。
    """
    out: dict[str, str] = {}
    exe = shutil.which("xpra")
    if exe:
        out["bin"] = exe
        py = xpra_python(exe)
        if py:
            # **它自己的解释器,不是我们的** —— PIL 要装进这个里面
            out["python"] = py
        try:
            r = subprocess.run([exe, "--version"], capture_output=True,
                               text=True, timeout=10)
            ver = (r.stdout or r.stderr).strip().splitlines()
            if ver:
                out["version"] = ver[0].replace("xpra", "").strip() or ver[0].strip()
        except Exception:                       # noqa: BLE001
            pass                                # 版本探不到不影响能不能跑
    return models.XpraFact(bin=out.get("bin", ""), python=out.get("python", ""),
                           version=out.get("version", ""))


def available() -> tuple[bool, str]:
    """**探到才叫有。** 缺一样都起不来,而且报错要指名道姓。"""
    missing = []
    exe = shutil.which("xpra")
    if not exe:
        missing.append("xpra")
    if not shutil.which("Xvfb"):
        # 两个发行版家族的包名不一样,**都写出来** —— 只说一个的话
        # 另一边的人得自己去猜。
        missing.append("Xvfb(Debian/Ubuntu:xvfb;"
                       "RHEL/CentOS/Alibaba:xorg-x11-server-Xvfb)")

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
            "--window-position=0,0",
            # **多要 2 像素。** 实测 `--window-size=1024,768` 在 1024×768 的显示上
            # 拿到的是 **1023×767** —— 右边和下边各留一列纯黑(那是 X 根窗口)。
            # 多要两格,超出的部分被显示裁掉,画面正好铺满。
            f"--window-size={width + 2},{height + 2}"]
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
            "RHEL/CentOS/Alibaba:yum install xpra xorg-x11-server-Xvfb python3-pillow;"
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
        f"--xvfb={XVFB}",                # **不看发行版配置**,见 XVFB
        f"--resize-display={width}x{height}",
        "--sharing=yes",                 # 一个观看者一条上游连接
        "--exit-with-children=yes",      # chrome 没了 xpra 也就没意义了
        *OFF,
        f"--start-child={_quote(chrome_argv)}",
    ]
    with open(log_path, "ab", buffering=0) as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=log,
                                start_new_session=True)
    return XpraSession(proc=proc, display=display, ws_port=ws_port,   # noqa: E501
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


# --------------------------------------------------------------------------
# 上行中继 —— 观看端 → xpra(原 view/relay.py)
# --------------------------------------------------------------------------

log = logging.getLogger("webmuxd.xpra")

#: 8 字节头([e](../docs/v2/works/e-client.md))。
#: `!BBBBL` = 'P'、proto flags、压缩级别、**包数组下标**、大端长度。
HEADER = struct.Struct("!BBBBL")
MAGIC = ord("P")

#: **客户端能往 xpra 发的全部东西。** 每一条都写清楚不发会怎样 ——
#: 这张表是安全边界,不是配置。
ALLOWED = {
    "hello":            "握手。不发连不上",
    "map-window":       "告诉服务端我在看。**不发一帧都不来**",
    "focus":            "键盘焦点。我们不用键盘走这条,但协议要",
    "damage-sequence":  "帧 ack。这是 xpra 的背压,对应我们的环 B",
    "ping_echo":        "心跳回应。不发一段时间后被服务端断开",
    "disconnect":       "关页面时好好说一声",
}

#: 上行最大包长。握手那个 caps 字典是最大的一个,几 KB;
#: **给一个上限,别让代理成为一个内存放大器**。
MAX_UP = 256 * 1024


def packet_type(body: bytes) -> str | None:
    """从 rencodeplus 的载荷里读出包名。读不出来返回 `None`(→ 丢弃)。

    只认两种形状,因为包名总是个短字符串:

        192+n            定长数组,n 个元素
        59               变长数组,以 127 结尾
        128+n            定长字符串,n 字节
        "<len>:" + bytes 变长字符串
    """
    if not body:
        return None
    head = body[0]
    if head == 59:                                  # CHR_LIST
        i = 1
    elif 192 <= head <= 255:                        # LIST_FIXED_START + len
        i = 1
    else:
        return None
    if i >= len(body):
        return None
    b = body[i]
    if 128 <= b <= 191:                             # STR_FIXED_START + len
        n = b - 128
        return body[i + 1:i + 1 + n].decode("utf-8", "replace")
    if 0x30 <= b <= 0x39:                           # "<len>:" 变长字符串
        j = i
        while j < len(body) and 0x30 <= body[j] <= 0x39:
            j += 1
        if j >= len(body) or body[j] != ord(":"):
            return None
        n = int(body[i:j])
        return body[j + 1:j + 1 + n].decode("utf-8", "replace")
    return None


def screen(frame: bytes) -> tuple[bool, str]:
    """一个上行帧过不过。返回 `(放行, 理由)` —— **理由是给日志的,不是给客户端的**。

    拒绝的四种情况,每一种都不是"可能有问题",而是"我们的客户端不会这么发":
    """
    if len(frame) < HEADER.size:
        return False, "帧比头还短"
    magic, flags, level, index, size = HEADER.unpack_from(frame)
    if magic != MAGIC:
        return False, f"头一个字节不是 'P'({magic})"
    if level != 0:
        # 我们的客户端报 `compression_level: 0`,上行永远不压。
        return False, f"上行带压缩(level={level}),我们的客户端不会这么发"
    if index != 0:
        # 大块二进制是**下行**才有的(像素)。上行没有需要分块的东西。
        return False, f"上行带 chunk 下标({index}),没有该分块的上行包"
    if size > MAX_UP or HEADER.size + size != len(frame):
        return False, f"长度对不上(声明 {size},实到 {len(frame) - HEADER.size})"
    t = packet_type(frame[HEADER.size:])
    if t is None:
        return False, "解不出包名"
    if t not in ALLOWED:
        return False, f"不在白名单里:{t}"
    return True, t


async def pump(request: web.Request, upstream_url: str, *,
               on_reject: Callable[[str], None] | None = None) -> web.WebSocketResponse:
    """把浏览器那条 WS 和 xpra 那条接起来。

    **下行原样透传**(像素,一个字节都不动),**上行过白名单**。
    """
    # **`heartbeat=None`,不是 0。** aiohttp 拿到 0 会 `call_later(0, ping)`,
    # 然后 pong 超时也是 0 —— 连上就立刻判定超时关掉。心跳由 xpra 自己的
    # `ping` / `ping_echo` 做(works/12 §7),这一层不要再加一份。
    ws = web.WebSocketResponse(heartbeat=None, max_msg_size=0,
                               protocols=("binary",))
    await ws.prepare(request)

    rejected: dict[str, int] = {}

    def reject(why: str) -> None:
        rejected[why] = rejected.get(why, 0) + 1
        if rejected[why] == 1:              # **一种理由只吵一次**
            log.warning("xpra 上行丢弃:%s", why)
            if on_reject:
                on_reject(why)

    session = aiohttp.ClientSession()
    try:
        async with session.ws_connect(upstream_url, protocols=("binary",),
                                      max_msg_size=0, heartbeat=None) as up:
            async def down() -> None:
                async for msg in up:
                    if msg.type is WSMsgType.BINARY:
                        await ws.send_bytes(msg.data)
                    elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                        break
                with contextlib.suppress(Exception):
                    await ws.close()

            task = asyncio.create_task(down())
            try:
                async for msg in ws:
                    if msg.type is not WSMsgType.BINARY:
                        if msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break
                        continue
                    ok, why = screen(msg.data)
                    if ok:
                        await up.send_bytes(msg.data)
                    else:
                        reject(why)
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    except aiohttp.ClientError as e:
        log.error("连不上 xpra(%s):%s", upstream_url, e)
        with contextlib.suppress(Exception):
            await ws.close(code=1011, message=b"xpra upstream unreachable")
    finally:
        await session.close()
    if rejected:
        log.info("这条 xpra 连接一共丢了 %d 个上行包:%s",
                 sum(rejected.values()), rejected)
    return ws
