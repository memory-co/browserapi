"""DOM 那条画面([c §5](../../docs/v2/works/c-view.md#5-第三条rrweb--它不传像素))。

这一套全是**不依赖浏览器**的:资源地址改写、事件缓冲怎么砍、注入守卫。
跑真浏览器那部分在别处 —— 但这几条是可以钉死的,而且它们各自都有过
"不报错、只是不工作"的前科。
"""

import json

from webmuxd.rrweb import MAX_EVENTS, RECORD_JS, DomSource


def _src():
    return DomSource()


# --------------------------------------------------------- 资源地址改写

def test_资源地址改写成走我们_观看端不回原站():
    """**观看端自己回原站拉是靠不住的。** 要登录的站、认 Referer 的 CDN
    全是破图 —— 实测某视频站一页 30 张图破 25 张(c §5.3)。"""
    d = _src()
    ev = {"type": 2, "data": {"node": {
        "tagName": "img", "attributes": {"src": "https://cdn.example.com/a.png"}}}}
    out = json.loads(d._rewrite(json.dumps(ev)))
    # **相对地址,前面没有斜杠。** 转发那条路由在 `/s/{sid}/api/res` 下,
    # 写成根路径 `/api/res` 的话**每一个资源都 404**(实测百度首页 25 个
    # 请求 0 成功),而重放出来的树节点数、文字、标题全都对 —— 只有样式和图没了。
    assert out["data"]["node"]["attributes"]["src"].startswith("api/res?u=")
    assert "cdn.example.com" in out["data"]["node"]["attributes"]["src"]


def test_只改资源地址_不动别的():
    """**`<a href>` 不能改。** 改了的话点链接会跳到我们的转发口上。"""
    d = _src()
    ev = {"type": 2, "data": {"node": {
        "tagName": "a", "attributes": {"href": "https://example.com/page"}}}}
    out = json.loads(d._rewrite(json.dumps(ev)))
    assert out["data"]["node"]["attributes"]["href"] == "https://example.com/page"
    # 而 <link href> 是资源,要改
    ev2 = {"type": 2, "data": {"node": {
        "tagName": "link", "attributes": {"href": "https://x.com/a.css"}}}}
    out2 = json.loads(d._rewrite(json.dumps(ev2)))
    assert out2["data"]["node"]["attributes"]["href"].startswith("api/res?u=")


def test_data_和_blob_不动():
    """`data:` 已经是内容本身,`blob:` 在别处根本不存在 —— 改了只会变破图。"""
    d = _src()
    for url in ("data:image/png;base64,AAA", "blob:https://x.com/abc", "/local.png"):
        ev = {"type": 2, "data": {"node": {"tagName": "img", "attributes": {"src": url}}}}
        out = json.loads(d._rewrite(json.dumps(ev)))
        assert out["data"]["node"]["attributes"]["src"] == url, url


def test_css_里的_url_也要改():
    d = _src()
    ev = {"type": 2, "data": {"node": {"tagName": "div", "attributes": {
        "style": "background:url(https://cdn.x.com/bg.jpg) no-repeat"}}}}
    out = json.loads(d._rewrite(json.dumps(ev)))
    assert "api/res?u=" in out["data"]["node"]["attributes"]["style"]


def test_按结构走_不拿正则扫整串():
    """**正文里长得像地址的文字不能被改。** 正则扫整串会误伤 ——
    用户打的字、页面上的说明,里面出现一个 http 就被改写掉。"""
    d = _src()
    ev = {"type": 3, "data": {"texts": [
        {"id": 7, "value": "去 https://example.com/a.png 看看"}]}}
    out = json.loads(d._rewrite(json.dumps(ev)))
    assert out["data"]["texts"][0]["value"] == "去 https://example.com/a.png 看看"


def test_srcset_每一项都改_但描述符留着():
    d = _src()
    ev = {"type": 2, "data": {"node": {"tagName": "img", "attributes": {
        "srcset": "https://x.com/a.png 1x, https://x.com/b.png 2x"}}}}
    out = json.loads(d._rewrite(json.dumps(ev)))
    v = out["data"]["node"]["attributes"]["srcset"]
    assert v.count("api/res?u=") == 2
    assert "1x" in v and "2x" in v          # 描述符不能丢,丢了浏览器选错图


