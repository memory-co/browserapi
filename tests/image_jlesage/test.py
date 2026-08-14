"""image_jlesage — 这层 wrapper 几乎什么都没加,那它到底加了什么. See README.md."""

import json
import os
import re
import shutil
import subprocess
import time
import urllib.request

import pytest

from tests.image_conftest import free_port, need_image, session_on, sweep

IMAGE = "ghcr.io/memory-co/webmuxd/jlesage-chromium:v26.08.1"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module", autouse=True)
def _have_image():
    need_image(IMAGE)
    sweep("t-jl-")
    yield
    sweep("t-jl-")


def test_the_labels_say_a_different_thing_than_kasm():
    """同一套代码要驱动两个完全不同的镜像,靠的就是这些值不一样。

    **端口和口令那几个是故意一样的** —— wrapper 把它们翻译掉了,所以
    `docker run` 的人不用记哪个镜像用哪个变量名。剩下的才是真差异。
    """
    from webmuxd.runtime.container import Profile

    p = Profile.read("docker", IMAGE)
    assert (p.window_port, p.window_scheme) == (5800, "https")
    assert p.password_env == "WEBMUXD_PASSWORD"
    assert p.args_env == "CHROMIUM_CUSTOM_ARGS"
    # **故意是空的**:这个底座只有 CHROMIUM_APP_URL,而它映射到 `--app=`
    # (无边框应用窗口),不是普通启动页。与其用错模式,不如不声明 ——
    # webmuxd 连上之后自己 open() 就是了。
    assert p.url_env == "", "别把启动页接到 --app= 上"
    assert p.window_user == "" and p.window_user_env, "登录名是变量定的,不是写死的"
    assert p.host_network == "multi"


def test_the_cdp_relay_is_the_base_images_own():
    """**这层 wrapper 的全部内容就是"把它默认打开"。**

    底座自己内置了 socat 转发,只是默认关着。所以这里断言的是:跑着的是
    `socat`(它的),而不是我们那个 `cdp-relay.py`(kasm 那边才需要)。
    """
    with session_on(IMAGE, "t-jl-cdp") as (handle, _sess):
        port = handle.detail["cdp_port"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                    timeout=10) as r:
            assert "Chrome/" in json.load(r)["Browser"]

        cid = handle.detail["container_id"]
        ps = subprocess.run(["docker", "exec", cid, "sh", "-c", "ps ax"],
                            capture_output=True, text=True).stdout
        assert "socat" in ps, "底座那个转发服务没起来"
        assert "cdp-relay" not in ps, "不该有我们的中继 —— 底座本来就有"


def test_webmuxd_can_drive_it():
    with session_on(IMAGE, "t-jl-drive") as (_handle, sess):
        tab = sess.open("https://example.com")
        assert tab.title == "Example Domain"
        assert tab.click("Learn more").ok
        assert "iana.org" in tab.url


