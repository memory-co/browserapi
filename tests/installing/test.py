"""`webmuxd install` 和环境记录 —— 对着 docs/v2/works/07-runtime.md §4.4 校。

v1 的 install 问两个问题(docker 能用吗、拉得到镜像吗)。**v2 换了另外两个**:
这个网络环境下得到那个浏览器吗、系统依赖齐吗。docker 那一问整个消失。

**记录的规矩一条没改**,所以这个文件里大半的用例是原样留下来的 ——
它们测的是"记录怎么用",而不是"记录里装的是什么"。
"""

import io
import json

import pytest

from webmuxd import browser, env
from webmuxd.cli.install import install
from webmuxd.errors import RuntimeUnavailable
from webmuxd.runtime.process import ProcessRuntime, resolve_browser


@pytest.fixture
def record_file(tmp_path, monkeypatch):
    p = tmp_path / ".webmuxd.json"
    monkeypatch.setenv("WEBMUXD_ENV_FILE", str(p))
    return p


@pytest.fixture
def fake_download(tmp_path, monkeypatch):
    """把真的下载换掉。**下载本身不在这测** —— 那要网络,而且它是 urllib 的事。"""
    exe = tmp_path / "chrome-fake" / "chrome"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    state = {"path": str(exe), "fail": False, "calls": 0}

    def fake_install(version=browser.PINNED, **kw):
        state["calls"] += 1
        if state["fail"]:
            raise RuntimeError("到不了下载源")
        return state["path"]

    monkeypatch.setattr("webmuxd.browser.install", fake_install)
    monkeypatch.setattr("webmuxd.browser.find", lambda v=browser.PINNED: None)
    monkeypatch.setattr("webmuxd.browser.find_system", lambda: None)
    monkeypatch.setattr("webmuxd.browser.missing_libs", lambda p: [])
    monkeypatch.setattr("webmuxd.browser.has_cjk_font", lambda: True)
    return state


# ------------------------------------------------------------------ 记录

def test_没有记录不是错误(record_file):
    """**没装过也能用** —— install 省的是重复开销,不是"必须先装"。"""
    assert env.load() is None


def test_未来版本的记录当没有(record_file):
    record_file.write_text(json.dumps({"version": 999, "default_browser": {}}))
    assert env.load() is None, "格式变了就重新探,而不是猜字段"


def test_垃圾文件当没有而不是崩掉(record_file):
    record_file.write_text("{ 这不是 json")
    assert env.load() is None


def test_写完读得回来(record_file):
    env.save({"default_browser": {"path": "/x/chrome", "version": "1.2.3.4"}})
    rec = env.load()
    assert rec["default_browser"]["path"] == "/x/chrome"
    assert rec["version"] == env.FORMAT_VERSION and "at" in rec


def test_值是_None_的键直接不写(record_file):
    env.save({"default_browser": None})
    assert "default_browser" not in env.load()


# ---------------------------------------------------------------- install

def test_install_记下浏览器(record_file, fake_download):
    out = io.StringIO()
    rec = install(out=out, force=True)
    assert rec["default_browser"]["path"] == fake_download["path"]
    assert rec["default_browser"]["version"] == browser.PINNED
    assert env.load()["default_browser"]["source"] == "chrome-for-testing"
    assert "docker" not in env.load(), "v2 不再关心机器上有没有 docker"


def test_install_是幂等的(record_file, fake_download, monkeypatch):
    """"检查"和"安装"是同一个命令 —— 已经在了就跳过,不重下。"""
    monkeypatch.setattr("webmuxd.browser.find",
                        lambda v=browser.PINNED: fake_download["path"])
    out = io.StringIO()
    install(out=out)
    install(out=out)
    assert fake_download["calls"] == 0, "已经下过还去下 —— 那不叫幂等"


def test_下不到就不写那个键_并且给出退路(record_file, fake_download):
    """**不记一个下不到的路径。** 键不在,就是"你得自己填"。"""
    fake_download["fail"] = True
    out = io.StringIO()
    rec = install(out=out)
    assert "default_browser" not in rec
    assert "default_browser" not in (env.load() or {})
    text = out.getvalue()
    assert browser.CN_MIRROR in text, "到不了源时该把国内那个源说出来"


def test_缺中文字体是一条警告不是沉默(record_file, fake_download, monkeypatch):
    """**裸服务器渲染中文全是豆腐块** —— 撞上的人一定会以为是 bug。"""
    monkeypatch.setattr("webmuxd.browser.has_cjk_font", lambda: False)
    out = io.StringIO()
    install(out=out, force=True)
    assert "fonts-noto-cjk" in out.getvalue()


def test_缺共享库要明说而不是等它起不来(record_file, fake_download, monkeypatch):
    monkeypatch.setattr("webmuxd.browser.missing_libs",
                        lambda p: ["libnss3.so", "libgbm.so.1"])
    out = io.StringIO()
    install(out=out, force=True)
    assert "libnss3.so" in out.getvalue() and "apt-get" in out.getvalue()


# ------------------------------------------------------------ 记录怎么被用

def test_记录里的浏览器会被用上(record_file, tmp_path):
    exe = tmp_path / "recorded-chrome"
    exe.write_text("#!/bin/sh\n")
    env.save({"default_browser": {"path": str(exe), "version": "1.2.3.4"}})
    assert resolve_browser() == str(exe)


def test_传进来的赢过记录(record_file, tmp_path):
    """**它不是配置文件。** 记的是机器的事实,你想用哪个永远是参数说了算。"""
    a, b = tmp_path / "a", tmp_path / "b"
    for p in (a, b):
        p.write_text("#!/bin/sh\n")
    env.save({"default_browser": {"path": str(a), "version": "1"}})
    assert resolve_browser(str(b)) == str(b)


def test_记录过期了要说去重跑_install(record_file, monkeypatch):
    """**记录会撒谎** —— 你删了缓存目录它不知道。"""
    monkeypatch.setenv("WEBMUXD_BROWSER", "/已经不在了/chrome")
    with pytest.raises(RuntimeUnavailable) as ei:
        ProcessRuntime().start("x", port=1)
    assert "install" in ei.value.hint


def test_那句提示里点名了命令():
    assert "webmuxd install" in env.stale_hint("chromium 在 /x")
