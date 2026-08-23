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

from urllib.parse import urlparse

import pytest

from tests import v2kit
from tests.site import site

pytestmark = pytest.mark.slow

MENU = "新闻"
#: 往新那页的输入框里敲的字。**ASCII,不是汉字** ——
#: 客户端是在 `compositionend` 上发文本的(`input/keyboard.ts`),那是真 IME
#: 走的路;而 Playwright 的 `keyboard.type("天气")` 走 `insertText`,
#: **一个组字事件都不发**。拿它当"中文输入坏了"是冤枉产品,
#: 要验 IME 得另起一条(用 `Input.imeSetComposition`),这儿不掺。
WORD = "web"


def selected(who) -> int:
    """**外挂那条 bar 上高亮的是第几个。**

    读的是 `.tab.on` —— 人眼看到的那个高亮,不是我们内部记着的什么状态。
    高亮不是恰好一个就直接失败:两个亮着和一个都不亮,都是"人不知道自己
    在哪一页",而这两种都出现过。
    """
    on = [i for i, t in enumerate(who.tabs()) if t["active"]]
    assert len(on) == 1, f"bar 上高亮的不是恰好一个:{who.tabs()}"
    return on[0]


def foreground(cli, target: str) -> list[str]:
    """**浏览器自己把哪一页放在前台。**

    判据是页面侧的 `document.visibilityState`(小站每一页都带,`site._VIS`)——
    **不是我们那张表里的任何一个字段**。这一条是这个函数存在的全部理由:
    上面那四样彼此对齐时,它们可能一起是错的,因为它们本来就是同一份账。
    """
    rows = cli.api("tabs", "-t", target)["tabs"]
    return [cli.out("get", "text", "-t", f"{target}:{n}", "--css", "#vis").strip()
            for n in range(len(rows))]


def agree(cli, who, target: str, when: str) -> dict:
    """**六样东西说的得是同一个 tab**,返回那个 tab。

    - 外挂 bar 上高亮的那个(人眼看到的)
    - 地址栏里那条(人眼看到的)
    - 后端那张表里的 `active`
    - 不带下标的命令落在谁身上(session 里那个指针)
    - **浏览器自己的前台**(`document.visibilityState`)
    - **画面上放的到底是哪一页**(`who.showing()`)

    **分开验各自都能绿。** bar 高亮着第一个、画面放着第二个,两边各自
    "自洽",合起来才是错的 —— 而人看到的正是合起来那一份。这条 bug 真出过:
    地址栏停在 `www.baidu.com/?tn=news`,画面里却是 news.baidu.com。

    **后两样是补上去的,而且它们和前四样不是一类东西。** 前四样全部来自
    我们自己那张表(或它的副本)—— 一份账抄四遍,再怎么对账也对不出问题:
    它们一起漂的时候一条都不会红。

    那次漏掉的就是这个:页面 `target=_blank` 开出来的 tab,**Chromium 直接把
    前台切过去了**,而"焦点不跟过去"这条规矩只写在我们的字段里,
    从没在浏览器那边落实过。VNC 上人看到的是新那页、四样却齐刷刷指着旧那页;
    JPG 上截屏挂在一个后台 target 上,画面冻在最后一帧,**看着还挺一致**。

    所以补的两样各自打断一处:

    - 第五样的**来源**不同 —— `document.visibilityState`,页面自己说的
    - 第六样的**问题**不同 —— 原来对画面只问过"有东西吗""变了吗",
      从来没问过"**你放的是哪一页**"。而后者才是人看到的那件事
    """
    i = selected(who)
    rows = cli.api("tabs", "-t", target)
    assert len(rows["tabs"]) == len(who.tabs()), \
        f"{when}:bar 上 {len(who.tabs())} 个,后端 {len(rows['tabs'])} 个"
    mine = rows["tabs"][i]
    assert rows["active"] == mine["id"], \
        f"{when}:bar 上高亮第 {i} 个({mine['id']}),后端说活的是 {rows['active']}"
    assert who.address_bar == (mine["url"] or ""), \
        f"{when}:地址栏是 {who.address_bar!r},高亮那个 tab 是 {mine['url']!r}"
    assert cli.out("url", "-t", target).strip() == (mine["url"] or ""), \
        f"{when}:不带下标的命令落在 {cli.out('url', '-t', target)!r},"\
        f"而高亮的是 {mine['url']!r}"
    vis = foreground(cli, target)
    want = ["visible" if n == i else "hidden" for n in range(len(vis))]
    assert vis == want, \
        f"{when}:浏览器的前台和我们说的对不上 —— 高亮第 {i} 个,页面自己报 {vis}"

    # **画面上放的是不是同一页。** 小站每页一个底色,所以这一问答得出来。
    where = urlparse(mine["url"] or "").path or "/"
    who._until(lambda: who.showing() == where,
               f"{when}:画面上该是 {where}",
               show=lambda: f"画面上是 {who.showing()!r}")
    return mine


