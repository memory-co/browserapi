"""测试用的那个小站 —— **一律不出外网。**

以前这些场景开的是百度。代价是实打实的:一天里的偶发红几乎全出在这儿 ——
`wait --css` 撞满 30 秒、`news.baidu.com` 的 `readyState` 永远停在 `loading`、
版面天天变所以写死的名字随时会失效。**测的是我们自己的东西,
不该把别人的可用性押进去。**

这儿的页面是钉死的:多高、有几个链接、点哪个会开新 tab,全都写在这份文件里。
跑起来也快 —— 一个本地回环请求,没有 DNS、没有 TLS、没有广告脚本。

**为什么是 http 服务而不是 `data:` URL**(那样连服务都不用起):
DOM 那条腿的记录器只在 `http(s)` 上录
(`RECORD_JS` 里那行 `if (!/^https?:$/.test(location.protocol)) return`),
`data:` 上它一个事件都不发 —— 三条腿就没法用同一张页面比。
"""

from __future__ import annotations

import contextlib
import http.server
import threading
import urllib.parse

#: 长页有多高。滚动的距离要远小于它 —— 滚到底就停了,量出来的差是错的。
TALL = 6000

_HEAD = ('<!doctype html><meta charset="utf-8">'
         '<meta name="viewport" content="width=device-width">'
         '<title>{title}</title>'
         '<style>body{{margin:0;font:16px/1.5 system-ui,monospace;padding:24px}}'
         'a{{color:#06c}} .row{{margin:10px 0}}</style>')


#: 一张图和一份外链样式表。**它们是"资源转发"那条路的探针。**
#:
#: DOM 那条腿会把页面里的资源地址改写成 `/s/{sid}/api/res?u=…` 由服务端转发。
#: 那条路断过一次(地址少了 session 前缀,**每一个资源都 404**),而当时
#: 重放出来的节点数、文字、标题**全都对** —— 只有样式表数和图片数是 0。
#: 所以小站上必须有这两样,不然那个探针就是瞎的。
#:
#: **必须是绝对地址**:记录器只改写 `http(s)://` 开头的,相对地址原样留着,
#: 而重放文档的 base 是观看页 —— 相对地址会指到观看页那边去。
IMG = ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
       '<rect width="64" height="64" fill="#06c"/></svg>')
CSS = "#hello{letter-spacing:1px}"


def _abs(host: str, path: str) -> str:
    return f"http://{host}{path}"


def _home(host: str) -> str:
    return _HEAD.format(title="小站首页") + f"""
<link rel="stylesheet" href="{_abs(host, '/style.css')}">
<img id="logo" src="{_abs(host, '/img.svg')}" width="64" height="64" alt="小站标">
""" + """
<h1 id="hello">小站</h1>
<form id="f" action="/search" method="get">
  <input id="q" name="q" placeholder="搜点什么" aria-label="搜索" style="width:280px">
  <button id="go" type="submit">搜一下</button>
</form>
<div class="row"><a id="about" href="/about">关于</a></div>
<div class="row"><a id="news" href="/news" target="_blank">新闻</a></div>
<div class="row"><a id="tall" href="/tall">长页</a></div>
<p id="blurb">这是本地的测试站,不出外网。</p>
"""


def _search(host: str, q: str) -> str:
    safe = q.replace("&", "&amp;").replace("<", "&lt;")
    rows = "".join(
        f'<div class="row"><a class="hit" href="/about">{safe} 的第 {i} 条结果</a></div>'
        for i in range(1, 6))
    return _HEAD.format(title=f"{safe}_搜索结果") + f"""
<link rel="stylesheet" href="{_abs(host, '/style.css')}">
<img id="logo" src="{_abs(host, '/img.svg')}" width="64" height="64" alt="小站标">
<h1 id="hello">搜索结果</h1>
<div id="wd">{safe}</div>
{rows}
<div class="row"><a id="back" href="/">回首页</a></div>
"""


def _news(host: str) -> str:
    return _HEAD.format(title="小站新闻") + f"""
<link rel="stylesheet" href="{_abs(host, '/style.css')}">
<img id="logo" src="{_abs(host, '/img.svg')}" width="64" height="64" alt="小站标">""" + """
<h1 id="hello">新闻</h1>
<input id="q2" aria-label="站内搜索" placeholder="站内搜索" style="width:280px">
<div class="row"><a id="home" href="/">小站首页</a></div>
<div class="row"><a class="story" href="/about">头条一</a></div>
<div class="row"><a class="story" href="/about">头条二</a></div>
"""


def _tall() -> str:
    blocks = "".join(
        f'<div style="height:200px">第 {i} 格 · y={i * 200}</div>'
        for i in range(TALL // 200))
    return _HEAD.format(title="长页") + f"""
<a id="top" href="#top">TOP</a>
<div style="background:linear-gradient(#fff,#ddd)">{blocks}</div>
"""


def _about() -> str:
    return _HEAD.format(title="关于") + """
<h1 id="hello">关于</h1><p id="blurb">没什么可说的。</p>
<div class="row"><a id="home" href="/">回首页</a></div>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):                                    # noqa: N802
        u = urllib.parse.urlparse(self.path)
        host = self.headers.get("Host") or f"127.0.0.1:{self.server.server_address[1]}"
        if u.path == "/style.css":
            self._send(CSS.encode(), "text/css; charset=utf-8")
            return
        if u.path == "/img.svg":
            self._send(IMG.encode(), "image/svg+xml")
            return
        if u.path == "/":
            body = _home(host)
        elif u.path == "/search":
            q = urllib.parse.parse_qs(u.query).get("q", [""])[0]
            body = _search(host, q)
        elif u.path == "/news":
            body = _news(host)
        elif u.path == "/tall":
            body = _tall()
        elif u.path == "/about":
            body = _about()
        else:
            self.send_error(404)
            return
        self._send(body.encode(), "text/html; charset=utf-8")

    def _send(self, raw: bytes, mime: str) -> None:
        self.send_response(200)
        self.send_header("content-type", mime)
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):                           # 别往 pytest 里刷日志
        pass


@contextlib.contextmanager
def site():
    """起那个小站,交出根地址(带结尾斜杠)。"""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()
        srv.server_close()
