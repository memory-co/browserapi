"""v2 · 网抖一下,画面回不回得来。

**最终用户最常撞的一类**:笔记本合盖、切了个 WiFi、地铁进隧道 ——
回来之后画面是继续动,还是永远停在那一帧。

写这条的时候发现两条通道**一条会重连一条不会**:`/channel/cdp` 断了
1 秒后自己爬回来,`/channel/xpra` 断了就报个 `closed` 完事。
而**代码里没有一句话说这是有意的** —— 是漏了。表现是 VNC 下网抖一次,
画面就永远停在最后一帧,只能刷新页面。

判据不能只看"画面上有没有东西":canvas 上留着断线前那一帧,
颜色数一模一样。**要证明的是新帧还在流** —— 所以断线恢复之后让里面动一下,
再看画面跟不跟。
"""

import pytest

from tests import v2kit
from tests.site import site

pytestmark = pytest.mark.slow

#: 换过去要**看得出来不一样**。
#: 第一版写的是 example.org —— 和 example.com 渲染出来是同一张页,
#: VNC 那条于是一动不动:xpra 只发变化的区域,**页面没变就没有帧**。
#: (JPG 那条却过了 —— 每帧重编码带点噪声,指纹照样会变。
#: 一个判据在两条腿上一真一假,那是判据没写对,不是腿有问题。)



@pytest.fixture
def cli(tmp_path):
    # **不出外网。** 页面是本地那个小站(tests/site.py)——
    # 测的是我们自己的东西,不该把别人的可用性押进来。
    with site() as base, v2kit.server(tmp_path) as c:
        c.site = base
        yield c


def _open(cli, sid: str, transport: str):
    cli.run("new", "--id", sid, "--transport", transport)
    cli.run("goto", "-t", sid, cli.site + "about")
    cli.run("wait", "-t", sid, "--css", "body", "--timeout", "30")
    return cli.out("attach", "-t", sid, "--print-only").strip()


def _check(cli, sid: str, who, kind: str) -> None:
    """掐掉 `kind` 那条,然后要它自己回来,**而且新帧真的在流**。"""
    who.wait_connected()
    who.wait_painted()
    before = who.channel_count(kind)
    assert before == 1, f"该有一条 {kind}:{[w.url for w in who.channels]}"

    assert who.cut(kind) == 1

    # **自己爬回来** —— 不用人刷新页面。多出来的那一条就是证据。
    for _ in range(60):
        if who.channel_count(kind) > before:
            break
        who.page.wait_for_timeout(500)
    else:
        raise AssertionError(
            f"{kind} 断了之后没重连:{who.status} / {[w.url for w in who.channels]}")

    # **回来了不只是"接上了",是"画面还在动"。**
    # 让里面换一页,画面得跟着变 —— 只看"有没有东西"是看不出来的,
    # 断线前那一帧还留在画布上,颜色数一模一样。
    was = who.paint()["sig"]
    cli.run("goto", "-t", sid, cli.site + "news")
    fresh = who.wait_fresh(was)
    assert fresh["colors"] > 1, fresh

    # 好起来了要说出来 —— 状态条回到「已连接」,画面不再是灰的
    assert "已连接" in who.status, who.status
    assert "dead" not in (who.screen().get_attribute("class") or "")
    assert who.errors == [], who.errors


def test_the_picture_channel_comes_back_on_jpg(cli):
    """无头那条:像素走 `/channel/cdp`,断的也是它。"""
    url = _open(cli, "demo", "jpg")
    with v2kit.human(url, intercept=True) as who:
        _check(cli, "demo", who, "cdp")


def test_the_picture_channel_comes_back_on_vnc(cli):
    """有头那条:像素走 `/channel/xpra`。**这一条以前回不来。**"""
    v2kit.need_vnc()
    url = _open(cli, "demo", "vnc")
    with v2kit.human(url, intercept=True) as who:
        _check(cli, "demo", who, "xpra")
