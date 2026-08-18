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
from webmuxd.cli import deps as deps_mod
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
    # **测试绝不许动这台机器的系统包。**
    #
    # 0.7.0 起 `install` 探到缺了就装,而这台机器上 `sudo -n` 很可能是通的 ——
    # 那样跑一次测试就会真的 `apt-get install xpra xvfb …`。
    # 这儿把包管理器那条路整个封死:探测一律说"齐",真去装就直接把用例判失败。
    monkeypatch.setattr("webmuxd.xpra.available", lambda: (True, ""))
    monkeypatch.setattr("webmuxd.cli.install.xpra_mod.available", lambda: (True, ""))
    monkeypatch.setattr(
        "webmuxd.cli.deps.apply",
        lambda *a, **k: pytest.fail("测试去动系统包了 —— 这条路必须是封死的"))
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


def test_没_root_时缺中文字体是一条警告不是沉默(record_file, fake_download, monkeypatch):
    """**裸服务器渲染中文全是豆腐块** —— 撞上的人一定会以为是 bug。

    0.7.0 起有 root 就直接装了,所以"打印"这条要在**装不了**的前提下验。
    """
    monkeypatch.setattr("webmuxd.browser.has_cjk_font", lambda: False)
    monkeypatch.setattr("webmuxd.cli.deps.can_root", lambda: False)
    out = io.StringIO()
    install(out=out, force=True)
    assert "fonts-noto-cjk" in out.getvalue()


def test_没_root_时缺共享库要明说而不是等它起不来(record_file, fake_download, monkeypatch):
    monkeypatch.setattr("webmuxd.browser.missing_libs",
                        lambda p: ["libnss3.so", "libgbm.so.1"])
    monkeypatch.setattr("webmuxd.cli.deps.can_root", lambda: False)
    out = io.StringIO()
    install(out=out, force=True)
    text = out.getvalue()
    assert "libnss3.so" in text and "apt-get" in text


def test_有_root_就直接装_不是打印一行让你自己跑(record_file, fake_download,
                                                monkeypatch):
    """**探到缺了却不装,等于把活原样退回去。**

    这是 0.7.0 翻过来的一条:`--with-deps` 从开关变成默认行为。
    """
    monkeypatch.setattr("webmuxd.browser.has_cjk_font", lambda: False)
    monkeypatch.setattr("webmuxd.cli.deps.can_root", lambda: True)
    monkeypatch.setattr("webmuxd.cli.deps.detect", lambda: deps_mod.APT)
    called = []

    def fake_apply(fam, pkgs, **kw):
        called.append(pkgs)
        monkeypatch.setattr("webmuxd.browser.has_cjk_font", lambda: True)
        return True, ""

    monkeypatch.setattr("webmuxd.cli.deps.apply", fake_apply)
    out = io.StringIO()
    install(out=out, force=True)
    assert called and "fonts-noto-cjk" in called[0]
    assert "装好了" in out.getvalue()


def test_with_deps_还认_但会说它已经是默认了(record_file, fake_download):
    """旧参数不静默吞 —— 脚本里还写着它的人得知道发生了什么。"""
    out = io.StringIO()
    install(out=out, force=True, with_deps=True)
    assert "已经是默认行为" in out.getvalue()


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
        ProcessRuntime().start("x", port=1, transport="screencast")
    assert "install" in ei.value.hint


def test_那句提示里点名了命令():
    assert "webmuxd install" in env.stale_hint("chromium 在 /x")


# ------------------------------------------------------------------ 挑下载源

