"""换一条像素来源 —— 对着 docs/v2/works/11 · 12 校。

**大部分用例不需要真的跑 xpra。** 白名单、编解码、语法、参数拼装都是纯逻辑,
真起一个 Xvfb + xpra 才能测的那几条单独标出来,装了就跑,没装就说没装。
"""

import json
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from webmuxd import xpra as xpra_mod
from webmuxd.view import relay

STATIC = Path(__file__).resolve().parents[2] / "webmuxd" / "view" / "static"
NODE = shutil.which("node")

try:
    from xpra.net.rencodeplus.rencodeplus import dumps as rdumps
except ImportError:                                       # pragma: no cover
    rdumps = None


def frame(body: bytes, *, level: int = 0, index: int = 0, magic: int = 0x50) -> bytes:
    return struct.pack("!BBBBL", magic, 0x10, level, index, len(body)) + body


def packet(obj) -> bytes:
    """用**真的** rencodeplus 编 —— 手搓的字节只能证明我们自洽。"""
    if rdumps is None:
        pytest.skip("本机没装 xpra 的 python 包,编不出真包")
    return frame(rdumps(obj))


# ------------------------------------------------------------------ 上行白名单

@pytest.mark.parametrize("p", [
    ["hello", {"version": "6.6"}],
    ["map-window", 4194308, 0, 0, 1024, 768, {}],
    ["focus", 1, []],
    ["damage-sequence", 12, 1, 1024, 768, 5, ""],
    ["ping_echo", 12345, 0, 0, 0, -1],
    ["disconnect", "bye"],
])
def test_协议要的那六个包放行(p):
    ok, why = relay.screen(packet(p))
    assert ok, why
    assert why == p[0]


@pytest.mark.parametrize("p", [
    ["button-action", 1, 1, True, (10, 20), []],
    ["key-action", 1, "a", True, [], 97, "a", 38, 0],
    ["pointer-position", 1, (10, 20), [], []],
    ["wheel-motion", 1, 4, 1.0, (10, 20), []],
])
def test_输入包一个都过不去(p):
    """[03 §1](../../docs/v2/works/03-input.md) 的收口在这条路上的落点。

    观看者能表达的意图只有 CDP `Input` 那四个命令 —— xpra 自带的输入协议
    要是能过去,这个边界就破了。
    """
    ok, why = relay.screen(packet(p))
    assert not ok
    assert "不在白名单里" in why


@pytest.mark.parametrize("p", [
    ["clipboard-token", "CLIPBOARD"],
    ["send-file", "x", 1, b"y"],
    ["shutdown-server"],
    ["start-command", "sh", ["sh"], True],
])
def test_剪贴板文件传输和执行命令也过不去(p):
    ok, why = relay.screen(packet(p))
    assert not ok


def test_没见过的包类型默认被拒_这就是白名单和黑名单的差别():
    ok, why = relay.screen(packet(["some-future-packet-xpra-7", 1]))
    assert not ok
    # **不需要我们提前知道它叫什么。** 黑名单会放行它。
    assert "some-future-packet-xpra-7" in why


def test_上行带压缩或者带分块下标都拒():
    body = rdumps(["hello", {}]) if rdumps else pytest.skip("没有 xpra 包")
    assert relay.screen(frame(body, level=0x10))[0] is False
    assert relay.screen(frame(body, level=0x40))[0] is False
    # 大块二进制是**下行**才有的(像素)。上行没有该分块的东西。
    assert relay.screen(frame(body, index=7))[0] is False


def test_畸形帧不会把代理搞崩_只是被拒():
    for bad in [b"", b"P", b"P" * 7, frame(b"", magic=0x51),
                frame(b"\xff\xff\xff"), struct.pack("!BBBBL", 0x50, 0x10, 0, 0, 99) + b"x"]:
        ok, why = relay.screen(bad)
        assert ok is False and why


def test_超大的上行包拒掉_代理不当内存放大器():
    huge = frame(b"\xc2" + b"x" * (relay.MAX_UP + 10))
    assert relay.screen(huge)[0] is False


def test_白名单每一条都写了不发会怎样():
    """这张表是安全边界,**得能读**。"""
    assert set(relay.ALLOWED) == {
        "hello", "map-window", "focus", "damage-sequence", "ping_echo", "disconnect"}
    for k, why in relay.ALLOWED.items():
        assert len(why) > 4, k