@pytest.fixture
def cli(tmp_path):
    # **不出外网。** 页面是本地那个小站(tests/site.py)——
    # 测的是我们自己的东西,不该把别人的可用性押进来。
    with site() as base, v2kit.server(tmp_path) as c:
        c.site = base
        yield c


def test_a_human_opens_and_juggles_tabs(cli):
    cli.run("new", "--id", "nt", "--transport", "jpg")
    cli.run("goto", "-t", "nt", cli.site)
    cli.run("wait", "-t", "nt", "--css", "input", "--timeout", "30")

    with v2kit.human(cli.out("attach", "-t", "nt", "--print-only").strip()) as who:
        who.wait_connected()
        who.wait_painted()

        # ---------------------------------------------- 一开始就一个
        one = who.wait_tabs(1)
        assert one[0]["active"], one
        # **tab 条上写的是主机名,不是 `<title>`** —— 短、认得出来,
        # 而 `<title>` 常常长得放不下(f §2)。
        assert "127.0.0.1" in one[0]["title"], f"tab 条上该认得出是哪一页:{one}"

        # ------------------------------- 人在画面上点了个 target=_blank
        link = cli.one("nt", "-i", role="link", name=MENU)

        # 移上去先看光标 —— **链接上该是手型**。读的是人看到的那个
        # `style.cursor`,不是我们发出去的那条消息。
        who.hover_blank()
        assert "pointer" in who.hover(link, "pointer"), \
            f"移到链接上,光标该变成手,实际:{who.cursor()!r}"

        who.click(link)

        # **条目先有,URL 后到** —— 不等的话下一句看到的是空地址栏
        two = who.wait_tabs(2, settled=True)
        # **焦点跟过去了。** 人普通左键点了个 `target=_blank`,浏览器把它
        # 开在**前台** —— `active` 就是"浏览器把哪一页放在前台",所以它跟着。
        #
        # 这儿以前写的是 `== [True, False]`("我们不切")。那条规矩只写在
        # 我们自己的字段里,**浏览器那边从没成立过**:同一时刻人看到的是新那页。
        # 断言和事实各自自洽,合起来是错的 —— 而人看到的正是合起来那一份。
        who._until(lambda: [t["active"] for t in who.tabs()] == [False, True],
                   "高亮跟到新开的那个上", show=lambda: who.tabs())
        assert agree(cli, who, "nt", "人点开了个新 tab 之后")["url"].endswith("/news")

        # 两边说的是同一件事 —— **不是副本,是同一份数据**
        back = cli.api("tabs", "-t", "nt")["tabs"]
        assert len(back) == len(two) == 2
        born = next(t for t in back if t["active"])
        home = next(t for t in back if not t["active"])
        assert born["opener"] == home["id"], f"新那个该认得爹:{back}"

        # **先等那个 tab 自己加载完再往里点。** 不等的话下面挑元素挑的是
        # 一片还没画完的东西。等的是"加载完"这件事本身,不是给
        # `wait --css` 一个更大的秒数。
        cli.until(lambda: cli.api("tabs", "-t", "nt")["tabs"][born["index"]]["loading"],
                  False, timeout=90, what="新那个 tab 自己加载完")
        cli.run("wait", "-t", f"nt:{born['index']}", "--css", "a", "--timeout", "30")

        # ------------------ 新那个 tab 里的光标,以及往里敲字
        #
        # **光标是这条测试的重点。** 前台换页之后光标那条通道得跟着换 ——
        # 它是**按当前那页的元素算的**(`Input.dispatchMouseEvent` 之后读
        # 回来的 `cursor`),照着切走的那一页算就全错,而**错了不会报**:
        # 人只是觉得"这浏览器怪怪的"。
        #
        # 挑元素**从新那页的快照里挑,不写死名字**:写死哪个链接就是
        # 把这条测试绑在某一版页面上。
        here = cli.snap("nt", "-i")
        links = [e for e in here
                 if e["role"] == "link" and e["in_viewport"]
                 and e["bbox"][2] >= 24 and e["bbox"][3] >= 10]
        assert links, f"新那页上一个能点的链接都没有?{len(here)} 个元素"

        # **每次先回空地** —— 光标是"变了才报",不给起点就分不清
        # "本来就是手" 和 "刚变成手"。
        who.hover_blank()
        assert "pointer" in who.hover(links[0], "pointer"), \
            f"新 tab 里移到链接上,光标该是手,实际:{who.cursor()!r}"

        boxes = [e for e in here if e["role"] == "textbox"]
        assert len(boxes) == 1, f"这一页上该只有一个输入框:{boxes}"
        top = boxes[0]

        who.hover_blank()
        assert "text" in who.hover(top, "text"), \
            f"新 tab 里移到输入框上,光标该是 I 型,实际:{who.cursor()!r}"

        # 敲字:**输入也得跟着切过去的那一页走**
        who.click(top)
        who.type(WORD)
        cli.until(lambda: cli.out("get", "value", "-t", "nt",
                                  "@" + top["ref"]).strip(),
                  WORD, what="人敲的字落进新那页的框里")

        # **敲完鼠标还停在输入框上,那就还该是 I 型。**
        assert "text" in who.cursor(), f"敲完光标不该变:{who.cursor()!r}"

        # ------------------------------- 人点回第一个 tab,画面换回去
        #
        # 上面那一下换页是**浏览器决定的**(人点了链接);这一下是**我们决定的**
        # (人点了 tab 条)。两条路都得走到 —— 而且走完之后那六样都得对上。
        was = who.paint()["sig"]
        who.pick_tab(0)

        after = who.wait_tabs(2)
        assert [t["active"] for t in after] == [True, False], after
        # **要整条地址,不能只找几个字母。** 原来写的是 `"news" in address_bar`
        # —— 而没切过去时地址栏上那条里正好也有 `news`,于是这条断言在真出
        # 问题的时候照样是绿的。**一条会在坏的时候通过的断言,比没有还糟。**
        assert who.address_bar == cli.site, f"地址栏该跟着换:{who.address_bar!r}"
        assert cli.api("tabs", "-t", "nt")["active"] == home["id"]
        # **画面真的换回去了** —— 光是"标记成 active"证明不了什么
        who.wait_fresh(was)

        # 不带下标的命令跟着回来了吗 —— 那是 session 里那个指针,
        # 和上面那个字段**不是一回事**
        assert cli.out("url", "-t", "nt").strip() == cli.site, \
            f"不带下标的 url 没跟着切回来:{cli.out('url', '-t', 'nt')!r}"
        assert agree(cli, who, "nt", "人点回第一个 tab 之后")["url"] == cli.site

        # ------------------------------------------ 人点 ＋ 开个空白页
        who.new_tab()
        three = who.wait_tabs(3)
        assert three[-1]["active"], three
        assert len(cli.api("tabs", "-t", "nt")["tabs"]) == 3
        # 高亮落在新那个上 —— 浏览器把它开在前台了。
        assert selected(who) == 2, f"点了 ＋ 该停在新那个上:{who.tabs()}"

        # -------------------------------- 人在地址栏敲个地址,回车就走
        #
        # **这是人最熟的那一下**,而且它走的是观看页自己的地址栏,
        # 不是我们的 CLI。
        who.go(cli.site + "about")
        here = next(t["url"] for t in cli.api("tabs", "-t", "nt")["tabs"] if t["active"])
        assert here.endswith("/about"), f"地址栏敲的那一下没到里面:{here}"
        # **走完之后地址栏上留的还得是这一条。** 敲进去和显示出来是两件事 ——
        # 里面跳转了而地址栏停在人敲的那一刻,人就分不清"到底走没走"。
        assert who.address_bar.endswith("/about"), \
            f"走完之后地址栏该是这一条:{who.address_bar!r}"
        agree(cli, who, "nt", "人在地址栏敲完之后")

        # ------------------------------------------- 人点 × 关掉中间那个
        who.close_tab(1)
        left = who.wait_tabs(2)
        # 用地址判,不用标题 —— 这一站所有页的主机名是同一个
        assert not any(t["url"].endswith("/news") for t in left), left
        assert len(cli.api("tabs", "-t", "nt")["tabs"]) == 2
        # **关掉一个之后高亮得有个着落。** 关的是没高亮的那个,
        # 高亮不该跟着跑;下标却整体前移了 —— 这一下最容易错位。
        agree(cli, who, "nt", "人关掉中间那个之后")

        assert who.errors == [], f"摆弄 tab 的时候报了错:{who.errors}"

    # 一开一关都进了那条流,**而且分得清是谁开的**
    tab_log = [e for e in cli.api("log", "-t", "nt", "--kind", "tab")["entries"]]
    assert [e["event"] for e in tab_log].count("opened") == 3, tab_log
    assert any(e.get("reason") == "page" for e in tab_log), "页面自己开的那个该标出来"
    assert any(e["event"] == "closed" for e in tab_log)


