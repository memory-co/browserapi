"""runtime —— 对着 docs/v2/works/07-runtime.md 校。

v2 的契约只剩一条:**一个 CDP 端点**。所以这个场景短了很多 ——
v1 那 600 行里大半是在验"容器命令怎么拼、镜像标签怎么读",
而那整套机制存在的理由是**描述别人的镜像长什么样**,v2 没有别人的镜像了。

`process` 是真跑真起的:浏览器 + sessiond 起来,lib 连上去点一下,
而且**画面就在同一个口上**。
"""

import socket
import time

import pytest

from webmuxd import Webmuxd, browser, runtime as rt
from webmuxd.errors import PortInUse, RuntimeUnavailable
from webmuxd.runtime.base import Handle, port_free, require_ports
from webmuxd.runtime.process import ProcessRuntime, resolve_browser
from webmuxd.runtime.remote import RemoteRuntime


def _free() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ 选择

def test_只有两种_runtime_而且默认是本机起一个():
    # 三分法塌成两种,**容器不在里面**(works/07 §2)
    assert set(rt.detect()) == {"process", "remote"}
    assert rt.DEFAULT == "process"


def test_没有的_runtime_要说清有哪些_并且指出容器去哪了():
    with pytest.raises(RuntimeUnavailable) as ei:
        rt.get("container")
    assert "process" in ei.value.hint and "remote" in ei.value.hint
    # 从 v1 升上来的人第一件事就是敲 container,得告诉他去看哪一篇
    assert "07" in ei.value.hint


def test_detect_是现探不是猜():
    assert rt.detect()["process"] is ProcessRuntime().available()[0]
    assert rt.detect()["remote"] is True     # 端点是你给的,永远"能用"


# ------------------------------------------------------------- 浏览器从哪来

def test_指定的浏览器不在就报错_不静默换一个(tmp_path):
    """**不降级** —— 静默换一个等于让你以为在跑钉死的那一版(works/07 §4.1)。"""
    with pytest.raises(RuntimeUnavailable) as ei:
        resolve_browser(str(tmp_path / "没有这个文件"))
    assert "install" in ei.value.hint


def test_传进来的赢(monkeypatch, tmp_path):
    fake = tmp_path / "chrome"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("WEBMUXD_BROWSER", "/根本没有")
    # 显式参数在环境变量之前 —— 和 v1 的 `--image` 一样,**传进来的赢**
    assert resolve_browser(str(fake)) == str(fake)


def test_钉死的版本号是包里的一个常量():
    """`tests/chrome_facts/` 那句"换大版本先跑它"要能执行,前提是版本确定。"""
    assert browser.PINNED.count(".") == 3
    assert browser.download_url().endswith(".zip")
    assert browser.PINNED in browser.download_url()


def test_换源只换前缀(monkeypatch):
    monkeypatch.setenv("WEBMUXD_BROWSER_MIRROR", browser.CN_MIRROR)
    u = browser.download_url()
    assert u.startswith(browser.CN_MIRROR) and browser.PINNED in u


# -------------------------------------------------------------- 不降级

def test_remote_没给_cdp_就拒绝():
    with pytest.raises(RuntimeUnavailable) as ei:
        RemoteRuntime().start("x", port=_free())
    assert "cdp" in str(ei.value)


def test_remote_的_stop_不动对面():
    """**只停本地的 sessiond,对面一个字节都不动**(works/07 §6)。"""
    h = Handle("remote", "prod", 7900, {"cdp": "http://elsewhere:9222"})
    RemoteRuntime().stop(h)          # 不该抛
    assert h.detail["cdp"] == "http://elsewhere:9222"


# ---------------------------------------------------------------- 端口

