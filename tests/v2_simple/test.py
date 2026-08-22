"""v2 · 一条完整的路:起服务 → 开 session → 打开百度 → 搜一个词 → 看到结果。

**这一条是样例**,见 [README](README.md)。两条规矩:

- **动作从 CLI 进** —— CLI 就是为了让这件事容易做而存在的
- **观察从观看端来** —— 人是从 `/channel/cdp` 那条连接上看的

要网络,而且**要有头**(`--transport vnc`)—— 见下面那条注释:
百度给无头浏览器弹图形验证码。没网或没 xpra 就跳过,不假装通过。
"""

import asyncio
import json
import socket
import urllib.request

import pytest
import websockets

from webmuxd.cli import main

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

SITE = "https://www.baidu.com/"
WORD = "webmuxd"


def _free() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _online() -> bool:
    try:
        urllib.request.urlopen(SITE, timeout=8).read(64)
        return True
    except Exception:
        return False


def run(*argv: str) -> int:
    """一条命令。**退出码就是契约**,不解析输出。"""
    code = main(list(argv))
    assert code == 0, f"`webmuxd {' '.join(argv)}` 退出码 {code}"
    return code


@pytest.fixture
def server(tmp_path, monkeypatch):
    """一个真 server —— `webmuxd start`,用完 `kill-server`。"""
    from webmuxd import xpra as xpra_mod

    if not _online():
        pytest.skip("没网 —— 这一条要真的打开百度")
    ok, why = xpra_mod.available()
    if not ok:
        # **不退回无头。** 无头那条这一步会撞验证码(见下面),
        # 退回去就是让这条测试在"看起来通过"和"其实没验到"之间摇摆
        pytest.skip(f"没有 VNC 那条腿:{why} —— 跑 `webmuxd install`")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("WEBMUXD_TARGET", raising=False)
    port = _free()
    run("start", "--port", str(port))
    yield port
    main(["kill-server"])          # 失败了也要收干净,所以不用 run()


class Viewer:
    """一条观看连接 —— **人看到的东西从这儿来**。"""

    def __init__(self, ws):
        self.ws = ws
        self.frames = 0
        self.msgs: list[dict] = []

    async def drain(self, seconds: float = 2.5) -> None:
        """把这段时间里推过来的都收下。"""
        try:
            while True:
                m = await asyncio.wait_for(self.ws.recv(), timeout=seconds)
                if isinstance(m, str):
                    self.msgs.append(json.loads(m))
                else:
                    self.frames += 1
        except asyncio.TimeoutError:
            pass

    async def move_to(self, x: float, y: float) -> list[str]:
        """把鼠标移过去,返回这一下带出来的光标变化。"""
        self.msgs.clear()
        await self.ws.send(json.dumps({"type": "mouse", "event": "move",
                                       "x": x, "y": y, "buttons": 0,
                                       "modifiers": 0}))
        await asyncio.sleep(0.5)
        await self.drain()
        return [m["cursor"] for m in self.msgs if m["type"] == "cursor"]


def js(port: int, expression: str):
    """页面里求一个值 —— **只用来观察,不用来操作**。

    操作全走 CLI;这儿是"人看到了什么"的取景器(比如搜索框在屏幕哪个位置)。
    """
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["--json", "send", "-t", "demo",
              json.dumps([{"type": "js", "expression": expression}])])
    return json.loads(json.loads(buf.getvalue())["results"][0]["value"])


