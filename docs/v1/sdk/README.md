# Python lib

```bash
pip install webmuxd
```

**这是主体。** 定位、观测、动作、日志这些行为定义在这儿;
[`../api`](../api/) 是把它导出去的那层壳,为调试和非 Python 集成而加,
不是反过来 —— 理由见 [works/02](../works/02-lib-and-api.md)。

所以读的顺序是:**先看这里,api 那边当序列化格式查**。逐行对照见 §7。

| 文件 | 内容 | 导出成 |
| --- | --- | --- |
| README.md(本文) | `Webmuxd` 入口、tab 句柄、`user`、异常、并发 | [api/README.md](../api/README.md) |
| [tabs.md](tabs.md) | tab 表在内存里怎么维护、`Tab` 句柄 | [api/tabs.md](../api/tabs.md) |
| [agent.md](agent.md) | `observe()` `act()` `log()` | [api/agent.md](../api/agent.md) |
| [events.md](events.md) | `watch()` | [api/events.md](../api/events.md) |
| [server.md](server.md) | 起停、runtime、端口、分享链接 | [api/server.md](../api/server.md) |

## 1. 一个 `Webmuxd` = 一个 port = 一个 Chrome

```python
from webmuxd import Webmuxd

web = Webmuxd(port=12345, token="changeme", runtime="container")
```

**构造即"确保在跑"**,幂等:那个端口上已经有 session 就接管,没有就按 runtime 拉一个起来。
像 `tmux new -A -s`,不用先判断存不存在。

**多个 session 就是多个 `Webmuxd`。**

```python
webs = [Webmuxd(port=7900 + i) for i in range(4)]
```

