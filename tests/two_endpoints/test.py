"""runtime —— 对着 docs/v1/works/05-server-session-runtime.md §4 校。

`process` 是真跑起来的:Chromium + sessiond 起来,lib 连上去点一下。
`container` 在这个环境里没有 docker,所以只验命令怎么拼和"不可用时怎么报"——
**没验的部分明说,不假装**。
"""

import json
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
        impl.start("x", api_port=_free(), view_port=_free())
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

KASM_LABELS = {
    'webmuxd.view.port': '6901',
    'webmuxd.view.scheme': 'https',
    'webmuxd.view.port_env': 'NO_VNC_PORT',
    'webmuxd.view.login': 'kasm_user',
    'webmuxd.view.password_env': 'VNC_PW',
    'webmuxd.cdp.port': '9222',
    'webmuxd.cdp.port_env': 'WEBMUXD_CDP_PORT',
    'webmuxd.chromium.args_env': 'APP_ARGS',
    'webmuxd.chromium.url_env': 'LAUNCH_URL',
    'webmuxd.host.network': 'single',
    'webmuxd.view.bind_env': 'WEBMUXD_BIND',
    'webmuxd.view.auth_env': 'WEBMUXD_AUTH',
}

JLESAGE_LABELS = {
    'webmuxd.view.port': '5800',
    'webmuxd.view.scheme': 'http',
    'webmuxd.view.port_env': 'WEB_LISTENING_PORT',
    'webmuxd.view.login_env': 'WEB_AUTHENTICATION_USERNAME',
    'webmuxd.view.password_env': 'WEB_AUTHENTICATION_PASSWORD',
    'webmuxd.cdp.port': '9222',
    'webmuxd.cdp.port_env': 'CHROMIUM_REMOTE_DEBUGGING_PORT',
    'webmuxd.chromium.args_env': 'CHROMIUM_CUSTOM_ARGS',
    'webmuxd.chromium.url_env': '',
    'webmuxd.host.network': 'multi',
    'webmuxd.view.bind_env': 'WEBMUXD_BIND',
    'webmuxd.view.auth_env': 'WEBMUXD_AUTH',
    'webmuxd.view.tls_env': 'WEBMUXD_TLS',
}


