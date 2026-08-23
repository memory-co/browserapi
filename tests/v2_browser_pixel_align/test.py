"""v2 · 像素对齐:人的窗口多大,里面那个浏览器就多大。

ttyd 把终端调成你窗口那么大,tmux 里的 80 列就真是 80 列 ——
**这一条我们也得做到**,不然人拉大窗口只是把同一张图放大,越拉越糊。

要验的是三个数**同时**相等:

    人窗口里给画面留的那块地  ==  画面元素占的地  ==  帧本身的像素

少验哪一个都会漏掉一整类错:只比前两个,一张 1024 宽的图撑在 1260 的框里
也算"对齐"(其实是拉伸);只比后两个,元素被 CSS 缩过一道也看不出来。

两条腿的机理完全不同,所以各验各的:

- **JPG**:一条 CDP 命令改视口,截图跟着出。三个数严丝合缝。
- **VNC**:画面是那个 X 桌面里的**一块** —— 桌面一次开到 4K 不动,
  里面那个 chrome 窗口才是画面,观看端只取左上那一块。改尺寸就是
  一条 CDP 命令摁窗口,**和 JPG 是同一个心智模型**。

DOM 那条腿这一轮不验:它重放的是 DOM,尺寸的判据是另一回事。

要网络;VNC 那个还要 xpra,没有就跳过。
"""

import time

import pytest

from tests import v2kit
from tests.site import site

pytestmark = pytest.mark.slow

#: **故意用一个不滚动的页面**(小站的 `/about`)。判据里有一条是
#: "页面自己以为的宽度",而 `cssVisualViewport` 是**不含滚动条**的 ——
#: 会滚的页面上它比画面小 15 像素,那不是错,是浏览器本来就这样。

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


def settle(cli, who, timeout: float = 30) -> dict:
    """等到帧的尺寸追上那块地,把**那一次**测量交出来。

    **等那件事发生,不睡一个秒数** —— 改尺寸要走一个来回,睡多久都是赌。

    **而且一轮只能量一次。** 第一版写的是
    `measure()["frame"] == measure()["stage"]`,然后 `return measure()` ——
    三个**不同时刻**的数。改尺寸中间那一瞬三者本来就不一致,于是它
    偶发地把一次半路状态判成"到位了",再把另一次半路状态交出去断言。
    **一条自己制造竞态的测试,红起来指的是被测的东西,查半天在自己身上。**

    `cli` 这个参数留着是为了调用处读起来一致,这儿用不上。
    """
    del cli
    deadline = time.monotonic() + timeout
    while True:
        m = measure(who)
        if m["frame"] == m["stage"]:
            return m
        assert time.monotonic() < deadline, \
            f"{timeout}s 内帧的尺寸没追上那块地:{m}"
        who.page.wait_for_timeout(300)


@pytest.fixture
def cli(tmp_path):
    # **不出外网。** 页面是本地那个小站(tests/site.py)——
    # 测的是我们自己的东西,不该把别人的可用性押进来。
    with site() as base, v2kit.server(tmp_path) as c:
        c.site = base
        yield c


def test_the_jpg_picture_tracks_the_window(cli):
    """JPG:三个数严丝合缝,而且**页面自己也是这个宽度**。

    最后那一条不是多余的:截图可以是对的而页面按另一个宽度排版 ——
    那时候人看到的图没问题,agent 拿到的元素坐标却是另一套。
    """
    cli.run("new", "--id", "demo", "--transport", "jpg")
    cli.run("goto", "-t", "demo", cli.site + "about")

    with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
        who.wait_connected()
        who.wait_painted()

        for w, h in SIZES:
            who.resize(w, h)
            # 「帧 == 那块地」由 `settle()` 押着(等不到就超时,带上三个数);
            # 这儿判的是**另一件事**:那张图有没有被 CSS 缩放过。
            m = settle(cli, who)
            assert m["el"] == m["stage"], f"画面元素没铺满:{m}"

            # **页面自己以为的宽度。** JPG 下视口是我们用一条 CDP 命令钉的,
            # 所以这儿要求完全相等 —— 差一个像素就说明那条命令没跟上。
            vp = cli.api("snapshot", "-t", "demo")["viewport"]
            assert [vp["w"], vp["h"]] == m["stage"], f"页面按别的宽度排的:{vp} vs {m}"


def test_the_vnc_picture_tracks_the_window(cli):
    """VNC:那个 X 桌面跟着人走,桌面里那个 chrome 窗口再跟着桌面走。"""
    v2kit.need_vnc()
    cli.run("new", "--id", "demo", "--transport", "vnc")
    cli.run("goto", "-t", "demo", cli.site + "about")

    with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
        who.wait_connected()
        who.wait_painted()

        for w, h in SIZES:
            who.resize(w, h)
            m = settle(cli, who)
            assert m["el"] == m["stage"], f"画面元素没铺满:{m}"

            # **和 JPG 一样,要求完全相等。**
            #
            # 一度是"画面 +1":那时画面就是整个 X 桌面,而 chrome 不接受一个
            # 正好等于屏幕大小的窗口(给它 WxH 到手永远是 W-1 x H-1)——
            # 于是只能多要一像素去盖住那条缝。
            # 现在桌面一次开到 4K 不动,画面是里面那个窗口,窗口永远比屏幕小,
            # **那条硬规则碰都碰不到**。多出来的一像素跟着没了。
            vp = cli.api("snapshot", "-t", "demo")["viewport"]
            assert [vp["w"], vp["h"]] == m["stage"], f"页面按别的宽度排的:{vp} vs {m}"
