"""v2 · 一个真人打开观看页,他会撞上什么。

前面那几条都是**我们自己发命令、我们自己读结果**。中间那一段 ——
**人在画面上点的那一下,到底有没有到里面** —— 一条都没验过。
而那一段恰恰是这个项目最不能出错的地方:[b](../../docs/v2/works/b-input.md)
那八步、[c](../../docs/v2/works/c-view.md) 那两条像素腿、
[e](../../docs/v2/works/e-client.md) 那个客户端,全在这一段里。

**只有一个 webmuxd session。** 另一边是 Playwright 起的一个真浏览器 ——
不是又一个 webmuxd session([v2kit.human](../v2kit.py) 里写了为什么)。

设计在 [works/test.md §5](../../docs/v2/works/test.md)。
"""

import pytest

from tests import v2kit

pytestmark = pytest.mark.slow

SITE = "https://www.baidu.com/"
WORD = "web"


@pytest.fixture
def cli(tmp_path):
    v2kit.need_network(SITE)
    with v2kit.server(tmp_path) as c:
        yield c


def test_a_human_opens_the_page_and_drives_the_browser(cli):
    cli.run("new", "--id", "demo", "--transport", "jpg")
    cli.run("goto", "-t", "demo", SITE)
    cli.run("wait", "-t", "demo", "--css", "input", "--timeout", "30")

    # **这就是 `webmuxd attach` 打印给人的那个地址。**
    watch = cli.out("attach", "-t", "demo", "--print-only").strip()
    assert watch.endswith("/s/demo/"), watch

    with v2kit.human(watch) as who:
        # **两件事,分开等。** 接上 ≠ 画出来了:WS 连上之后服务端才开始
        # screencast,第一帧还要走一个来回。
        who.wait_connected()
        who.wait_painted()

        # -------------------------------------------- 他看到了什么
        #
        # **一条报错都不该有。** 用户说"打开是白屏"的时候,这是第一手信息,
        # 而我们的 CLI 今天一条都读不到 —— 这一条只有真浏览器验得了。
        assert who.errors == [], f"观看页自己报错了:{who.errors}"

        # 画面真的画上去了 —— `naturalWidth` 是 0 就是一帧都没落地
        cw, ch = who.cast()
        assert cw > 0 and ch > 0, f"画面是空的:{who.status}"
        assert f"{cw}×{ch}" in who.status, f"状态条和实际对不上:{who.status}"

        # 地址栏和 tab 条上是**里面那个页面**的状态 —— 真的同步过来了
        assert who.address_bar.startswith("https://www.baidu.com"), who.address_bar
        assert "baidu" in who.tab_bar, who.tab_bar

        # **读屏的人也找得到那块画面。** `alt=""` 的意思是"这张图没信息,
        # 跳过它",而它是整页唯一有信息的地方 —— 那是个真 bug,修了。
        assert who.page.get_by_role("img", name="浏览器画面").count() >= 1, \
            "画面没有可访问名 —— 用读屏软件的人打开这页什么都听不到"

        # ------------------------------------------------ 他点一下
        #
        # **这一下是这条测试的全部理由。** 它从真浏览器的 DOM 事件出发,
        # 经过归一化 → 上行消息 → 服务端翻译成 `Input.*` → 里面那个
        # Chromium。中间任何一环断了,这一下就什么都不会发生 ——
        # **而且不会报错。**
        box = next(e for e in cli.snap("demo", "-i")
                   if "type" in e["affords"] and e["in_viewport"])
        at = who.click(box)

        hits = [e for e in cli.api("log", "-t", "demo", "--user", "human")["entries"]
                if e.get("action") == "pointerdown"]
        assert hits, f"人在 {at} 点了,里面一条都没记下 —— 那一下没到"
        hit = hits[-1]["hit"]
        assert hit["role"] in ("textarea", "textbox", "combobox", "searchbox"), \
            f"该点在搜索框上,实际点中的是 {hit}"

        # ------------------------------------------------ 他敲字
        #
        # 顺序是有意义的:观看端在 `mousedown` 时才把焦点交给隐藏的
        # textarea(IME 要它),**所以"敲字"之前必须先有"点一下"**。
        who.type(WORD)
        typed = [e for e in cli.snap("demo", "-i") if "type" in e["affords"]]
        assert typed and typed[0]["value"] == WORD, \
            f"人敲的字该出现在里面那个框里,实际:{[(e['ref'], e['value']) for e in typed]}"

        # ------------------------------------- 他把窗口拉小,画面跟着变
        #
        # **这是"用起来像个普通浏览器"里最容易坏的一条** ——
        # 里面那个 session 的分辨率跟着观看的人走,不是写死的。
        before = cli.api("snapshot", "-t", "demo")["viewport"]
        who.resize(900, 700)
        after = cli.api("snapshot", "-t", "demo")["viewport"]
        assert after["w"] < before["w"], f"窗口拉小了,里面没跟着变:{before} → {after}"
        assert who.cast()[0] > 0, "改完窗口画面就没了"

        # 从头到尾,观看页一条错都没报
        assert who.errors == [], f"操作过程中报了错:{who.errors}"

    # ------------------------- 人和程序进同一条流,而且分得开
    #
    # **这是把 CDP 端点直接交出去的方案做不到的事** ——
    # 人点的那一下和程序发的 `Input.dispatchMouseEvent` 在线上是同一种字节。
    # 我们分得开,是因为画面和输入都经过自己这一层
    # ([i §4](../../docs/v2/works/i-agent-surface.md))。
    stream = [e for e in cli.api("log", "-t", "demo")["entries"]
              if e["kind"] == "action"]
    who_did = {e["user"] for e in stream}
    assert {"cli", "human"} <= who_did, f"同一条流上该同时有人和程序:{who_did}"
    assert [e["seq"] for e in stream] == sorted(e["seq"] for e in stream), \
        "一条流,一个序号,按发生顺序"

    # 而且**记的是控件身份,不是控件内容**
    # ([i §4](../../docs/v2/works/i-agent-surface.md))—— 不然人在密码框里
    # 敲的东西会进日志。
    human_did = [e for e in stream if e["user"] == "human"]
    assert all(set(e.get("hit") or {}) <= {"role", "name"} for e in human_did), human_did
    assert not any("text" in e or "value" in e for e in human_did), \
        "人敲进去的内容不该进日志"
