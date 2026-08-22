"""runtime —— 对着 docs/v2/works/07-runtime.md 校。

v2 的契约只剩一条:**一个 CDP 端点**。所以这个场景短了很多 ——
v1 那 600 行里大半是在验"容器命令怎么拼、镜像标签怎么读",
而那整套机制存在的理由是**描述别人的镜像长什么样**,v2 没有别人的镜像了。

`process` 是真跑真起的:浏览器 + sessiond 起来,lib 连上去点一下,
而且**画面就在同一个口上**。
"""

import contextlib
import shutil
import socket
import tempfile
import time

import pytest

from webmuxd import Webmuxd
from webmuxd import config
from webmuxd import install as install_mod
from webmuxd import sessions as rt
from webmuxd.exceptions import PortInUse, RuntimeUnavailable
from webmuxd.models import SessionInfo
from webmuxd.processes import port_free, require_ports
from webmuxd.processes import resolve_browser
from webmuxd.sessions import ProcessRuntime
from webmuxd.sessions import RemoteRuntime


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
    """换大版本时要说得出换的是哪两个版本 —— 前提是版本确定。"""
    assert config.PINNED.count(".") == 3
    assert install_mod.download_url().endswith(".zip")
    assert config.PINNED in install_mod.download_url()


def test_换源只换前缀(monkeypatch):
    monkeypatch.setenv("WEBMUXD_BROWSER_MIRROR", install_mod.CN_MIRROR)
    u = install_mod.download_url()
    assert u.startswith(install_mod.CN_MIRROR) and config.PINNED in u


# -------------------------------------------------------------- 不降级

def test_remote_没给_cdp_就拒绝():
    with pytest.raises(RuntimeUnavailable) as ei:
        RemoteRuntime().start("x", port=_free())
    assert "cdp" in str(ei.value)


def test_remote_的_stop_不动对面():
    """**只停本地的 sessiond,对面一个字节都不动**(works/07 §6)。"""
    h = SessionInfo("remote", "prod", {"cdp": "http://elsewhere:9222"})
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


def test_端口不在_session_上():
    """**一个 server 一个口,session 是它下面的一段路径**
    ([k](../../docs/v2/works/k-one-server.md))。

    v1 一个 session 两个端口,v2 收成一个,现在收到 server 上 ——
    那个"一个 session 一个端口"从来不是设计,是 kasm 的 web 口不归我们控制。
    """
    h = SessionInfo("process", "work", {})
    assert h.path() == "/s/work/"
    assert not hasattr(h, "port"), "端口又回到 session 上了"


# ---------------------------------------------------------- 真起真跑

def test_runtime_只产出一个_cdp_端点():
    """**这条是真起真跑。** runtime 不再起 sessiond —— 那个进程没有了,
    server 自己就是([k §5](../../docs/v2/works/k-one-server.md))。
    """
    if not ProcessRuntime().available()[0]:
        pytest.skip("本机没有浏览器")

    impl = ProcessRuntime()
    h = impl.start("t-proc", transport="screencast")
    try:
        assert impl.alive(h) and h.kind == "process"
        cdp = h.detail["cdp"]
        assert cdp.startswith("http://127.0.0.1:")
        import urllib.request
        with urllib.request.urlopen(cdp + "/json/version", timeout=10) as r:
            assert r.status == 200
    finally:
        impl.stop(h)
    time.sleep(0.5)
    assert not impl.alive(h), "stop 之后浏览器还活着"


@pytest.mark.slow
def test_两个_session_一个口():
    """**这就是这次改动要的东西**:一个 server 一个口,session 住在它下面。"""
    if not ProcessRuntime().available()[0]:
        pytest.skip("本机没有浏览器")

    from webmuxd import processes
    port = _free()
    data = tempfile.mkdtemp(prefix="wm-t-")
    proc = processes.spawn_server(port=port, data=data)
    assert processes.wait_http(f"http://127.0.0.1:{port}/healthz", 30)
    web = Webmuxd(port=port)
    try:
        a = web.session(id="t-a", transport="screencast")
        b = web.session(id="t-b", transport="screencast")
        assert a.status()["ok"] and b.status()["ok"]
        assert web.session(id="t-a") is a, "同一个 id 要给同一个对象"
        # **同一个口,两段路径**
        assert a.api_url == f"http://127.0.0.1:{port}/s/t-a"
        assert b.api_url == f"http://127.0.0.1:{port}/s/t-b"
        assert {r["id"] for r in web.list()} == {"t-a", "t-b"}
        web.kill("t-a")
        assert {r["id"] for r in web.list()} == {"t-b"}
    finally:
        with contextlib.suppress(Exception):
            web.kill_server()
        time.sleep(1)
        proc.kill()
        shutil.rmtree(data, ignore_errors=True)      # 用完就收
    time.sleep(0.5)
    assert port_free(port), "server stop 之后端口还占着 —— 进程没清干净"


def test_v1_的参数名不静默吞掉():
    """从 v1 升上来的人会带着旧名来,**落进 kw 被丢掉最糟**。"""
    web = Webmuxd()
    for old in ("port", "api_port", "view_port", "image", "network"):
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
    from webmuxd import processes as proc_mod

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

    from webmuxd import serve as serve_main
    src = inspect.getsource(serve_main.main)
    assert '"--bind"' in src, "统一叫 --bind,不叫 --host"
    assert '"0.0.0.0"' not in src.split("--bind")[1].split("\n")[0], \
        "默认还是 0.0.0.0"

    # 老名字留作别名,不然 works/07 里那条命令会突然报 unrecognized
    p = argparse.ArgumentParser()
    p.add_argument("--bind", "--host", dest="bind", default="127.0.0.1")
    assert p.parse_args([]).bind == "127.0.0.1"
    assert p.parse_args(["--host", "0.0.0.0"]).bind == "0.0.0.0"


def test_绑非回环要留一条警告(tmp_path, monkeypatch, capsys):
    """对外开放是**你的决定**,但不能悄悄发生。

    这条跟着端口一起搬到 server 上了 —— 以前每个 session 各绑各的,
    现在**一个口**,所以警告也只在 `webmuxd start` 那一次说
    ([k](../../docs/v2/works/k-one-server.md))。
    """
    from webmuxd import cli as cli_mod
    from webmuxd import processes as proc_mod

    class FakePopen:
        def __init__(self, *a, **kw): self.pid = 1
        def terminate(self): pass

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(proc_mod, "spawn_server", lambda **kw: FakePopen())
    monkeypatch.setattr(proc_mod, "wait_http", lambda *a, **k: True)
    monkeypatch.setattr(proc_mod, "require_ports", lambda *a, **k: None)

    assert cli_mod.main(["server", "start", "--port", "7999", "--bind", "0.0.0.0"]) == 0
    assert "0.0.0.0" in capsys.readouterr().err, "对外开放却没说一声"

    assert cli_mod.main(["server", "start", "--port", "7998"]) == 0
    assert "0.0.0.0" not in capsys.readouterr().err, "默认不该报警"
