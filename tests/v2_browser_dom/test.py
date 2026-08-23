"""v2 · DOM 那条腿:传的是网页本身,不是像素。

另外两条腿传的是**一张图**,判据是"上面有没有东西、多大"。
这一条传的是**一棵 DOM**,rrweb 在观看端重建出来 ——
`#screen3` 是个 `<div>`,画不进 canvas,**判据必须换一套**
([works/test.md §5.9](../../docs/v2/works/test.md) 里挂了很久的那个 🔲)。

判四件事,而且**缺一件都会漏掉一整类错**:

1. **那棵树长出来了** —— 节点数、标题。
2. **样式和图也到了** —— 这一条是被一个真 bug 逼出来的:资源改写成了
   根路径 `/api/res`,而路由在 `/s/{sid}/api/res` 下,于是**每一个资源都 404**
   (实测 25 个请求 0 成功)。重放出来的是一棵**没有样式的**真 DOM:
   节点数、文字、标题**全都对** —— 只有样式表数和图片数是 0。
   **只按"有没有内容"判的话,这个 bug 一辈子发现不了。**
3. **只读是结构性的** —— 重放那棵树整个 `pointer-events: none`,
   不是靠"我们不给它绑事件"。
4. **人的输入照样到得了里面** —— 事件落在外面那个容器上,走 `/channel/cdp`
   翻译成 `Input.*`;和另外两条腿一个字不差。

要网络。
"""

import pytest

from tests import v2kit

pytestmark = pytest.mark.slow

SITE = "https://www.baidu.com/"
WORD = "web"


@pytest.fixture
def cli(tmp_path):
    v2kit.need_network(SITE)
    with v2kit.server(tmp_path) as c:
        yield c


def replay(who) -> dict:
    """重放那棵树现在什么样。"""
    return who.paint()


def test_a_human_watches_a_page_replayed_as_dom(cli):
    cli.run("new", "--id", "demo", "--transport", "dom")
    cli.run("goto", "-t", "demo", SITE)
    cli.run("wait", "-t", "demo", "--css", "input", "--timeout", "30")

    with v2kit.human(cli.out("attach", "-t", "demo", "--print-only").strip()) as who:
        who.wait_connected()
        # 判据是"那棵树长出来了",不是颜色 —— 见 kit 里 `wait_painted`
        got = who.wait_painted()

        assert got["kind"] == "dom", f"当值的该是 DOM 那条:{got}"
        assert got["nodes"] > 200, f"重放出来的树太小,不像一张真页:{got}"
        assert "百度" in got["title"], f"重放的是别的页?{got}"

        # ---------------------------------------- 样式和图也得到位
        #
        # **这一条抓的是"看起来对、其实全丢"那一类。**
        # 资源要经过 `/s/{sid}/api/res` 转发;地址拼错的时候
        # 上面那三条断言**全是绿的**,而人看到的是一张没有样式的白页。
        assert got["sheets"] > 0, f"一张样式表都没有 —— 资源没转过来:{got}"
        assert got["images"] > 0, f"一张图都没有 —— 资源没转过来:{got}"

        # ------------------------------- 只读是结构性的,不是靠自觉
        # **两道,挡的是两件事。**
        # `pointer-events: none` 挡鼠标;`inert` 挡**焦点** ——
        # 少了后面那道,rrweb 一放出录下来的 focus 事件就把键盘焦点
        # 整个夺进那个 iframe,人再敲什么都到不了里面,而且一条错都不报。
        blocked = who.page.evaluate("""() => {
          const ifr = document.querySelector('#paintbox iframe');
          const wrap = document.querySelector('#paintbox .replayer-wrapper');
          return {ifr: getComputedStyle(ifr).pointerEvents,
                  wrap: wrap ? getComputedStyle(wrap).pointerEvents : '(没有)',
                  inert: !!ifr.contentDocument?.documentElement?.inert};
        }""")
        assert blocked["ifr"] == "none" and blocked["wrap"] == "none", \
            f"重放那棵树该是点不到的:{blocked}"
        assert blocked["inert"], f"重放那棵树该是拿不走焦点的:{blocked}"

        # ------------------------------- 人点一下、敲几个字,里面要收到
        #
        # 坐标换算在 DOM 下走的是**重放 iframe 的位置 + 它里面那页的宽度**
        # (kit `_BOX_JS`)—— 那棵树被 `transform: scale()` 缩过,
        # 拿外面 `#screen3` 的 rect 算会整体偏掉。
        boxes = [e for e in cli.snap("demo", "-i") if e["role"] == "textbox"]
        assert boxes, "首页上一个输入框都没有?"
        box = min(boxes, key=lambda e: e["bbox"][1])      # 顶上那个,规则写明
        who.click(box)
        # **焦点得留在观看端那个隐藏 textarea 上**,不能被重放的 iframe 夺走
        assert who.page.evaluate("() => document.activeElement.id") == "ime", \
            "点完之后键盘焦点不在 ime 上 —— 敲进去的字到不了里面"
        who.type(WORD)
        cli.until(lambda: cli.out("get", "value", "-t", "demo",
                                  "@" + box["ref"]).strip(),
                  WORD, what="人敲的字落进里面那个框")

        # ------------------------------- 里面变了,重放跟着变
        #
        # **这才是"在放",不是"放过一次"。** 上面那几条只证明第一张快照到了。
        cli.until(lambda: WORD in who.page.evaluate("""() => {
            const d = document.querySelector('#paintbox iframe').contentDocument;
            return [...d.querySelectorAll('input')].map(i => i.value).join('|');
        }"""), True, what="人敲的字出现在重放里")

        # **指名放行一条,别的一条都不许有。**
        # 重放里那个 `<video>` 放不了:转发那条路不认 `Range`,媒体元素
        # 要边下边播 —— 记在 [issues](../../docs/v2/issues/DOM-重放里的视频放不了.md)。
        # 写成"允许有错"就等于把这一类全放过去了,所以是**指名**。
        rest = [e for e in who.errors if "no supported source" not in e]
        assert rest == [], f"DOM 重放的时候报了别的错:{rest}"
