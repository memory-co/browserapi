"""Python lib —— 对着 docs/v1/sdk/ 校,打到真 sessiond 上。

lib 是**同步**的(sdk/README §6),所以 sessiond 跑在后台线程里,
测试从主线程用同步 API 调它 —— 跟真实用法一样。
"""

import asyncio
import threading
import time

import pytest

from webmuxd import Tab, Webmuxd
from webmuxd.cdp import CDP
from webmuxd.exceptions import BadRequest, NotFound, RuntimeUnavailable, TabGone
from webmuxd.serve import build
from webmuxd.sessions import Server


def _one(session, sid: str = "work"):
    """一个只装着这一个 session 的 server。

    **测试也走 `/s/<id>/`** —— 那是真实的地址形状,绕过它就等于不测路由
    ([k §4](../../docs/v2/works/k-one-server.md#4-路由s-id-前缀))。
    """
    import atexit
    import shutil
    import tempfile

    root = tempfile.mkdtemp(prefix="wm-srv-")
    # **用完就收。** 不收只是攒着,直到有人发现 /tmp 里几百个 `wm-*` —— 真发生过
    atexit.register(shutil.rmtree, root, True)
    srv = Server(data_root=root)
    srv.adopt(sid, session)
    return srv
from webmuxd.sessions import Session as CoreSession


def _free_port() -> int:
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

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
    import shutil, socket, subprocess, os, contextlib, tempfile

    chromium = shutil.which("chromium-browser") or shutil.which("chromium")
    if not chromium:
        pytest.skip("没有 chromium")

    def free():
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    cdp_port, api_port, page_port = free(), free(), free()
    work = tempfile.mkdtemp(prefix="wm-lib-")

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
         f"--user-data-dir={work}/profile", "about:blank"],
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
            sess = CoreSession(cdp, data_dir=f"{work}/data",
                               human_yield_ms=0)
            await sess.start()
            runner = aioweb.AppRunner(build(_one(sess)))
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
    shutil.rmtree(work, ignore_errors=True)      # 用完就收


@pytest.fixture
def page_url(live):
    return live[1]


@pytest.fixture
def sess(live):
    # **端口在 Webmuxd 上,不在 session 上**(k)
    web = Webmuxd(port=live[0], user="claudecode")
    s = web.session(id="work")
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

def test_端口在_manager_上_不在_session_上(live):
    """**一个 server 一个口**([k](../../docs/v2/works/k-one-server.md))。

    以前是 `web.session(id=, port=)` —— 那是 kasm 留下的:它的 web 口
    不归我们控制,只能一个 session 一个。画面自己产之后那条硬约束没了。
    """
    web = Webmuxd(port=live[0])
    assert web.base == f"http://127.0.0.1:{live[0]}"
    # 旧写法**不静默吞** —— 落进 **kw 会被无声丢掉,然后报一个指向别处的错
    with pytest.raises(BadRequest) as ei:
        web.session(id="work", port=live[0])
    assert "Webmuxd(port=" in str(ei.value)


def test_session_is_idempotent_and_returns_the_same_object(live):
    """**同一个 id 永远给你同一个 session**,连 Python 对象都是同一个 ——
    每个 Session 背后有一条 WS 和一份内存表,给两个就是两条连接
    (sdk/manager.md §1)。"""
    web = Webmuxd(port=live[0])
    a = web.session(id="work")
    b = web.session(id="work")
    assert a is b
    a.detach()


def test_没有_server_就说没有_不猜一个(live):
    """**server 不按需自启。** tmux 能自启是因为它用 socket 没端口要挑;
    我们有,而那条规矩是"端口由你给"(h §6)。"""
    from webmuxd.exceptions import ChromeGone
    web = Webmuxd(port=_free_port())          # 那个口上什么都没有
    with pytest.raises(ChromeGone):
        web.list()


def test_起不来的_session_要说清并且给_hint(live):
    """runtime 自己起不来 —— 这条要给 hint,而且**要跨过 HTTP 传回来**。"""
    web = Webmuxd(port=live[0])
    with pytest.raises(RuntimeUnavailable) as ei:
        web.session(id="没端点的", runtime="remote")
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


# ------------------------------------------------------------------ 读一眼

def test_读一眼只有两样(sess, page_url):
    """**一张图,和正文。** 以前这儿是 `tab.observe()` 回一整包东西 ——
    砍了([capture.py](../../webmuxd/capture.py))。"""
    tab = sess.open(page_url)
    assert tab.screenshot()[:4] == b"RIFF"
    assert "提交订单" in tab.text()
    tab.close()


def test_按人看得见的文字点(sess, page_url):
    """**定位就是"人看得见的那几个字"。** 没有"先观测拿编号,再按编号点" ——
    编号只在一次快照里成立,而快照现在是 act 自己抓的、不对外
    ([locate.resolve](../../webmuxd/locate.py))。"""
    tab = sess.open(page_url)
    r = tab.click("提交订单")
    assert r.ok
    assert tab.js("document.getElementById('out').textContent") == "订单已提交"
    tab.close()


def test_歧义回候选_候选够拿来重试(sess, page_url):
    """**定位失败不是异常,是候选**(i §2②)。而候选要带着
    `role` + `name` —— 那是**跨快照仍然成立**的说法,编号不是。"""
    from webmuxd import NotFound

    tab = sess.open(page_url)
    try:
        tab.click("订单")            # 提交订单 / 取消订单,两个都含"订单"
    except NotFound as e:
        cands = e.details.get("candidates") or []
        assert len(cands) >= 2, cands
        assert all("role" in c and "name" in c for c in cands), cands
        # 拿候选直接重试:_locator 只取 role + name
        assert tab.click(cands[0]).ok
    else:
        raise AssertionError("两个都含「订单」,该报歧义")
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
    assert not hasattr(sess, "screenshot")


def test_status_and_sync(sess, page_url):
    assert sess.status()["ok"] is True
    sess.sync()
    assert not sess.stale
