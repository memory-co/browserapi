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

def _fake_docker(monkeypatch, seen):
    """一台"docker 什么都答应"的假机器。"""
    class R:
        def __init__(self, rc=0, out="deadbeef"):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake(args, **kw):
        seen.append(args)
        return R()

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run", fake)
    monkeypatch.setattr("webmuxd.runtime.container.shutil.which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr("webmuxd.runtime.container.wait_http", lambda *a, **k: True)
    monkeypatch.setattr("webmuxd.runtime.container._spawn_sessiond",
                        lambda *a, **k: type("P", (), {"pid": 4242,
                                                       "terminate": lambda self: None})())


def test_container_command_carries_what_the_docs_say(monkeypatch):
    """没有 docker 也能验命令 —— 端口映射、label、shm、镜像。"""
    seen = []
    _fake_docker(monkeypatch, seen)

    impl = ContainerRuntime(image="kasmweb/chromium:1.18.0")
    h = impl.start("work", api_port=7900, vnc_port=6901,
                   viewport="1280x800", volume="webmuxd-work", token="t0ken1")

    run = next(a for a in seen if a[1] == "run")
    joined = " ".join(run)
    assert "-p 127.0.0.1:6901:6901" in joined, \
        "画面口要映射,而且**只绑 127.0.0.1** —— 放出去是上层的决定"
    assert "--shm-size=1g" in joined, "少于 1G Chromium 会崩"
    assert "webmuxd.session=work" in joined, "没打 label,server 重启后认不回来"
    assert "VNC_PW=t0ken1" in joined, "token 就是 KasmVNC 的密码,拿着它的人能看画面"
    assert "webmuxd-work:/data" in joined
    assert run[-1] == "kasmweb/chromium:1.18.0"
    assert h.detail["container_id"] == "deadbeef"


def test_nothing_of_ours_is_installed_into_the_image(monkeypatch):
    """**跑的就是 kasm 原厂镜像,没有派生层。**

    容器里唯一多出来的东西是那一跳中继,而它用的是镜像自带的 python3 ——
    所以 `--image` 指哪个 kasm 镜像都能用,起 session 也不用等 pip。
    """
    seen = []
    _fake_docker(monkeypatch, seen)
    ContainerRuntime().start("work", api_port=7900, vnc_port=6901)

    for call in seen:
        line = " ".join(call)
        assert "pip install" not in line and "apt-get" not in line, \
            f"往容器里装东西了:{line}"
        assert call[1] != "build", "又去 build 镜像了"
    execs = [a for a in seen if a[1] == "exec"]
    assert execs, "没有 exec 进去起中继"
    assert not any("webmuxd.serve" in " ".join(a) for a in execs), \
        "sessiond 不该起在容器里 —— 它跑在调用方这边"


def test_the_only_thing_exec_ed_in_is_a_relay_that_needs_nothing(monkeypatch):
    """中继只用 `python3 -c`,**不依赖镜像里装了什么**。"""
    seen = []
    _fake_docker(monkeypatch, seen)
    ContainerRuntime().start("work", api_port=7900, vnc_port=6901)

    relay = next(a for a in seen if a[1] == "exec" and "python3" in a)
    assert relay[-2] == "-c", "中继该是内联源码,不是容器里的某个文件"
    assert "asyncio.start_server" in relay[-1]


def test_the_cdp_port_is_published_because_chromium_will_not_bind_outward(monkeypatch):
    """Chromium 把调试口绑死在容器内 127.0.0.1,`-p` 够不着它 ——
    所以中继监听 9223,映射出去的是 9223,**不是 9222**。

    而且它和另外两个口一样**只绑 127.0.0.1**:CDP 比 API 更底层、
    没有动作日志,能连上它就等于绕过了整层。
    """
    seen = []
    _fake_docker(monkeypatch, seen)
    h = ContainerRuntime().start("work", api_port=7900, vnc_port=6901)

    run = next(a for a in seen if a[1] == "run")
    published = [run[i + 1] for i, a in enumerate(run) if a == "-p"]
    assert all(p.startswith("127.0.0.1:") for p in published), \
        f"有口绑到了 0.0.0.0:{published}"
    assert not any(p.endswith(":9222") for p in published), \
        f"直接映射 9222 是空的,Chromium 没在 eth0 上听:{published}"
    assert any(p.endswith(":9223") for p in published), f"中继口没映射:{published}"
    assert h.detail["cdp_port"] not in (0, None)
    # 浏览器那边确实开着调试口,只是只在容器内 127.0.0.1 上
    assert "--remote-debugging-port=9222" in " ".join(run)


def test_a_too_short_vnc_password_is_caught_here(monkeypatch):
    """kasm 要求至少 6 位,短了容器直接退出,**报的错和密码毫无关系**
    (`kill: usage: ...`)—— 所以在这儿拦住。"""
    seen = []
    _fake_docker(monkeypatch, seen)
    with pytest.raises(RuntimeUnavailable) as ei:
        ContainerRuntime().start("work", api_port=7900, vnc_port=6901, token="x")
    assert "6" in str(ei.value)
    assert not any(a[1] == "run" for a in seen), "都知道要失败了还去 docker run"


def test_container_discover_parses_published_ports(monkeypatch):
    """server 重启后靠 label 把跑着的容器认回来 —— 它们本来就活着。

    **认回来的只有容器。** sessiond 跑在调用方那边,跟着上一个 server 死了,
    所以 `api_port` 是 0 —— 接管的一方要自己重新起一个,而不是以为它还在。
    """
    out = "abc123\twork\t0.0.0.0:6901->6901/tcp, 0.0.0.0:41234->9223/tcp\n"

    class R:
        returncode, stdout, stderr = 0, out, ""

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run",
                        lambda *a, **k: R())
    handles = ContainerRuntime().discover()
    assert len(handles) == 1
    h = handles[0]
    assert (h.id, h.vnc_port) == ("work", 6901)
    assert h.api_port == 0, "sessiond 不在容器里,认不回来"
    assert h.detail["cdp_port"] == 41234, "中继口要认回来,重新起 sessiond 得用它"
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
