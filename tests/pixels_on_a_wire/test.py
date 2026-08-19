"""画面是我们自己产的 —— 对着 docs/v2/works/01 · 02 · 03 · 05 校,跑在真 Chromium 上。

交叉验证的姿态和 demo 的 e2e 一样:**不只看我们发了什么,还另开一条 CDP
去读远端页面的真实状态**。不然"点了一下"只能证明我们发出去了,证明不了它落地。
"""

import asyncio
import contextlib
import json

import pytest
from aiohttp.test_utils import TestClient, TestServer

from webmuxd.core.cdp import CDP
from webmuxd.serve.app import build
from webmuxd.serve.session import Session
from webmuxd.view import cursor as cursor_probe
from webmuxd.view.protocol import HEADER_SIZE, parse_header
from webmuxd.view.viewer import ACK_CREDIT, BUFFER

#: 一直在动的页面 —— screencast 只在画面变化时产帧,静止页面测不出流。
MOVING = ("data:text/html," + (
    "<body style='margin:0;font:40px monospace'>"
    "<div id=t></div>"
    "<input id=box><textarea id=area></textarea>"
    "<script>let n=0;setInterval(()=>{t.textContent='F'+(n++);"
    "document.body.style.background='hsl('+(n*7%360)+',70%,85%)'},50);"
    "window.keys=[];addEventListener('keydown',e=>keys.push(e.key));"
    "window.clicks=0;addEventListener('click',()=>clicks++);</script></body>"
).replace(" ", "%20").replace("#", "%23"))

STILL = "data:text/html,<body style='background:%23eef'>still</body>"


@pytest.fixture
async def live(chromium_endpoint, tmp_path):
    """一个真的 session + 它的 HTTP 面,外加一条独立的 CDP 用来交叉验证。"""
    conn = await CDP.connect(chromium_endpoint)
    session = Session(conn, data_dir=tmp_path, human_yield_ms=0)
    await session.start()
    client = TestClient(TestServer(build(session)))
    await client.start_server()
    probe = await CDP.connect(chromium_endpoint)          # 第二条,只用来读真相
    try:
        yield session, client, probe
    finally:
        await probe.close()
        with contextlib.suppress(Exception):
            await client.close()
        await session.close()
        await conn.close()


async def _frames(ws, n, *, timeout=15, ack=True):
    """收 n 帧,返回 (帧字节, 收到的 JSON 消息)。"""
    got, notes = [], []
    async with asyncio.timeout(timeout):
        while len(got) < n:
            msg = await ws.receive()
            if msg.type.name == "BINARY":
                got.append(msg.data)
                if ack:
                    await ws.send_json({"type": "ack"})
            elif msg.type.name == "TEXT":
                notes.append(json.loads(msg.data))
            else:
                break
    return got, notes


async def _open(session, url):
    tab = await session.open_tab(url)
    return tab


# --------------------------------------------------------------------- 画面

async def test_一连上就有画面而且帧头是我们说的那个形状(live):
    session, client, _ = live
    tab = await _open(session, MOVING)
    async with client.ws_connect("/api/view") as ws:
        frames, notes = await _frames(ws, 3)

    hello = next(m for m in notes if m["type"] == "hello")
    assert hello["protocol"] == HEADER_SIZE
    assert hello["writable"] is True

    for f in frames:
        assert len(f) > HEADER_SIZE
        h = parse_header(f)
        # targetId 进头部不是装饰:客户端靠它丢掉切 tab 前的残帧(02 §1)
        assert h["target_id"] == tab.target_id.lower()
        assert f[HEADER_SIZE:HEADER_SIZE + 2] == b"\xff\xd8"      # JPEG 魔数

    ids = [parse_header(f)["frame_id"] for f in frames]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)       # 单调递增


async def test_没人看就不产帧(live):
    session, client, _ = live
    await _open(session, MOVING)
    async with client.ws_connect("/api/view") as ws:
        await _frames(ws, 2)
        assert session.view.stats()["on"] is True
    await asyncio.sleep(0.3)
    # 最后一个观看者走了 —— 整条流停掉。整块屏一直在那儿是 VNC 的毛病(cast.py)
    assert session.view.stats()["on"] is False


# ----------------------------------------------------------------- ack 背压