# ------------------------------------------------------------- 事件缓冲

def test_砍历史必须从一张全量快照砍起():
    """**从中间砍等于把增量链断在半路** —— 重放出来的 DOM 从此和真页面
    不一致,而且不自恢复、不报错(c §5.5)。"""
    d = _src()
    d.events = [json.dumps({"type": 3, "i": i}) for i in range(MAX_EVENTS)]
    # 后半段塞一张全量快照
    cut = int(MAX_EVENTS * 0.7)
    d.events[cut] = json.dumps({"type": 4, "meta": True})
    d._trim()
    assert json.loads(d.events[0])["type"] == 4, "第一条必须是全量快照"
    assert len(d.events) == MAX_EVENTS - cut


def test_没有可切的点就宁可留着_不乱砍():
    """砍不掉总比砍错好 —— 砍错是静默的错,留着只是占内存。"""
    d = _src()
    d.events = [json.dumps({"type": 3, "i": i}) for i in range(MAX_EVENTS)]
    before = len(d.events)
    d._trim()
    assert len(d.events) == before


def test_meta_一到就重新开始攒():
    """新的一页 = 新的一条增量链。**旧的必须全丢** ——
    拿旧链上的增量去改新页的 DOM,改出来的是一棵没人见过的树。"""
    d = _src()
    d._on_binding({"name": "__wm_dom_emit", "payload": json.dumps({"type": 3})}, None)
    d._on_binding({"name": "__wm_dom_emit", "payload": json.dumps({"type": 3})}, None)
    d._on_binding({"name": "__wm_dom_emit", "payload": json.dumps({"type": 4})}, None)
    assert len(d.events) == 1 and json.loads(d.events[0])["type"] == 4


# --------------------------------------------------------------- 注入守卫

def test_注入脚本要挡住自己造的_iframe():
    """**记录器自己会造 about:blank iframe,而注入对每个新文档生效** ——
    被注入的 iframe 又造 iframe,实测每秒新建二十来个,主页面的全量快照
    直接被饿死。这两道守卫是必须的,不是优化。"""
    assert "window.top !== window" in RECORD_JS, "得挡住 iframe"
    assert "https?:" in RECORD_JS, "得挡住 about:blank"
    assert "__wm_dom" in RECORD_JS, "同一个文档只录一次"


def test_页面里抛的错要报出来_不能吞():
    """吞掉的表现是"DOM 模式画面永远不出来",和"页面没动"分不清。"""
    d = _src()
    d._on_binding({"name": "__wm_dom_emit",
                   "payload": json.dumps({"type": -1, "err": "boom"})}, None)
    assert d.events == [], "出错那条不该进缓冲"


# ------------------------------------------------- 自己那条通道(e §6.1)

def test_事件发给通道上的每一个观看者():
    """一条数据一条路 —— 事件只往 `/channel/rrweb` 的订阅者发。"""
    import asyncio

    d = _src()
    got: list[dict] = []

    async def sink(m):
        got.append(m)

    async def run():
        d.listeners.add(sink)
        d._on_binding({"name": "__wm_dom_emit",
                       "payload": json.dumps({"type": 4})}, None)
        await asyncio.sleep(0)          # 让 create_task 跑起来
        await asyncio.sleep(0)

    asyncio.run(run())
    assert [m["type"] for m in got] == ["dom"]


def test_新来的从最近一张全量快照接上_不从半路接():
    """**从半路接重放出来的是一棵错的 DOM,而且不报错**(c §5.5)。"""
    d = _src()
    for ev in ({"type": 4}, {"type": 2}, {"type": 3}, {"type": 3}):
        d._on_binding({"name": "__wm_dom_emit", "payload": json.dumps(ev)}, None)
    first = json.loads(d.snapshot_for_new_viewer()[0])
    assert first["type"] == 4, "补发的第一条必须是 Meta"


def test_这条通道不承载输入_是结构上没有_不是过滤():
    """**输入永远只走 /channel/cdp**(b §1)。

    这里查的不是"有没有过滤",是**这个 handler 里根本没有接收端** ——
    过滤是黑名单模型,漏一类就是一个缺口;没有接收端才是收口。
    """
    import inspect

    from webmuxd import serve as app

    src = inspect.getsource(app.h_rrweb)
    assert "handle_input" not in src and "view.switch" not in src
    # 收到的消息除了判断断开,不做任何事
    assert "读完就丢" in src


