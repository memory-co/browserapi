# Python SDK

```bash
pip install webmuxd
```

**SDK 是 HTTP API 的一层薄封装,不是第二套实现。** API 有什么,SDK 就有什么,
名字一一对应,逐行对照见 §6。

| 文件 | 内容 | 对应 |
| --- | --- | --- |
| README.md(本文) | 两个入口、鉴权、异常、并发 | [api/README.md](../api/README.md) |
| [tabs.md](tabs.md) | `b.tabs()` `b.new_tab()` `Tab` 对象 | [api/tabs.md](../api/tabs.md) |
| [agent.md](agent.md) | `b.observe()` `b.act()` `Observation` `b.log()` | [api/agent.md](../api/agent.md) |
| [events.md](events.md) | `b.watch()` | [api/events.md](../api/events.md) |
| [server.md](server.md) | `Server` `Session` 生命周期 | [api/server.md](../api/server.md) |

## 1. 两个入口

**`Browser` 是一个 session**(`http://host:7900/api`),
**`Server` 是管 session 的那个**(`http://host:7800/api`)。分得和 API 一样清楚。

```python
from webmuxd import Browser, Server

b = Browser("http://localhost:7900", token="changeme")     # 直连一个 session
b = Server().get("work").browser()                          # 从 server 要一个

b.goto("https://shop.example.com")
b.click("登录")                            # 按可见文字找
b.type("手机号", "13800000000")            # 按标签找输入框
b.type("密码", "hunter2")
b.click(role="button", name="登录")        # 说不清的时候加 role
b.wait_for(url_contains="/home")

print(b.url, b.title)
print(b.text())                            # 页面正文
rows = b.extract(".cart-item", mode="table")
b.screenshot("cart.png")
```

顺手起一个(内部就是 `Server().new(...)`,见 [server.md](server.md)):

```python
b = Browser.start(name="work", port=7900, volume="webmuxd-work")
print(b.view_url)      # http://localhost:7800/s/work/ —— 拿去浏览器里看
```

经 server 代理时,`Browser("http://host:7800/s/work")` 和直连 `:7900` 用法完全一样 ——
因为 `/api` 之后的部分一模一样([api/server.md §2](../api/server.md#2-代理))。

## 2. 命名规则

不用查表也能猜到方法名,规则就三条:

| API | SDK |
| --- | --- |
| `GET /api/x` | `b.x()` —— `observe()` `tabs()` `text()` `status()` `log()` |
| `POST /api/act` 的动作 `type` | 同名方法 —— `click()` `type()` `select()` `wait_for()` |
| 路径里的 `{id}` | 对象上的方法 —— `b.tab("t_7").close()` |

蛇形命名(`wait_for` ↔ `wait_for`,`new_tab` ↔ `POST /api/tabs`),
`type` 这个动作和 Python 内建重名但**照样叫 `type`**,不为了避让改名。

## 3. 异常

对应 [api/README §4](../api/README.md#4-错误) 那张表,一个错误码一个类:

```
WebmuxdError
├─ ActionError        这一步没做成,你能自愈 —— 换个写法或重试
│  ├─ NotFound        not_found      .candidates
│  ├─ NotClickable    not_clickable
│  ├─ Timeout         timeout
│  ├─ NavFailed       nav_failed     .net_error
│  ├─ TabGone         tab_gone
│  ├─ Busy            busy           .retry_after_ms
│  └─ BusyHuman       busy_human     .retry_after_ms
├─ PlatformError      这个 session 出事了 —— 该告警,别盲目重试
│  ├─ ChromeGone      chrome_gone
│  ├─ SessionDead     session_dead
│  ├─ RuntimeUnavailable  runtime_unavailable   .hint
│  └─ NoPort          no_port
└─ UsageError         你代码写错了 —— 重试多少次都一样
   ├─ BadRequest      bad_request
   ├─ ReadOnly        read_only
   ├─ SessionNotFound session_not_found
   └─ SessionExists   session_exists
```

**这个二分就是 API 那个二分**:`except ActionError` 是重试循环,
`except PlatformError` 是告警。

```python
try:
    b.click("提交订单")
except NotFound as e:
    print(e.candidates)   # [button "提交订单(2)", link "订单", button "提交"]
except PlatformError:
    alert("session 挂了")
```

每个异常都带 `.code` `.message` `.details` `.http_status`,原样来自响应体 ——
新加的错误码即使 SDK 还没建类,也会以基类形式抛出来,不会变成 `KeyError`。

## 4. 并发

**一个 session 同时只跑一个动作。** 并发调会拿到 `409 busy` → `Busy` 异常,
不排队、不交错([api/README §1](../api/README.md#1-约定))。

v1 只有同步 API。要真并发就多起几个 session,这也是 tmux 的答案:

```python
browsers = [Browser.start(name=f"w{i}") for i in range(4)]
with ThreadPoolExecutor(4) as pool:
    pool.map(run_one, browsers)          # 一个线程一个 session
```

`Browser` 实例**不是线程安全的**,别拿同一个跨线程用。

人在 VNC 里操作时会收到 `BusyHuman`,带 `.retry_after_ms`
([api/README §5](../api/README.md#5-人在操作时的让路))。SDK **不自动等**:

```python
except BusyHuman as e:
    time.sleep(e.retry_after_ms / 1000)   # 要等你自己等,SDK 不替你决定
```

## 5. 鉴权和幂等

```python
b = Browser("http://localhost:7900", token=os.environ["WEBMUXD_TOKEN"])
```

不传 `token` 时读 `WEBMUXD_TOKEN`,没设就不带头(对应服务端没设 token 的情况)。
用只读 token 的话所有写方法抛 `ReadOnly`。

`POST` 全部支持幂等键,`act()` 尤其该用 ——
网络重试导致的重复点击是真实事故([api/README §1](../api/README.md#1-约定)):

```python
b.act(actions, idempotency_key=f"order-{order_id}")
```

不传时 SDK **不自动生成** —— 自动生成会让"重试"和"再点一次"变得没法区分。

## 6. ↔ API 对照

| SDK | API | 详见 |
| --- | --- | --- |
| `Browser(url, token=)` | base = `<url>/api` | 本文 §1 |
| `b.status()` | `GET /api/status` | [agent.md](agent.md) |
| `b.viewport()` | `GET /api/viewport` | [agent.md](agent.md) |
| `b.reset()` | `POST /api/reset` | [agent.md](agent.md) |
| `b.observe()` | `GET /api/observe` | [agent.md](agent.md) |
| `b.act()` / `click` `type` `key` … | `POST /api/act` | [agent.md](agent.md) |
| `b.screenshot()` `b.text()` | `GET /api/screenshot` `/api/text` | [agent.md](agent.md) |
| `b.log()` `b.bundle()` | `GET /api/log` `/api/log/bundle` | [agent.md](agent.md) |
| `b.upload()` `b.download()` | `POST /api/upload` `GET /api/download/{name}` | [agent.md](agent.md) |
| `b.tabs()` `b.tab()` `b.new_tab()` `b.reorder()` | `/api/tabs*` | [tabs.md](tabs.md) |
| `b.watch()` | `WS /api/events` | [events.md](events.md) |
| `b.live_token()` | `POST /api/live-token` | [server.md](server.md) |
| `Server()` `s.sessions()` `s.new()` `s.kill()` | `/api/sessions*` `/api/server` | [server.md](server.md) |

**SDK 多出来的东西**只有对象化(`Observation` `Tab` `Session`)、
异常树(§3)和自动重连([events.md](events.md))。语义一概不改。