def test_包名解析认识定长和变长两种字符串():
    # 定长:128+len;变长:"<len>:"
    assert relay.packet_type(bytes([192 + 1, 128 + 5]) + b"hello") == "hello"
    assert relay.packet_type(bytes([59]) + b"5:hello") == "hello"
    assert relay.packet_type(b"") is None
    assert relay.packet_type(bytes([1, 2, 3])) is None


# ------------------------------------------------------ xpra 模式下不发 screencast

class _FakeCDP:
    def __init__(self):
        self.sent = []
        self.handlers = {}

    def on(self, event, fn):
        self.handlers[event] = fn

    async def send(self, method, params=None, session_id=None):
        self.sent.append(method)
        return {}


class _FakeTab:
    target_id = "T1"


class _FakeTabs:
    active = "t_1"

    def get(self, _id):
        return _FakeTab()


class _FakeSession:
    def __init__(self):
        self.cdp = _FakeCDP()
        self.tabs = _FakeTabs()

    async def cdp_session_for(self, _tab):
        return "S1"


def _caster(transport):
    from webmuxd.view.cast import Screencaster
    return Screencaster(_FakeSession(), transport=transport)


async def test_xpra_模式下一条_startScreencast_都不发():
    """**两条都开着等于同一份画面编码两遍。**"""
    c = _caster("xpra")
    c.viewers.add(object())
    await c.follow("t_1", force=True)
    assert not any("Screencast" in m for m in c.session.cdp.sent)


async def test_但是切_tab_照样_activateTarget():
    """画面跟着 tab 走,在两条路上是**同一个机制**(works/11 §4)。"""
    c = _caster("xpra")
    c.viewers.add(object())
    await c.follow("t_1", force=True)
    assert "Target.activateTarget" in c.session.cdp.sent


async def test_screencast_模式一切照旧():
    c = _caster("screencast")
    c.viewers.add(object())
    await c.follow("t_1", force=True)
    assert "Page.startScreencast" in c.session.cdp.sent
    assert "Target.activateTarget" in c.session.cdp.sent


async def test_xpra_下不改视口_尺寸是那个_X_显示说了算():
    """再发 setDeviceMetricsOverride,页面会被渲染成另一个尺寸而窗口不变。"""
    c = _caster("xpra")
    await c.resize(800, 600)
    assert (c.width, c.height) == (1024, 768)
    assert not any("Emulation" in m for m in c.session.cdp.sent)


def test_状态里报的出来现在走的是哪条():
    """**报的是使用者看得见的那个词。** 旧名字进得来,但不再回传出去 ——
    回传旧词等于承认有两套叫法(c §9.1)。"""
    assert _caster("xpra").stats()["transport"] == "vnc"
    assert _caster("screencast").stats()["transport"] == "jpg"
    assert _caster("rrweb").stats()["mode_label"] == "DOM"


def test_旧名字还认_但一律归一到新词():
    """`--transport xpra` 已经写进别人的脚本了,**不能说不认就不认**;
    但归一之后全程只用新词,不让两套叫法在系统里并存。"""
    from webmuxd.view import modes
    for old, new in (("screencast", "jpg"), ("cdp", "jpg"), ("xpra", "vnc"),
                     ("rrweb", "dom"), ("JPG", "jpg"), (" vnc ", "vnc")):
        assert modes.canon(old) == new, old
    assert modes.canon("mp4") is None          # 不认识就说不认识,不猜


def test_能用哪几种是起的时候定的():
    """**VNC 要一个真实的 X 显示,无头浏览器没有。**
    所以那个选择不是"用哪种",是"以后能选哪几种"(c §9.3)。"""
    from webmuxd.view import modes
    assert modes.available_in(headed=True) == ("vnc", "jpg", "dom")
    assert "vnc" not in modes.available_in(headed=False)
    assert "vnc" not in modes.available_in(headed=True, remote=True)
    # 另外两条不依赖系统里的东西,**在哪都在**
    for where in (dict(headed=True), dict(headed=False),
                  dict(headed=True, remote=True)):
        assert {"jpg", "dom"} <= set(modes.available_in(**where))


# ------------------------------------------------------------------ 起浏览器

def test_xpra_下的浏览器不带_bar_起():
    """`--kiosk` 是"没有 crop_top 这回事"的前提(works/12 §10)。"""
    argv = xpra_mod.build_chrome_argv("/x/chrome", cdp_port=9222, profile="/p",
                                      url="about:blank", width=1024, height=768)
    assert "--kiosk" in argv
    # 这两条按下那 55 像素的提示条,不按下去 kiosk 也白搭
    assert "--test-type" in argv and "--disable-infobars" in argv
    # **不是 headless** —— xpra 要截的是真窗口
    assert not any("headless" in a for a in argv)
    assert "--remote-debugging-port=9222" in argv