def test_the_picture_follows_what_the_browser_decided_on_vnc(cli):
    """**同一个链接,三种点法 —— 前台开还是后台开,浏览器判,画面跟。**

    这一条是整条规则的落点,而且**只能在 VNC 上跑**:那条腿的画面是那个
    真窗口,浏览器切走画面就跟着走,所以"人到底看到哪一页"在这儿是可断言的。
    JPG 那条腿抓不到 —— 后台 tab 不产帧,画面**冻在上一帧**,
    于是"画面上是哪一页"照样答"旧那页"。(试过,确实抓不到。)

    三种点法的分别是实打实的,直连 Chromium 量过:

    | 怎么点 | Chromium |
    | --- | --- |
    | 普通左键 | **前台开** |
    | Ctrl + 左键 | **后台开** |
    | 中键 | **后台开** |

    而我们那条输入腿本来就把 `modifiers` 和 `button` 原样转给了 CDP。
    所以**人的意图靠手势表达,Chromium 解释它,我们只负责跟上** ——
    这比我们自己定"跟不跟"强:我们那套分不出 Ctrl+左键。
    """
    v2kit.need_vnc()
    cli.run("new", "--id", "nv", "--transport", "vnc")
    cli.run("goto", "-t", "nv", cli.site)
    cli.run("wait", "-t", "nv", "--css", "input", "--timeout", "30")

    with v2kit.human(cli.out("attach", "-t", "nv", "--print-only").strip()) as who:
        who.wait_connected()
        who.wait_painted()
        who._until(lambda: who.showing() == "/", "一开始画面上是首页",
                   show=who.showing)

        link = cli.one("nv", "-i", role="link", name=MENU)

        # ---------------------------------------- ① 普通左键:前台开
        who.click(link)
        who.wait_tabs(2, settled=True)
        who._until(lambda: who.showing() == "/news",
                   "普通左键是前台开,画面该跟过去", show=who.showing)
        # **六样一起看** —— 光看画面不够,光看 bar 也不够
        assert who.address_bar.endswith("/news"), who.address_bar
        assert selected(who) == 1, who.tabs()
        assert cli.out("url", "-t", "nv").strip().endswith("/news")

        # 切回首页,好让下一种点法从同一个起点出发
        who.pick_tab(0)
        who._until(lambda: who.showing() == "/", "切回首页", show=who.showing)

        # ------------------------------------ ② Ctrl + 左键:后台开
        #
        # **这一条是这条规则存在的理由。** 我们自己判"人点了就跟过去"的话,
        # 这一下会判错 —— 而 Chromium 判对了。
        who.click(link, ctrl=True)
        who.wait_tabs(3, settled=True)
        who._until(lambda: who.showing() == "/",
                   "Ctrl+左键是后台开,画面不该动", show=who.showing)
        assert who.address_bar == cli.site, who.address_bar
        assert selected(who) == 0, who.tabs()
        assert cli.out("url", "-t", "nv").strip() == cli.site

        # --------------------------------------------- ③ 中键:后台开
        who.click(link, button="middle")
        who.wait_tabs(4, settled=True)
        who._until(lambda: who.showing() == "/",
                   "中键也是后台开,画面不该动", show=who.showing)
        assert selected(who) == 0, who.tabs()

        assert who.errors == [], who.errors