async def test_不回_ack_的客户端被卡住而正常的那个不受影响(live):
    session, client, _ = live
    await _open(session, MOVING)
    async with client.ws_connect("/api/view") as slow, \
               client.ws_connect("/api/view") as fast:
        got_fast, _ = await _frames(fast, 6)                      # 这个照常回 ack

        got_slow = []
        with contextlib.suppress(asyncio.TimeoutError):
            async with asyncio.timeout(2):
                while True:
                    m = await slow.receive()
                    if m.type.name == "BINARY":
                        got_slow.append(m.data)                   # **故意不 ack**

    assert len(got_fast) >= 6
    # 额度 2 + 缓冲 3 —— 卡住的那个最多就这些,再多它也拿不到(02 §2)
    assert len(got_slow) <= ACK_CREDIT + BUFFER


# ------------------------------------------------------------ active 与切 tab

async def test_active_就是_screencast_挂在哪个_target_上(live):
    session, client, _ = live
    a = await _open(session, MOVING)
    b = await _open(session, MOVING)
    async with client.ws_connect("/api/view") as ws:
        await _frames(ws, 2)
        assert session.view.stats()["tab"] == session.tabs.active == b.id

        await ws.send_json({"type": "tab", "id": a.id})
        # 切过去之后,帧头里的 targetId 必须变成 a —— 而不是"我们记了一笔账"
        async with asyncio.timeout(15):
            while True:
                m = await ws.receive()
                if m.type.name != "BINARY":
                    continue
                await ws.send_json({"type": "ack"})
                if parse_header(m.data)["target_id"] == a.target_id.lower():
                    break
    assert session.tabs.active == a.id


async def test_后台_tab_不产帧(live):
    session, client, _ = live
    await _open(session, MOVING)          # 这个会被挤到后台
    front = await _open(session, STILL)
    async with client.ws_connect("/api/view") as ws:
        frames, _ = await _frames(ws, 1, timeout=15)
        assert frames
        # 前台是那个静止页,后台那个一直在动 —— 如果后台也产帧,
        # 这里会收到大量帧。收不到才对(05 §2 实测)
        n = 0
        with contextlib.suppress(asyncio.TimeoutError):
            async with asyncio.timeout(2):
                while True:
                    m = await ws.receive()
                    if m.type.name == "BINARY":
                        n += 1
                        await ws.send_json({"type": "ack"})
        assert n <= 3, f"静止的前台不该一直产帧,收到 {n} 帧"
    assert session.tabs.active == front.id


# --------------------------------------------------------------------- 输入

async def test_点击落在远端页面上(live):
    session, client, probe = live
    tab = await _open(session, MOVING)
    sid = (await probe.send("Target.attachToTarget",
                            {"targetId": tab.target_id, "flatten": True}))["sessionId"]
    async with client.ws_connect("/api/view") as ws:
        await _frames(ws, 2)
        await ws.send_json({"type": "mouse", "event": "down", "x": 60, "y": 40,
                            "button": 0, "buttons": 1, "clicks": 1})
        await ws.send_json({"type": "mouse", "event": "up", "x": 60, "y": 40,
                            "button": 0, "buttons": 0, "clicks": 1})
        await asyncio.sleep(0.5)

    r = await probe.send("Runtime.evaluate",
                         {"expression": "window.clicks", "returnByValue": True},
                         session_id=sid)
    assert r["result"]["value"] >= 1


async def test_打字进得去而且页面收到的是真实_keydown(live):
    session, client, probe = live
    tab = await _open(session, MOVING)
    sid = (await probe.send("Target.attachToTarget",
                            {"targetId": tab.target_id, "flatten": True}))["sessionId"]
    await probe.send("Runtime.evaluate", {"expression": "box.focus()"}, session_id=sid)

    async with client.ws_connect("/api/view") as ws:
        await _frames(ws, 2)
        for ch in "hi":
            await ws.send_json({"type": "key", "event": "down", "key": ch, "code": "Key" + ch.upper()})
            await ws.send_json({"type": "key", "event": "up", "key": ch, "code": "Key" + ch.upper()})
        await asyncio.sleep(0.5)

    val = (await probe.send("Runtime.evaluate",
                            {"expression": "box.value", "returnByValue": True},
                            session_id=sid))["result"]["value"]
    keys = (await probe.send("Runtime.evaluate",
                             {"expression": "JSON.stringify(window.keys)",
                              "returnByValue": True},
                             session_id=sid))["result"]["value"]
    assert val == "hi"
    # **这一项就是 03 §2 那张表**:insertText 也能让 value 变成 hi,
    # 但页面收不到 keydown,监听按键的站点就废了
    assert json.loads(keys) == ["h", "i"]


