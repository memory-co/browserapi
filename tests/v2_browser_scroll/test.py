"""v2 · 人在画面上滚滚轮,里面那一页要跟着滚 —— **三条腿都得。**

滚动是这套东西里**最容易被漏掉的一下**:点和敲都有明显的后果(弹窗、字出现),
滚了却只是"画面动了一点",看着像没坏。而它走的路和点、敲**不是同一条**:
点和敲是 `now`(立刻发),滚轮进的是 `queue`(攒一批再发,
[b](../../docs/v2/works/b-input.md))—— 那一批要是没被冲出去,滚轮就是死的。

**判据是里面那一页真的滚了,不是画面变了。** 画面变了可能只是别的东西在动;
所以量的是**顶上那个元素的坐标**:滚下去之后它该往上走。

三条腿各验一遍,因为它们接事件的**不是同一个元素**
(JPG 是 `<img>`、VNC 是 `<canvas>`、DOM 是那个容器),
`bindPointer` 那个列表漏掉哪一个,那条腿的滚轮就是死的,**而且不报错**。

页面是本地那个小站的 `/tall`(见 [tests/site.py](../site.py))—— 滚动不该赌网速,
而且真站的高度是它说了算,今天 4000 明天 6000。
"""

import pytest

from tests import v2kit
from tests.site import TALL, site

pytestmark = pytest.mark.slow

#: 滚多少。**远小于页面总高**(`site.TALL`),不然滚到底就停了,量出来的差是错的。
DY = 900
assert DY * 3 < TALL
#: 允许的误差。滚轮到里面是按像素换算的,但浏览器有自己的平滑/节流,
#: 不必分毫不差 —— 要押住的是"**滚了,而且方向和量级对**"。
SLACK = 0.45


def top_y(cli) -> float:
    """顶上那个链接现在在视口的什么高度。**滚下去它就该往上走。**"""
    return cli.one("demo", "-i", role="link", name="TOP")["bbox"][1]


def check_one_leg(cli, who, leg: str) -> None:
    before = top_y(cli)
    was = who.paint().get("sig")

    who.wheel(DY)

    after = cli.until_value(lambda: top_y(cli), lambda y: y < before - DY * SLACK,
                            timeout=20,
                            what=f"{leg}:滚下去之后顶上那个元素该往上走")
    moved = before - after
    assert moved <= DY * 1.6, f"{leg}:滚过头了 —— 滚 {DY} 走了 {moved:.0f}"

    # **画面也得跟上。** 里面滚了而画面没动,人看到的还是旧的那一屏。
    # DOM 那条不是一张图,`sig` 是正文长度,滚动不改它 —— 那条另判。
    if who.paint().get("kind") != "dom":
        assert who.paint().get("sig") != was, f"{leg}:里面滚了,画面没跟上"

    # 再往回滚,得回得去 —— 只验一个方向的话,"滚轮只认一个方向"这类错漏得掉
    who.wheel(-DY)
    cli.until_value(lambda: top_y(cli), lambda y: y > after + DY * SLACK,
                    timeout=20, what=f"{leg}:往回滚该回得去")


@pytest.fixture
def cli(tmp_path):
    with v2kit.server(tmp_path) as c:
        yield c


def test_the_wheel_scrolls_the_page_on_jpg(cli):
    with site() as base:
        cli.run("new", "--id", "demo", "--transport", "jpg")
        cli.run("goto", "-t", "demo", base + "tall")
        with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
            who.wait_connected(); who.wait_painted()
            check_one_leg(cli, who, "JPG")
            assert who.errors == [], who.errors


def test_the_wheel_scrolls_the_page_on_vnc(cli):
    v2kit.need_vnc()
    with site() as base:
        cli.run("new", "--id", "demo", "--transport", "vnc")
        cli.run("goto", "-t", "demo", base + "tall")
        with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
            who.wait_connected(timeout=60000); who.wait_painted(timeout=45)
            check_one_leg(cli, who, "VNC")
            assert who.errors == [], who.errors


def test_the_wheel_scrolls_the_page_on_dom(cli):
    with site() as base:
        cli.run("new", "--id", "demo", "--transport", "dom")
        cli.run("goto", "-t", "demo", base + "tall")
        with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
            who.wait_connected(); who.wait_painted()
            check_one_leg(cli, who, "DOM")
            assert who.errors == [], who.errors
