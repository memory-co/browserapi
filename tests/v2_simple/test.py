"""v2 · 一条完整的路:起服务 → 开 session → 打开百度 → 搜一个词 → 看到结果。

**这一条是样例**,见 [README](README.md)。三条规矩:

- **动作从 CLI 进**,而且是**真的跑 `webmuxd`**,不是 import `main()` 调一下 ——
  in-process 调函数测不出装完跑不起来那类问题(入口点写错过一次)
- **观察也从 CLI 进** —— `snapshot` 给的 `@e1` 就是页面结构,不写一行 JS
- **只有"人看到了什么"从观看端来** —— 光标那一段,人是从
  `/s/<id>/channel/cdp` 那条连接上看的

要网络,而且**要有头**(`--transport vnc`)—— 见下面那条注释:
百度给无头浏览器弹图形验证码。没网或没 xpra 就跳过,不假装通过。
"""

import asyncio
import json
import os
import socket
import subprocess
import sys
import urllib.request

import pytest
import websockets

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

SITE = "https://www.baidu.com/"
WORD = "webmuxd"

#: 跑哪个 webmuxd。**一个真进程,跑的是工作树那份。**
#:
#: 不用 PATH 上的 `webmuxd`:那个指向 site-packages,可能是上一版
#: ——写这条测试的时候它就是,`webmuxd start` 在那儿还叫 `webmuxd new --port`。
#: 测试要测的是这棵树,不是机器上碰巧装着的东西。
#: 但**必须是子进程**:in-process 调 `main()` 测不出 argv 解析、
#: 退出码、stdout 编码那一层,而那一层出过事。
BIN = [sys.executable, "-m", "webmuxd"]
ENV: dict[str, str] = {}


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


# ---------------------------------------------------------------------------
# 三个 helper —— **一条命令有两份输出,是两种契约**
# ---------------------------------------------------------------------------

def sh(*argv: str) -> subprocess.CompletedProcess:
    """跑一条,原样交回来。退出码由调用方判。"""
    return subprocess.run([*BIN, *argv], env=ENV, capture_output=True,
                          text=True, timeout=120)


def run(*argv: str) -> None:
    """**退出码就是契约。** 大多数命令用这个,不看输出。"""
    r = sh(*argv)
    assert r.returncode == 0, (
        f"`webmuxd {' '.join(argv)}` 退出码 {r.returncode}\n{r.stderr}")


def out(*argv: str) -> str:
    """人读的那份 stdout —— `capture` / `url` 这类。"""
    r = sh(*argv)
    assert r.returncode == 0, f"`webmuxd {' '.join(argv)}` 挂了:{r.stderr}"
    return r.stdout


def api(*argv: str) -> dict:
    """`--json` 那份 —— 它是 **API 的原始响应**(`cli.py` 的 `_out`),
    所以解析它不算"解析输出",它就是 API。"""
    return json.loads(out("--json", *argv))


def snap(*argv: str) -> list[dict]:
    return api("snapshot", "-t", "demo", *argv)["elements"]


def a_box(el: dict) -> tuple[float, float]:
    """元素中间偏左的一个点 —— 移鼠标和点击都用它。"""
    x, y, w, h = el["bbox"]
    return x + w / 3, y + h / 2


@pytest.fixture
def server(tmp_path):
    """一个真 server —— `webmuxd start`,用完 `kill-server`。"""
    from webmuxd import xpra as xpra_mod

    if not _online():
        pytest.skip("没网 —— 这一条要真的打开百度")
    ok, why = xpra_mod.available()
    if not ok:
        # **不退回无头。** 无头那条这一步会撞验证码(见下面),
        # 退回去就是让这条测试在"看起来通过"和"其实没验到"之间摇摆
        pytest.skip(f"没有 VNC 那条腿:{why} —— 跑 `webmuxd install`")

    ENV.clear()
    ENV.update(os.environ)
    ENV["XDG_RUNTIME_DIR"] = str(tmp_path)      # 一套独立的 registry
    ENV.pop("WEBMUXD_TARGET", None)

    port = _free()
    run("start", "--port", str(port))
    yield port
    sh("kill-server")                            # 失败了也要收干净


class Viewer:
    """一条观看连接 —— **人看到的东西从这儿来**。"""

    def __init__(self, ws):
        self.ws = ws
        self.frames = 0
        self.msgs: list[dict] = []

    async def drain(self, seconds: float = 2.5) -> None:
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