def _fake_docker(monkeypatch, seen, labels=None):
    """一台"docker 什么都答应"的假机器,镜像的标签由调用方给。"""
    labels = KASM_LABELS if labels is None else labels

    class R:
        def __init__(self, rc=0, out="deadbeef"):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake(args, **kw):
        seen.append(args)
        if "inspect" in args and "Config.Labels" in " ".join(args):
            return R(out=json.dumps(labels))
        return R()

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run", fake)
    monkeypatch.setattr("webmuxd.runtime.container.shutil.which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr("webmuxd.runtime.container.wait_http", lambda *a, **k: True)
    monkeypatch.setattr("webmuxd.runtime.container._spawn_sessiond",
                        lambda *a, **k: type("P", (), {"pid": 4242,
                                                       "terminate": lambda self: None})())


def _run_cmd(seen):
    return next(a for a in seen if a[1] == "run" and "-d" in a)


def test_container_command_carries_what_the_docs_say(monkeypatch):
    """端口映射、label、shm、镜像。"""
    seen = []
    _fake_docker(monkeypatch, seen)
    h = ContainerRuntime(image="ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0").start(
        "work", api_port=7900, view_port=6901,
        window_size="1280x800", volume="webmuxd-work", password="t0ken1")

    joined = " ".join(_run_cmd(seen))
    assert "--network host" in joined, "共享 netns 才有那个 localhost"
    assert "-p " not in joined, "host 网络下不该有端口映射"
    assert "NO_VNC_PORT=6901" in joined, "画面口是直接告诉镜像的"
    assert "--shm-size=1g" in joined, "少于 1G Chromium 会崩"
    assert "webmuxd.session=work" in joined, "没打 label,server 重启后认不回来"
    assert "webmuxd-work:/data" in joined
    assert _run_cmd(seen)[-1] == "ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0"
    assert h.detail["container_id"] == "deadbeef"


def test_the_env_names_come_from_the_image_not_from_us(monkeypatch):
    """**这条是这次重写的全部意义。**

    同一份代码,喂两套标签,产出的变量名跟着变 —— 说明 runtime 里没有
    任何一个镜像的名字。加第三个镜像不用改代码,给它打标签就行。
    """
    seen = []
    _fake_docker(monkeypatch, seen, KASM_LABELS)
    ContainerRuntime().start("work", api_port=7900, view_port=6901, password="t0ken1",
                             url="https://example.com")
    kasm = " ".join(_run_cmd(seen))
    assert "VNC_PW=t0ken1" in kasm and "LAUNCH_URL=https://example.com" in kasm
    assert "APP_ARGS=" in kasm
    assert "NO_VNC_PORT=6901" in kasm

    seen.clear()
    _fake_docker(monkeypatch, seen, JLESAGE_LABELS)
    ContainerRuntime().start("work", api_port=7900, view_port=6901, password="t0ken1",
                             url="https://example.com")
    jl = " ".join(_run_cmd(seen))
    assert "WEB_AUTHENTICATION_PASSWORD=t0ken1" in jl
    assert "CHROMIUM_CUSTOM_ARGS=" in jl
    # **这个镜像没有"启动页"这个变量**(它只有 CHROMIUM_APP_URL,而那个映射到
    # `--app=` 无边框窗口,不是普通启动页)。profile 里宁可缺一项,也不填一个
    # 语义不对的 —— 缺了就由 webmuxd 连上之后自己 open()。
    assert "https://example.com" not in jl, "不该把启动页塞给一个没有这个概念的镜像"
    assert "WEB_LISTENING_PORT=6901" in jl, "换个镜像,改画面口的变量名也不一样"

    # 一个都不该串台
    assert "VNC_PW" not in jl and "WEB_AUTHENTICATION_PASSWORD" not in kasm


def test_the_window_scheme_and_multi_open_come_from_labels(monkeypatch):
    """报给人的 URL 用什么 scheme、能不能一机多开,都是镜像的事实。"""
    for labels, scheme, host_net in ((KASM_LABELS, "https", "single"),
                                     (JLESAGE_LABELS, "http", "multi")):
        seen = []
        _fake_docker(monkeypatch, seen, labels)
        h = ContainerRuntime().start("work", api_port=7900, view_port=6901)
        assert h.detail["view_scheme"] == scheme
        assert h.detail["host_network"] == host_net


def test_an_image_without_labels_is_a_hard_error(monkeypatch):
    """**没有标签就不猜。** 猜错的后果是容器起来了、画面在别的口上,
    而报错指向"连不上",查半天。"""
    seen = []
    _fake_docker(monkeypatch, seen, {})
    with pytest.raises(RuntimeUnavailable) as ei:
        ContainerRuntime().start("work", api_port=7900, view_port=6901)
    assert "标签" in str(ei.value)
    assert not any(a[1] == "run" and "-d" in a for a in seen), "不知道怎么驱动还去 docker run"


def test_we_no_longer_exec_a_cdp_relay_into_the_container(monkeypatch):
    """CDP 是**镜像自己送出来的**(wrapper 那一层负责),runtime 不再 exec 中继。"""
    seen = []
    _fake_docker(monkeypatch, seen)
    ContainerRuntime().start("work", api_port=7900, view_port=6901)
    for call in seen:
        line = " ".join(call)
        assert "pip install" not in line and "apt-get" not in line, \
            f"往容器里装东西了:{line}"
        assert call[1] != "build", "又去 build 镜像了"
    assert not any(a[1] == "exec" for a in seen), "还在 exec 进容器挂中继"


def test_the_window_port_is_told_to_the_image_not_mapped(monkeypatch):
    """**host 网络下没有 `-p`。**

    所以画面口不是映射出来的,是**直接告诉镜像听在那儿**。镜像要是没说
    这个变量叫什么(`webmuxd.view.port_env`),我们就没办法让它听在
    调用方要的口上 —— 那就直接报错,而不是让它听在默认口上装作成功。
    """
    seen = []
    _fake_docker(monkeypatch, seen)
    h = ContainerRuntime().start("work", api_port=7900, view_port=6901)
    assert h.detail["cdp_port"] not in (0, None)
    # 默认只在本机 —— host 下没有 `-p`,但镜像自己能绑(见 bind_env 那条)
    assert h.detail["view_bind"] == "127.0.0.1"

    seen.clear()
    no_port_env = dict(KASM_LABELS)
    no_port_env.pop("webmuxd.view.port_env")
    _fake_docker(monkeypatch, seen, no_port_env)
    with pytest.raises(RuntimeUnavailable) as ei:
        ContainerRuntime().start("work", api_port=7900, view_port=6901)
    assert "view.port_env" in str(ei.value)


def test_bridge_is_still_there_for_when_host_will_not_do(monkeypatch):
    """**host 是默认,不是唯一。**

    要网络隔离、或者那个镜像在 host 下开不了多个,就用 bridge。代价写在
    works/08 §6.2:容器里的 `localhost` 是它自己的,够不着你机器上只绑
    loopback 的服务。

    两种模式下 CDP 口都**只绑 127.0.0.1** —— 它比 API 更底层、没有动作日志。
    """
    seen = []
    _fake_docker(monkeypatch, seen)
    h = ContainerRuntime().start("work", api_port=7900, view_port=6901,
                                 network="bridge", bind="0.0.0.0")

    run = _run_cmd(seen)
    joined = " ".join(run)
    assert "--network host" not in joined
    assert "-p 0.0.0.0:6901:6901" in joined, "画面口跟着 bind 走"
    published = [run[i + 1] for i, a in enumerate(run) if a == "-p"]
    cdp = [p for p in published if p.endswith(":9222")]
    assert cdp and all(p.startswith("127.0.0.1:") for p in cdp), \
        f"CDP 口放出去了:{published}"
    assert h.detail["network"] == "bridge"
    assert h.detail["view_bind"] == "0.0.0.0"

    # bridge 下不需要镜像声明"画面口怎么改" —— `-p` 就够了
    seen.clear()
    no_port_env = dict(KASM_LABELS)
    no_port_env.pop("webmuxd.view.port_env")
    _fake_docker(monkeypatch, seen, no_port_env)
    ContainerRuntime().start("work", api_port=7900, view_port=6901, network="bridge")


def test_bind_reaches_the_image_in_both_network_modes(monkeypatch):
    """**"绑哪个地址"在两种模式下落点不同,但对调用方是同一个参数。**

    - host:容器的网络栈就是宿主机的,所以直接告诉镜像绑哪儿
    - bridge:容器内**必须**绑 `0.0.0.0`(否则 `-p` 够不着,DNAT 到的是 eth0),
      对外收不收得住由 `-p` 前面那个地址决定
    """
    seen = []
    _fake_docker(monkeypatch, seen)
    ContainerRuntime().start("work", api_port=7900, view_port=6901,
                             bind="127.0.0.1")
    assert "WEBMUXD_BIND=127.0.0.1" in " ".join(_run_cmd(seen))

    seen.clear()
    _fake_docker(monkeypatch, seen)
    ContainerRuntime().start("work", api_port=7900, view_port=6901,
                             network="bridge", bind="127.0.0.1")
    joined = " ".join(_run_cmd(seen))
    assert "WEBMUXD_BIND=0.0.0.0" in joined, "bridge 下容器内必须绑 0.0.0.0"
    assert "-p 127.0.0.1:6901:6901" in joined, "对外收在 -p 这一层"


def test_an_image_that_cannot_be_restricted_says_so(monkeypatch):
    """镜像没说"绑哪儿"怎么配,而调用方要求只在本机 —— **管不住就说管不住**,
    别让他以为限制住了。"""
    no_bind = {k: v for k, v in KASM_LABELS.items() if k != "webmuxd.view.bind_env"}
    seen = []
    _fake_docker(monkeypatch, seen, no_bind)
    with pytest.raises(RuntimeUnavailable) as ei:
        ContainerRuntime().start("work", api_port=7900, view_port=6901,
                                 bind="127.0.0.1")
    assert "bind_env" in str(ei.value)

    # 但显式承认它是对外的,就放行
    seen.clear()
    _fake_docker(monkeypatch, seen, no_bind)
    ContainerRuntime().start("work", api_port=7900, view_port=6901, bind="0.0.0.0")


def test_auth_and_tls_are_switches_when_the_image_has_them(monkeypatch):
    """**组合是调用方的事,我们只负责把开关接出来。**

    host + 只绑本机 + 不要口令 + http,是个合理组合(自己机器上调试);
    对外暴露还关口令则是另一回事 —— 那是调用方的决定,不是我们替他拦。
    """
    seen = []
    _fake_docker(monkeypatch, seen, JLESAGE_LABELS)
    h = ContainerRuntime().start("work", api_port=7900, view_port=6901,
                                 bind="127.0.0.1", auth=False, tls=False)
    joined = " ".join(_run_cmd(seen))
    assert "WEBMUXD_AUTH=0" in joined and "WEBMUXD_TLS=0" in joined
    assert "WEBMUXD_BIND=127.0.0.1" in joined
    assert h.detail["auth"] is False
    assert h.detail["view_password"] == "" and h.detail["view_login"] == ""
    # **scheme 得跟着算**,不然调用方会拼出一个连不上的 URL
    assert h.detail["view_scheme"] == "http"


def test_a_capability_the_image_lacks_is_an_error_not_a_pretence(monkeypatch):
    """KasmVNC 的画面口恒 TLS(实测:拿掉 `-sslOnly` 也一样),
    所以要求 http 只能报错 —— **装作可以,调用方就会按 http 去拼 URL**。"""
    seen = []
    _fake_docker(monkeypatch, seen, KASM_LABELS)     # 没有 tls_env
    with pytest.raises(RuntimeUnavailable) as ei:
        ContainerRuntime().start("work", api_port=7900, view_port=6901, tls=False)
    assert "TLS" in str(ei.value)

    # 关鉴权同理:镜像没这个能力就不能默默留着口令装作关了
    no_auth_env = {k: v for k, v in KASM_LABELS.items()
                   if k != "webmuxd.view.auth_env"}
    seen.clear()
    _fake_docker(monkeypatch, seen, no_auth_env)
    with pytest.raises(RuntimeUnavailable):
        ContainerRuntime().start("work", api_port=7900, view_port=6901, auth=False)


def test_a_missing_image_is_pulled_not_refused(monkeypatch):
    """**本机没有就自己拉。**

    `docker run` 本来就会自动拉;是我们为了读标签先 `inspect` 了一下,才把它
    挡成"本机没有镜像,先 docker pull" —— 那是自己制造的障碍,不是真要求。
    """
    seen = []
    state = {"local": False}

    class R:
        def __init__(self, rc=0, out="deadbeef"):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake(args, **kw):
        seen.append(args)
        if "inspect" in args and "Config.Labels" in " ".join(args):
            if not state["local"]:
                return R(rc=1, out="")            # 本机还没有
            return R(out=json.dumps(KASM_LABELS))
        if args[1] == "pull":
            state["local"] = True                 # 拉完就有了
            return R()
        return R()

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run", fake)
    monkeypatch.setattr("webmuxd.runtime.container.shutil.which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr("webmuxd.runtime.container.wait_http", lambda *a, **k: True)
    monkeypatch.setattr("webmuxd.runtime.container._spawn_sessiond",
                        lambda *a, **k: type("P", (), {"pid": 1, "terminate": lambda s: None})())

    ContainerRuntime().start("work", api_port=7900, view_port=6901)
    assert any(a[1] == "pull" for a in seen), "本机没有却不去拉"
    assert any(a[1] == "run" and "-d" in a for a in seen), "拉完了却没起"


def test_an_unpullable_image_says_why(monkeypatch):
    """拉不到就说拉不到,并且**把 registry 的原话带上** —— 名字打错和网络不通
    是两件事,提示里要分得开。"""
    class R:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def fake(args, **kw):
        if "inspect" in args and "Config.Labels" in " ".join(args):
            return R(1)
        if args[1] == "pull":
            return R(1, err="Error response from daemon: manifest unknown")
        return R(0, "deadbeef")

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run", fake)
    monkeypatch.setattr("webmuxd.runtime.container.shutil.which", lambda _n: "/usr/bin/docker")
    with pytest.raises(RuntimeUnavailable) as ei:
        ContainerRuntime().start("work", api_port=7900, view_port=6901)
    assert "manifest unknown" in str(ei.value)


def test_alive_means_you_can_use_it_not_just_that_docker_says_up(monkeypatch):
    """**容器活着不等于这个 session 能用。**

    sessiond 掉了、容器没掉的时候,`alive()` 只问 docker 就会报 ready,于是
    `webmuxd new` 说一句"已经在跑了"然后什么都不做 —— 而 `api_url` 是死的,
    人就卡在那儿。`ready` 承诺的是"你现在就能用它"。
    """
    class R:
        returncode, stdout, stderr = 0, "true", ""

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run", lambda *a, **k: R())
    h = Handle("container", "work", 7900, 6901, {"container_id": "deadbeef"})

    monkeypatch.setattr("webmuxd.runtime.container.wait_http", lambda *a, **k: False)
    assert not ContainerRuntime().alive(h), "API 不应答就不算 ready"

    monkeypatch.setattr("webmuxd.runtime.container.wait_http", lambda *a, **k: True)
    assert ContainerRuntime().alive(h)


def _fake_docker_with_prior(monkeypatch, seen, *, running, view=6901, cdp=9333):
    """假机器上**已经有一个叫 webmuxd-work 的容器**了。"""
    inspected = [{
        "Id": "c9cda52032c1", "State": {"Running": running},
        "Config": {"Image": "ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0",
                   "Env": [f"WEBMUXD_VIEW_PORT={view}", f"WEBMUXD_CDP_PORT={cdp}",
                           "WEBMUXD_PASSWORD=old-one", "WEBMUXD_LOGIN=kasm_user"]},
    }]

    class R:
        def __init__(self, rc=0, out="deadbeef"):
            self.returncode, self.stdout, self.stderr = rc, out, ""

    def fake(args, **kw):
        seen.append(args)
        joined = " ".join(args)
        if "inspect" in args and "Config.Labels" in joined:
            return R(out=json.dumps(KASM_LABELS))
        if "inspect" in args and "webmuxd-work" in args:
            return R(out=json.dumps(inspected))
        return R()

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run", fake)
    monkeypatch.setattr("webmuxd.runtime.container.shutil.which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr("webmuxd.runtime.container.wait_http", lambda *a, **k: True)
    monkeypatch.setattr("webmuxd.runtime.container._spawn_sessiond",
                        lambda *a, **k: type("P", (), {"pid": 4242, "poll": lambda s: None})())


def test_a_dead_container_left_over_gets_cleared_not_reported(monkeypatch):
    """**上次起失败留下的尸体不该挡住这次。**

    它一直占着 `webmuxd-work` 这个名字,于是下一次 `webmuxd new` 撞在
    docker 的 "name is already in use" 上 —— 报错指向 docker,而真正该做的事
    (把尸体删掉)一个字都没提。停着的容器里没有任何值得留的东西。
    """
    seen = []
    _fake_docker_with_prior(monkeypatch, seen, running=False)
    ContainerRuntime().start("work", api_port=7900, view_port=6901)

    assert any(a[1] == "rm" and "c9cda52032c1" in a for a in seen), "尸体没删掉"
    assert _run_cmd(seen), "删完要照常起一个新的"


def test_a_live_container_is_reattached_not_rebuilt(monkeypatch):
    """**活着的容器不重建** —— 同一个 id 就是同一个浏览器,这才叫幂等。

    重建等于把人正开着的页面、登录态、下载全丢掉。走到这里说明 sessiond 掉了、
    容器没掉,把 sessiond 接回去就行。
    """
    seen = []
    _fake_docker_with_prior(monkeypatch, seen, running=True, cdp=9333)
    h = ContainerRuntime().start("work", api_port=7900, view_port=6901)

    assert not any(a[1] == "run" and "-d" in a for a in seen), "不该重建"
    assert not any(a[1] == "rm" for a in seen), "更不该删"
    assert h.detail["reattached"] and h.detail["cdp_port"] == 9333
    assert h.detail["view_password"] == "old-one", "口令是容器启动那刻定的,得如实报"
    assert h.view_url.startswith("https://"), "scheme 仍然从镜像标签读"


def test_reattach_refuses_to_pretend_the_view_port_changed(monkeypatch):
    """容器的画面口是它启动那一刻定的,**改不了**。

    默默沿用旧口的话,调用方会拿着 `--view-port` 给的那个去连一个空端口。
    """
    seen = []
    _fake_docker_with_prior(monkeypatch, seen, running=True, view=6901)
    with pytest.raises(RuntimeUnavailable) as e:
        ContainerRuntime().start("work", api_port=7900, view_port=8090)
    assert "6901" in str(e.value) and "8090" in str(e.value)


def test_host_mode_pins_the_hostname_to_loopback(monkeypatch):
    """**云主机的 /etc/hosts 里常常没有自己 hostname 的 IPv4 记录**
    (阿里云是典型)。host 网络下容器沿用这份 hosts,kasm 启动时 `xauth` 拿
    hostname 拼显示名就失败,容器起不来 —— 而报出来的是 `kill: usage:` 和
    `Exited (2)`,和 hostname 一点关系看不出来。

    所以 host 模式下自己钉一条,**不去动宿主机的系统文件**。
    """
    import socket

    seen = []
    _fake_docker(monkeypatch, seen)
    ContainerRuntime().start("work", api_port=7900, view_port=6901)
    joined = " ".join(_run_cmd(seen))
    assert f"--add-host {socket.gethostname()}:127.0.0.1" in joined

    # bridge 下 docker 自己会把容器 hostname 写进 /etc/hosts,不用我们管
    seen.clear()
    _fake_docker(monkeypatch, seen)
    ContainerRuntime().start("work", api_port=7900, view_port=6901, network="bridge")
    assert "--add-host" not in " ".join(_run_cmd(seen))


def test_a_too_short_password_is_caught_before_docker_run(monkeypatch):
    """kasm 少于 6 位会直接退出,报的错是 `kill: usage:`、和密码毫无关系。"""
    seen = []
    _fake_docker(monkeypatch, seen)
    with pytest.raises(RuntimeUnavailable) as ei:
        ContainerRuntime().start("work", api_port=7900, view_port=6901, password="x")
    assert "6" in str(ei.value)
    assert not any(a[1] == "run" and "-d" in a for a in seen), "都知道要失败了还去 docker run"


def test_container_discover_parses_published_ports(monkeypatch):
    """server 重启后靠 label 把跑着的容器认回来 —— 它们本来就活着。

    **认回来的只有容器。** sessiond 跑在调用方那边,跟着上一个 server 死了,
    所以 `api_port` 是 0 —— 接管的一方要自己重新起一个。
    """
    out = "abc123\twork\t127.0.0.1:6901->6901/tcp, 127.0.0.1:41234->9222/tcp\n"

    class R:
        returncode, stdout, stderr = 0, out, ""

    monkeypatch.setattr("webmuxd.runtime.container.subprocess.run",
                        lambda *a, **k: R())
    handles = ContainerRuntime().discover()
    assert len(handles) == 1
    h = handles[0]
    assert (h.id, h.view_port) == ("work", 6901)
    assert h.api_port == 0, "sessiond 不在容器里,认不回来"
    assert h.detail["adopted"] is True


# ------------------------------------------------------- process 真跑一次

@pytest.mark.slow
def test_process_runtime_actually_brings_a_session_up():
    """**这条是真起真跑**:Chromium + sessiond 起来,lib 连上去点一下。"""
    if not ProcessRuntime().available()[0]:
        pytest.skip("本机没有 chromium")

    impl = ProcessRuntime()
    api, vnc = _free(), _free()
    h = impl.start("t-proc", api_port=api, view_port=vnc)
    try:
        assert impl.alive(h)
        assert h.kind == "process"
        # 没有 Xvnc 时要**说出来**,不能装作有画面
        if not h.detail.get("display"):
            assert any("没有画面" in n for n in h.detail["notes"])

        web = Webmuxd()
        sess = web.session(id="t-proc", api_port=api, view_port=vnc, runtime="process")
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
    sess = web.session(id="t-auto", api_port=api, view_port=vnc, runtime="process")
    try:
        assert sess.status()["ok"] is True
        again = web.session(id="t-auto")
        assert again is sess, "第二次该给同一个对象,而不是再起一个"
    finally:
        web.shutdown()          # process 的跟着死
    time.sleep(0.5)
    assert port_free(api), "shutdown 之后端口还占着 —— 进程没清干净"
