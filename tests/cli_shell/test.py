"""CLI —— 对着 docs/v1/cli/ 校。

重点在**退出码**(那是给脚本的契约)和**目标解析**(那是 CLI 唯一多出来的东西)。
真起 session 的用例标了 slow。
"""

import json
import os
import socket
import time

import pytest

from webmuxd.cli import main
from webmuxd.cli import Registry
from webmuxd.sessions import ProcessRuntime


def _free() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def home(tmp_path, monkeypatch):
    """每个用例一套独立的登记簿。"""
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("WEBMUXD_TARGET", raising=False)
    return tmp_path


def run(*argv: str) -> int:
    return main(list(argv))


# ------------------------------------------------------------------ 退出码

def test_exit_codes_are_the_documented_contract():
    """给脚本用的契约,**不要靠解析输出**(cli/README §6)。"""
    from webmuxd.cli import EXIT
    assert EXIT["not_found"] == 4 and EXIT["not_clickable"] == 4
    assert EXIT["timeout"] == 5
    assert EXIT["busy"] == 6 and EXIT["busy_human"] == 6
    assert EXIT["chrome_gone"] == 7
    assert EXIT["bad_request"] == 2 and EXIT["blocked_url"] == 2
    assert EXIT["session_not_found"] == 3 and EXIT["tab_gone"] == 3


def test_no_command_prints_help_and_exits_2(capsys):
    assert run() == 2
    assert "webmuxd" in capsys.readouterr().out


def test_has_returns_3_when_missing(home):
    """`webmuxd has -t work || webmuxd new -s work` —— 就靠这个退出码。"""
    assert run("has", "-t", "work") == 3


def test_talking_to_a_missing_session_is_3(home, capsys):
    assert run("status", "-t", "根本没有") == 3
    assert "session_not_found" in capsys.readouterr().err


def test_没有_server_时说的是去_start(home, capsys):
    """**server 不按需自启** —— 那条规矩是"端口由你给"(h §6),
    所以这儿只能说该跑哪一行,不能替人挑一个口。"""
    assert run("tabs") == 3
    err = capsys.readouterr().err
    assert "没有在跑的 server" in err and "webmuxd start" in err


# -------------------------------------------------------------- 登记簿

def test_登记的只剩_server_在哪(home):
    """以前这儿是一张 session 表,`ls` 要读表再逐个探活 ——
    **那个文件在冒充 server**。现在有真的了(k)。"""
    reg = Registry(name="default")
    reg.put(port=7999, bind="127.0.0.1", pid=999999)
    assert reg.read()["port"] == 7999


def test_文件会撒谎_探不到就当没有(home):
    """进程被 OOM 杀了它不知道 —— **按记录去连,连不上就当没有**。"""
    reg = Registry(name="default")
    reg.put(port=_free(), bind="127.0.0.1", pid=999999)   # 那个口上什么都没有
    assert reg.read() is not None, "记录还在"
    assert reg.base() is None, "但探不到 —— 就不该说它在"


def test_没有_server_时_ls_不崩(home, capsys):
    assert run("ls") == 0
    assert "webmuxd start" in capsys.readouterr().out


def test_info_reports_probed_runtimes(home, capsys):
    assert run("info") == 0
    out = capsys.readouterr().out
    assert "runtime" in out and "process" in out


def test_kill_a_missing_session_is_3(home):
    assert run("kill", "-t", "没有这个") == 3


# ------------------------------------------------------- 起不来要说清楚

def test_没有浏览器时退出码_7_而且提示指向_install(home, capsys, monkeypatch):
    """**不静默降级** —— 随便挑一个浏览器等于让你以为在跑钉死的那一版。

    这条现在跨 HTTP:浏览器是**在 server 进程里**起的,所以环境变量要在
    `start` 之前设好 —— 这本身就是新模型的一条事实,值得钉住。
    错误在 server 里抛,`code` 和 `hint` 都要原样传回来。
    """
    monkeypatch.setenv("WEBMUXD_BROWSER", "/根本没有这个/chrome")
    assert run("start", "--port", str(_free())) == 0
    capsys.readouterr()
    try:
        code = run("new", "-s", "w")
        err = capsys.readouterr().err
    finally:
        run("kill-server")
    assert code == 7
    assert "runtime_unavailable" in err and "install" in err


def test_remote_without_cdp_exits_7(server, capsys):
    assert run("new", "-s", "r", "--runtime", "remote") == 7
    assert "cdp" in capsys.readouterr().err


def test_端口被占了要说清是哪一种(home, capsys):
    """**"被占"和"没权限"指向不同的下一步**,不能糊成一句 ——
    报"被占了"会让人去查一个根本不存在的进程。"""
    from webmuxd.cli import EXIT
    assert run("start", "--port", "1") == EXIT["port_in_use"]
    assert "root" in capsys.readouterr().err


# ------------------------------------------------------------ 真跑一遍