async def test_start_open_baidu_search_and_see_results(server, tmp_path):
    port = server

    # ---------------------------------------------------------------- 起
    #
    # **退出码是给脚本用的那一半。** `has` 什么都不打印,只回码 ——
    # `webmuxd has -t work || webmuxd new --id work` 就是靠这个。
    assert sh("has", "-t", "demo").returncode == 3, "还没有 demo,该回 3"

    # **走 VNC(有头),不是 JPG(无头)。** 实测:同一次搜索,无头那条
    # 回车之后跳到 `wappass.baidu.com/.../tuxing_v2.html`(图形验证码),
    # 有头这条直接出结果。这不是我们的 bug,是站点在挡自动化 ——
    # 但它决定了这条测试只能走有头,顺带也就真的验了 VNC 那条腿。
    run("new", "--id", "demo", "--transport", "vnc")
    run("has", "-t", "demo")

    sessions = api("ls")["sessions"]
    assert [s["id"] for s in sessions] == ["demo"]
    assert sessions[0]["url"] == "/s/demo/", "session 住在那个口下面"

    # ------------------------------------------------------- 打开百度
    run("goto", "-t", "demo", SITE)
    # **等那件事发生,不等一个秒数。** 睡固定时长是在赌网速 ——
    # 赌输了就是一条时灵时不灵的测试,而那比没有更坏。
    #
    # 等的是"有个输入框了",不是"文字里有『百度』" —— 后者试过,
    # 会偶发超时:那条路走 `body.innerText` 的行,而首页那几行
    # 什么时候渲染出来跟网速有关。**结构比文案先到。**
    run("wait", "-t", "demo", "--css", "input", "--timeout", "30")

    body = out("capture", "-t", "demo")
    assert "百度" in body, f"打开的不是百度?正文开头:{body[:200]!r}"

    shot = str(tmp_path / "p.webp")
    run("capture", "-t", "demo", "--shot", shot)
    data = open(shot, "rb").read()
    assert data[:4] == b"RIFF", "截图不是 webp"
    assert len(data) > 5000, "截图太小,多半是白屏"

    # ------------------------------------------- 这一页上有什么(@e1)
    #
    # **这一段以前是一坨 JS。** `snapshot` 之前没有出口,找搜索框只能
    # `document.querySelectorAll('input,textarea')` 自己挑一个 ——
    # 那不是"逃生舱用得克制",那是一个缺的命令被 JS 顶掉了。
    boxes = [e for e in snap("-i") if "type" in e["affords"] and e["in_viewport"]]
    assert boxes, f"页面上找不到一个能输入的框:{out('snapshot', '-t', 'demo', '-i')}"
    box = boxes[0]
    assert box["ref"], "snapshot 出来的每一样都该有号"

    # --------------------------------------------- 观看端:光标要变
    async with websockets.connect(
            f"ws://127.0.0.1:{port}/s/demo/channel/cdp") as ws:
        v = Viewer(ws)
        await v.drain(3)

        hello = next(m for m in v.msgs if m["type"] == "hello")
        assert hello["transport"] == "vnc", hello
        # **VNC 下这条通道上没有帧** —— 像素走 `/channel/xpra`,
        # 这条只管输入和那几条控制消息([e §6.1](../../docs/v2/works/e-client.md))。
        assert v.frames == 0, "VNC 下帧不该从 /channel/cdp 来"

        async with websockets.connect(
                f"ws://127.0.0.1:{port}/s/demo/channel/xpra",
                subprotocols=["binary"]) as px:
            assert px.state.name == "OPEN", "VNC 下像素那条通道该在"

        # **先移到空白处,再移到框上** —— 光标是"变了才报",不给个起点就没得变。
        # 坐标从 snapshot 的 bbox 来,不是自己去页面里量。
        await v.move_to(20, 700)
        on_box = await v.move_to(*a_box(box))
        assert "text" in on_box, f"移到搜索框上,光标该变成 I 型,实际:{on_box}"

        away = await v.move_to(20, 700)
        assert "default" in away, f"移开该变回箭头,实际:{away}"

    # ------------------------------------------------------------ 输入
    #
    # **`@e1` 直接就能点** —— 不用坐标,也不用再说一遍它叫什么。
    ref = "@" + box["ref"]
    run("click", "-t", "demo", ref)
    run("--user", "agent", "--note", "搜一个词", "type", "-t", "demo", ref, WORD)

    # 框里有字了 —— **再 snapshot 一次,value 就在树里**,不用读 DOM。
    # 同一句话再问一遍(第一个能输入又看得见的),该找到同一个框。
    again = [e for e in snap("-i") if "type" in e["affords"] and e["in_viewport"]]
    assert again, "重新 snapshot 之后一个能输入的框都没有"
    assert again[0]["value"] == WORD, f"框里应该是 {WORD!r},实际 {again[0]['value']!r}"
    # **号是新的。** 只增不重用 —— 拿旧号去点会报错,不会点到别的东西。
    assert again[0]["ref"] != box["ref"], "第二次 snapshot 该发新号"

    # ------------------------------------------------------------ 回车
    run("--user", "agent", "key", "-t", "demo", "Enter")
    run("wait", "-t", "demo", "--url-contains", WORD, "--timeout", "20")

    here = out("url", "-t", "demo").strip()
    assert WORD in here, f"地址栏该带上搜索词,实际 {here}"

    # ------------------------------------------------------ 看到结果
    #
    # **有结果**。至于结果标题里有没有那个词,取决于百度的索引 ——
    # 那不是我们能测的东西,写进断言只会换来一条时灵时不灵的测试。
    links = [e for e in snap() if e["role"] == "link" and e["name"].strip()]
    assert len(links) >= 3, f"结果页上一条结果都没有:{[e['name'] for e in links]}"
    print(f"  搜到 {len(links)} 条,头一条:{links[0]['name']!r}")

    # 过期的号:**要报错,不能点到别的东西**
    stale = sh("click", "-t", "demo", ref)
    assert stale.returncode == 4, f"过期的号该回 4,实际 {stale.returncode}"
    assert "snapshot" in stale.stderr, f"报错要说清楚下一步:{stale.stderr!r}"

    # ------------------------------------------------------ 干过什么
    #
    # **人和 agent 进同一条流,每条标明是谁做的** —— 这是 agent-browser
    # 没有的那一半([i](../../docs/v2/works/i-agent-surface.md))。
    mine = [e for e in api("log", "-t", "demo", "--user", "agent")["entries"]
            if e["kind"] == "action"]
    assert [e["action"] for e in mine] == ["type", "key"], mine
    assert mine[0]["note"] == "搜一个词"

    # -------------------------------------------------------------- 收
    run("kill", "-t", "demo")
    assert sh("has", "-t", "demo").returncode == 3, "关掉就该没了"
