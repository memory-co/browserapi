# SDK · session 与 server

对应 [api/server.md](../api/server.md)。管的是**有哪些 session**;
某个浏览器里发生什么在 [agent.md](agent.md) 和 [tabs.md](tabs.md)。

## 1. `Server`

```python
from webmuxd import Server

s = Server()                                        # 本机 socket,按需自启
s = Server("https://browser.internal:7800",         # 远端,必须带 token
           token=os.environ["WEBMUXD_TOKEN"])
s = Server(socket="/tmp/x.sock")                    # 换 socket,= CLI 的 -S
s = Server(name="ci")                               # = CLI 的 -L ci
```

走 socket 时靠文件权限鉴权,**不需要 token**;走 TCP 必须带
([api/server.md §6](../api/server.md#6-鉴权))。

```python
s.sessions()                   # [Session] —— 每次都现场探活,不是读缓存
s.get("work")                  # Session,没有就抛 SessionNotFound
s.has("work")                  # bool
s.new(name="work", runtime="container", url="https://example.com",
      viewport="1280x800", port=7900, volume="webmuxd-work")
s.kill("work")
s.info()                       # version / listen / sessions / runtimes / default_runtime
s.shutdown()                   # = kill-server
s.watch()                      # server 级事件流,见 events.md
```

## 2. `Session`

```python
sess = s.get("work")

sess.name  sess.runtime  sess.state       # starting | ready | dead | unreachable
sess.endpoint                             # http://127.0.0.1:7900
sess.proxy                                # /s/work/
sess.tab_count  sess.active_tab_url  sess.created_at
sess.handle                               # {"container_id": ...} 或 {"display":..., "pids":...}

b = sess.browser()                        # → Browser,接下来见 agent.md / tabs.md
sess.rename("work2")
sess.kill()
```

**`Session` 管生命周期,`Browser` 管里面的浏览器。** 这条界线和 API 的两组接口一致,
所以 `sess.click(...)` 这种方法**故意不给** —— 要操作就先 `.browser()`。

### 观看链接

```python
sess.view_url                                  # 你自己看,完整权限
sess.share()                                   # 给别人,默认只读,1 小时
sess.share(writable=True, ttl=3600)            # 可操作 —— 能碰你所有登录态
```

`share()` **默认 `read_only=True`**,和 API、CLI、ttyd 的默认一致。
SDK 不做"代码里方便所以更宽松"这种事。

## 3. `Browser.start()`

绝大多数脚本只需要这一个:

```python
b = Browser.start(name="work", port=7900, volume="webmuxd-work")
print(b.view_url)
```

等价于 `Server().new(...).browser()`。参数和 `s.new()` 一样。

```python
with Browser.start(name="tmp") as b:      # 退出时 kill 掉
    b.goto("https://example.com")
    ...
```

**只有 `Browser.start()` 建的才会被 `with` 关掉**;
`Browser("http://...")` 连上去的不会 —— 连接方不该有权杀掉不是自己建的 session。

## 4. runtime 不可用时抛,不降级

```python
try:
    b = Browser.start(name="work")
except RuntimeUnavailable as e:
    print(e.hint)     # "改用 runtime=process,但那样没有隔离"
```

对应 `503 runtime_unavailable`。docker 不通时**不会静默换成 `process`** ——
那等于把页面偷偷挪到你自己机器上跑,没有隔离
([api/server.md §3](../api/server.md#3-session-管理))。

`s.info().runtimes` 是探测结果,想先看一眼再决定就查它。

## 5. `kill-server` 之后

和 CLI 一样,**取决于 runtime**:`process` 跟着死,`container` 和 `remote` 活着
([cli/server.md §5](../cli/server.md#5-kill-server-之后会怎样))。
所以 `sess.runtime` 这个字段不是给你看着玩的。

`s.kill(name)` 对 `remote` 只删本地记录,不动对面:

```python
r = s.kill("prod")
r.note    # "remote session,对面仍在运行"
```

## 6. ↔ API 对照

| SDK | API |
| --- | --- |
| `Server(url, token=)` | base = `<url>/api` |
| `Server(socket=)` / `Server(name=)` | unix socket,不经 HTTP |
| `s.sessions()` | `GET /api/sessions` |
| `s.get(name)` / `s.has(name)` | `GET /api/sessions/{name}` |
| `s.new(...)` | `POST /api/sessions` |
| `s.kill(name)` / `sess.kill()` | `DELETE /api/sessions/{name}` |
| `sess.rename(new)` | `POST /api/sessions/{name}/rename` |
| `s.info()` | `GET /api/server` |
| `s.shutdown()` | `POST /api/server/shutdown` |
| `sess.share(writable=, ttl=)` | `POST /api/sessions/{name}/live-token` |
| `s.watch()` | server 的 `WS /api/events` |
| `sess.browser()` | 拿 `endpoint`(或 `proxy`)构造 `Browser` |
| `Browser.start(...)` | `POST /api/sessions` + 构造 `Browser` |

**对不上的地方**:`Browser.start()` 和 `with` 的自动清理是 SDK 自己的组合,
API 没有"建完就用"这一步;`sess.browser()` 走 `proxy` 还是 `endpoint`
由 SDK 按连的是哪种 `Server` 自己选,API 两个地址都给你。