def test_端口被占了就说被占了_不替你换一个():
    """**端口是部署决定的**(works/04 §5)。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        taken = s.getsockname()[1]
        assert not port_free(taken)
        with pytest.raises(PortInUse) as ei:
            require_ports(taken)
        assert ei.value.details["port"] == taken


def test_一个_session_一个口_画面和_api_都在它上面():
    """v1 的 Handle 有 api_port 和 view_port 两个;v2 只有一个(works/04 §1)。"""
    h = Handle("process", "work", 7900, {})
    assert h.api_url == "http://127.0.0.1:7900"
    assert h.view_url.startswith("http://127.0.0.1:7900/")
    # v1 里"没有画面"是空字符串 —— v2 画面是我们自己产的,只要活着就有
    assert h.view_url


# ---------------------------------------------------------- 真起真跑

def test_本机起一个_然后画面和_api_都在那个口上():
    """**这条是真起真跑**:浏览器 + sessiond 起来,lib 连上去点一下。"""
    if not ProcessRuntime().available()[0]:
        pytest.skip("本机没有浏览器")

    impl = ProcessRuntime()
    port = _free()
    h = impl.start("t-proc", port=port, transport="screencast")
    try:
        assert impl.alive(h) and h.kind == "process"
        assert h.port == port

        import urllib.request
        with urllib.request.urlopen(h.view_url, timeout=10) as r:
            page = r.read()
        # 画面页就在那个口的根上,而且是我们自己的那一份
        assert r.status == 200 and b"/channel/cdp" in page,\
                "内置页得从同一个口拿帧 —— 路径已改叫 /channel/cdp(e §6.1),"\
                "旧的 /api/view 仍然可用但内置页不再用它"

        web = Webmuxd()
        sess = web.session(id="t-proc", port=port, runtime="process",
                           transport="screencast")
        tab = sess.open("about:blank")
        assert tab.js("1+1") == 2
        assert sess.view_url.startswith(f"http://127.0.0.1:{port}")
        sess.detach()
    finally:
        impl.stop(h)
    time.sleep(0.5)
    assert not impl.alive(h), "stop 之后进程还活着"


@pytest.mark.slow
def test_session_拿不到就拉起来_而且第二次给同一个对象():
    if not ProcessRuntime().available()[0]:
        pytest.skip("本机没有浏览器")

    web = Webmuxd()
    port = _free()
    sess = web.session(id="t-auto", port=port, runtime="process",
                       transport="screencast")
    try:
        assert sess.status()["ok"] is True
        assert web.session(id="t-auto") is sess
    finally:
        web.shutdown()
    time.sleep(0.5)
    assert port_free(port), "shutdown 之后端口还占着 —— 进程没清干净"


def test_v1_的参数名不静默吞掉():
    """从 v1 升上来的人会带着旧名来,**落进 kw 被丢掉最糟**。"""
    web = Webmuxd()
    for old in ("api_port", "view_port", "image", "network"):
        with pytest.raises(Exception) as ei:
            web.session(id="x", **{old: 1})
        assert old in str(ei.value)


# ------------------------------------------------- 起不来的时候要说清为什么

def test_浏览器起不来时把它自己那句话带出来(tmp_path):
    """**别让人"手工跑一遍看报什么"** —— 那等于把排查工作原样退回去。

    0.5.2 之前 chrome 的 stderr 是 DEVNULL,而起不来的原因(root 没关沙箱、
    缺共享库、profile 写不了)全写在里面。
    """
    fake = tmp_path / "fakechrome"
    fake.write_text(
        "#!/bin/sh\n"
        "echo '[206402:206402:0818/205945.649553:ERROR:content/browser/zygote_host/"
        "zygote_host_impl_linux.cc:102] Running as root without --no-sandbox is not "
        "supported. See https://crbug.com/638180.' >&2\n"
        "exit 1\n")
    fake.chmod(0o755)

    with pytest.raises(RuntimeUnavailable) as ei:
        ProcessRuntime().start("x", port=_free(), browser_path=str(fake),
                               data_dir=str(tmp_path / "work"),
                               transport="screencast")
    msg = str(ei.value)
    assert "no-sandbox" in msg, f"浏览器自己那句话没带出来:{msg}"
    # 那一坨 [pid:pid:时间:ERROR:文件:行] 前缀对使用者没意义,会把真正的话挤出屏幕
    assert "zygote_host_impl_linux.cc" not in msg
    assert "chrome.log" in ei.value.details["hint"], "完整日志在哪也得说"


def test_root_下自动关沙箱_并且说出来(monkeypatch, tmp_path):
    """**root + 沙箱没有能跑的配置**(crbug 638180)—— 报错让人自己去查,
    等于把一个无解的选择丢回去。而我们自己推荐的隔离路子(webmuxd 装进容器)
    默认就是 root。所以自动加上,**但要说出来**。
    """
    import os as _os
    from webmuxd.runtime import process as proc_mod

    seen = {}

    class FakePopen:
        def __init__(self, args, **kw):
            seen["args"] = args
            self.pid = 1

        def poll(self): return None
        def send_signal(self, s): pass
        def wait(self, timeout=None): return 0
        def kill(self): pass

    monkeypatch.setattr(_os, "geteuid", lambda: 0)
    monkeypatch.setattr(proc_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(proc_mod, "wait_port", lambda *a, **k: False)
    monkeypatch.delenv("WEBMUXD_NO_SANDBOX", raising=False)

    with pytest.raises(RuntimeUnavailable):
        ProcessRuntime().start("x", port=_free(), browser_path="/bin/true",
                               data_dir=str(tmp_path), transport="screencast")
    assert "--no-sandbox" in seen["args"], "root 下不加的话根本起不来"


# ------------------------------------------------------------- 绑哪个地址

def test_默认只绑回环():
    """**默认不该是"谁能连上谁就能用这个浏览器"。**

    v1 的 sessiond 默认 `0.0.0.0`,那时候它跑在容器里 —— 那个 0.0.0.0 是
    **容器内的**,外面还有 `docker -p` 决定暴不暴露。v2 没有容器了,
    前提变了,默认值必须跟着变([works/07](../../docs/v2/works/07-runtime.md))。
    """
    import argparse
    import inspect

    from webmuxd.serve import __main__ as serve_main
    src = inspect.getsource(serve_main.main)
    assert '"--bind"' in src, "统一叫 --bind,不叫 --host"
    assert '"0.0.0.0"' not in src.split("--bind")[1].split("\n")[0], \
        "默认还是 0.0.0.0"

    # 老名字留作别名,不然 works/07 里那条命令会突然报 unrecognized
    p = argparse.ArgumentParser()
    p.add_argument("--bind", "--host", dest="bind", default="127.0.0.1")
    assert p.parse_args([]).bind == "127.0.0.1"
    assert p.parse_args(["--host", "0.0.0.0"]).bind == "0.0.0.0"


def test_绑非回环要留一条警告(tmp_path, monkeypatch):
    """对外开放是**你的决定**,但不能悄悄发生。"""
    from webmuxd.runtime import process as proc_mod

    class FakePopen:
        def __init__(self, args, **kw): self.pid = 1
        def poll(self): return None
        def send_signal(self, s): pass
        def wait(self, timeout=None): return 0
        def kill(self): pass

    monkeypatch.setattr(proc_mod.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(proc_mod, "wait_port", lambda *a, **k: True)
    monkeypatch.setattr(proc_mod, "wait_http", lambda *a, **k: True)
    monkeypatch.setattr(proc_mod, "spawn_sessiond", lambda *a, **k: FakePopen([]))

    h = ProcessRuntime().start("x", port=_free(), browser_path="/bin/true",
                               data_dir=str(tmp_path), bind="0.0.0.0",
                               transport="screencast")
    assert any("0.0.0.0" in n for n in h.detail["notes"]), h.detail["notes"]

    h2 = ProcessRuntime().start("y", port=_free(), browser_path="/bin/true",
                                data_dir=str(tmp_path / "2"),
                                transport="screencast")
    assert not any("0.0.0.0" in n for n in h2.detail["notes"]), "默认不该报警"