async def test_中文走_insertText_一次送最终文本(live):
    session, client, probe = live
    tab = await _open(session, MOVING)
    sid = (await probe.send("Target.attachToTarget",
                            {"targetId": tab.target_id, "flatten": True}))["sessionId"]
    await probe.send("Runtime.evaluate", {"expression": "box.focus()"}, session_id=sid)

    async with client.ws_connect("/api/view") as ws:
        await _frames(ws, 2)
        await ws.send_json({"type": "text", "text": "提交订单"})
        await asyncio.sleep(0.5)

    val = (await probe.send("Runtime.evaluate",
                            {"expression": "box.value", "returnByValue": True},
                            session_id=sid))["result"]["value"]
    assert val == "提交订单"


async def test_只读连接的输入被服务端丢掉(live, monkeypatch):
    session, client, probe = live
    tab = await _open(session, MOVING)
    sid = (await probe.send("Target.attachToTarget",
                            {"targetId": tab.target_id, "flatten": True}))["sessionId"]
    token = session.mint_token(read_only=True, ttl_s=60)

    async with client.ws_connect(f"/api/view?t={token}") as ws:
        _, notes = await _frames(ws, 2)
        hello = next(m for m in notes if m["type"] == "hello")
        assert hello["writable"] is False
        await ws.send_json({"type": "mouse", "event": "down", "x": 60, "y": 40,
                            "button": 0, "buttons": 1, "clicks": 1})
        await ws.send_json({"type": "text", "text": "不该进去"})
        await asyncio.sleep(0.5)

    clicks = (await probe.send("Runtime.evaluate",
                               {"expression": "window.clicks", "returnByValue": True},
                               session_id=sid))["result"]["value"]
    val = (await probe.send("Runtime.evaluate",
                            {"expression": "box.value", "returnByValue": True},
                            session_id=sid))["result"]["value"]
    # **服务端丢弃,不是前端把按钮变灰**(04 §3)—— 只读连接照样收得到帧
    assert clicks == 0 and val == ""


# --------------------------------------------------------------------- 光标

def test_光标值必须过白名单():
    assert cursor_probe.sanitize("pointer") == "pointer"
    assert cursor_probe.sanitize("TEXT") == "text"
    # 远端页面不可信:url(...) 原样透传等于让它指使客户端去拉任意 URL(03 §5)
    assert cursor_probe.sanitize("url(https://evil.example/x.png), auto") == "default"
    assert cursor_probe.sanitize("") == "default"


# ------------------------------------------------------------- ack 按帧号记账

def _stub_viewer():
    sent: list[bytes] = []

    async def send_bytes(b: bytes) -> None:
        sent.append(b)

    async def send_json(_o: dict) -> None:
        pass

    from webmuxd.view.viewer import Viewer
    return Viewer(send_bytes, send_json, writable=True), sent


async def test_漏一个_ack_不会让后面的_rtt_全错位():
    """**按帧号查表,不是弹最旧的那个时间戳。**

    弹最旧的写法在漏掉一个 ack 之后会永久错位:之后每个 RTT 都算成上一帧的,
    而且不会自愈([09 §6.3](../../docs/v2/works/09-wire-format.md))。
    """
    v, sent = _stub_viewer()
    await v.offer(b"f1", 1)
    await v.offer(b"f2", 2)
    assert len(sent) == 2 and v.credit == 0

    # 客户端只回了第 2 帧的 ack —— 第 1 帧的那个漏了(比如解码失败)
    rtt2 = await v.on_ack(2)
    assert rtt2 is not None

    await v.offer(b"f3", 3)
    rtt3 = await v.on_ack(3)
    assert rtt3 is not None, "第 3 帧该算得出 RTT"
    # 关键:第 1 帧那条记录还挂着,但**没有被错当成第 3 帧的**
    assert 1 in v._sent_at, "漏掉的那条不该被别人顶掉"


