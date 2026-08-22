"""v2 · 人从画面里开了个新 tab,那条 tab 条跟不跟得上。

[v2_cli_new_tab](../v2_cli_new_tab/) 验的是**后端那张表**:popup 转成 tab、
认得爹、焦点不跟过去。这一条验的是**人看到的那条 tab 条** ——
它是 [f](../../docs/v2/works/f-tabs.md) 说的"外挂的 bar,和真的那张表是同一份
数据",而**"同一份数据"这句话以前没有任何一处在验**。

一路都是人的动作:在画面上点链接、点 tab、点 `×`、点 `＋`、在地址栏敲回车。
每一下之后同时看两边 —— 人的屏幕上,和 `webmuxd tabs` 里。

**切过去之后要验到"用"那一半。** 只看 tab 条上的高亮和那张表里的 `active`,
验的都是"看"的那一半;而人接下来打的每一条**不带下标**的命令落在哪一页,
靠的是 session 里那个指针。所以切完之后还要:问一次不带下标的 `url`、
从内容上认一次那一页、再在**新那页**的输入框里敲几个字并盯住光标。
"""

import pytest

from tests import v2kit

pytestmark = pytest.mark.slow

SITE = "https://www.baidu.com/"
MENU = "新闻"
ELSE = "https://example.com/"
#: 点了 MENU 之后会落到这儿。
NEWS = "https://news.baidu.com/"
#: 往新那页的输入框里敲的字。**ASCII,不是汉字** ——
#: 客户端是在 `compositionend` 上发文本的(`input/keyboard.ts`),那是真 IME
#: 走的路;而 Playwright 的 `keyboard.type("天气")` 走 `insertText`,
#: **一个组字事件都不发**。拿它当"中文输入坏了"是冤枉产品,
#: 要验 IME 得另起一条(用 `Input.imeSetComposition`),这儿不掺。
WORD = "web"


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
        #
        # **先等那个 tab 自己加载完再切。** 不等的话切过去是一片还没画完的
        # 东西,而"画面跟过去了"这条判据要的是**新帧在流**,不是"切了"。
        # (news.baidu.com 挺重,满负载时它能拖到 30 秒开外。)
        cli.run("wait", "-t", f"nt:{born['index']}", "--css", "a", "--timeout", "30")

        was = who.paint()["sig"]
        who.pick_tab(1)

        after = who.wait_tabs(2)
        assert [t["active"] for t in after] == [False, True], after
        # **要整条地址,不能只找"news"三个字母。**
        # 原来写的是 `"news" in who.address_bar` —— 而没切过去时地址栏上是
        # `https://www.baidu.com/?tn=news`,**里面正好就有 news**,
        # 于是这条断言在真出问题的时候照样是绿的。
        # 一条会在坏的时候通过的断言,比没有还糟。
        assert who.address_bar.startswith(NEWS), \
            f"地址栏该跟着换:{who.address_bar!r}"
        assert cli.api("tabs", "-t", "nt")["active"] == born["id"]
        # **画面真的换过去了** —— 光是"标记成 active"证明不了什么
        who.wait_fresh(was)

        # -------------------------- 切了之后,"当前那个 tab"到底指着谁
        #
        # 上面那条 `["active"] == born["id"]` 验的是**那张表上的一个字段**。
        # 而人接下来打的每一条**不带下标**的命令落在哪一页,靠的是 session
        # 里那个指针 —— **两者不是一回事**。指针没跟过去的话,人看着新闻页、
        # 命令打在百度上,**全程一句错都不会报**。所以这儿从指针那一侧再问一次。
        assert cli.out("url", "-t", "nt").strip().startswith(NEWS), \
            f"不带下标的 url 还停在原来那页:{cli.out('url', '-t', 'nt')!r}"

        # ------------------ 新那个 tab 里的光标,以及往里敲字
        #
        # **光标是这条测试的重点。** 切过去之后光标那条通道得跟着换页 ——
        # 它是**按当前那页的元素算的**(`Input.dispatchMouseEvent` 之后读
        # 回来的 `cursor`),照着切走的那一页算就全错,而**错了不会报**:
        # 人只是觉得"这浏览器怪怪的"。
        #
        # 挑元素**从新那页的快照里挑,不写死名字** —— news.baidu.com 的
        # 版面天天在变,写死哪个链接就是给自己埋一个偶发红。
        here = cli.snap("nt", "-i")
        links = [e for e in here
                 if e["role"] == "link" and e["in_viewport"]
                 and e["bbox"][2] >= 24 and e["bbox"][3] >= 10]
        assert links, f"新那页上一个能点的链接都没有?{len(here)} 个元素"

        # **每次先回空地** —— 光标是"变了才报",不给起点就分不清
        # "本来就是手" 和 "刚变成手"。
        who.hover_blank()
        assert "pointer" in who.hover(links[0]), \
            f"新 tab 里移到链接上,光标该是手,实际:{who.cursor()!r}"

        boxes = [e for e in here if e["role"] == "textbox"]
        # **规则写明,不是随便挑一个** —— 新闻页上不止一个输入框
        # (底下还有个订阅框),要的是最靠上那个。
        top = min(boxes, key=lambda e: e["bbox"][1])
        assert top["bbox"][1] < 150, f"最靠上那个输入框都不在顶上:{top['bbox']}"

        who.hover_blank()
        assert "text" in who.hover(top), \
            f"新 tab 里移到输入框上,光标该是 I 型,实际:{who.cursor()!r}"

        # 敲字:**输入也得跟着切过去的那一页走**
        who.click(top)
        who.type(WORD)
        cli.until(lambda: cli.out("get", "value", "-t", "nt",
                                  "@" + top["ref"]).strip(),
                  WORD, what="人敲的字落进新那页的框里")

        # **敲完鼠标还停在输入框上,那就还该是 I 型。**
        assert "text" in who.cursor(), f"敲完光标不该变:{who.cursor()!r}"

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
        # **走完之后地址栏上留的还得是这一条。** 敲进去和显示出来是两件事 ——
        # 里面跳转了而地址栏停在人敲的那一刻,人就分不清"到底走没走"。
        assert who.address_bar.startswith(ELSE), \
            f"走完之后地址栏该是这一条:{who.address_bar!r}"

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
