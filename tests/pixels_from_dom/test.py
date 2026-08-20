"""DOM 那条画面([c §5](../../docs/v2/works/c-view.md#5-第三条rrweb--它不传像素))。

这一套全是**不依赖浏览器**的:资源地址改写、事件缓冲怎么砍、注入守卫。
跑真浏览器那部分在别处 —— 但这几条是可以钉死的,而且它们各自都有过
"不报错、只是不工作"的前科。
"""

import json

from webmuxd.view.dom import MAX_EVENTS, RECORD_JS, DomSource


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
    assert out["data"]["node"]["attributes"]["src"].startswith("/api/res?u=")
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
    assert out2["data"]["node"]["attributes"]["href"].startswith("/api/res?u=")


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
    assert "/api/res?u=" in out["data"]["node"]["attributes"]["style"]


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
    assert v.count("/api/res?u=") == 2
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