async def test_未知帧号的_ack_照样恢复额度():
    """这就是"3 秒补一个 ack"能解开死锁的原因(09 §6.4)。

    心跳补的那一发,帧号多半已经 ack 过了 —— **算不出 RTT 无所谓,
    额度必须回来**,否则丢一帧就是永久卡死。
    """
    v, sent = _stub_viewer()
    await v.offer(b"f1", 1)
    await v.offer(b"f2", 2)
    assert v.credit == 0, "额度用光了"

    rtt = await v.on_ack(99999)          # 谁都不认识的号
    assert rtt is None, "对不上就别算 RTT,不能污染窗口"
    assert v.credit == 1, "额度必须无条件恢复 —— 这是防死锁那一条"

    await v.offer(b"f3", 3)
    assert len(sent) == 3, "额度回来了就该能继续发"


async def test_没额度时缓冲留最新那帧_并且帧号跟着走():
    v, sent = _stub_viewer()
    await v.offer(b"f1", 1)
    await v.offer(b"f2", 2)              # 额度用光
    for i in (3, 4, 5):
        await v.offer(f"f{i}".encode(), i)

    await v.on_ack(1)
    assert sent[-1] == b"f5", "缓冲里该只取最新那帧"
    # 而且它的帧号要记对,否则下一个 ack 又对不上
    assert 5 in v._sent_at and 3 not in v._sent_at


async def test_真链路上回显帧号之后算得出_rtt(live):
    session, client, _ = live
    await _open(session, MOVING)
    async with client.ws_connect("/api/view") as ws:
        # _frames 里的 ack 是裸的 {"type":"ack"} —— 这里手动带上帧号
        got = 0
        async with asyncio.timeout(15):
            while got < 3:
                m = await ws.receive()
                if m.type.name == "BINARY":
                    got += 1
                    await ws.send_json({"type": "ack",
                                        "frameId": parse_header(m.data)["frame_id"]})
        await asyncio.sleep(0.3)
        stats = session.view.stats()["viewers"][0]
        assert stats["rtt_ms"] is not None, "带了帧号就该算得出 RTT"


# --------------------------------------------------------- RTT 自适应降质

async def test_链路慢了会降质_而且降的过程进_scrollback(live, monkeypatch):
    """**这套逻辑本机验不到,除非把阈值挪到本机 RTT 之下。**

    02 §3 一直写着"想验证它必须人为加延迟"—— 换个做法:把阈值搬下来,
    死区仍然保留(`FAST < SLOW`),就能在本机跑出真实的降级路径。
    """
    from webmuxd.view import quality
    # 压到任何真实 RTT 都必然高于它 —— 进程内的 WS 往返只有零点几毫秒,
    # 阈值设在 0.5 会卡在边界上,用例就飘了。**死区仍然留着**(FAST < SLOW)。
    monkeypatch.setattr(quality, "SLOW_MS", 0.0001)
    monkeypatch.setattr(quality, "FAST_MS", 0.00001)
    monkeypatch.setattr(quality, "THROTTLE_S", 0.2)

    session, client, _ = live
    await _open(session, MOVING)
    seen = []
    async with client.ws_connect("/api/view") as ws:
        n = 0
        with contextlib.suppress(asyncio.TimeoutError):
            async with asyncio.timeout(20):
                while n < 40:
                    m = await ws.receive()
                    if m.type.name == "BINARY":
                        n += 1
                        await ws.send_json({
                            "type": "ack",
                            "frameId": parse_header(m.data)["frame_id"]})
                    elif m.type.name == "TEXT":
                        d = json.loads(m.data)
                        if d["type"] == "quality":
                            seen.append(d["quality"])
                    if len(seen) >= 3:
                        break

    assert seen, "链路判为慢了却一直不降质"
    # **先砍画质,砍到底才抽帧** —— 糊一点的连续画面比清晰的卡顿画面可用得多
    assert seen == sorted(seen, reverse=True), f"该单调下降,实际 {seen}"
    assert seen[0] == 60, f"第一步该是 80-20=60,实际 {seen[0]}"

    # **降质要能事后查到**,不能只刷一下状态栏
    rows = [e for e in session.log.read(limit=50, kind="session")
            if e.get("event") == "quality_changed"]
    assert rows, "scrollback 里没有降质记录"
    assert rows[0]["direction"] == "down" and "rtt_ms" in rows[0]


