"""v2 · 画面上那两块浮层:左下角延迟 + 日志,右下角画质。

**为什么是浮层而不是状态栏**:后面要做全屏,那时所有控制层都得和主屏融合,
底下那条栏没地方待。所以现在就放对位置 —— 而且左右对称,像视频播放器。

顺带砍掉了一堆读数(fps / kbps / 帧尺寸 / 有效缩放)。它们是调试期的东西,
天天挂在界面上只是噪音;真要看,日志里都有。**只留延迟** ——
那是人唯一会看的那个数,"卡不卡"就靠它。
"""

import pytest

from tests import v2kit
from tests.site import site

pytestmark = pytest.mark.slow


@pytest.fixture
def cli(tmp_path):
    with site() as base, v2kit.server(tmp_path) as c:
        c.site = base
        yield c


def test_the_two_corners_and_the_log_button(cli):
    cli.run("new", "--id", "x", "--transport", "jpg")
    cli.run("goto", "-t", "x", cli.site)

    with v2kit.human(cli.out("attach", "-t", "x", "--print-only").strip()) as who:
        who.wait_connected()
        who.wait_painted()

        # ---------------------------------------------- 那条状态栏没了
        assert who.page.locator("#status").count() == 0, "底下那条状态栏该撤了"

        # ---------------------------------------------- 延迟:真量出来的
        #
        # **这个数以前是假的** —— 那一格从来没有人写过,永远是 `–`。
        # 现在是观看端每隔几秒发一条 ping、服务端原样把时间戳送回来,
        # 减的是同一个钟上的两个读数。
        assert "ms" in who.status, f"左下角该显示延迟:{who.status!r}"

        # ---------------------------------------------- 左右对称
        box = who.page.evaluate("""() => {
          const s = document.getElementById('stage').getBoundingClientRect();
          const h = document.getElementById('hud').getBoundingClientRect();
          const q = document.getElementById('quality').getBoundingClientRect();
          return {左: Math.round(h.left - s.left), 左下: Math.round(s.bottom - h.bottom),
                  右: Math.round(s.right - q.right), 右下: Math.round(s.bottom - q.bottom)};
        }""")
        assert box["左"] == box["右"] and box["左下"] == box["右下"], \
            f"两块该是对称的:{box}"

        # ---------------------------------------------- 日志按钮:点了就下载
        #
        # **拉的是服务端渲染好的那一份**,和 `webmuxd log` 同一份代码
        # (`webmuxd/logfmt.py`)—— 两处各写一遍的话,人拿到的两份
        # "同一个 session 的日志"会长得不一样。
        with who.page.expect_download(timeout=20000) as got:
            who.page.locator("#h-log").click()
        dl = got.value
        assert dl.suggested_filename.startswith("webmuxd-x-"), dl.suggested_filename

        text = open(dl.path(), encoding="utf-8").read()
        # 编号在最左边 —— 它和事件流共用一个计数器
        assert any(ln.strip().split(" ")[0].isdigit() for ln in text.splitlines()), \
            f"每条该带编号:{text[:200]!r}"
        # 时间到毫秒 —— 秒级分不出同一秒里那几件事的先后
        assert any("." in ln[6:20] for ln in text.splitlines()), \
            f"时间戳该到毫秒:{text[:200]!r}"
        # 这个 session 真做过的事得在里面
        assert "goto" in text, f"日志里没有那次 goto:{text[:300]!r}"

        assert who.errors == [], who.errors
