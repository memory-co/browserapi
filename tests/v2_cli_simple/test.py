"""v2 · 起服务 → 开 session → 打开百度 → 搜一个词 → 看到结果。

**这一条是样例**,见 [README](README.md)。规矩在 [v2kit](../v2kit.py) 的开头。

**从头到尾只有 CLI。** 画面、光标那些"人看到了什么"的东西不在这儿 ——
它们要一个真浏览器才验得了,在 [v2_browser_simple](../v2_browser_simple/)。
**一条测试只从一个口子进去**,混着来的那条既说不清自己在验什么,
坏了也不知道该往哪边查。

要网络,而且**要有头**(`--transport vnc`)—— 见下面那条注释:
百度给无头浏览器弹图形验证码。没网或没 xpra 就跳过,不假装通过。
"""

import pytest

from tests import v2kit

pytestmark = pytest.mark.slow

SITE = "https://www.baidu.com/"
WORD = "webmuxd"


@pytest.fixture
def cli(tmp_path):
    v2kit.need_network(SITE)
    v2kit.need_vnc()
    with v2kit.server(tmp_path) as c:
        yield c


def test_start_open_baidu_search_and_see_results(cli, tmp_path):
    # ---------------------------------------------------------------- 起
    #
    # **退出码是给脚本用的那一半。** `has` 什么都不打印,只回码 ——
    # `webmuxd has -t work || webmuxd new --id work` 就是靠这个。
    assert cli.sh("has", "-t", "demo").returncode == 3, "还没有 demo,该回 3"

    # **走 VNC(有头),不是 JPG(无头)。** 实测:同一次搜索,无头那条
    # 回车之后跳到 `wappass.baidu.com/.../tuxing_v2.html`(图形验证码),
    # 有头这条直接出结果。这不是我们的 bug,是站点在挡自动化 ——
    # 但它决定了这条测试只能走有头,顺带也就真的验了 VNC 那条腿。
    # (无头那条腿由 [v2_cli_new_tab](../v2_cli_new_tab/) 验。)
    cli.run("new", "--id", "demo", "--transport", "vnc")
    cli.run("has", "-t", "demo")

    sessions = cli.api("ls")["sessions"]
    assert [s["id"] for s in sessions] == ["demo"]
    assert sessions[0]["url"] == "/s/demo/", "session 住在那个口下面"

    # ------------------------------------------------------- 打开百度
    cli.run("goto", "-t", "demo", SITE)
    # **等那件事发生,不等一个秒数。** 睡固定时长是在赌网速 ——
    # 赌输了就是一条时灵时不灵的测试,而那比没有更坏。
    #
    # 等的是"有个输入框了",不是"文字里有『百度』" —— 后者试过,
    # 会偶发超时:那条路走 `body.innerText` 的行,而首页那几行
    # 什么时候渲染出来跟网速有关。**结构比文案先到。**
    cli.run("wait", "-t", "demo", "--css", "input", "--timeout", "30")

    body = cli.out("capture", "-t", "demo")
    assert "百度" in body, f"打开的不是百度?正文开头:{body[:200]!r}"

    shot = str(tmp_path / "p.webp")
    cli.run("capture", "-t", "demo", "--shot", shot)
    data = open(shot, "rb").read()
    assert data[:4] == b"RIFF", "截图不是 webp"
    assert len(data) > 5000, "截图太小,多半是白屏"

    # ------------------------------------------- 这一页上有什么(@e1)
    #
    # **这一段以前是一坨 JS。** `snapshot` 之前没有出口,找搜索框只能
    # `document.querySelectorAll('input,textarea')` 自己挑一个 ——
    # 那不是"逃生舱用得克制",那是一个缺的命令被 JS 顶掉了。
    boxes = [e for e in cli.snap("demo", "-i")
             if "type" in e["affords"] and e["in_viewport"]]
    assert boxes, "页面上找不到一个能输入的框:\n" + cli.out("snapshot", "-t", "demo", "-i")
    box = boxes[0]
    assert box["ref"], "snapshot 出来的每一样都该有号"

    # ------------------------------------------------------------ 输入
    #
    # **`@e1` 直接就能点** —— 不用坐标,也不用再说一遍它叫什么。
    ref = "@" + box["ref"]
    cli.run("click", "-t", "demo", ref)
    cli.run("--user", "agent", "--note", "搜一个词", "type", "-t", "demo", ref, WORD)

    # 框里有字了 —— **再 snapshot 一次,value 就在树里**,不用读 DOM。
    # 同一句话再问一遍(第一个能输入又看得见的),该找到同一个框。
    again = [e for e in cli.snap("demo", "-i")
             if "type" in e["affords"] and e["in_viewport"]]
    assert again, "重新 snapshot 之后一个能输入的框都没有"
    assert again[0]["value"] == WORD, f"框里应该是 {WORD!r},实际 {again[0]['value']!r}"
    # **号是新的。** 只增不重用 —— 拿旧号去点会报错,不会点到别的东西。
    assert again[0]["ref"] != box["ref"], "第二次 snapshot 该发新号"

    # ------------------------------------------------------------ 回车
    cli.run("--user", "agent", "key", "-t", "demo", "Enter")
    cli.run("wait", "-t", "demo", "--url-contains", WORD, "--timeout", "20")

    here = cli.out("url", "-t", "demo").strip()
    assert WORD in here, f"地址栏该带上搜索词,实际 {here}"

    # ------------------------------------------------------ 看到结果
    #
    # **有结果**。至于结果标题里有没有那个词,取决于百度的索引 ——
    # 那不是我们能测的东西,写进断言只会换来一条时灵时不灵的测试。
    links = [e for e in cli.snap("demo") if e["role"] == "link" and e["name"].strip()]
    assert len(links) >= 3, f"结果页上一条结果都没有:{[e['name'] for e in links]}"
    print(f"  搜到 {len(links)} 条,头一条:{links[0]['name']!r}")

    # ------------------------------------------------- 过期的号点不动
    #
    # **先真的换一页。** 原来这儿是搜完之后直接拿旧号点,以为搜索就算换页了 ——
    # 不是:百度那条搜索是**同文档跳转**,地址变了,而搜索框那个节点一直活着。
    # 拿旧号点它其实**是对的**,于是这条断言时灵时不灵,还两次把我引到别处。
    # **前提不成立的断言,比没有断言更费时间。**
    #
    # 「同文档跳转之后旧号该不该失效」是个**没定的语义问题**,不是 bug ——
    # 记在 [issues](../../docs/v2/issues/同文档跳转之后旧号还认.md),先不解决。
    cli.run("goto", "-t", "demo", "https://example.com/")
    cli.run("wait", "-t", "demo", "--css", "body", "--timeout", "20")

    stale = cli.sh("click", "-t", "demo", ref)
    assert stale.returncode == 4, (
        f"换了一页,旧号该回 4,实际 {stale.returncode} —— "
        f"点中了别的东西?{stale.stdout.strip()!r}")
    assert "上一个页面" in stale.stderr, f"要说清是页面换了:{stale.stderr!r}"
    assert "snapshot" in stale.stderr, f"报错要说清楚下一步:{stale.stderr!r}"

    # ------------------------------------------------------ 干过什么
    #
    # **人和 agent 进同一条流,每条标明是谁做的** —— 这是 agent-browser
    # 没有的那一半([i](../../docs/v2/works/i-agent-surface.md))。
    mine = [e for e in cli.api("log", "-t", "demo", "--user", "agent")["entries"]
            if e["kind"] == "action"]
    assert [e["action"] for e in mine] == ["type", "key"], mine
    assert mine[0]["note"] == "搜一个词"

    # -------------------------------------------------------------- 收
    cli.run("kill", "-t", "demo")
    assert cli.sh("has", "-t", "demo").returncode == 3, "关掉就该没了"