async def test_死区防的是来回震荡():
    """`FAST < SLOW` 之间那段是**故意留的**。

    没有死区(两个条件能同时成立)的话,一个在阈值附近的链路会一直升降,
    画质来回变 —— 比一直糊更难受。
    """
    from webmuxd.view.quality import Adaptor, FAST_MS, SLOW_MS
    assert FAST_MS < SLOW_MS, "死区没了,两边会同时成立"

    a = Adaptor(80)
    mid = (FAST_MS + SLOW_MS) / 2          # 落在死区里
    for _ in range(10):
        assert a.feed(mid) is None, "死区里不该动"
    assert a.quality == 80


async def test_画质有下限_到底了改抽帧():
    """**q5 是马赛克,根本没法用。**

    降质的意义是"糊一点但还能操作",不是"糊到看不清" —— 而 20 → 5 是个断崖。
    默认下限 25 有出处:BrowserBox 自己在 Tor 模式下就压到 25
    ([01 §4](../../docs/v2/works/01-frame-source.md))。
    """
    from webmuxd.view.quality import Adaptor, QUALITY_FLOOR
    assert QUALITY_FLOOR == 25

    a = Adaptor(80)
    path = [80]
    for _ in range(8):
        a._last_down = 0
        a._down()
        if a.quality != path[-1]:
            path.append(a.quality)
    assert path == [80, 60, 40, 25], path
    assert a.every_nth > 1, "画质到底了就该改抽帧,不能停在那儿不动"


async def test_下限可配_而且不能高过上限():
    from webmuxd.view.quality import Adaptor
    a = Adaptor(80, floor=40)
    for _ in range(6):
        a._last_down = 0
        a._down()
    assert a.quality == 40

    # 下限高过上限的话它会在两头之间反复横跳 —— 夹住
    assert Adaptor(50, floor=90).floor == 50


SECRET_FORM = ("data:text/html;charset=utf-8,"
               "<label for=p>Password</label>"
               "<input type=password id=p name=passwd placeholder=Enter>")


async def test_人的动作进日志_但密码不进(live):
    """**实测漏过。**

    页面里那个输入探针原来报的是 `innerText || value`,而 `value` 在密码框上
    就是明文密码 —— 它会被写进 `log.jsonl`,`webmuxd log` 打得出来、
    `log/bundle` 打包带得走。[log.py](../../webmuxd/core/log.py) 的注释写着
    "明文不该走到这儿",但那条掩码只管 API 那条路,**人从画面进来的这条绕过去了**。

    控件的身份是它的**标签**,不是它的内容。
    """
    session, client, probe = live
    tab = await _open(session, SECRET_FORM)
    sid = (await probe.send("Target.attachToTarget",
                            {"targetId": tab.target_id, "flatten": True}))["sessionId"]
    await probe.send("Runtime.evaluate",
                     {"expression": "document.getElementById('p').value='hunter2SECRET'"},
                     session_id=sid)
    await asyncio.sleep(0.6)                 # 躲开"这是我们刚发的那一下"那个窗口

    async with client.ws_connect("/api/view") as ws:
        await ws.send_json({"type": "mouse", "event": "down", "x": 80, "y": 12,
                            "button": 0, "buttons": 1, "clicks": 1})
        await ws.send_json({"type": "mouse", "event": "up", "x": 80, "y": 12,
                            "button": 0, "buttons": 0, "clicks": 1})
        await asyncio.sleep(0.6)
        await ws.send_json({"type": "key", "event": "down", "key": "X", "code": "KeyX"})
        await asyncio.sleep(1.0)

    entries = session.log.read(limit=60, user="human")
    assert entries, "人的动作一条都没进日志 —— 那条流就只剩 API 干过的事了"
    blob = json.dumps(entries, ensure_ascii=False)
    assert "hunter2SECRET" not in blob, f"密码明文进日志了:{blob[:300]}"


def test_探针不许去读表单控件的_value():
    """不依赖跑浏览器的那一半 —— **永远会跑**。"""
    from webmuxd.core import shim
    js = shim.HUMAN_INPUT_JS
    assert "e.target.value" not in js and "el.value" not in js, \
        "输入探针又去读 value 了 —— 密码框上那就是明文"
    assert "aria-label" in js and "placeholder" in js, "得从标签取控件身份"