def test_root_下才加_no_sandbox_而且是显式传进来的():
    a = xpra_mod.build_chrome_argv("/x/chrome", cdp_port=1, profile="/p",
                                   url="u", width=1, height=1, no_sandbox=False)
    assert "--no-sandbox" not in a
    b = xpra_mod.build_chrome_argv("/x/chrome", cdp_port=1, profile="/p",
                                   url="u", width=1, height=1, no_sandbox=True)
    assert "--no-sandbox" in b


def test_只要像素_剪贴板音频文件传输全在启动时关掉():
    """**关在服务端**,不是靠客户端不去用它(works/11 §5)。"""
    joined = " ".join(xpra_mod.OFF)
    for off in ("clipboard", "file-transfer", "printing", "speaker", "webcam"):
        assert off in joined


def test_显示号看_socket_文件不看进程(tmp_path, monkeypatch):
    import os
    real = os.path.exists
    monkeypatch.setattr(os.path, "exists",
                        lambda p: True if p.endswith(("X80", "X81")) else real(p))
    assert xpra_mod.free_display(80, 90) == ":82"


def test_探不到就说缺什么_不猜(monkeypatch):
    monkeypatch.setattr(xpra_mod.shutil, "which", lambda n: None)
    ok, why = xpra_mod.available()
    assert not ok
    assert "xpra" in why and "Xvfb" in why


# ------------------------------------------------------------------ 客户端的 js

def _script_of(html: Path) -> str:
    m = re.search(r"<script>(.*)</script>", html.read_text(), re.S)
    assert m, "观看页里没有 <script>"
    return m.group(1)


JS_FILES = ["xpra.js", "rencode.js"]


def test_注释里不许藏着代码():
    """**0.5.5 真的发生过**:删一个分支时,`} else if (...) {` 被写进了上一行注释,
    整个 `<script>` 变成语法错,画面页彻底不工作 —— 而且发了两个版本没人发现。

    这一条不依赖 node,永远会跑。
    """
    files = [STATIC / "index.html"] + [STATIC / f for f in JS_FILES]
    for f in files:
        for i, line in enumerate(f.read_text().splitlines(), 1):
            s = line.strip()
            if not s.startswith("//"):
                continue
            assert ") {" not in s and "} else" not in s, \
                f"{f.name}:{i} 注释里像是吞了一行代码:{s}"