def test_不是_dom_模式时这条通道要明说没有_并且说清怎么才有():
    import inspect

    from webmuxd import serve as app

    src = inspect.getsource(app.h_rrweb)
    assert "--transport dom" in src, "得说清怎么才能有这条通道"


def test_内置页不往这条通道发东西():
    """**只读要在客户端也是结构性的。**

    不是"发之前判断一下" —— 那个文件里根本没有发送函数
    (`tests/two_implementations/` 里还有一条一模一样的,两边都守)。
    """
    import pathlib
    import re

    ch = pathlib.Path("webmuxjs/client/src/channel/rrweb.ts").read_text()
    code = re.sub(r"//.*", "", re.sub(r"/\*.*?\*/", "", ch, flags=re.S))
    assert ".send(" not in code, "这条通道上不该有上行"

    main = pathlib.Path("webmuxjs/client/src/viewer/session-view.ts").read_text()
    assert "/channel/rrweb" in main, "内置页得连这条通道"


# --------------------------------------------- 记录器从哪来(d §2)

def test_版本钉死_不用_latest():
    """**`@latest` 意味着两台机器可能拿到不同版本。**

    而记录器和观看端的重放器必须是同一版 —— 对不上的表现是
    "画面局部不更新"且不报错。这正是 d 篇那条"同一条命令在两台机器上
    结果不同"要防的事。
    """
    from webmuxd import rrweb as dom

    assert "@latest" not in dom.RRWEB_URL
    assert dom.RRWEB_VERSION in dom.RRWEB_URL
    assert dom.RRWEB_VERSION in dom.RRWEB_CSS
    # 缓存目录带上版本 —— 换版本时不会读到上一版留下的文件
    assert dom.RRWEB_VERSION in str(dom.CACHE)


def test_ready_只探不下():
    """**探测不该有副作用。** `ready()` 走网络的话,
    `webmuxd status` 这种只读命令会莫名其妙卡住。"""
    import inspect

    from webmuxd import rrweb as dom

    src = inspect.getsource(dom.ready)
    assert "urlopen" not in src and "download" not in src


def test_没下过时报错要指向_install_不能偷偷下():
    """**起 session 的时候现下,离线的机器要到那一刻才知道。**

    而 install 存在的意义正是"一次探清楚,之后不再猜"(d)。
    """
    import inspect

    from webmuxd import rrweb as dom

    src = inspect.getsource(dom._read)
    assert "webmuxd install" in src, "得告诉人去跑 install"
    assert "urlopen" not in src, "运行时不该偷偷下"


def test_记录器和观看端用的是同一份文件():
    """两边版本对不上的表现是"画面局部不更新"且不报错 —— 所以只有一份。"""
    import inspect

    from webmuxd import rrweb as dom

    assert inspect.getsource(dom.viewer_js).count("_read(\"js\")") == 1
    assert inspect.getsource(dom.recorder_js).count("_read(\"js\")") == 1


def test_install_会把它下下来_并记进路径表():
    import inspect

    from webmuxd.install import install

    src = inspect.getsource(install)
    assert "dom_mod.download()" in src, "install 得负责下"
    assert "facts.rrweb = models.RrwebFact" in src, \
        "得记进路径表,否则没人知道装的是哪一版"
    # 下不到只影响一种画面,得说清楚 —— 不能让人以为整个装挂了
    assert "jpg / vnc 不受影响" in src


def test_rrweb_是路径表认得的键():
    from webmuxd import config

    assert "rrweb" in config.KEYS


# ------------------------------------------- binding 那条(issues/dom-binding-不活过导航)

class _FakeCDP:
    """记下发过哪些命令,别的什么都不做。"""

    def __init__(self):
        self.sent = []
        self.subs = {}

    async def send(self, method, params=None, *, session_id=None, **kw):
        self.sent.append((method, params or {}, session_id))
        return {}

    def on(self, method, fn):
        self.subs.setdefault(method, []).append(fn)
        return lambda: None

    def methods(self):
        return [m for m, _p, _s in self.sent]