@pytest.fixture
def server(home):
    """一个真 server。**每个用例一套** —— 端口和登记簿都是独立的。"""
    port = _free()
    assert run("start", "--port", str(port)) == 0
    yield port
    run("kill-server")


@pytest.fixture
def session(server):
    if not ProcessRuntime().available()[0]:
        pytest.skip("本机没有 chromium")
    assert run("new", "-s", "work", "--runtime", "process") == 0
    yield server
    run("kill", "-t", "work")


@pytest.mark.slow
def test_new_is_idempotent(session, capsys):
    """同一个 id 再建一次是接管,不报错(像 `tmux new -A -s`)。"""
    assert run("new", "-s", "work", "--runtime", "process") == 0
    out = capsys.readouterr().out
    assert "/s/work/" in out, "第二次要把同一个给你(像 tmux new -A -s)"


@pytest.mark.slow
def test_has_and_ls_see_it(session, capsys):
    assert run("has", "-t", "work") == 0
    assert run("ls") == 0
    assert "work" in capsys.readouterr().out


@pytest.mark.slow
def test_the_whole_loop(session, capsys, tmp_path):
    """开 tab → 点 → 看日志,一条命令一条命令来 —— 跟人真用一样。"""
    html = tmp_path / "p.html"
    html.write_text("<!doctype html><meta charset=utf-8><title>结算</title>"
                    "<button onclick=\"document.title='点过了'\">提交订单</button>")
    url = f"file://{html}"

    assert run("new-tab", "-t", "work", "-u", url) == 0
    capsys.readouterr()

    assert run("tabs", "-t", "work") == 0
    assert "结算" in capsys.readouterr().out

    assert run("--note", "冒烟", "--user", "claudecode",
               "click", "-t", "work", "提交订单") == 0
    out = capsys.readouterr().out
    assert "✓ click" in out and "提交订单" in out

    assert run("log", "-t", "work", "--kind", "action") == 0
    log = capsys.readouterr().out
    assert "💭 claudecode:冒烟" in log, "note 和署名没进日志"
    assert "click" in log


@pytest.mark.slow
def test_a_miss_exits_4_and_lists_candidates(session, capsys, tmp_path):
    html = tmp_path / "q.html"
    html.write_text("<!doctype html><meta charset=utf-8>"
                    "<button>提交订单</button><button>提交并支付</button>")
    run("new-tab", "-t", "work", "-u", f"file://{html}")
    capsys.readouterr()

    code = run("click", "-t", "work", "提交")     # 两个都含"提交" → 多义
    err = capsys.readouterr().err
    assert code == 4, "定位失败该是 4"
    assert "提交订单" in err and "提交并支付" in err, "候选没列出来"


@pytest.mark.slow
def test_target_can_pick_a_tab_by_title(session, capsys, tmp_path):
    """`-t work:购物车` 按标题匹配 —— **CLI 唯一多出来的东西之一**,
    而且全在客户端做(cli/README §2)。"""
    html = tmp_path / "t.html"
    html.write_text("<!doctype html><meta charset=utf-8><title>购物车</title>x")
    run("new-tab", "-t", "work", "-u", f"file://{html}")
    capsys.readouterr()

    assert run("url", "-t", "work:购物车") == 0
    assert "t.html" in capsys.readouterr().out


@pytest.mark.slow
def test_send_is_the_escape_hatch(session, capsys, tmp_path):
    html = tmp_path / "s.html"
    html.write_text("<!doctype html><meta charset=utf-8>"
                    "<select id=c><option value=a>甲<option value=b>乙</select>")
    run("new-tab", "-t", "work", "-u", f"file://{html}")
    capsys.readouterr()

    code = run("send", "-t", "work",
               json.dumps([{"type": "select", "role": "combobox", "value": "b"}]))
    assert code == 0, capsys.readouterr().err


# ------------------------------------------------- 升级之后留下的旧文件

def test_上一版的_sessions_json_不该把命令带崩(home, capsys):
    """**0.5.1 真的崩过一次**,起因是登记表里留着上一版的行。

    这一版换了文件名(`sessions.json` → `server.json`),所以旧文件我们
    **根本不看**。但那个文件还躺在目录里 —— 它的存在不该影响任何一条命令。

    规矩不变:**格式对不上就当没有**。
    """
    reg = Registry(name="default")
    (reg.dir / "sessions.json").write_text(json.dumps({
        "work": {"id": "work", "runtime": "container",
                 "api_port": 7900, "view_port": 6901, "detail": {}}}))
    assert reg.read() is None, "没有 server.json 就是没有"
    assert run("ls") == 0                   # 不该抛
    assert "webmuxd start" in capsys.readouterr().out


def test_server_json_读不懂就当没有(home):
    reg = Registry(name="default")
    for junk in ("{既不是 json", "[]", '{"port": "7900"}', ""):
        reg.file.write_text(junk)
        assert reg.read() is None, junk