@pytest.mark.skipif(not NODE, reason="本机没有 node —— 语法这一层只剩上面那条启发式")
def test_观看页和客户端的_js_能被解析():
    """`node --check`。**这是上一条测不到的那部分。**"""
    src = _script_of(STATIC / "index.html")
    p = Path(subprocess.run(["mktemp", "--suffix=.js"], capture_output=True,
                            text=True).stdout.strip())
    try:
        p.write_text(src)
        r = subprocess.run([NODE, "--check", str(p)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
    finally:
        p.unlink(missing_ok=True)
    for f in JS_FILES:                      # 这两个是 ES module
        r = subprocess.run([NODE, "--input-type=module", "-e",
                            f"await import('{STATIC / f}')"],
                           capture_output=True, text=True)
        assert r.returncode == 0, f + ": " + r.stderr


@pytest.mark.skipif(not NODE or rdumps is None, reason="要 node 和 xpra 的 python 包")
@pytest.mark.parametrize("obj", [
    ["hello", {"version": "6.6", "n": 7, "f": False, "neg": -5, "big": 4194308,
               "l": [1, 2, 3], "nested": {"a": {"b": 1}}}],
    ["map-window", 4194308, 0, 0, 1024, 768, {}],
    ["damage-sequence", 99, 1, 1024, 768, 5, ""],
    ["ping_echo", 12345, 0, 0, 0, -1],
])
def test_js_编的包_python_解得开(obj):
    """**自己写协议客户端之后唯一的风险点。** 两边对不上就是画面不动,
    而且报错会指向完全不相干的地方。"""
    from xpra.net.rencodeplus.rencodeplus import loads
    r = subprocess.run(
        [NODE, "--input-type=module", "-e",
         f"const m=await import('{STATIC / 'rencode.js'}');"
         f"console.log(JSON.stringify(Array.from(m.rencode({json.dumps(obj)}))))"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = loads(bytes(json.loads(r.stdout)))
    assert json.loads(json.dumps(got, default=list)) == obj
    # 顺带:它必须能过我们自己的白名单
    assert relay.screen(frame(bytes(json.loads(r.stdout))))[0] is True


@pytest.mark.skipif(not NODE or rdumps is None, reason="要 node 和 xpra 的 python 包")
def test_python_编的包_js_解得开():
    cases = [
        ("draw", 1, 0, 0, 1024, 768, "webp", b"", 7, 4096, {"quality": 80, "frame": 3}),
        ("new-window", 4194308, 0, 0, 1024, 768, {"title": "T", "has-alpha": False}, {}),
        ("hello", {"desktop_size": (1024, 768), "f": 1.5, "neg": -300, "big": 2 ** 40}),
        ("ping", 1755500000000, 1, 2, 3),
    ]
    blobs = json.dumps([list(rdumps(c)) for c in cases])
    r = subprocess.run(
        [NODE, "--input-type=module", "-e",
         f"const m=await import('{STATIC / 'rencode.js'}');"
         f"const bs={blobs};"
         "console.log(JSON.stringify(bs.map(b=>m.rdecode(Uint8Array.from(b))),"
         "(k,v)=>v instanceof Uint8Array?'<bytes>':v))"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert got[0][:7] == ["draw", 1, 0, 0, 1024, 768, "webp"]
    assert got[1][6]["title"] == "T" and got[1][6]["has-alpha"] is False
    assert got[2][1]["neg"] == -300 and got[2][1]["big"] == 2 ** 40
    assert got[3] == ["ping", 1755500000000, 1, 2, 3]


def test_客户端不报视频编码_所以不用背_webcodecs():
    """服务端只发客户端报过的(works/12 §8)。这条声明就是"要写多少代码"的开关。"""
    src = (STATIC / "xpra.js").read_text()
    assert "full_csc_modes" not in src.split("//")[0] or "不报 full_csc_modes" in src
    assert "h264" not in re.sub(r"//.*", "", src)
    assert "VideoDecoder" not in src


def test_客户端只写了那六种包的发送代码():
    """**少写一行发送代码,那边就少一条能过的路。**"""
    src = re.sub(r"//.*", "", (STATIC / "xpra.js").read_text())
    sent = set(re.findall(r'_send\(\["([a-z_-]+)"', src))
    assert sent == set(relay.ALLOWED), sent


# ------------------------------------------------------------------ 不静默降级

def test_remote_上没有_xpra_这条路_而且要说清为什么():
    """**悄悄给一个 screencast 的画面,等于让人以为自己在看 xpra 的画质。**"""
    from webmuxd.errors import RuntimeUnavailable
    from webmuxd.runtime.remote import RemoteRuntime
    with pytest.raises(RuntimeUnavailable) as ei:
        RemoteRuntime().start("x", port=1, cdp="http://x", transport="xpra")
    assert "VNC" in ei.value.message
    assert "CDP" in str(ei.value.details)          # 说清了为什么做不到


def test_xpra_装不上时报错要指名道姓(monkeypatch):
    from webmuxd.errors import RuntimeUnavailable
    monkeypatch.setattr(xpra_mod.shutil, "which", lambda n: None)
    with pytest.raises(RuntimeUnavailable) as ei:
        xpra_mod.start(display=":99", ws_port=1, cdp_port=2, chrome_argv=["x"],
                       width=1, height=1, work="/tmp/x")
    # 缺什么、怎么装、以及"不想装可以走哪条"
    assert "apt install" in str(ei.value.details) or "apt install" in ei.value.message
    assert "screencast" in str(ei.value.details) + ei.value.message


# ------------------------------------------------------------------ rgb 解码

RGB_PROBE = """
globalThis.ImageData = class {{ constructor(d,w,h){{ this.data=d; this.width=w; this.height=h; }} }};
const {{ XpraClient }} = await import("{static}/xpra.js");
const c = new XpraClient("ws://x", {{ width:0, height:0, getContext: () => ({{}}) }}, {{}});
const out = c._rgb(Uint8Array.from({data}), {w}, {h}, {{rgb_format:"{fmt}"}}, {stride});
console.log(JSON.stringify(Array.from(out.data)));
"""


def _rgb(data, w, h, fmt, stride):
    r = subprocess.run([NODE, "--input-type=module", "-e",
                        RGB_PROBE.format(static=STATIC, data=list(data), w=w, h=h,
                                         fmt=fmt, stride=stride)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="要 node")
def test_rgb_的_rowstride_来自包的第九格_不是_options():
    """**拿错了整张图会斜掉。** rowstride 是 `draw[9]`,不在 options 里 ——
    而且它不等于 `w*4`:服务端会按 4 字节对齐补 padding。
    """
    # 2×2 的 RGBX,每行 12 字节(实际只用 8),红 绿 / 蓝 (10,20,30)
    stride, data = 12, bytearray(24)
    for i, px in enumerate([(255, 0, 0), (0, 255, 0), (0, 0, 255), (10, 20, 30)]):
        o = (i // 2) * stride + (i % 2) * 4
        data[o:o + 3] = bytes(px)
    got = _rgb(data, 2, 2, "RGBX", stride)
    assert got == [255, 0, 0, 255, 0, 255, 0, 255,
                   0, 0, 255, 255, 10, 20, 30, 255]


@pytest.mark.skipif(not NODE, reason="要 node")
def test_通道次序按服务端说的来_不猜():
    """BGRX 的第一个字节是蓝。猜成 RGB 的话红蓝互换 —— 而这种错**看起来
    像是"颜色有点怪"**,不像 bug,能活很久。"""
    got = _rgb(bytes([255, 0, 0, 0, 0, 0, 255, 0]), 2, 1, "BGRX", 8)
    assert got == [0, 0, 255, 255, 255, 0, 0, 255]


@pytest.mark.skipif(not NODE, reason="要 node")
def test_没有_alpha_的格式要补成不透明():
    got = _rgb(bytes([1, 2, 3, 0]), 1, 1, "RGBX", 4)
    assert got[3] == 255
    got = _rgb(bytes([1, 2, 3, 128]), 1, 1, "RGBA", 4)
    assert got[3] == 128


def test_dsf_在_xpra_上没用_就要报错而不是悄悄吃掉():
    """**给了却不起作用,比报错难查得多。**"""
    from webmuxd.errors import RuntimeUnavailable
    from webmuxd.runtime.process import ProcessRuntime
    with pytest.raises(RuntimeUnavailable) as ei:
        # 参数校验在最前面,所以既不会去找浏览器也不会去占端口
        ProcessRuntime().start("x", port=65000, transport="xpra", dsf=2.0)
    assert "dsf" in ei.value.message
    assert "window-size" in str(ei.value.details)         # 说了等价的做法


# ------------------------------------------------- 探的是"跑 xpra 的那个 python"

def test_探_PIL_要探跑_xpra_的那个解释器_不是我们自己的(tmp_path):
    """**webmuxd 很可能装在 venv 里,而 `xpra` 是带 shebang 的系统脚本。**

    拿我们自己的 `import PIL` 判断,两个方向都会错:venv 里没有而系统有
    (拦下一个本来能跑的模式),或者反过来(说能跑,起的时候才炸)。
    """
    fake = tmp_path / "xpra"
    fake.write_text("#!/opt/weird/python3.11\nprint('x')\n")
    fake.chmod(0o755)
    assert xpra_mod.xpra_python(str(fake)) == "/opt/weird/python3.11"

    # `#!/usr/bin/env python3` 这种形式,真正的解释器是第二个词
    fake.write_text("#!/usr/bin/env python3.12\n")
    assert xpra_mod.xpra_python(str(fake)) == "python3.12"


def test_读不出_shebang_就说不知道_而不是猜(tmp_path):
    """**不知道就不要拿一个猜的答案去挡人。**"""
    binary = tmp_path / "xpra"
    binary.write_bytes(b"\x7fELF\x02\x01\x01\x00")
    assert xpra_mod.xpra_python(str(binary)) is None
    assert xpra_mod.xpra_python(str(tmp_path / "不存在")) is None


def test_那个解释器里没有_PIL_才报缺_而且要说在哪装(tmp_path, monkeypatch):
    fake = tmp_path / "xpra"
    fake.write_text("#!" + str(tmp_path / "nopil") + "\n")
    nopil = tmp_path / "nopil"
    nopil.write_text("#!/bin/sh\nexit 1\n")          # 任何 import 都失败
    nopil.chmod(0o755)
    monkeypatch.setattr(xpra_mod.shutil, "which",
                        lambda n: str(fake) if n == "xpra" else "/usr/bin/" + n)
    ok, why = xpra_mod.available()
    assert not ok and "PIL" in why
    assert str(nopil) in why, "得说清是哪个解释器缺它"


def test_窗口比显示多要两格_否则右下会有一条黑边():
    """实测:`--window-size=1024,768` 在 1024×768 的显示上拿到的是 **1023×767**,
    右边和下边各留一列纯黑(那是 X 根窗口露出来了,像素值实测 (0,0,0))。

    多要两格之后 Chrome 拿到的正好是 1026×770,超出显示的部分被裁掉,
    **画面铺满**。代价写在明处:页面视口是 1026×770,右下各 2 像素在可见区域外。
    """
    argv = xpra_mod.build_chrome_argv("/x/chrome", cdp_port=1, profile="/p",
                                      url="u", width=1024, height=768)
    assert "--window-size=1026,770" in argv


# ------------------------------------------------- 虚拟显示由我们指定,不看发行版

def test_虚拟显示钉死_Xvfb_不看发行版的配置(tmp_path, monkeypatch):
    """**同一份 xpra,vfb 是打包方定的。**

    Debian 那边默认 `Xvfb`,RHEL 那边默认 `xpra_Xdummy`(Xorg + dummy 驱动),
    而 Xdummy 要装 Xorg —— 云主机上基本没有,真机上报的是
    `failed to locate Xorg binary to run` + `vfb failed to start`。

    更坏的是这**绕过探测**:`which("Xvfb")` 明明探到了,xpra 转头去用 Xdummy。
    **探的东西和用的东西必须是同一个**,所以自己指定。
    """
    seen = {}

    class FakePopen:
        def __init__(self, argv, **kw):
            seen["argv"] = argv
            self.pid = 1

        def poll(self):
            return None

    monkeypatch.setattr(xpra_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(xpra_mod, "available", lambda: (True, ""))
    xpra_mod.start(display=":99", ws_port=1, cdp_port=2, chrome_argv=["/x/chrome", "u"],
                   width=1024, height=768, work=str(tmp_path))

    xvfb = [a for a in seen["argv"] if a.startswith("--xvfb=")]
    assert xvfb, "没有指定 vfb —— 那就是把选择权交回给发行版了"
    assert xvfb[0].startswith("--xvfb=Xvfb "), xvfb[0]
    assert "Xdummy" not in xvfb[0] and "Xorg" not in xvfb[0]
    # 真实尺寸由 resize-display 定,屏幕开大是给 RandR 留余地
    assert f"--resize-display=1024x768" in seen["argv"]


def test_缺_Xvfb_时两个发行版家族的包名都要说(monkeypatch):
    """只说一个的话,另一边的人得自己去猜。"""
    monkeypatch.setattr(xpra_mod.shutil, "which",
                        lambda n: None if n == "Xvfb" else "/usr/bin/" + n)
    ok, why = xpra_mod.available()
    assert not ok
    assert "xvfb" in why and "xorg-x11-server-Xvfb" in why


def test_起不来时先说清是哪一层没起来():
    """**头一句话指错方向,后面的日志再全也白搭。**

    真机上看到的是"xpra 起来了但浏览器的 CDP 没监听",而实际是虚拟显示没起来、
    xpra 自己就退了 —— 那句话把人往浏览器的方向指,问题在 X 那一层。
    """
    src = (Path(__file__).resolve().parents[2] / "webmuxd" / "runtime" /
           "process.py").read_text()
    assert "sess.proc.poll() is not None" in src, "没有区分 xpra 死没死"
    assert "xpra 自己退了" in src and "虚拟显示" in src


# ------------------------------------------------------------------ 默认是 xpra

def test_默认走_vnc():
    """VNC 按 damage 区域编码,滚动时 `scroll` 包零字节搬像素(c §4.1)——
    这是默认值该给的东西。"""
    from webmuxd.runtime.process import resolve_transport
    assert resolve_transport(None) == "vnc"


def test_显式给的赢():
    from webmuxd.runtime.process import resolve_transport
    assert resolve_transport("jpg") == "jpg"
    assert resolve_transport("vnc") == "vnc"
    assert resolve_transport("dom") == "dom"
    assert resolve_transport("screencast") == "jpg"     # 旧名字照样赢


def test_不认识的画面名要报错_不能悄悄给一个默认():
    """**给了个我们不认识的词,就是写错了。** 悄悄换成默认的那条,
    等于让人以为自己在看另一种画面。"""
    from webmuxd.errors import UsageError
    from webmuxd.runtime.process import resolve_transport
    with pytest.raises(UsageError) as ei:
        resolve_transport("mp4")
    for word in ("JPG", "VNC", "DOM"):                  # 报错里要写清有哪几种
        assert word in ei.value.message


def test_xpra_起不来时报错_不静默退回_screencast(monkeypatch):
    """**静默退回等于让你以为自己在看 xpra 的画质。**

    退路是显式说一声,不是我们替你决定 —— 所以那句话里既要有"怎么装",
    也要有"不想装走哪条"。
    """
    from webmuxd.errors import RuntimeUnavailable
    from webmuxd.runtime.process import resolve_transport
    monkeypatch.setattr(xpra_mod.shutil, "which",
                        lambda n: None if n == "Xvfb" else "/usr/bin/" + n)
    with pytest.raises(RuntimeUnavailable) as ei:
        resolve_transport(None)
    assert "默认走 VNC" in ei.value.message
    hint = str(ei.value.details)
    assert "webmuxd install" in hint            # 怎么装
    assert "jpg" in hint and "dom" in hint      # 不想装的话还有哪两条


def test_remote_上少一个选项不是降级_是那条路上的全集():
    """**这不是"降级"。** 我们手里只有一个 CDP 端点,那台机器上的 X 显示
    碰不到 —— JPG 和 DOM 就是那条路上的全部(c §9.3)。"""
    import inspect
    from webmuxd.runtime.remote import RemoteRuntime
    src = inspect.getsource(RemoteRuntime.start)
    assert "modes.available_in(headed=False, remote=True)" in src
    assert "modes.JPG" in src
    assert inspect.signature(RemoteRuntime.start).parameters["transport"].default is None


def test_dsf_报错要说清_xpra_是你选的还是默认来的(monkeypatch):
    """没说要 VNC 的人被告知"dsf 在 VNC 上没用",第一反应是"我什么时候要 VNC 了"。"""
    from webmuxd.errors import RuntimeUnavailable
    from webmuxd.runtime.process import ProcessRuntime
    with pytest.raises(RuntimeUnavailable) as ei:
        ProcessRuntime().start("x", port=65010, dsf=2.0)
    assert "默认的 VNC" in ei.value.message
    with pytest.raises(RuntimeUnavailable) as ei:
        ProcessRuntime().start("x", port=65010, dsf=2.0, transport="xpra")
    assert "--transport vnc" in ei.value.message
    assert "--transport jpg" in str(ei.value.details)  # 要 dsf 该走哪条


# --------------------------------------------------------------- install 装依赖

def test_两个发行版家族的包名是真的不一样():
    """**这不是换个前缀就完了。** 撞了才知道:RHEL 那边 Xvfb 的包名是
    `xorg-x11-server-Xvfb`,Pillow 是 `python3-pillow`。"""
    from webmuxd.cli import deps
    assert deps.APT.xpra == ("xpra", "xvfb", "python3-pil")
    assert deps.YUM.xpra == ("xpra", "xorg-x11-server-Xvfb", "python3-pillow")
    assert deps.DNF.xpra == deps.YUM.xpra
    # chrome 的共享库两边一个都对不上
    assert not set(deps.APT.chrome) & set(deps.YUM.chrome)
    assert "mesa-libgbm" in deps.YUM.chrome and "libgbm1" in deps.APT.chrome


def test_装不上要分清是没这个包还是没权限(monkeypatch):
    """**两者的下一步完全不同**:前者要加软件源,后者要 sudo。"""
    from webmuxd.cli import deps

    class R:
        def __init__(self, rc, err): self.returncode, self.stderr, self.stdout = rc, err, ""

    monkeypatch.setattr(deps.subprocess, "run",
                        lambda *a, **k: R(1, "No match for argument: xpra"))
    ok, why = deps.apply(deps.YUM, deps.YUM.xpra)
    assert not ok and "源里没有" in why
    assert deps.XPRA_REPO in why, "RHEL 上 xpra 不在基础源里,得说去哪加源"

    monkeypatch.setattr(deps.subprocess, "run",
                        lambda *a, **k: R(1, "Permission denied"))
    ok, why = deps.apply(deps.APT, deps.APT.xpra)
    assert not ok and "没权限" in why


def test_没有_root_时只打印_而且给完整的那一行(monkeypatch):
    """**"装一下依赖"不是提示,一整行命令才是。**"""
    import io
    from webmuxd.cli import deps, install as ins
    monkeypatch.setattr(deps, "can_root", lambda: False)
    monkeypatch.setattr(deps, "detect", lambda: deps.YUM)
    monkeypatch.setattr(deps, "apply", lambda *a, **k: pytest.fail("没 root 还去装了"))
    monkeypatch.setattr(xpra_mod, "available", lambda: (False, "缺:Xvfb"))
    out = io.StringIO()
    ins.install(out=out)
    text = out.getvalue()
    assert "sudo yum install -y -q xpra xorg-x11-server-Xvfb python3-pillow" in text
    assert "--transport jpg" in text, "得说清不想装可以走哪条"


def test_装完要重新探一遍_不看安装器的退出码(monkeypatch):
    """`apt-get` 返回 0 只说明命令没报错,不说明东西真的有了。
    **判据永远是探测结果。**"""
    import io
    from webmuxd.cli import deps, install as ins
    monkeypatch.setattr(deps, "can_root", lambda: True)
    monkeypatch.setattr(deps, "detect", lambda: deps.APT)
    monkeypatch.setattr(deps, "apply", lambda *a, **k: (True, ""))   # 装"成功"了
    monkeypatch.setattr(xpra_mod, "available", lambda: (False, "缺:Xvfb"))  # 但还是没有
    out = io.StringIO()
    ins.install(out=out)
    assert "装好了" not in out.getvalue(), "安装器说成功就信了"


# --------------------------------------------- 默认那条路上,那几条也得成立

def _fake_xpra_start(monkeypatch, tmp_path):
    """把 xpra 那条路上的三个外部动作都换掉,只留下"我们拼了什么参数"。"""
    from webmuxd.runtime import process as proc_mod
    seen = {}

    class FakePopen:
        def __init__(self, argv, **kw):
            seen.setdefault("argv", []).append(argv)
            self.pid = 1

        def poll(self): return None
        def send_signal(self, s): pass
        def wait(self, timeout=None): return 0
        def kill(self): pass

    monkeypatch.setattr(xpra_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(xpra_mod, "available", lambda: (True, ""))
    monkeypatch.setattr(xpra_mod, "stop", lambda *a, **k: None)
    monkeypatch.setattr(proc_mod, "wait_port", lambda *a, **k: True)
    monkeypatch.setattr(proc_mod, "wait_http", lambda *a, **k: True)
    monkeypatch.setattr(proc_mod, "spawn_sessiond", lambda *a, **k: FakePopen([]))
    monkeypatch.setattr(proc_mod.browser, "missing_libs", lambda p: [])
    monkeypatch.setattr(proc_mod.browser, "has_cjk_font", lambda: True)
    return seen


def test_默认那条路上_root_也要自动关沙箱并且说出来(monkeypatch, tmp_path):
    """**root + 沙箱没有能跑的配置**(crbug 638180)。这条在 screencast 那边
    有测试守着,而 0.7.0 之后**默认走的是 xpra** —— 默认那条不能没人看着。
    """
    import os as _os
    from webmuxd.runtime.process import ProcessRuntime
    seen = _fake_xpra_start(monkeypatch, tmp_path)
    monkeypatch.setattr(_os, "geteuid", lambda: 0)
    monkeypatch.delenv("WEBMUXD_NO_SANDBOX", raising=False)

    h = ProcessRuntime().start("x", port=65020, browser_path="/bin/true",
                               data_dir=str(tmp_path))
    child = [a for a in seen["argv"][0] if a.startswith("--start-child=")][0]
    assert "--no-sandbox" in child, "root 下不加的话浏览器根本起不来"
    assert any("沙箱是关着的" in n for n in h.detail["notes"]), "关了不说等于偷偷关"


def test_默认那条路上_绑非回环也要留一条警告(monkeypatch, tmp_path):
    """对外开放是**你的决定**,但不能悄悄发生 —— 换了默认 transport 不改变这条。"""
    from webmuxd.runtime.process import ProcessRuntime
    _fake_xpra_start(monkeypatch, tmp_path)
    h = ProcessRuntime().start("x", port=65021, browser_path="/bin/true",
                               data_dir=str(tmp_path), bind="0.0.0.0")
    assert any("0.0.0.0" in n for n in h.detail["notes"]), h.detail["notes"]
    h2 = ProcessRuntime().start("y", port=65022, browser_path="/bin/true",
                                data_dir=str(tmp_path / "2"))
    assert not any("0.0.0.0" in n for n in h2.detail["notes"]), "默认不该报警"


def test_有头下要显式指定软件_GL_否则_WebGL_整个是关的():
    """**换默认时差点弄丢的功能。**

    headless 会自己退到 SwiftShader,有头不会 —— 实测 `SystemInfo.getInfo`
    报 `webgl: disabled_off`。而且 `--disable-gpu` **救不回来**,
    有头下它关得更彻底(实测三种组合,只有下面这一组能用)。
    """
    argv = xpra_mod.build_chrome_argv("/x/chrome", cdp_port=1, profile="/p",
                                      url="u", width=1024, height=768)
    assert "--use-gl=angle" in argv and "--use-angle=swiftshader" in argv
    # 这个是陷阱:看着像"关掉 GPU 走软件",实际是把 WebGL 一起关了
    assert "--disable-gpu" not in argv
