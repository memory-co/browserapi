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
    h = impl.start("t-proc", port=port)
    try:
        assert impl.alive(h) and h.kind == "process"
        assert h.port == port

        import urllib.request
        with urllib.request.urlopen(h.view_url, timeout=10) as r:
            page = r.read()
        # 画面页就在那个口的根上,而且是我们自己的那一份
        assert r.status == 200 and b"/api/view" in page

        web = Webmuxd()
        sess = web.session(id="t-proc", port=port, runtime="process")
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
    sess = web.session(id="t-auto", port=port, runtime="process")
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