async def test_起服务_开百度_搜一个词_看到结果(server):
    port = server

    # ---------------------------------------------------------------- 起
    #
    # **走 VNC(有头),不是 JPG(无头)。** 实测:同一次搜索,无头那条
    # 回车之后跳到 `wappass.baidu.com/.../tuxing_v2.html`(图形验证码),
    # 有头这条直接出结果。这不是我们的 bug,是站点在挡自动化 ——
    # 但它决定了这条测试只能走有头,顺带也就真的验了 VNC 那条腿。
    run("new", "--id", "demo", "--transport", "vnc")
    listing = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions"))
    assert [s["id"] for s in listing["sessions"]] == ["demo"]
    assert listing["sessions"][0]["url"] == "/s/demo/", "session 住在那个口下面"

    # ------------------------------------------------------- 打开百度
    run("goto", "-t", "demo", SITE)
    await asyncio.sleep(3)

    body = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/s/demo/api/text").read().decode()
    assert "百度" in body, f"页面没打开?正文:{body[:120]!r}"

    shot = urllib.request.urlopen(
        f"http://127.0.0.1:{port}/s/demo/api/screenshot").read()
    assert shot[:4] == b"RIFF", "截图不是 webp"
    assert len(shot) > 5000, "截图太小,多半是白屏"

    # --------------------------------------------- 观看端:光标要变
    async with websockets.connect(
            f"ws://127.0.0.1:{port}/s/demo/channel/cdp") as ws:
        v = Viewer(ws)
        await v.drain(3)

        hello = next(m for m in v.msgs if m["type"] == "hello")
        assert hello["transport"] == "vnc", hello
        # **VNC 下这条通道上没有帧** —— 像素走 `/channel/xpra`,
        # 这条只管输入和那几条控制消息([e §6.1](../../docs/v2/works/e-client.md))。
        # 写成"一连上就该有帧"是把 JPG 那条的模型套到这儿。
        assert v.frames == 0, "VNC 下帧不该从 /channel/cdp 来"

        # 像素那条在不在。**只验它接得上,不在这儿冒充 xpra 客户端** ——
        # 那个协议要先握手才推东西,而握手是浏览器端那份的活
        # (`webmuxjs/client/src/channel/xpra.ts`,它有自己的测试)。
        async with websockets.connect(
                f"ws://127.0.0.1:{port}/s/demo/channel/xpra",
                subprotocols=["binary"]) as px:
            assert px.state.name == "OPEN", "VNC 下像素那条通道该在"

        # 搜索框在屏幕哪儿 —— **找"第一个能输入的可见元素"**,不写死百度的 id。
        # 顺手把它记在 window 上:后面要验"框里有字了",得认准**同一个**元素
        # (百度页面里还藏着好几个存 CSS 的 textarea)。
        box = js(port, """(() => {
          for (const e of document.querySelectorAll('input,textarea')) {
            const r = e.getBoundingClientRect();
            if (r.width > 80 && r.height > 10 && e.type !== 'hidden') {
              window.__wm_box = e;
              return JSON.stringify({x: r.x + r.width / 3, y: r.y + r.height / 2});
            }
          }
          return JSON.stringify({});
        })()""")
        assert box, "页面上找不到一个能输入的框"

        # **先移到空白处,再移到框上** —— 光标是"变了才报",不给个起点就没得变
        await v.move_to(20, 700)
        on_box = await v.move_to(box["x"], box["y"])
        assert "text" in on_box, f"移到搜索框上,光标该变成 I 型,实际:{on_box}"

        away = await v.move_to(20, 700)
        assert "default" in away, f"移开该变回箭头,实际:{away}"

    # ------------------------------------------------------------ 输入
    run("click", "-t", "demo", "--at", f"{box['x']},{box['y']}")
    run("type", "-t", "demo", "--at", f"{box['x']},{box['y']}", WORD)
    await asyncio.sleep(1)

    typed = js(port, "JSON.stringify((window.__wm_box || {}).value || '')")
    assert typed == WORD, f"框里应该是 {WORD!r},实际 {typed!r}"

    # ------------------------------------------------------------ 回车
    run("key", "-t", "demo", "Enter")

    # **等那件事发生,不等一个秒数。** 睡固定时长是在赌网速 ——
    # 赌输了就是一条时灵时不灵的测试,而那比没有更坏。
    run("wait", "-t", "demo", "--url-contains", WORD, "--timeout", "20000")

    tabs = json.load(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/s/demo/api/tabs"))
    here = next(t["url"] for t in tabs["tabs"] if t["active"])
    assert WORD in here, f"地址栏该带上搜索词,实际 {here}"

    # 结果页上**看得见**那个词:标题,以及那一列结果标题
    title = js(port, "JSON.stringify(document.title)")
    assert WORD.lower() in title.lower(), f"标题里没有搜索词:{title!r}"

    # **有结果**。至于结果标题里有没有那个词,取决于百度的索引 ——
    # 那不是我们能测的东西,写进断言只会换来一条时灵时不灵的测试。
    heads = js(port, """JSON.stringify(
      [...document.querySelectorAll('h3')].map(e => e.innerText).filter(Boolean)
    )""")
    assert len(heads) >= 3, f"结果页上一条结果都没有:{heads!r}"
    print(f"  搜到 {len(heads)} 条,头一条:{heads[0]!r}")
