"""v2 · 一个 server 底下两个 session,各干各的,互不串。

**这是 tmux 那一半的核心承诺**:一个 server 持有多个 session,
`-t` 说的是哪一个([k](../../docs/v2/works/k-one-server.md))。
串了会怎样:两个 agent 同时在跑,A 的点击落到了 B 的页面上 ——
**而两边都不会报错**。

从头到尾只有 CLI。
"""

import pytest

from tests import v2kit
from tests.site import site

pytestmark = pytest.mark.slow



@pytest.fixture
def cli(tmp_path):
    # **不出外网。** 页面是本地那个小站(tests/site.py)——
    # 测的是我们自己的东西,不该把别人的可用性押进来。
    with site() as base, v2kit.server(tmp_path) as c:
        c.site = base
        yield c


def test_two_sessions_never_bleed_into_each_other(cli):
    # ---------------------------------------------------------- 两个
    cli.run("new", "--id", "alpha", "--transport", "jpg")
    cli.run("new", "--id", "beta", "--transport", "jpg")

    rows = {s["id"]: s for s in cli.api("ls")["sessions"]}
    assert set(rows) == {"alpha", "beta"}
    # **一个 server 一个口,session 是那个口下面的一段路径**
    assert rows["alpha"]["url"] == "/s/alpha/"
    assert rows["beta"]["url"] == "/s/beta/"

    # **`new` 幂等** —— 同一个 id 再来一次不该失败(像 `tmux new -A -s`)
    cli.run("new", "--id", "alpha")
    assert len(cli.api("ls")["sessions"]) == 2, "幂等不该多出一个"

    # --------------------------------------------- 各自去各自的地方
    cli.run("goto", "-t", "alpha", cli.site + "about")
    cli.run("goto", "-t", "beta", cli.site + "news")
    cli.run("wait", "-t", "alpha", "--css", "body", "--timeout", "30")
    cli.run("wait", "-t", "beta", "--css", "input", "--timeout", "30")

    assert cli.out("url", "-t", "alpha").strip().endswith("/about")
    assert cli.out("url", "-t", "beta").strip().endswith("/news")

    # 正文也是两回事 —— **不是同一个页面被读了两遍**
    assert "没什么可说的" in cli.out("capture", "-t", "alpha")
    assert "新闻" in cli.out("capture", "-t", "beta")

    # ------------------------------------------- 号不串(这条最要紧)
    #
    # `@e1` 是 session 里的号,而**号里自己带着 tab**
    # ([models.RefTable](../../webmuxd/models.py))。拿 alpha 的号去
    # beta 上点,必须报错 —— 悄悄点中 beta 上某个元素是最难查的一类错。
    a_ref = "@" + cli.snap("alpha")[0]["ref"]
    wrong = cli.sh("click", "-t", "beta", a_ref)
    assert wrong.returncode == 4, f"别的 session 的号该点不动:{wrong.stdout!r}"

    # ------------------------------------------------- tab 也是各自的
    cli.run("new-tab", "-t", "alpha", "-u", cli.site + "about")
    assert len(cli.api("tabs", "-t", "alpha")["tabs"]) == 2
    assert len(cli.api("tabs", "-t", "beta")["tabs"]) == 1, "beta 不该跟着多一个"

    # ------------------------------------------------ 日志也是各自的
    urls = {e.get("url") for e in cli.api("log", "-t", "beta")["entries"]}
    assert not any(u and u.endswith("/about") for u in urls), \
        f"beta 的日志里不该有 alpha 去过的地方:{urls}"

    # ------------------------------------- 关掉一个,另一个照常能用
    #
    # **这才是"互不影响"的那一下。** 共享着浏览器进程或事件流的实现
    # 会在这儿露馅:关掉 alpha 之后 beta 跟着哑掉,而且不报错。
    cli.run("kill", "-t", "alpha")
    assert cli.sh("has", "-t", "alpha").returncode == 3
    cli.run("has", "-t", "beta")

    cli.run("goto", "-t", "beta", cli.site + "about")
    cli.run("wait", "-t", "beta", "--css", "body", "--timeout", "30")
    assert "没什么可说的" in cli.out("capture", "-t", "beta"), \
        "关掉 alpha 之后 beta 还得能干活"

    assert [s["id"] for s in cli.api("ls")["sessions"]] == ["beta"]