async def test_arm_要先开_runtime_域():
    """**"命令成功"不等于"事件会来"。**

    `Runtime.bindingCalled` 只在这个域开着的时候才推。不开的话:
    `addBinding` 照样成功、页面里那个函数照样在、页面照样调它 ——
    **而服务端一条都收不到,还不报错**
    (issues/dom-binding-不活过导航.md ①)。
    """
    from webmuxd import rrweb

    src = rrweb.DomSource()
    cdp = _FakeCDP()
    await src.arm(cdp, "sid-1")
    ms = cdp.methods()
    assert "Runtime.enable" in ms, "没开 Runtime 域 —— 页面发什么都到不了"
    assert ms.index("Runtime.enable") < ms.index("Runtime.addBinding"), \
        "要先开域再装 binding"


async def test_每个新文档都要补一次_binding():
    """**binding 每次导航都没了。**

    实测:导航前 `typeof window.__wm_dom_emit === "function"`,
    导航后 `undefined` —— 而记录器照跑,emit 全抛进黑洞。
    所以要订 `Runtime.executionContextCreated`,一个新上下文补一次。
    """
    import asyncio

    from webmuxd import rrweb

    src = rrweb.DomSource()
    cdp = _FakeCDP()
    await src.arm(cdp, "sid-1")
    assert "Runtime.executionContextCreated" in cdp.subs, "没订新上下文"

    await asyncio.sleep(0.05)          # arm 里那个补注入是异步的,等它落完
    cdp.sent.clear()
    for fn in cdp.subs["Runtime.executionContextCreated"]:
        fn({"context": {"id": 2}}, "sid-1")
    await asyncio.sleep(0.05)
    assert ("Runtime.addBinding", {"name": rrweb.BINDING}, "sid-1") in cdp.sent, \
        "新文档来了没补 binding"


async def test_别的_tab_的新上下文不乱补():
    import asyncio

    from webmuxd import rrweb

    src = rrweb.DomSource()
    cdp = _FakeCDP()
    await src.arm(cdp, "sid-1")
    await asyncio.sleep(0.05)          # arm 里那个补注入是异步的,等它落完
    cdp.sent.clear()
    for fn in cdp.subs["Runtime.executionContextCreated"]:
        fn({"context": {"id": 9}}, "别的-tab")
    await asyncio.sleep(0.05)
    assert not cdp.sent, "给没装过记录器的 tab 也补了 binding"


def test_binding_还没到时先攒着_不静默丢():
    """**那个 `catch (_) {}` 是这条链路上最贵的一行。**

    页面脚本是 document-start 的,**必然比服务端补 binding 早** ——
    直接发就是必丢。而丢了不报错,表现和"页面没动"一模一样。
    """
    from webmuxd import rrweb

    import re

    js = rrweb.RECORD_JS
    code = re.sub(r"//.*", "", js)      # 注释里提到那行不算
    assert "catch (_) {}" not in code, "又把发送失败吞掉了"
    assert "pend.push" in code and "typeof send !== \"function\"" in code, \
        "binding 没到的时候得先攒着"
    # **满了整个丢,不从中间截** —— 增量链断在中间,重放出来的 DOM 从此是错的
    assert "pend.length = 0" in code and "pend.splice" not in code
    assert "lost" in code, "丢过要说出来,不能悄悄丢"


def test_不录鼠标_重放里就不会多出一个指针():
    """**画面上不该有两个光标。**

    rrweb 会照着录下来的鼠标轨迹画一个自己的指针出来,而人自己的光标
    本来就在那儿。实测:一个 20x20 的鬼影,跟着人的鼠标从画面这头跑到那头。

    从源头关 —— 鼠标是增量事件里最密的一路,不录就不传,顺带省那份带宽。
    `mouseInteraction` 一起关:点击和 focus/blur 我们都不需要
    (输入走 `Input.*`),而 focus 那几条正是把观看端键盘焦点夺走的那一类。
    """
    from webmuxd import rrweb as dom_mod
    js = dom_mod.RECORD_JS
    assert "mousemove: false" in js, "鼠标轨迹又开始录了 —— 重放里会多一个指针"
    assert "mouseInteraction: false" in js, "点击/焦点事件又开始录了"
