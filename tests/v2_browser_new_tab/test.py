"""v2 · 人从画面里开了个新 tab,那条 tab 条跟不跟得上。

[v2_cli_new_tab](../v2_cli_new_tab/) 验的是**后端那张表**:popup 转成 tab、
认得爹、焦点不跟过去。这一条验的是**人看到的那条 tab 条** ——
它是 [f](../../docs/v2/works/f-tabs.md) 说的"外挂的 bar,和真的那张表是同一份
数据",而**"同一份数据"这句话以前没有任何一处在验**。

一路都是人的动作:在画面上点链接、点 tab、点 `×`、点 `＋`、在地址栏敲回车。
每一下之后同时看两边 —— 人的屏幕上,和 `webmuxd tabs` 里。
"""

import pytest

from tests import v2kit

pytestmark = pytest.mark.slow

SITE = "https://www.baidu.com/"
MENU = "新闻"
ELSE = "https://example.com/"


@pytest.fixture
def cli(tmp_path):
    v2kit.need_network(SITE)
    with v2kit.server(tmp_path) as c:
        yield c


def test_a_human_opens_and_juggles_tabs(cli):
    cli.run("new", "--id", "nt", "--transport", "jpg")
    cli.run("goto", "-t", "nt", SITE)
    cli.run("wait", "-t", "nt", "--css", "input", "--timeout", "30")

    with v2kit.human(cli.out("attach", "-t", "nt", "--print-only").strip()) as who:
        who.wait_connected()
        who.wait_painted()

        # ---------------------------------------------- 一开始就一个
        one = who.wait_tabs(1)
        assert one[0]["active"], one
        assert "baidu" in one[0]["title"], f"tab 条上该是里面那页的标题:{one}"

        # ------------------------------- 人在画面上点了个 target=_blank
        link = cli.one("nt", "-i", role="link", name=MENU)

        # 移上去先看光标 —— **链接上该是手型**。读的是人看到的那个
        # `style.cursor`,不是我们发出去的那条消息。
        who.hover_blank()
        assert "pointer" in who.hover(link), \
            f"移到链接上,光标该变成手,实际:{who.cursor()!r}"

        who.click(link)

        # **条目先有,URL 后到** —— 不等的话下一句看到的是空地址栏
        two = who.wait_tabs(2, settled=True)
        # **焦点不跟过去。** 浏览器里点 `target=_blank` 会切过去,我们不切 ——
        # 切了就等于替人决定"接下来看哪个"。这一条 [v2_cli_new_tab] 从后端
        # 验过,这儿验的是**人确实也看到自己还停在原来那个上**。
        assert [t["active"] for t in two] == [True, False], two

        # 两边说的是同一件事 —— **不是副本,是同一份数据**
        back = cli.api("tabs", "-t", "nt")["tabs"]
        assert len(back) == len(two) == 2
        born = next(t for t in back if not t["active"])
        assert born["opener"] == next(t["id"] for t in back if t["active"])

        # ---------------------------------------- 人点第二个 tab,画面换
        was = who.paint()["sig"]
        who.pick_tab(1)

        after = who.wait_tabs(2)
        assert [t["active"] for t in after] == [False, True], after
        assert "news" in who.address_bar, f"地址栏该跟着换:{who.address_bar}"
        assert cli.api("tabs", "-t", "nt")["active"] == born["id"]
        # **画面真的换过去了** —— 光是"标记成 active"证明不了什么
        who.wait_fresh(was)

        # ------------------------------------------ 人点 ＋ 开个空白页
        who.new_tab()
        three = who.wait_tabs(3)
        assert three[-1]["active"], three
        assert len(cli.api("tabs", "-t", "nt")["tabs"]) == 3

        # -------------------------------- 人在地址栏敲个地址,回车就走
        #
        # **这是人最熟的那一下**,而且它走的是观看页自己的地址栏,
        # 不是我们的 CLI。
        who.go(ELSE)
        here = next(t["url"] for t in cli.api("tabs", "-t", "nt")["tabs"] if t["active"])
        assert here.startswith(ELSE), f"地址栏敲的那一下没到里面:{here}"

        # ------------------------------------------- 人点 × 关掉中间那个
        who.close_tab(1)
        left = who.wait_tabs(2)
        assert not any("news" in t["title"] for t in left), left
        assert len(cli.api("tabs", "-t", "nt")["tabs"]) == 2

        assert who.errors == [], f"摆弄 tab 的时候报了错:{who.errors}"

    # 一开一关都进了那条流,**而且分得清是谁开的**
    tab_log = [e for e in cli.api("log", "-t", "nt", "--kind", "tab")["entries"]]
    assert [e["event"] for e in tab_log].count("opened") == 3, tab_log
    assert any(e.get("reason") == "page" for e in tab_log), "页面自己开的那个该标出来"
    assert any(e["event"] == "closed" for e in tab_log)