def test_it_uses_no_named_abstract_socket():
    """**它比 kasm 强的那一点,以及为什么。**

    KasmVNC 用 `.KasmVNCSock<pid>` 做内部会合点 —— 抽象 unix socket 归 network
    namespace 管、名字来自 Xvnc 的容器内 PID,所以共享 netns 的第二个容器必然
    撞名(kasmtech/KasmVNC#363)。共享 netns 正是"容器里的 localhost 就是宿主机
    的 localhost"的前提,所以这不是小事。

    **这里直接断言机制,而不是去起两个容器观察后果。** 后者要跑好几分钟、
    受机器负载左右,而且失败时只告诉你"第二个没起来",不告诉你为什么。
    机制这一条快、稳,而且红了就直接指向原因。
    """
    # **故意用 bridge 起一个来看。**
    #
    # 要测的是"这个镜像会不会自己起带名字的抽象 socket",那是镜像的属性。
    # host 网络下容器看到的是**宿主机那份**抽象命名空间(实测会看到宿主机的
    # `@/var/spool/exim4/exim_daemon_notify` 之类),根本分不清谁是谁的 ——
    # 换句话说,用生产的跑法反而测不了这件事。
    cid = subprocess.run(
        ["docker", "run", "-d", "--name", "t-jl-sock", "--shm-size=1g", IMAGE],
        capture_output=True, text=True).stdout.strip()
    assert cid, "容器没起来"
    try:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            got = subprocess.run(["docker", "exec", cid, "pgrep", "Xvnc"],
                                 capture_output=True, text=True)
            if got.returncode == 0:
                break
            time.sleep(3)
        else:
            pytest.fail("Xvnc 没起来")

        raw = subprocess.run(
            ["docker", "exec", cid, "sh", "-c",
             "cat /proc/$(pgrep Xvnc | head -1)/cmdline"],
            capture_output=True).stdout
        cmdline = " ".join(raw.decode("utf-8", "replace").split("\x00"))
        # **只断言真正决定成败的那条**:`-nolisten local` 关掉 X 的抽象 socket。
        # RFB 开不开 TCP 口不重要(`-rfbport` 可配置,实测见过 5900 也见过 -1)
        # —— 端口撞了改一下就好,抽象 socket 的名字撞了没得改。
        assert "-nolisten local" in cmdline, "X 的抽象 socket 没关掉"
        assert "-rfbunixpath=" in cmdline, "RFB 没走文件系统 socket"

        names = subprocess.run(
            ["docker", "exec", cid, "sh", "-c",
             "grep -oE '@[^ ]+' /proc/net/unix | sort -u"],
            capture_output=True, text=True).stdout.split()
        # 匿名 autobind 无所谓 —— 内核给的是五位十六进制(`@f0fa9`),天生各不相同。
        named = [n for n in names if not re.fullmatch(r"@[0-9a-f]{5}", n)]
        assert not named, f"这个镜像自己起了带名字的抽象 socket:{named}"
    finally:
        subprocess.run(["docker", "rm", "-f", "t-jl-sock"], capture_output=True)


@pytest.mark.skipif(
    os.environ.get("WEBMUXD_SLOW_IMAGE_TESTS") != "1",
    reason="真起两个共享 host netns 的容器,好几分钟且受机器负载左右;"
           "机制那条(test_it_uses_no_named_abstract_socket)已经覆盖了结论。"
           "要跑就 WEBMUXD_SLOW_IMAGE_TESTS=1")
def test_two_of_them_can_share_the_host_network():
    """**这是它比 kasm 强的那一点,也是选它的唯一理由。**

    KasmVNC 用 `.KasmVNCSock<pid>` 做内部会合点 —— 抽象 unix socket 归 network
    namespace 管,名字来自 Xvnc 的容器内 PID,所以共享 netns 的第二个容器必然
    撞名。这个底座给 Xvnc 的是 `-nolisten local -rfbport=-1 -rfbunixpath=…`,
    X 和 RFB 都走文件系统上的 socket,抽象命名空间里一个带名字的都没有。

    共享 netns 正是"容器里的 localhost 就是宿主机的 localhost"的前提,
    所以这条不是锦上添花。
    """
    if not shutil.which("docker"):
        pytest.skip("没有 docker")

    names, ports = [], []

    def up(port, budget):
        deadline = time.monotonic() + budget
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/version", timeout=3):
                    return True
            except Exception:
                time.sleep(3)
        return False

    try:
        # **逐个起、逐个等。** 要证明的是"两个同时活着",不是"两个同时启动" ——
        # 并发启动只会让这条用例被机器负载左右。
        for i in (1, 2):
            cdp, win = free_port(), free_port()
            name = f"t-jl-hostnet-{i}"
            r = subprocess.run(
                ["docker", "run", "-d", "--name", name, "--shm-size=1g",
                 "--network", "host",
                 "-e", f"CHROMIUM_REMOTE_DEBUGGING_PORT={cdp}",
                 "-e", f"WEB_LISTENING_PORT={win}", IMAGE],
                capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
            names.append(name)
            ports.append(cdp)
            assert up(cdp, 240), f"第 {i} 个没起来 —— " + subprocess.run(
                ["docker", "logs", "--tail", "5", name],
                capture_output=True, text=True).stdout[-300:]

        # 第一个在第二个起来之后**还活着**,才叫共存
        assert up(ports[0], 20), "第一个被第二个挤掉了"

        for name in names:
            log = subprocess.run(["docker", "logs", name],
                                 capture_output=True, text=True)
            assert "already in use" not in (log.stdout + log.stderr).lower()
    finally:
        for name in names:
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
