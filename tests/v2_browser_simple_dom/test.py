"""v2 · **中途切到 DOM**:走一遍普通人的路,到了页面上再换画面。

和 [v2_browser_dom](../v2_browser_dom/) 差的就一件事,而那一件是要害:

| | 起 session 就选 DOM | **人到了页面上再切** |
| --- | --- | --- |
| 记录器什么时候注进去 | 页面还没开始跑的时候 | 页面**早就加载完了** |

`Page.addScriptToEvaluateOnNewDocument` **只对之后的文档生效**。
中途切过去的时候当前这一页已经跑完了,记录器一个事件都发不出来 ——
[c §9.4](../../docs/v2/works/c-view.md#94-切到-dom-要先把记录器注进去) 讲的
就是这件事,代码里也留了一句 warning。

**这条测试就是来钉这一条的**:人点了 DOM 那个按钮,画面就得出来,
而不是"等你下次导航"。人不知道什么叫记录器,他只知道自己点了一下。

前半段照抄 `v2_browser_simple`:JPG 起、进百度、确认画面真的在,
**然后才切** —— 因为要复现的正是"页面已经在跑了"这个前提。
"""

import pytest

from tests import v2kit

pytestmark = pytest.mark.slow

SITE = "https://www.baidu.com/"


@pytest.fixture
def cli(tmp_path):
    v2kit.need_network(SITE)
    with v2kit.server(tmp_path) as c:
        yield c


def test_a_human_switches_to_dom_on_a_page_already_loaded(cli):
    # ---------------------------------------- 前半段:和 v2_browser_simple 一样
    cli.run("new", "--id", "demo", "--transport", "jpg")
    cli.run("goto", "-t", "demo", SITE)
    # **先等"加载完"这件事,再等那个元素。**
    # 只写第二句的话就是在赌网速:百度挺重,跑全量的时候 30 秒不够,
    # 于是偶发红在一个和本条测试无关的地方(v2_browser_new_tab 同样栽过)。
    cli.until(lambda: cli.api("tabs", "-t", "demo")["tabs"][0]["loading"],
              False, timeout=90, what="页面自己加载完")
    cli.run("wait", "-t", "demo", "--css", "input", "--timeout", "30")

    with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
        who.wait_connected()
        first = who.wait_painted()
        assert first["kind"] == "img", f"前半段该是 JPG 那条:{first}"

        # 这一页**已经加载完了** —— 这就是要复现的前提
        assert who.address_bar.startswith("https://www.baidu.com"), who.address_bar

        # ---------------------------------------- 人点了 DOM 那个按钮
        got = who.switch_to("DOM")

        # **判据和 v2_browser_dom 是同一套**(works/test.md §5.9):
        # 树、样式和图、只读、输入。一样都不能少 ——
        # 少了"样式和图"那条,资源全丢的时候上面那条照样绿。
        assert got["kind"] == "dom", f"点了 DOM,当值的还不是它:{got}"
        assert got["nodes"] > 200, f"重放出来的树太小,不像一张真页:{got}"
        assert "百度" in got["title"], f"重放的是别的页?{got}"
        assert got["sheets"] > 0, f"一张样式表都没有 —— 资源没转过来:{got}"
        assert got["images"] > 0, f"一张图都没有 —— 资源没转过来:{got}"

        # 只读那两道
        blocked = who.page.evaluate("""() => {
          const ifr = document.querySelector('#paintbox iframe');
          return {ifr: getComputedStyle(ifr).pointerEvents,
                  inert: !!ifr.contentDocument?.documentElement?.inert};
        }""")
        assert blocked["ifr"] == "none" and blocked["inert"], \
            f"重放那棵树该是点不到、也拿不走焦点的:{blocked}"

        rest = [e for e in who.errors if "no supported source" not in e]
        assert rest == [], f"切到 DOM 的时候报了错:{rest}"
