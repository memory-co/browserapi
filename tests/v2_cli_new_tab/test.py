"""v2 · 点一个 `target=_blank` 的链接,弹出来的东西**是一个 tab**。

和 [v2_cli_simple](../v2_cli_simple/) 同一条路,换掉中间那一段:搜索 → 点「新闻」。
规矩在 [v2kit](../v2kit.py) 的开头。

**这一条走无头(JPG)**,而 v2_cli_simple 走有头(VNC)。不是随便挑的:

- 这一条没有搜索,不会撞百度的图形验证码,所以能走无头
- 走无头就顺带验了**另一条腿**:JPG 下画面帧**是从 `/channel/cdp` 来的**,
  而 VNC 下那条通道上一帧都没有(像素走 `/channel/xpra`)。
  两条测试各验一条,合起来才算把画面这一面盖住了。
"""

import pytest

from tests import v2kit
from tests.v2kit import BLANK

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]

SITE = "https://www.baidu.com/"
MENU = "新闻"


@pytest.fixture
def cli(tmp_path):
    v2kit.need_network(SITE)
    with v2kit.server(tmp_path) as c:
        yield c


async def test_clicking_a_blank_link_becomes_a_tab(cli):
    # ---------------------------------------------------------------- 起
    cli.run("new", "--id", "nt", "--transport", "jpg")
    cli.run("goto", "-t", "nt", SITE)
    cli.run("wait", "-t", "nt", "--css", "input", "--timeout", "30")

    tabs = cli.api("tabs", "-t", "nt")["tabs"]
    assert len(tabs) == 1, f"一开始就该只有一个 tab:{tabs}"
    first = tabs[0]["id"]

    # ------------------------------------------- 顶上那排菜单里的「新闻」
    #
    # **按人看得见的字找**,不写死百度的 DOM。要求唯一 ——
    # 找到两个就直接失败,不随便挑一个。
    link = cli.one("nt", "-i", role="link", name=MENU)

    # --------------------------------------------- 观看端:光标要变手型
    async with cli.viewer("nt") as ws:
        v = v2kit.Viewer(ws)
        await v.drain(3)

        assert v.first("hello")["transport"] == "jpg"
        # **JPG 下帧就从这条通道来** —— 和 VNC 那条正相反。
        assert v.frames > 0, "JPG 下一连上就该有帧"

        on_link = await v.cursor_over(link)
        assert "pointer" in on_link, f"移到链接上,光标该变成手,实际:{on_link}"
        assert "default" in await v.move_to(*BLANK), "移开该变回箭头"

    # ------------------------------------------------------------ 点它
    cli.run("--user", "agent", "--note", "开个新闻看看",
            "click", "-t", "nt", "@" + link["ref"])

    # ------------------------------------------------- 弹出来的是个 tab
    #
    # 新 tab 是页面自己开的,异步冒出来 —— **等它出现,不是睡一觉**。
    # (`wait` 等不了这个,见 `wait_tabs` 的注释。)
    tabs = cli.wait_tabs("nt", 2)
    assert len(tabs) == 2, f"点完该有两个 tab:{[t['url'] for t in tabs]}"
    born = next(t for t in tabs if t["id"] != first)

    # **popup 一律转成 tab**,而且**转完还认得爹**
    # ([works/g](../../docs/v2/works/g-native-ui.md))—— 少了 opener,
    # `window.close()` 和 `window.opener` 这一类就断了。
    assert born["opener"] == first, f"新 tab 该记得是谁开的:{born}"
    assert born["reason"] == "page", "页面自己开的,不是人开的"
    assert "news.baidu" in born["url"], f"点「{MENU}」该去新闻:{born['url']}"

    # **焦点没跟过去。** 浏览器里点 `target=_blank` 会切过去,我们不切 ——
    # 因为切了就等于替调用方决定"接下来看哪个",而它可能正在别的 tab 上干活。
    # 要切是一条独立的命令。
    assert cli.api("tabs", "-t", "nt")["active"] == first

    # ------------------------------------------------ 新 tab 上照样能用
    #
    # `-t session:tab` 一个语法寻址到具体哪个 tab。
    here = f"nt:{born['index']}"
    cli.run("select-tab", "-t", here)
    assert cli.api("tabs", "-t", "nt")["active"] == born["id"]
    assert "news.baidu" in cli.out("url", "-t", "nt").strip()

    # **等的是那个 tab,不是当前 tab。** 上面那次 `tabs` 只证明"记录有了",
    # 页面内容还在路上 —— 不等就会 snapshot 到一个空页。
    cli.run("wait", "-t", here, "--css", "a", "--timeout", "30")
    on_news = cli.snap(here, "-i")
    assert len(on_news) >= 5, f"新闻页上该有一堆链接:{on_news}"
    # 号是接着发的,不是又从 e1 来一遍 —— 换了 tab 也一样
    assert int(on_news[0]["ref"][1:]) > int(link["ref"][1:])

    # -------------------------------------------------------------- 收
    cli.run("kill-tab", "-t", here)
    left = cli.api("tabs", "-t", "nt")["tabs"]
    assert [t["id"] for t in left] == [first], f"关掉就该只剩一个:{left}"

    # 一开一关都在流里,**而且说得出是谁开的**
    opened = [e for e in cli.api("log", "-t", "nt", "--kind", "tab")["entries"]]
    assert [e["event"] for e in opened] == ["opened", "opened", "closed"], opened
    assert opened[1]["reason"] == "page" and opened[1]["opener"] == first
