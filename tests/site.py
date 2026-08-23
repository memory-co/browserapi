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

#: **这一页现在是不是浏览器的前台。**
#:
#: 每一页都带着,因为它是**唯一一个不靠我们自己那张表**就能回答
#: "浏览器到底把哪个 tab 放在前台"的东西 —— `document.visibilityState`
#: 是标准的,DevTools 连上去也能独立读到同一个值。
#:
#: 为什么非要它:我们那张表里的 `active` 是**我们记的**,而浏览器自己
#: 也会动前台(页面 `target=_blank` 开出来的那个,Chromium 直接切过去)。
#: 两边一漂,VNC 上人看到的是新那页、tab 条却高亮着旧那页,**一句错都不报**。
#: 拿我们的字段去验我们的字段永远是绿的,所以判据必须来自页面这一侧。
#:
#: `position:fixed` 且挪到屏外:读得到,但不进版面、不撑滚动条、
#: 不出现在 `in_viewport` 的快照里 —— 别的场景当它不存在。
_VIS = ('<span id="vis" style="position:fixed;left:-9999px;top:0"></span>'
        '<script>(function(){var s=document.getElementById("vis");'
        'function v(){s.textContent=document.visibilityState}'
        'document.addEventListener("visibilitychange",v);v()})()</script>')


#: **每一页一个底色。**
#:
#: 这不是装饰,是让"画面上现在是哪一页"**能被断言**。
#:
#: 原来观看端那一侧只答得出两件事:画面上有没有东西(`colors > 1`)、
#: 和刚才比变没变(`sig`)。两样都答不了"你放的是哪一页" ——
#: 而那正是用户报过来的那个 bug 的样子:tab 条说首页、**画面上是新闻页**。
#: JPG 那条腿更阴:后台 tab 不产帧,画面**冻在上一帧**,
#: "有东西"和"没变"两条判据它全过。
#:
#: 底色要**离得足够远**:推过来的是 JPEG,平坦区域偏个两三度,
#: 靠最近邻匹配认回来(`v2kit.Human.showing`)。
TINT = {
    "/":       "#1f6feb",   # 蓝
    "/news":   "#2ea043",   # 绿
    "/about":  "#d29922",   # 琥珀
    "/tall":   "#8957e5",   # 紫
    "/search": "#bf3989",   # 品红
    "/ticker": "#0f4f4f",   # 深青
}

#: 调色板里最近的两个隔多远(实测 87.6)—— `v2kit.Human.showing()`
#: 的容差取它的一半,所以"认错页"和"认不出"之间没有灰带。

#: 标题 → 路径。DOM 那条腿画面是一棵真 DOM,不是一张图,
#: 认页靠 `title` 比认底色直接。
TITLES = {
    "小站首页": "/", "小站新闻": "/news", "关于": "/about",
    "长页": "/tall", "一直在动": "/ticker",
}


def _head(title: str, path: str = "/") -> str:
    tint = TINT.get(path, "#1f6feb")
    return (_HEAD.format(title=title)
            + f'<style>body{{background:{tint};color:#fff}}'
            f'a{{color:#fff;text-decoration:underline}}</style>' + _VIS)


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
    return _head("小站首页", "/") + f"""
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
    return _head(f"{safe}_搜索结果", "/search") + f"""
<link rel="stylesheet" href="{_abs(host, '/style.css')}">
<img id="logo" src="{_abs(host, '/img.svg')}" width="64" height="64" alt="小站标">
<h1 id="hello">搜索结果</h1>
<div id="wd">{safe}</div>
{rows}
<div class="row"><a id="back" href="/">回首页</a></div>
"""


def _news(host: str) -> str:
    return _head("小站新闻", "/news") + f"""
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
    return _head("长页", "/tall") + f"""
<a id="top" href="#top">TOP</a>
<div>{blocks}</div>
"""


def _ticker(host: str) -> str:
    """**一直在动的一页。** 用来验"后台 tab 的变化会不会混进来"。"""
    return _head("一直在动", "/ticker") + """
<h1 id="hello">ticker</h1>
<div class="row">这一页每 200ms 改一次下面那个数。</div>
<div class="row">用来验:后台 tab 的变化会不会混进当前 tab 的增量链。</div>
<div class="row"><a id="home" href="/">回首页</a></div>
<div class="row">计数:<b id="n">0</b></div>
<script>let i=0;setInterval(()=>{document.getElementById('n').textContent=++i;},200)</script>
"""


def _about() -> str:
    return _head("关于", "/about") + """
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
        elif u.path == "/ticker":
            body = _ticker(host)
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
