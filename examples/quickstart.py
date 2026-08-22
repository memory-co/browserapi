"""跑一遍 webmuxd,看它到底能干什么。

    docker run --rm -v "$PWD":/src webmuxd-dev python /src/examples/quickstart.py

自带一个小页面服务器,所以不需要联网。跑完你会看到:
起 session → 开 tab → 按可见文字点 → 观测 → 回看日志。
"""

import http.server
import socket
import threading

from webmuxd import Webmuxd

PAGE = """<!doctype html><meta charset=utf-8><title>结算</title>
<style>body{font:16px system-ui;margin:3rem}button{font-size:16px;padding:.4rem 1rem}</style>
<h1>结算</h1>
<label for=phone>手机号</label> <input id=phone>
<p>
<button onclick="document.getElementById('out').textContent='订单已提交'">提交订单</button>
<button>取消订单</button>
<div id=out style="margin-top:1rem;color:#c00"></div>
"""


def serve_page() -> str:
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = PAGE.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    httpd = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    url = serve_page()
    port = free_port()

    print("① 管理实例 —— 空壳,不起任何浏览器")
    web = Webmuxd(port=port, user="claudecode")

    print(f"② 起一个 session(一个浏览器)  一个口 :{port}")
    sess = web.session(id="quickstart", runtime="process")
    print(f"   画面和 API 在同一个口上:{sess.view_url}")

    try:
        print(f"③ 开一个 tab  {url}")
        tab = sess.open(url)
        print(f"   标题 {tab.title!r}   URL {tab.url}")
        print("   (这两个是读内存,没发请求)")

        print("④ 按可见文字操作 —— 不用写选择器")
        tab.type("手机号", "13800000000")
        r = tab.click("提交订单")
        print(f"   命中 {r.results[0]['hit']['role']} "
              f"{r.results[0]['hit']['name']!r}   {r.results[0]['ms']}ms")
        print(f"   页面变化:{r.results[0]['after'].get('changed')}")

        print("⑤ 有歧义时给候选,而不是替你挑一个")
        miss = tab.act([{"type": "click", "text": "订单"}])
        print(f"   ok={miss.ok}  {miss.failed['error']}:{miss.failed['message']}")
        print("   候选:" + "、".join(repr(c["name"]) for c in miss.candidates))

        print("⑥ 观测 —— 一次调用拿到喂给模型的全部东西")
        shot = tab.screenshot()
        print("   " + obs.as_prompt().replace("\n", "\n   "))
        print(f"   标注截图 {len(obs.screenshot)} 字节")
        if obs.notes:
            print(f"   盲区:{obs.notes}")

        print("⑦ 回看它干了什么")
        for e in sess.log(kind="action"):
            hit = (e.get("hit") or {}).get("name")
            line = f"   {e['seq']:>3} {e.get('user','')} {e['action']}"
            if e.get("target"):
                line += f" {e['target']}"
            if hit:
                line += f" → {hit}"
            if e.get("error"):
                line += f"  ✗ {e['error']}"
            print(line)
            changed = (e.get("after") or {}).get("changed")
            if changed:
                print(f"       {changed}")

        print("\n✓ 跑通了。")
        print(f"  画面在 {sess.view_url} —— 浏览器打开就能看,能上手")
    finally:
        web.shutdown()          # 起的两个进程都是我们的子进程,跟着死


if __name__ == "__main__":
    main()
