"""runtime —— 对着 docs/v1/works/05-server-session-runtime.md §4 校。

`process` 是真跑起来的:Chromium + sessiond 起来,lib 连上去点一下。
`container` 在这个环境里没有 docker,所以只验命令怎么拼和"不可用时怎么报"——
**没验的部分明说,不假装**。
"""

import socket
import time

import pytest

from webmuxd import Webmuxd, runtime as rt
from webmuxd.errors import PortInUse, RuntimeUnavailable
from webmuxd.runtime.base import Handle, port_free, require_ports
from webmuxd.runtime.container import ContainerRuntime
from webmuxd.runtime.process import ProcessRuntime
from webmuxd.runtime.remote import RemoteRuntime


def _free() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------ 选择

def test_three_runtimes_and_a_default():
    assert set(rt.detect()) == {"container", "process", "remote"}
    assert rt.DEFAULT == "container", "默认该是有隔离的那个"


def test_unknown_runtime_says_what_there_is():
    with pytest.raises(RuntimeUnavailable) as ei:
        rt.get("虚拟机")
    assert "container" in ei.value.hint


def test_detect_is_probing_not_guessing():
    """CLI 靠它给出**准确的**报错提示 —— 所以它得真去探。"""
    d = rt.detect()
    assert d["process"] is (ProcessRuntime().available()[0])
    assert d["container"] is (ContainerRuntime().available()[0])


# -------------------------------------------------------------- 不降级

def test_container_unavailable_raises_with_a_useful_hint():
    """**不静默降级** —— 换成 process 等于把页面偷偷挪到你自己机器上跑,
    没有隔离(works/05 §4)。"""
    impl = ContainerRuntime(docker="根本没有这个命令")
    ok, why = impl.available()
    assert not ok and "找不到" in why

    with pytest.raises(RuntimeUnavailable) as ei:
        impl.start("x", api_port=_free(), vnc_port=_free())
    assert "process" in ei.value.hint and "隔离" in ei.value.hint, \
        "提示里得说清换成 process 的代价"
    assert ei.value.details["runtime"] == "container"


def test_remote_without_an_endpoint_is_rejected():
    with pytest.raises(RuntimeUnavailable) as ei:
        RemoteRuntime().start("x")
    assert "endpoint" in str(ei.value)


def test_remote_stop_does_not_touch_the_other_side():
    """**只删本地记录,不动对面**(api/server.md §3)。"""
    h = Handle("remote", "prod", 7900, 0, {"endpoint": "http://elsewhere:7900"})
    RemoteRuntime().stop(h)          # 不该抛,也不该做任何事
    assert h.detail["endpoint"] == "http://elsewhere:7900"


# ---------------------------------------------------------------- 端口

def test_taken_port_is_reported_not_worked_around():
    """**端口是部署决定的,我们不替你换一个**(sdk/manager.md §1)。"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        taken = s.getsockname()[1]
        assert not port_free(taken)
        with pytest.raises(PortInUse) as ei:
            require_ports(taken)
        assert ei.value.details["port"] == taken


# ------------------------------------------------- container 的命令怎么拼

def test_container_command_carries_what_the_docs_say(monkeypatch):
    """没有 docker 也能验命令 —— 端口映射、label、shm、镜像。"""
    seen = {}

    class FakeRun:
        def __init__(self, rc=0, out="deadbeef"):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake(args, **kw):
        seen.setdefault("calls", []).append(args)
        if args[1] == "info":
            return FakeRun()
        return FakeRun()

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run", fake)
    monkeypatch.setattr("webmuxd.runtime.container.shutil.which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr("webmuxd.runtime.container.wait_http", lambda *a, **k: True)

    impl = ContainerRuntime(image="webmuxd/operator:1.0")
    h = impl.start("work", api_port=7900, vnc_port=6901,
                   viewport="1280x800", volume="webmuxd-work", token="t0k")

    run = next(a for a in seen["calls"] if a[1] == "run")
    joined = " ".join(run)
    assert "-p 6901:6901" in joined and "-p 7900:7900" in joined, \
        "两个口都要映射 —— 一个 session 两个端口"
    assert "--shm-size=1g" in joined, "少于 1G Chromium 会崩"
    assert "webmuxd.session=work" in joined, "没打 label,server 重启后认不回来"
    assert "WEBMUXD_TOKEN=t0k" in joined
    assert "webmuxd-work:/data" in joined
    assert run[-1] == "webmuxd/operator:1.0"
    assert h.detail["container_id"] == "deadbeef"


def test_container_discover_parses_published_ports(monkeypatch):
    """server 重启后靠 label 把跑着的容器认回来 —— 它们本来就活着。"""
    out = "abc123\twork\t0.0.0.0:6901->6901/tcp, 0.0.0.0:7900->7900/tcp\n"

    class R:
        returncode, stdout, stderr = 0, out, ""

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run",
                        lambda *a, **k: R())
    handles = ContainerRuntime().discover()
    assert len(handles) == 1
    h = handles[0]
    assert (h.id, h.api_port, h.vnc_port) == ("work", 7900, 6901)
    assert h.detail["adopted"] is True


# ------------------------------------------------------- process 真跑一次

@pytest.mark.slow
def test_process_runtime_actually_brings_a_session_up():
    """**这条是真起真跑**:Chromium + sessiond 起来,lib 连上去点一下。"""
    if not ProcessRuntime().available()[0]:
        pytest.skip("本机没有 chromium")

    impl = ProcessRuntime()
    api, vnc = _free(), _free()
    h = impl.start("t-proc", api_port=api, vnc_port=vnc)
    try:
        assert impl.alive(h)
        assert h.kind == "process"
        # 没有 Xvnc 时要**说出来**,不能装作有画面
        if not h.detail.get("display"):
            assert any("没有画面" in n for n in h.detail["notes"])

        web = Webmuxd()
        sess = web.session(id="t-proc", port=api, vnc_port=vnc, runtime="process")
        tab = sess.open("about:blank")
        assert tab.js("1+1") == 2
        sess.detach()
    finally:
        impl.stop(h)
    time.sleep(0.5)
    assert not impl.alive(h), "stop 之后进程还活着"


@pytest.mark.slow
def test_manager_starts_a_session_that_is_not_there_yet():
    """`session()` 拿不到就**拉起来** —— 幂等的另一半(sdk/manager.md §1)。"""
    if not ProcessRuntime().available()[0]:
        pytest.skip("本机没有 chromium")

    web = Webmuxd()
    api, vnc = _free(), _free()
    sess = web.session(id="t-auto", port=api, vnc_port=vnc, runtime="process")
    try:
        assert sess.status()["ok"] is True
        again = web.session(id="t-auto")
        assert again is sess, "第二次该给同一个对象,而不是再起一个"
    finally:
        web.shutdown()          # process 的跟着死
    time.sleep(0.5)
    assert port_free(api), "shutdown 之后端口还占着 —— 进程没清干净"