这是**和 tmux 不一样的地方**,而且是硬约束:tmux 一个 socket 复用所有 session,
kasm 不行 —— 每个 session 自带一块 VNC 屏和一个 HTTP 口,**端口没法复用**。
所以 lib 里没有「先拿 server 再列 session」那一层,你手里有几个 `Webmuxd` 就是几个。
**也没有 `Server` 类** —— 遍历和清理是运维,交给 `webmuxd ls` / `webmuxd kill`,
理由见 [server.md §5](server.md#5-lib-不管有哪些-session)。

## 2. tab 是句柄,不是"当前 tab"

```python
tab = web.open("https://shop.example.com", user="human")
tab.click("登录", user="claudecode")

print(tab.url, tab.title)
```

`web.open()` = 新建 tab + 导航 + 返回句柄,一次调用。之后所有页面操作都在句柄上。

```python
web.tabs                      # [Tab],内存里就有,见 §3
web.active                    # 当前那个
web.tab("t_7")                # 按 id
web.tab(title="购物车")        # 按标题,唯一匹配才行
```

**lib 这层不需要「不传就作用在当前 tab」那条规则** —— 你手里本来就攥着 tab。
那条规则是 HTTP 才需要的([api/README §2](../api/README.md#2-一条贯穿全局的规则tab-参数)),
因为线上没有句柄这种东西。这是「lib 先定形状,api 跟着导出」的一个典型例子。

## 3. tab 的状态在内存里

**`tab.url` 是读内存,不发请求。**

lib 连上 `WS /api/events` 之后,`tab.created` / `tab.updated` / `tab.activated` /
`tab.closed` 四个事件加起来就是一份完整的 tab 表。这份表本来就是为了让**外挂的
tab 条和地址栏**能画出来而设计的([works/04](../works/04-chrome-ui-externalization.md)),
lib 就是那个 client。

界线很干净:

| 在内存里(读属性,0 往返) | 要发请求 |
| --- | --- |
| `url` `title` `loading` `favicon` | `observe()` 元素表和标注截图 |
| `active` `index` `security` `crashed` | `text()` 页面正文 |
| `can_go_back` `can_go_forward` `opener` | `screenshot()` |
| 整张 `web.tabs` 表 | `log()` 操作日志 |

**外挂 UI 画得出来的东西在内存里,画不出来的要请求。** 事件流里不塞大字段
([api/events.md §1](../api/events.md#1-信封)),所以右边那一列没法省。

左边那一列**人在画面里操作也会更新** —— 他点个 `target=_blank` 的链接,
你内存里就多一个 tab。怎么做到的见 [works/06](../works/06-sync-paths.md)。

### 动作的响应也回灌内存

`POST /api/act` 的响应带 `after.url` 和 `after.new_tabs`,lib 拿到就直接更新内存 ——
所以 `click()` 返回的那一刻 `tab.url` 已经是新的,**不用等 WS 那条 `tab.updated` 追上来**。
不这么做,开头那个例子里的 `print(tab.url)` 就是个竞态。

### 旧了会告诉你

lib 按 [api/events.md §3](../api/events.md#3-客户端该怎么写) 那三条办事,
不是"建议",是义务:字段级合并、收到 `gap` 或 `chrome.restarted` 自动重新拉全量。

```python
web.stale        # WS 断了 → True,内存不保证新鲜
web.sync()       # 手动重新拉全量
```

**WS 断开期间属性读会退化成直接 GET**(慢,但不骗你),同时后台一直在重连。

`web.active` **没有兜底轮询,也不会慢半拍** —— 唯一会让它失准的是特权页面
(`chrome://` 那一类),而那些页面被禁掉了:`tab.goto("chrome://settings")` 抛
`BlockedURL`,人用快捷键捅出来的也会被导回 `about:blank`
([api/tabs.md §5](../api/tabs.md#5-当前是哪个-tab怎么来的))。

## 4. `user` —— 署名

```python
tab.click("登录", user="claudecode")
web.open(url, user="human")

web = Webmuxd(port=12345, user="claudecode")   # 设默认,省得每次带
```

**它是署名,不是身份,也不是锁。** 安全边界是 token:
拿着同一个 token 就能自称任意 `user`,lib 和服务端都不校验。

它解决的是**多个 agent 和人共用一个浏览器时,回看分不清谁干的**。
署名会进操作日志和事件流,所以:

```python
web.log(user="claudecode")      # 只看它干了什么
```

默认值:不传 → 构造时的 `user=` → 再没有就是 `"api"`;
人在 VNC 里手动点的,服务端记 `"human"`。

`user` **要导出到 HTTP**(它进日志,是行为不是客户端便利),
对应 `POST /api/act` 的 `user` 字段和日志条目的 `user` 列。

## 5. 异常

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
   ├─ BlockedURL      blocked_url    特权页面,见 [tabs.md](tabs.md)
   ├─ ReadOnly        read_only
   └─ SessionExists   session_exists
```

**异常是原生表达,错误码是它的序列化。** `.candidates` 在这儿是属性,
到了 HTTP 只能塞进 `details`。

```python
try:
    tab.click("提交订单")
except NotFound as e:
    print(e.candidates)   # [button "提交订单(2)", link "订单", button "提交"]
except PlatformError:
    alert("session 挂了")
```

每个异常都带 `.code` `.message` `.details` `.http_status`,原样来自响应体 ——
新加的错误码即使还没建类,也会以基类形式抛出来,不会变成 `KeyError`。

## 6. 并发

**一个 `Webmuxd` 同时只跑一个动作。** 并发调会拿到 `Busy`,不排队、不交错
([api/README §1](../api/README.md#1-约定))。`user` 不改变这条 —— 署名不是锁,
两个 agent 同时点,照样是一个 `Busy`。

要真并发就多起几个,每个自己的端口(§1):

```python
webs = [Webmuxd(port=7900 + i) for i in range(4)]
with ThreadPoolExecutor(4) as pool:
    pool.map(run_one, webs)          # 一个线程一个 Webmuxd
```

`Webmuxd` 实例**不是线程安全的**,别跨线程共用一个。
(它内部有一个后台线程在收事件维护 §3 那份内存,那是 lib 自己的,和你的线程无关。)

人在 VNC 里操作时会收到 `BusyHuman`,带 `.retry_after_ms`
([api/README §5](../api/README.md#5-人在操作时的让路))。**lib 不自动等**:

```python
except BusyHuman as e:
    time.sleep(e.retry_after_ms / 1000)   # 要等你自己等
```

## 7. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `Webmuxd(port=, token=, runtime=)` | 确保 session 在跑 + base = `<host:port>/api`,见 [server.md](server.md) |
| `web.open(url)` | `POST /api/tabs` + `POST /api/tabs/{id}/goto` |
| `web.tabs` `web.active` `tab.url` `tab.title` | **不请求** —— 内存,由 `WS /api/events` 维护 |
| `web.sync()` | `GET /api/tabs` + `GET /api/status` |
| `tab.click/type/key/...`、`tab.act()` | `POST /api/act`(带 `tab`、`user`) |
| `tab.observe()` | `GET /api/observe?tab=` |
| `tab.text()` `tab.screenshot()` | `GET /api/text` `/api/screenshot` |
| `web.log()` `web.bundle()` | `GET /api/log` `/api/log/bundle` |
| `web.watch()` | `WS /api/events`(和内存共用同一条连接) |
| `web.status()` `web.viewport()` `web.reset()` | `GET /api/status` `/api/viewport` `POST /api/reset` |
| `web.share()` `web.view_url` | `POST /api/live-token` |
| `web.kill()` | `DELETE /api/sessions/{name}` —— 只能停你手里这个 |

**没导出去的**:tab 句柄本身、内存里那份表、异常树、`with` 自动清理、按标题找 tab。
这些在 HTTP 上要么没法表达、要么表达出来也没人用 —— 不导出是对的,不是缺口。

反过来,**api 有而这里没有的东西**只有一处,而且是故意的:session 的遍历和清理
(`GET /api/sessions`、`GET /api/server`)—— 那是运维,归 CLI,见
[server.md §5](server.md#5-lib-不管有哪些-session)。除此之外再发现别的,
那就是导出面跑到主体前面去了。
