"""v2 · 换画面:三个按钮,人点了要真的换,而且换得回来。

**这条是被一个 bug 逼出来的。** `VNC → JPG → VNC` 切不回去:第二次点 VNC
按钮,画面纹丝不动 —— **没有报错,console 也是干净的**。
原因是"显示哪个元素"那三行只写在 `startXpra()` 里,而它被 `if (!xpra)`
挡着(切走时那条连接没关)。两件事缠在一起,就漏了一条路。

顺带这也是**VNC 那条腿唯一的端到端验证**:
[v2_cli_simple](../v2_cli_simple/) 走 VNC 但只验到"那条通道接得上",
真正"xpra 的像素有没有画到 canvas 上"要一个真浏览器才判得了。

要 xpra,没有就跳过。
"""

import pytest

from tests import v2kit
from tests.site import site

pytestmark = pytest.mark.slow



@pytest.fixture
def cli(tmp_path):
    # **不出外网。** 页面是本地那个小站(tests/site.py)——
    # 测的是我们自己的东西,不该把别人的可用性押进来。
    v2kit.need_vnc()
    with site() as base, v2kit.server(tmp_path) as c:
        c.site = base
        yield c


def test_switching_the_picture_back_and_forth(cli):
    cli.run("new", "--id", "demo", "--transport", "vnc")
    cli.run("goto", "-t", "demo", cli.site)
    cli.run("wait", "-t", "demo", "--css", "input", "--timeout", "30")

    with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
        who.wait_connected()

        # ------------------------------------------------ VNC 那条腿
        #
        # **判据是画布上真的有东西,不是"有尺寸"** —— 一整块死白也是有尺寸的。
        vnc = who.wait_painted()
        assert vnc["kind"] == "canvas", f"VNC 该画在 canvas 上:{vnc}"
        assert vnc["colors"] > 1, f"canvas 是一整块纯色 —— 没画出来:{vnc}"
        assert "xpra" in who.status, who.status

        # 输入**永远只走一条通道**([b §1](../../docs/v2/works/b-input.md)),
        # 和像素从哪来无关。VNC 下点一下也该到里面。
        _poke(cli, who, "vnc", "vnc")

        # ------------------------------------------------ 切到 JPG
        jpg = who.switch_to("JPG")
        assert jpg["kind"] == "img", f"JPG 该画在 img 上:{jpg}"
        assert jpg["colors"] > 1, f"切过去之后是白屏:{jpg}"
        # **两条腿的尺寸该是同一个。**
        #
        # 第一版写的是"该不一样",红了 —— 想当然以为 JPG 总是跟着人的窗口走。
        # 不对:有头这条路上浏览器跑在 xpra 的 X 显示里,**窗口是那个显示
        # 定死的**,JPG 截的也是同一个视口。客户端里那句
        # 「xpra 的尺寸是 X 显示定的,问也没用」说的就是这件事。
        #
        # (跟着人的窗口走那条在 [v2_browser_simple](../v2_browser_simple/) ——
        # 那边是无头 session,视口是 `setDeviceMetricsOverride` 说了算。)
        assert (jpg["w"], jpg["h"]) == (vnc["w"], vnc["h"]), \
            f"同一个 X 显示,两条腿该量到同一个尺寸:{vnc} / {jpg}"

        _poke(cli, who, "jpg", "vncjpg")

        # ------------------------------------------- 切回 VNC ← 就是这条
        #
        # **这一步曾经什么都不做。** 而且不报错 —— 人点了按钮,画面还是
        # 上一条腿的最后一帧,看上去像"卡住了"。
        back = who.switch_to("VNC")
        assert back["kind"] == "canvas", f"切回 VNC 该回到 canvas:{back}"
        assert back["colors"] > 1, f"切回来是白屏:{back}"
        assert (back["w"], back["h"]) == (vnc["w"], vnc["h"]), \
            f"切回来尺寸该和第一次一样:{vnc} / {back}"

        _poke(cli, who, "!", "vncjpg!")

        # 从头到尾一条错都没报 —— **这个 bug 当初就是这样藏住的**
        assert who.errors == [], f"换画面报了错:{who.errors}"


def _poke(cli, who, text: str, want: str) -> None:
    """**每次都重新问一遍那个框在哪**,再点、再敲。

    不能把 bbox 存下来复用 —— 第一版那么写,红了:敲完第一个词之后
    百度首页的搜索框从 y=195 挪到了 y=25(logo 缩起来了),
    拿旧坐标去点就点到了页面别处,**而且不报错**。

    这跟 `@e1` 那条规矩是同一件事:**页面变了就重新 snapshot**。
    测试自己也得守。
    """
    box = next(e for e in cli.snap("demo", "-i")
               if "type" in e["affords"] and e["in_viewport"])
    who.click(box)
    who.type(text)
    # **等它真的到了里面**,别赌那几百毫秒够不够 —— 满负载时不够。
    cli.until(lambda: _value(cli), want, what=f"「{text}」落进框里")


def _value(cli) -> str:
    return next(e["value"] for e in cli.snap("demo", "-i") if "type" in e["affords"])
