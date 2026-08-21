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


def test_no_session_at_all_is_3_not_a_crash(home, capsys):
    assert run("tabs") == 3
    assert "没有在跑的 session" in capsys.readouterr().err


# -------------------------------------------------------------- 登记簿

def test_registry_probes_liveness_instead_of_trusting_the_file(home):
    """**文件只是线索,`alive()` 才是真相**(works/05 §6)。"""
    reg = Registry(name="default")
    from webmuxd.models import SessionInfo
    reg.put(SessionInfo("process", "ghost", 9, {"pids": {"sessiond": 999999}}))

    rows = reg.list()
    assert rows[0]["id"] == "ghost"
    assert rows[0]["state"] == "dead", "文件里有就当它活着 —— 那就成了骗人"


def test_ls_shows_dead_ones_with_how_to_clean_them(home, capsys):
    from webmuxd.models import SessionInfo
    Registry(name="default").put(SessionInfo("process", "stale", 9,
                                        {"pids": {"sessiond": 999999}}))
    assert run("ls") == 0
    out = capsys.readouterr().out
    assert "stale" in out and "dead" in out
    assert "webmuxd kill" in out, "看得到死的,却不告诉人怎么清 —— 说了等于没说"


def test_ls_json_is_the_raw_shape(home, capsys):
    from webmuxd.models import SessionInfo
    Registry(name="default").put(SessionInfo("process", "x", 1234, {}))
    assert run("--json", "ls") == 0
    d = json.loads(capsys.readouterr().out)
    assert d["sessions"][0]["port"] == 1234


def test_info_reports_probed_runtimes(home, capsys):
    assert run("info") == 0
    out = capsys.readouterr().out
    assert "runtime" in out and "process" in out


def test_kill_a_missing_session_is_3(home):
    assert run("kill", "-t", "没有这个") == 3


# ------------------------------------------------------- 起不来要说清楚

def test_没有浏览器时退出码_7_而且提示指向_install(home, capsys, monkeypatch):
    """**不静默降级** —— 随便挑一个浏览器等于让你以为在跑钉死的那一版。"""
    monkeypatch.setenv("WEBMUXD_BROWSER", "/根本没有这个/chrome")
    code = run("new", "-s", "w", "-p", str(_free()))
    err = capsys.readouterr().err
    assert code == 7
    assert "runtime_unavailable" in err and "install" in err


def test_remote_without_cdp_exits_7(home, capsys):
    assert run("new", "-s", "r", "-p", str(_free()), "--runtime", "remote") == 7
    assert "cdp" in capsys.readouterr().err


# ------------------------------------------------------------ 真跑一遍

@pytest.fixture
def session(home):
    if not ProcessRuntime().available()[0]:
        pytest.skip("本机没有 chromium")
    port = _free()
    assert run("new", "-s", "work", "-p", str(port), "--runtime", "process") == 0
    yield port
    run("kill", "-t", "work")


@pytest.mark.slow
def test_new_is_idempotent(session, capsys):
    """同一个 id 再建一次是接管,不报错(像 `tmux new -A -s`)。"""
    assert run("new", "-s", "work", "-p", str(session), "--runtime", "process") == 0
    assert "已经在跑" in capsys.readouterr().out


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


# ------------------------------------------------- 升级之后表里还有旧行

def test_登记表里的旧行不该把命令带崩(home, capsys):
    """**0.5.1 真的崩过。**

    v1 的行是 `api_port` / `view_port`,v2 只有 `port`。升级之后表里还留着旧行,
    而代码里是 `row["port"]` —— 第一条命令就 KeyError,报错还完全不指方向。

    规矩和环境记录那条一样:**格式对不上就当没有**。差别是这儿要说出来 ——
    那些 session 可能还真在跑,人得知道去自己清。
    """
    reg = Registry(name="default")
    reg.file.write_text(json.dumps({
        "work": {"id": "work", "runtime": "container",
                 "api_port": 7900, "view_port": 6901, "detail": {}},
        "ok": {"id": "ok", "runtime": "process", "port": 7777, "detail": {}},
    }, ensure_ascii=False))

    rows = reg.list()                       # 不该抛
    assert [r["id"] for r in rows] == ["ok"], "旧行该被滤掉,好行该留着"

    err = capsys.readouterr().err
    assert "读不懂" in err and "work" in err, "扔掉了却不说,人不知道去清什么"
    assert str(reg.file) in err, "得告诉人表在哪"


def test_ls_遇到旧行照常列出好的那些(home, capsys):
    reg = Registry(name="default")
    reg.file.write_text(json.dumps({
        "老的": {"id": "老的", "runtime": "container", "api_port": 1, "detail": {}},
    }, ensure_ascii=False))
    assert run("ls") == 0
    out = capsys.readouterr().out
    assert "没有 session" in out, "全是旧行的话,等于一个都没有"