def test_候选源里只放真的托管_chrome_for_testing_的():
    """**看着相关不等于能用。**

    `mirrors.aliyun.com/google-chrome/` 是个真实存在的坑:它托管的是 Google
    Chrome 稳定版的 `.deb` / `.rpm` **系统包**,不是 Chrome for Testing 的 zip;
    而且只有 `current`,**没有版本可钉** —— 拿它当镜像等于把"每个 release 钉一个
    版本"那条作废掉([works/07 §4.1](../../docs/v2/works/07-runtime.md))。
    """
    bases = [b for _n, b in browser.MIRRORS]
    assert browser.DEFAULT_MIRROR in bases
    for b in bases:
        assert "chrome-for-testing" in b, f"{b} 不是 CfT 的源"
    assert not any("aliyun" in b for b in bases)


def test_探测按吞吐排序_探不通的排最后(monkeypatch):
    """探不通不是错误,是**那一格没有数** —— 排最后,别让它顶掉能用的。"""
    speeds = {"官方": None, "npmmirror": 900.0, "npmmirror cdn": 120.0}

    def fake_map(fn, items):
        return [(n, b, speeds[n]) for n, b in items]

    class Pool:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def map(self, fn, items): return fake_map(fn, items)

    monkeypatch.setattr("concurrent.futures.ThreadPoolExecutor",
                        lambda **kw: Pool())
    ranked = browser.probe_mirrors()
    assert [n for n, _b, _s in ranked] == ["npmmirror", "npmmirror cdn", "官方"]
    assert browser.fastest_mirror()[0] == "npmmirror"


def test_全都探不通就退回官方_不静默失败(monkeypatch):
    class Pool:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def map(self, fn, items): return [(n, b, None) for n, b in items]

    monkeypatch.setattr("concurrent.futures.ThreadPoolExecutor",
                        lambda **kw: Pool())
    name, base, kbps = browser.fastest_mirror()
    assert base == browser.DEFAULT_MIRROR and kbps is None


def test_显式指定源就不探_传进来的赢(record_file, fake_download, monkeypatch):
    """探测是"这台机器上哪个快"的事实;**你指定哪个是你的选择**。"""
    probed = []
    monkeypatch.setattr("webmuxd.browser.probe_mirrors",
                        lambda *a, **k: probed.append(1) or [])
    install(out=io.StringIO(), force=True, mirror="https://mine.example/cft")
    assert not probed, "显式给了源还去探"

    monkeypatch.setenv("WEBMUXD_BROWSER_MIRROR", "https://env.example/cft")
    install(out=io.StringIO(), force=True)
    assert not probed, "环境变量给了源还去探"


def test_下不到时把原因整句打出来_不截断(record_file, fake_download):
    """截在半句上的提示等于没有提示 —— 而原因决定了下一步该做什么。"""
    fake_download["fail"] = True
    out = io.StringIO()
    install(out=out, mirror="https://mine.example/cft")
    assert "到不了下载源" in out.getvalue(), out.getvalue()


# --------------------------------------------------- 装完了才算装完了

def test_解压到一半不算装好了(tmp_path, monkeypatch):
    """**"那个 exe 在"不等于"装完了"。**

    解压到一半被打断,`chrome` 可能已经落盘、也已经 chmod 过,而别的文件全缺。
    没有标记文件的话 `find()` 会说装好了,然后我们去跑一个残缺的浏览器
    ([works/10 §4.2](../../docs/v2/works/10-install.md))。
    """
    monkeypatch.setenv("WEBMUXD_BROWSERS_PATH", str(tmp_path))
    exe = browser.binary_path()
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)

    assert browser.find() is None, "只有一个 exe 就当装好了 —— 那是半个安装"

    browser.marker_path().write_text(browser.PINNED)
    assert browser.find() == str(exe), "标记在了就该认"


def test_标记是最后一步写的(tmp_path, monkeypatch):
    """顺序错了这条守卫就白设 —— 标记必须在**所有**文件都就位之后才落盘。"""
    import inspect
    src = inspect.getsource(browser.install)
    assert src.index("marker_path") > src.index("extractall"), \
        "标记写在解压之前 —— 那它就证明不了任何事"
    assert src.index("marker_path") > src.index("exe.chmod"), \
        "标记写在 chmod 之前"
