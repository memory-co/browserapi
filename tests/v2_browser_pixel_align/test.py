"""v2 · 像素对齐:人的窗口多大,里面那个浏览器就多大。

ttyd 把终端调成你窗口那么大,tmux 里的 80 列就真是 80 列 ——
**这一条我们也得做到**,不然人拉大窗口只是把同一张图放大,越拉越糊。

要验的是三个数**同时**相等:

    人窗口里给画面留的那块地  ==  画面元素占的地  ==  帧本身的像素

少验哪一个都会漏掉一整类错:只比前两个,一张 1024 宽的图撑在 1260 的框里
也算"对齐"(其实是拉伸);只比后两个,元素被 CSS 缩过一道也看不出来。

两条腿的机理完全不同,所以各验各的:

- **JPG**:一条 CDP 命令改视口,截图跟着出。三个数严丝合缝。
- **VNC**:画面是一个真的 X 桌面。链条是 观看端报尺寸 → xpra 调 X 显示 →
  服务端把新尺寸回给观看端 → 观看端这才让我们去摁那个 chrome 窗口。
  中间任何一环断了,人拉窗口就是白拉 —— 这条链上**每一环都真断过一次**,
  记在 `docs/v2/works/test.md`。

DOM 那条腿这一轮不验:它重放的是 DOM,尺寸的判据是另一回事。

要网络;VNC 那个还要 xpra,没有就跳过。
"""

import pytest

from tests import v2kit

pytestmark = pytest.mark.slow

#: **故意用一个不滚动的页面。** 判据里有一条是"页面自己以为的宽度",
#: 而 `cssVisualViewport` 是**不含滚动条**的 —— 百度那种会滚的页面上,
#: 它比画面小 15 像素,那不是错,是浏览器本来就这样。
#: 拿会滚的页面来验这一条,量的就不是对齐,是滚动条宽度。
SITE = "https://example.com/"

#: 人会拉到的几个尺寸。**故意有奇数**1151 不是随手写的,
#: 是为了让"少一像素多一像素"这类错露出来 —— 全用偶数的话,
#: 一个 `//2*2` 的舍入 bug 可以一路蒙混过去。
SIZES = ((1000, 700), (1440, 820), (1151, 641), (1280, 900))

#: 画面元素和帧的尺寸。**一次 evaluate 全拿到**,不分三次 ——
#: 分三次的话中间可能又来一帧,量到的是两个时刻的东西。
_MEASURE = """
(sel) => {
  const st = document.getElementById("stage");
  const el = document.querySelector(sel);
  const r  = el.getBoundingClientRect();
  const w  = el.naturalWidth  || el.width;
  const h  = el.naturalHeight || el.height;
  return {
    stage: [st.clientWidth - 20, st.clientHeight - 20],
    el:    [Math.round(r.width), Math.round(r.height)],
    frame: [w, h],
  };
}
"""


def measure(who) -> dict:
    return who.page.evaluate(_MEASURE, who.screen_sel())


def settle(cli, who) -> dict:
    """等到帧的尺寸追上那块地,再把三个数一起交出来。

    **等那件事发生,不睡一个秒数。** 改尺寸这条链上有三个来回
    (观看端 → xpra → 观看端 → 我们),睡多久都是赌。
    """
    cli.until(lambda: measure(who)["frame"] == measure(who)["stage"], True,
              timeout=30, what="帧的尺寸追上窗口")
    return measure(who)


@pytest.fixture
def cli(tmp_path):
    v2kit.need_network(SITE)
    with v2kit.server(tmp_path) as c:
        yield c


def test_the_jpg_picture_tracks_the_window(cli):
    """JPG:三个数严丝合缝,而且**页面自己也是这个宽度**。

    最后那一条不是多余的:截图可以是对的而页面按另一个宽度排版 ——
    那时候人看到的图没问题,agent 拿到的元素坐标却是另一套。
    """
    cli.run("new", "--id", "demo", "--transport", "jpg")
    cli.run("goto", "-t", "demo", SITE)

    with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
        who.wait_connected()
        who.wait_painted()

        for w, h in SIZES:
            who.resize(w, h)
            m = settle(cli, who)
            assert m["el"] == m["stage"], f"画面元素没铺满:{m}"
            assert m["frame"] == m["stage"], f"帧的像素不是这么多:{m}"

            # **页面自己以为的宽度。** JPG 下视口是我们用一条 CDP 命令钉的,
            # 所以这儿要求完全相等 —— 差一个像素就说明那条命令没跟上。
            vp = cli.api("snapshot", "-t", "demo")["viewport"]
            assert [vp["w"], vp["h"]] == m["stage"], f"页面按别的宽度排的:{vp} vs {m}"


def test_the_vnc_picture_tracks_the_window(cli):
    """VNC:那个 X 桌面跟着人走,桌面里那个 chrome 窗口再跟着桌面走。"""
    v2kit.need_vnc()
    cli.run("new", "--id", "demo", "--transport", "vnc")
    cli.run("goto", "-t", "demo", SITE)

    with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
        who.wait_connected()
        who.wait_painted()

        for w, h in SIZES:
            who.resize(w, h)
            m = settle(cli, who)
            assert m["el"] == m["stage"], f"画面元素没铺满:{m}"
            assert m["frame"] == m["stage"], f"桌面不是这么大:{m}"

            # **VNC 下窗口比桌面大一像素,那是故意的。**
            # chrome 不接受一个正好等于屏幕大小的窗口,给它 WxH 到手永远是
            # W-1 x H-1 —— 那样画面右下会各露一条 1 像素的桌面底色,**有缝**。
            # 多要一像素则是窗口盖满桌面,多出来的落在桌面外,看不见。
            # 理由写在 `webmuxd/screen.py: _fill_screen()`。
            vp = cli.api("snapshot", "-t", "demo")["viewport"]
            assert [vp["w"], vp["h"]] == [m["stage"][0] + 1, m["stage"][1] + 1], \
                f"窗口没盖住桌面(或盖过头了):{vp} vs {m}"
