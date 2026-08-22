"""v2 那几条测试共用的骨架。

**三条规矩,`v2_*` 每一条都照这个来**([v2_simple](v2_simple/) 是样例):

1. **动作从 CLI 进,而且真起一个进程。** `[sys.executable, "-m", "webmuxd"]`,
   不是 `from webmuxd.cli import main` 调一下 —— in-process 调函数测不出
   argv 解析、退出码、stdout 那一层,而那一层出过事(入口点写错过一次,
   装完根本起不来,全套单元测试没有一条发现)。

   不用 PATH 上那个 `webmuxd`:它指向 site-packages,可能是上一版
   ——写这套东西的时候它就是。**测的是这棵树,不是机器上碰巧装着的东西。**

2. **观察也从 CLI 进。** `snapshot` 给的 `@e1` 就是页面结构,
   不往页面里塞 JS。

3. **只有"人看到了什么"从观看端来** —— 画面帧、光标,人是从
   `/s/<id>/channel/cdp` 那条连接上看的。要验人看到的东西,
   就得从人看的地方看。

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
