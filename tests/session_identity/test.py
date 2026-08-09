"""Python lib —— 对着 docs/v1/sdk/ 校,打到真 sessiond 上。

lib 是**同步**的(sdk/README §6),所以 sessiond 跑在后台线程里,
测试从主线程用同步 API 调它 —— 跟真实用法一样。
"""

import asyncio
import threading
import time

import pytest

from webmuxd import Tab, Webmuxd
from webmuxd.core.cdp import CDP
from webmuxd.errors import BadRequest, NotFound, RuntimeUnavailable, TabGone
from webmuxd.serve.app import build
from webmuxd.serve.session import Session as CoreSession

# 用**真的 HTTP 页面**,不是 data: URL —— `targetInfo.title` 对 data: URL
# 给的是 URL 本身,真页面上才等于 document.title。用 data: 测 title 会失真。
HTML = """<!doctype html><meta charset=utf-8><title>结算</title>
<button id=go onclick="document.getElementById('out').textContent='订单已提交'">
提交订单</button><button>取消订单</button>
<label for=p>手机号</label><input id=p><div id=out></div>"""


@pytest.fixture(scope="module")
def live(request):
    """在后台线程里跑一个真 sessiond,返回它的端口。"""
    from aiohttp import web as aioweb
    import shutil, socket, subprocess, os, contextlib

    chromium = shutil.which("chromium-browser") or shutil.which("chromium")
    if not chromium:
        pytest.skip("没有 chromium")

    def free():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    cdp_port, api_port, page_port = free(), free(), free()

    # 一个极小的页面服务器 —— 让被测页面是真的 http://,导航和 title 才正常
    import http.server
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a):
            pass
    httpd = http.server.HTTPServer(("127.0.0.1", page_port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    proc = subprocess.Popen(
        [chromium, "--headless=new", "--no-sandbox", "--disable-gpu",
         f"--remote-debugging-port={cdp_port}",
         f"--user-data-dir=/tmp/lib-{cdp_port}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(150):
        with contextlib.suppress(Exception):
            socket.create_connection(("127.0.0.1", cdp_port), 0.3).close()
            break
        time.sleep(0.2)

    box: dict = {}

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def boot():
            cdp = await CDP.connect(f"http://127.0.0.1:{cdp_port}")
            sess = CoreSession(cdp, data_dir=f"/tmp/libdata-{api_port}",
                               human_yield_ms=0)
            await sess.start()
            runner = aioweb.AppRunner(build(sess))
            await runner.setup()
            await aioweb.TCPSite(runner, "127.0.0.1", api_port).start()
            box["ready"] = True
            await asyncio.Event().wait()

        loop.run_until_complete(boot())

    threading.Thread(target=run, daemon=True).start()
    for _ in range(150):
        if box.get("ready"):
            break
        time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("sessiond 没起来")

    yield api_port, f"http://127.0.0.1:{page_port}/form"
    httpd.shutdown()
    proc.kill()


@pytest.fixture
def page_url(live):
    return live[1]


@pytest.fixture
def sess(live):
    web = Webmuxd(user="claudecode")
    s = web.session(id="work", port=live[0], vnc_port=6901)
    yield s
    # sessiond 是模块级共享的,用完把 tab 清掉 —— 不然下一个用例
    # 按标题找 tab 会匹配到上一个用例留下的那个
    for t in s.tabs[1:]:
        try:
            t.close()
        except Exception:
            pass
    s.detach()


# ------------------------------------------------------------- 三个对象

def test_manager_is_an_empty_shell():
    """`Webmuxd()` 不起容器、不占端口 —— 它只是"我要开始管 session 了"。"""
    web = Webmuxd()
    assert web.port is None
    assert web.sessions() == []


def test_session_is_idempotent_and_returns_the_same_object(live):
    """**同一个 id 永远给你同一个 session**,连 Python 对象都是同一个 ——
    每个 Session 背后有一条 WS 和一份内存表,给两个就是两条连接
    (sdk/manager.md §1)。"""
    web = Webmuxd()
    a = web.session(id="work", port=live[0], vnc_port=6901)
    b = web.session(id="work")
    assert a is b
    a.detach()


def test_a_new_id_without_ports_is_refused(live):
    """端口是**部署决定**的,我们不替你分配。"""
    web = Webmuxd()
    with pytest.raises(BadRequest) as ei:
        web.session(id="全新的")
    assert "port" in str(ei.value)


def test_nothing_running_on_that_port_says_so(live):
    web = Webmuxd()
    with pytest.raises(RuntimeUnavailable) as ei:
        web.session(id="没起来的", port=1, vnc_port=2)
    assert ei.value.hint


# --------------------------------------------------------------- tab 句柄

def test_open_returns_a_live_handle(sess, page_url):
    tab = sess.open(page_url)
    assert isinstance(tab, Tab)
    assert tab.title == "结算"
    assert tab.id in [t.id for t in sess.tabs]
    tab.close()


def test_properties_read_memory_not_the_wire(sess, page_url):
    """`tab.url` 是读内存 —— 表在本地,不发请求(sdk/README §3)。"""
    tab = sess.open(page_url)
    calls = []
    orig = sess._t._call
    sess._t._call = lambda *a, **k: (calls.append(a[:2]), orig(*a, **k))[1]
    try:
        _ = tab.url, tab.title, tab.loading, tab.active, tab.index
        assert calls == [], f"读属性发了请求:{calls}"
    finally:
        sess._t._call = orig
        tab.close()


def test_click_feeds_the_memory_back(sess, page_url):
    """`click()` 返回的那一刻 `tab.url` 已经是新的 —— 不用等 WS 追上来。"""
    tab = sess.open(page_url)
    r = tab.click("提交订单")
    assert r.ok
    assert tab.url.startswith("http://"), tab.url
    tab.close()


def test_shortcut_raises_but_act_does_not(sess, page_url):
    """**这是 lib 里唯一一处故意不一致**:写脚本用快捷方法(错了就该炸),
    写 agent 循环用 `act()`(错了要把候选喂回模型)。"""
    tab = sess.open(page_url)
    with pytest.raises(NotFound) as ei:
        tab.click("根本没有这个")
    assert ei.value.candidates, "异常上得带候选"

    r = tab.act([{"type": "click", "text": "根本没有这个"}])
    assert not r.ok and r.candidates, "act() 不该抛,要把候选还回来"
    tab.close()


def test_type_by_label_not_by_content(sess, page_url):
    """`type` 的 text 是**内容**不是定位 —— 规格里踩过(api/act.md §4.1)。"""
    tab = sess.open(page_url)
    tab.type("手机号", "13800000000")
    assert tab.js("document.getElementById('p').value") == "13800000000"
    tab.close()


def test_tab_by_title_is_local_matching(sess, page_url):
    tab = sess.open(page_url)
    assert sess.tab(title="结算").id == tab.id
    with pytest.raises(NotFound):
        sess.tab(title="没有这个标题")
    tab.close()


def test_closed_tab_keeps_its_last_values_but_refuses_actions(sess, page_url):
    """回看一个已经关掉的 tab 最后停在哪,是常见需求(sdk/tab/README §3)。"""
    tab = sess.open(page_url)
    title = tab.title
    tab.close()
    time.sleep(0.3)
    assert tab.closed
    assert tab.title == title, "关掉之后属性该还能读到最后的值"
    with pytest.raises(TabGone):
        tab.goto("about:blank")


# ---------------------------------------------------------------- observe

def test_observation_is_an_object_not_a_dict(sess, page_url):
    """线上是一坨 JSON,这边是个能下标、能 find、能进 prompt 的东西 ——
    这个落差就是"主体在 lib"的样子(works/02 §1)。"""
    tab = sess.open(page_url)
    obs = tab.observe()

    assert len(obs) >= 2
    assert obs[1].role == "button"
    assert obs.find(role="button", name="取消订单").id
    assert '[1] button   "提交订单"' in obs.as_prompt()
    assert obs.page.title == "结算"
    assert obs.screenshot[:4] == b"RIFF"
    assert isinstance(obs.notes, list)
    tab.close()


def test_clicking_an_element_object_binds_the_observation(sess, page_url):
    tab = sess.open(page_url)
    obs = tab.observe()
    r = tab.click(obs.find(role="button", name="提交订单"))
    assert r.ok
    assert tab.js("document.getElementById('out').textContent") == "订单已提交"
    tab.close()


# -------------------------------------------------------------------- 日志

def test_log_carries_note_and_signature(sess, page_url):
    tab = sess.open(page_url)
    tab.act([{"type": "click", "text": "提交订单"}], note="购物车已确认")
    entries = tab.log(kind="action")
    assert entries[-1]["note"] == "购物车已确认"
    assert entries[-1]["user"] == "claudecode", "构造时设的默认署名没跟着走"
    tab.close()


def test_tab_lifecycle_is_queryable_after_the_tab_is_gone(sess, page_url):
    tab = sess.open(page_url)
    tid = tab.id
    tab.close()
    time.sleep(0.3)
    events = [(e["event"], e.get("tab")) for e in sess.log(kind="tab")]
    assert ("opened", tid) in events and ("closed", tid) in events


# -------------------------------------------------------------------- 其它

def test_session_has_no_page_actions(sess, page_url):
    """`sess.click(...)` **故意不给** —— 一个 session 有多个 tab,
    "在哪个 tab 上点"不该靠隐式的当前值(sdk/session.md §2)。"""
    assert not hasattr(sess, "click")
    assert not hasattr(sess, "observe")


def test_status_and_sync(sess, page_url):
    assert sess.status()["ok"] is True
    sess.sync()
    assert not sess.stale
