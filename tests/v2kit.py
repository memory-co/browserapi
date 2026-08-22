"""v2 那几条测试共用的骨架。

**三条规矩,`v2_*` 每一条都照这个来**([v2_cli_simple](v2_cli_simple/) 是样例):

1. **动作从 CLI 进,而且真起一个进程。** `[sys.executable, "-m", "webmuxd"]`,
   不是 `from webmuxd.cli import main` 调一下 —— in-process 调函数测不出
   argv 解析、退出码、stdout 那一层,而那一层出过事(入口点写错过一次,
   装完根本起不来,全套单元测试没有一条发现)。

   不用 PATH 上那个 `webmuxd`:它指向 site-packages,可能是上一版
   ——写这套东西的时候它就是。**测的是这棵树,不是机器上碰巧装着的东西。**

2. **观察也从 CLI 进。** `snapshot` 给的 `@e1` 就是页面结构,
   不往页面里塞 JS。

3. **"人看到了什么"从一个真的浏览器来。**

   - 协议那一层(帧、光标、控制消息)接一条 `/s/<id>/channel/cdp` 看
     —— 那是**人看的地方**,不是我们的内部状态。
   - 整页那一层用 [`human()`](#human) 起一个**真的浏览器**打开观看页。
     它能看到我们看不到的:**观看页自己报的错**、画面到底画没画出来、
     窗口一改会怎样。那些正是最终用户会撞上的问题。

## 一条命令有两份输出,是两种契约

    cli.run(...)   只看退出码 —— 大多数命令
    cli.out(...)   人读的那份 stdout —— capture / url
    cli.api(...)   `--json` 那份,它是 API 的**原始响应**(cli.py 的 `_out`),
                   所以解析它不算"解析输出",它就是 API
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

#: 跑哪个 webmuxd —— 见上面第 1 条。
BIN = [sys.executable, "-m", "webmuxd"]


# ---------------------------------------------------------------------------
# 跑不跑得起来
# ---------------------------------------------------------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def need_network(url: str) -> None:
    """**没网就跳过,不假装通过。**"""
    try:
        urllib.request.urlopen(url, timeout=8).read(64)
    except Exception as e:
        pytest.skip(f"连不上 {url}({e})—— 这一条要真的打开它")


def need_vnc() -> None:
    """要有头那条腿。**不退回无头** —— 退回去就是让测试在
    "看起来通过"和"其实没验到"之间摇摆。"""
    from webmuxd import xpra as xpra_mod
    ok, why = xpra_mod.available()
    if not ok:
        pytest.skip(f"没有 VNC 那条腿:{why} —— 跑 `webmuxd install`")


# ---------------------------------------------------------------------------
# 对着一个真 server 说话
# ---------------------------------------------------------------------------

class Cli:
    """一个起好的 server,和对它说话的那几条命令。"""

    def __init__(self, env: dict[str, str], port: int) -> None:
        self.env = env
        self.port = port

    # -- 三种契约 ----------------------------------------------------------

    def sh(self, *argv: str) -> subprocess.CompletedProcess:
        """跑一条,原样交回来。退出码由调用方判。"""
        return subprocess.run([*BIN, *argv], env=self.env, capture_output=True,
                              text=True, timeout=120)

    def run(self, *argv: str) -> None:
        """**退出码就是契约。**"""
        r = self.sh(*argv)
        assert r.returncode == 0, (
            f"`webmuxd {' '.join(argv)}` 退出码 {r.returncode}\n{r.stderr}")

    def out(self, *argv: str) -> str:
        """人读的那份 stdout。"""
        r = self.sh(*argv)
        assert r.returncode == 0, f"`webmuxd {' '.join(argv)}` 挂了:{r.stderr}"
        return r.stdout

    def api(self, *argv: str) -> dict:
        """`--json` 那份 —— API 的原始响应。"""
        return json.loads(self.out("--json", *argv))

    # -- 常用的几下 --------------------------------------------------------

    def snap(self, target: str, *flags: str) -> list[dict]:
        return self.api("snapshot", "-t", target, *flags)["elements"]

    def one(self, target: str, *flags: str, **want: object) -> dict:
        """快照里**唯一**满足条件的那个。找不到或多于一个都直接失败 ——
        「随便挑一个」是这个项目从头到尾拒绝的事。"""
        hits = [e for e in self.snap(target, *flags)
                if all(e.get(k) == v for k, v in want.items())]
        assert len(hits) == 1, (
            f"要 {want},找到 {len(hits)} 个:"
            f"{[(e['ref'], e['role'], e['name']) for e in hits[:6]]}")
        return hits[0]

    def wait_tabs(self, sid: str, n: int, timeout: float = 30) -> list[dict]:
        """等到有 `n` 个 tab,**而且每个都落到了一个地址上**。

        两件事都得等,因为它们不同时发生:**tab 记录先有,URL 后到** ——
        `Target.targetCreated` 一来我们就建记录,那一刻 `url` 还是空的。
        只等第一件,下一句 `assert "news.baidu" in url` 就会看到空串。

        **这一条是 CLI 的一个缺口**:`wait` 等得了页面上的文字、元素、地址,
        等不了"又开了一个 tab"。这儿用轮询顶上,但**别当成没问题** ——
        记在 [cli/tabs.md](../docs/v2/cli/tabs.md)。
        """
        import time
        deadline = time.monotonic() + timeout
        while True:
            tabs = self.api("tabs", "-t", sid)["tabs"]
            done = len(tabs) >= n and all(t["url"] for t in tabs)
            if done or time.monotonic() > deadline:
                return tabs
            time.sleep(0.3)

    def viewer(self, sid: str, channel: str = "cdp"):
        import websockets
        return websockets.connect(f"ws://127.0.0.1:{self.port}/s/{sid}/channel/{channel}")


@contextlib.contextmanager
def server(tmp_path):
    """`webmuxd start`,用完 `kill-server`。**收干净是这个上下文的责任。**"""
    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = str(tmp_path)      # 一套独立的 registry
    env.pop("WEBMUXD_TARGET", None)

    cli = Cli(env, free_port())
    cli.run("start", "--port", str(cli.port))
    try:
        yield cli
    finally:
        cli.sh("kill-server")                   # 失败了也要收


# ---------------------------------------------------------------------------
# 人看到了什么
# ---------------------------------------------------------------------------

def center(el: dict) -> tuple[float, float]:
    x, y, w, h = el["bbox"]
    return x + w / 3, y + h / 2


#: 页面上一块**确定没有东西**的地方。光标是"变了才报",
#: 所以每次问之前得先把它挪回一个已知的起点。
BLANK = (20, 700)


class Viewer:
    """一条观看连接 —— **人看到的东西从这儿来**。"""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.frames = 0
        self.msgs: list[dict] = []

    async def drain(self, seconds: float = 2.0) -> None:
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

    def first(self, type_: str) -> dict:
        return next(m for m in self.msgs if m["type"] == type_)

    async def move_to(self, x: float, y: float) -> list[str]:
        """把鼠标移过去,返回这一下带出来的光标变化。"""
        self.msgs.clear()
        await self.ws.send(json.dumps({"type": "mouse", "event": "move",
                                       "x": x, "y": y, "buttons": 0,
                                       "modifiers": 0}))
        await asyncio.sleep(0.6)
        await self.drain(1.5)
        return [m["cursor"] for m in self.msgs if m["type"] == "cursor"]

    async def cursor_over(self, el: dict) -> list[str]:
        """**先回到空白处,再移到它上面** —— 不给起点就没得变。"""
        await self.move_to(*BLANK)
        return await self.move_to(*center(el))


# ---------------------------------------------------------------------------
# 一个真的浏览器,当最终用户用
# ---------------------------------------------------------------------------

class Human:
    """坐在观看页前面的那个人。

    **它握着一个真浏览器的 page**,所以能看到我们自己看不到的东西:

    - `errors` —— **观看页自己报的错**。用户说"打开是白屏"的时候,
      这是第一手信息,而我们的 CLI 今天一条都看不到
      ([cli/debug.md](../docs/v2/cli/debug.md) 里 `console` 还是 🔲)
    - 画面**到底画没画出来** —— `<img>` 的 `naturalWidth` 不是 0
    - 窗口一改会怎样 —— 里面那个 session 跟不跟着变

    坐标换算的正向公式在
    [`input/mods.ts`](../webmuxjs/client/src/input/mods.ts):

        inner = (client − rect.topLeft) × (cast ÷ rect.size)

    这儿算它的逆。**`cast` 从 `<img>` 的自然尺寸来** ——
    那就是实际推过来那张图有多大,不是 session 名义上的分辨率。
    """

    #: 画面那三个元素。**只有一个是可见的**,看模式(JPG / VNC / DOM)。
    SCREENS = ("#screen", "#screen2", "#screen3")

    def __init__(self, page, channels: list | None = None) -> None:
        self.page = page
        #: 拦下来的那几条通道(`human(intercept=True)` 才有)。
        #: **每重连一次就多一条** —— 所以数它就知道断没断过。
        self.channels = channels
        self.errors: list[str] = []
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: m.type == "error"
                and self.errors.append(f"console.error: {m.text}"))

    # -- 看 ----------------------------------------------------------------

    @property
    def address_bar(self) -> str:
        return self.page.locator("#url").input_value()

    @property
    def tab_bar(self) -> str:
        return self.page.locator("#tabs").inner_text()

    @property
    def status(self) -> str:
        return self.page.locator("#status").inner_text().replace("\n", " ")

    def screen_sel(self) -> str:
        """当值的那个画面元素的选择器。**三个里只有一个可见。**

        用 Playwright 的可见性判断,不自己在 JS 里猜 ——
        第一版在 JS 里用 `offsetParent !== null` 挑,VNC 模式下挑中了那个
        **隐藏着的 `<img>`**,于是量到的是上一条腿留下的旧图。
        **两处各判一次"哪个可见",就会有一处判错。**
        """
        for sel in self.SCREENS:
            el = self.page.locator(sel)
            if el.count() and el.is_visible():
                return sel
        raise AssertionError(
            f"一个画面元素都不可见:{self.page.locator('#stage').inner_html()[:200]}")

    def screen(self):
        return self.page.locator(self.screen_sel())

    #: **把当值的那个画面画进一张离屏 canvas,采样数颜色。**
    #:
    #: 为什么绕这一道:JPG 那条腿是 `<img>`,有 `naturalWidth` 可问;
    #: VNC 那条是 `<canvas>`,**没有那个属性** —— 只判 `naturalWidth > 0`
    #: 的话 VNC 下永远是 0,一条测试要么写不了要么写成两套。
    #: 画进 canvas 之后两条腿是同一个判据,而且**它比"有没有尺寸"更严**:
    #: 一整块死白也是有尺寸的。
    _PAINT_JS = """(sel) => {
      const el = document.querySelector(sel);
      if (!el) return {kind: 'none', w: 0, h: 0, colors: 0};
      if (el.tagName === 'DIV') return {kind: 'dom', w: 0, h: 0, colors: -1};
      const w = el.naturalWidth || el.width || 0;
      const h = el.naturalHeight || el.height || 0;
      if (!w || !h) return {kind: el.tagName.toLowerCase(), w, h, colors: 0};
      const off = document.createElement('canvas');
      off.width = w; off.height = h;
      const g = off.getContext('2d');
      try { g.drawImage(el, 0, 0); } catch (e) { return {kind: 'tainted', w, h, colors: -1}; }
      const d = g.getImageData(0, 0, w, h).data;
      const seen = new Set();
      let sig = 0;
      for (let i = 0; i < d.length; i += 4 * 997) {
        seen.add(`${d[i]},${d[i+1]},${d[i+2]}`);
        sig = (sig * 31 + d[i] + d[i+1] * 7 + d[i+2] * 13) >>> 0;
      }
      return {kind: el.tagName.toLowerCase(), w, h, colors: seen.size, sig};
    }"""

    def paint(self) -> dict:
        """画面上**到底有没有东西**:`{kind, w, h, colors}`。

        `colors <= 1` 是一整块纯色 —— 那是白屏,不是画面。
        DOM 模式回 `colors: -1`(那不是一张图,画不进 canvas)。
        """
        return self.page.evaluate(self._PAINT_JS, self.screen_sel())

    def cast(self) -> tuple[int, int]:
        """推过来那张图**实际**多大 —— 不是 session 名义上的分辨率。"""
        p = self.paint()
        return p.get("w", 0), p.get("h", 0)

    def wait_connected(self, timeout: float = 20000) -> None:
        """等到那条 WS 接上。"""
        self.page.wait_for_selector("#s-conn:has-text('已连接')", timeout=timeout)

    def wait_painted(self, timeout: float = 40) -> dict:
        """等到**画面上真的有东西**(不止一种颜色)。

        **「已连接」不等于「画出来了」,这是两件事。**
        WS 接上之后服务端才开始推像素,第一帧还要走一个来回 ——
        中间那段时间状态条上是「帧 –」,而人看到的是一块空白。

        第一版只等了「已连接」就去量画面,一跑就红 ——
        **那不是 flake,那是把两件事当成了一件。**

        每轮重新问"哪个元素当值",所以**切模式之后也能用**。
        """
        deadline = time.monotonic() + timeout
        while True:
            p = self.paint()
            if p.get("colors", 0) > 1:
                return p
            assert time.monotonic() < deadline, f"{timeout}s 内画面上还是一片空白:{p}"
            self.page.wait_for_timeout(300)

    # -- 动 ----------------------------------------------------------------

    def point_for(self, el: dict) -> tuple[float, float]:
        """里面那个元素,在**人的屏幕上**是哪一点。"""
        rect = self.screen().bounding_box()
        cw, ch = self.cast()
        assert cw and ch, f"一帧都没画出来,没法换算:{self.paint()}"
        bx, by, bw, bh = el["bbox"]
        return (rect["x"] + (bx + bw / 2) * rect["width"] / cw,
                rect["y"] + (by + bh / 2) * rect["height"] / ch)

    def click(self, el: dict) -> tuple[float, float]:
        """在画面上点里面那个元素。返回点的是屏幕上哪一点(报错时好看)。"""
        x, y = self.point_for(el)
        self.page.mouse.click(x, y)
        self.page.wait_for_timeout(1200)
        return x, y

    def type(self, text: str) -> None:
        """敲字。**得先点过一下** —— 观看端在 `mousedown` 时才把焦点交给
        那个隐藏 textarea(IME 要它)。"""
        self.page.keyboard.type(text)
        self.page.wait_for_timeout(1500)

    def wait_fresh(self, was: int, timeout: float = 30) -> dict:
        """等到画面**变了**(采样指纹和 `was` 不一样)。

        **判"画面回来了"不能只看有没有东西** —— canvas 上留着断线前的最后
        一帧,颜色数一模一样。要证明的是**新帧还在流**,那就得让里面动一下,
        再看画面跟不跟。
        """
        deadline = time.monotonic() + timeout
        while True:
            p = self.paint()
            if p.get("sig") != was and p.get("colors", 0) > 1:
                return p
            assert time.monotonic() < deadline, f"{timeout}s 内画面一动没动:{p}"
            self.page.wait_for_timeout(400)

    def cut(self, kind: str) -> int:
        """把某条通道掐了(`cdp` / `xpra`)。返回掐掉几条。

        要 `human(..., intercept=True)`。
        """
        assert self.channels is not None, "要 human(..., intercept=True) 才掐得动"
        hit = [w for w in self.channels if w.url.rstrip("/").endswith(kind)]
        for w in hit:
            w.close()
        return len(hit)

    def channel_count(self, kind: str) -> int:
        assert self.channels is not None, "要 human(..., intercept=True)"
        return sum(1 for w in self.channels if w.url.rstrip("/").endswith(kind))

    def resize(self, w: int, h: int) -> None:
        self.page.set_viewport_size({"width": w, "height": h})
        self.page.wait_for_timeout(2000)

    def switch_to(self, label: str) -> dict:
        """点那几个画面模式按钮之一(**使用者看到的是 JPG / VNC / DOM**),
        等到新那条腿真的把画面铺上。"""
        self.page.get_by_role("button", name=label, exact=True).click()
        self.page.wait_for_timeout(500)
        return self.wait_painted()


@contextlib.contextmanager
def human(url: str, *, size: tuple[int, int] = (1280, 900),
          intercept: bool = False):
    """起一个**真的**浏览器打开 `url`,当最终用户用。

    **为什么不是又一个 webmuxd session。** 试过,不对:

    1. 用自己的栈去测自己的栈是**循环的** —— 截屏那条腿坏了,
       "被观看的"和"观看的"会一起坏,而测试照样绿
    2. 要测的是**最终用户会撞上什么**,那第二个浏览器就得是用户那种浏览器
    3. 用户那边最要紧的一类信息 —— **观看页自己报的错** ——
       我们的 CLI 今天根本读不到

    没装就跳过,不假装通过。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("没装 playwright —— `pip install playwright && playwright install chromium`")
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as e:                       # 浏览器没下过
            pytest.skip(f"playwright 的浏览器起不来({e})—— `playwright install chromium`")
        page = browser.new_page(viewport={"width": size[0], "height": size[1]})
        channels: list | None = None
        if intercept:
            # **把那几条通道从中间接过来**,好在测试里说掐就掐。
            # Chromium 自己的断网模拟(`Network.emulateNetworkConditions`
            # 和 `context.set_offline`)对 **loopback 上已经建好的 WebSocket
            # 一律无效** —— 两个都试过,状态一直是「已连接」。
            channels = []
            page.route_web_socket("**/channel/**", lambda ws: (
                channels.append(ws), ws.connect_to_server()))
        h = Human(page, channels)
        page.goto(url)
        try:
            yield h
        finally:
            browser.close()
