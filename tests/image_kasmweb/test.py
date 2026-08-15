"""image_kasmweb — 我们给 kasm 加的那一层真的成立吗. See README.md."""

import pytest

from tests.image_conftest import need_image, session_on, sweep

IMAGE = "ghcr.io/memory-co/webmuxd/kasmweb-chromium:1.18.0"

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module", autouse=True)
def _have_image():
    need_image(IMAGE)
    sweep("t-kasm-")
    yield
    sweep("t-kasm-")


def test_the_labels_say_what_this_image_is():
    """**profile 是镜像自己声明的。** 没有这些标签,runtime 就不知道怎么驱动它 ——
    所以标签本身是这层 wrapper 的产出物之一,不是注释。"""
    from webmuxd.runtime.container import Profile

    p = Profile.read("docker", IMAGE)
    assert (p.view_port, p.view_scheme) == (6901, "https")
    assert p.password_env == "WEBMUXD_PASSWORD"
    assert p.args_env == "APP_ARGS" and p.url_env == "LAUNCH_URL"
    assert p.view_login == "kasm_user"
    # KasmVNC 的 .KasmVNCSock<pid> 是抽象 socket、归 netns 管,
    # 所以共享 netns 的第二个容器必然撞名(kasmtech/KasmVNC#363)
    assert p.host_network == "single"


def test_the_window_is_up_and_asks_for_a_password():
    """窗那一半原样是 kasm 的 —— 我们没碰它,它就该还是它。"""
    import urllib.error
    import urllib.request

    with session_on(IMAGE, "t-kasm-win") as (handle, _sess):
        assert handle.detail["view_scheme"] == "https"
        try:
            urllib.request.urlopen(handle.view_url, timeout=10)
            raise AssertionError("画面口居然不要口令")
        except urllib.error.HTTPError as e:
            assert e.code == 401, f"该要口令,实际 {e.code}"
        except urllib.error.URLError as e:
            # 自签名证书:握手被拒也说明它在听,而且是 https
            assert "CERTIFICATE" in str(e).upper() or "SSL" in str(e).upper()


def test_cdp_comes_out_without_us_exec_ing_anything():
    """**这层 wrapper 存在的全部理由。**

    底座没有把 CDP 送出来(Chromium 只肯听容器内 127.0.0.1),我们补了一个中继。
    这条测的就是:runtime 什么都不用 exec,CDP 就在宿主机上够得着。
    """
    import json
    import urllib.request

    with session_on(IMAGE, "t-kasm-cdp") as (handle, _sess):
        port = handle.detail["cdp_port"]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version",
                                    timeout=10) as r:
            assert "Chrome/" in json.load(r)["Browser"]

        # 中继是镜像里那个,不是我们 exec 进去的
        out = subprocess_out(["docker", "exec", handle.detail["container_id"],
                              "sh", "-c", "ps ax | grep -c '[c]dp-relay'"])
        assert out.strip() != "0", "中继没在跑"


def test_webmuxd_can_drive_it():
    """开页面、按可见文字点、观测 —— 三样都得在真镜像上成立。"""
    with session_on(IMAGE, "t-kasm-drive") as (_handle, sess):
        tab = sess.open("https://example.com")
        assert tab.title == "Example Domain"
        assert "Learn more" in tab.observe().as_prompt()
        assert tab.click("Learn more").ok
        assert "iana.org" in tab.url


def subprocess_out(argv) -> str:
    import subprocess
    return subprocess.run(argv, capture_output=True, text=True).stdout
