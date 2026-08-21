# Python lib

```bash
pip install webmuxd
```

**这是主体。** 定位、观测、动作、日志这些行为定义在这儿;
[`../api`](../api/) 是把它导出去的那层壳,为调试和非 Python 集成而加,
不是反过来 —— 理由见 [works/02](../works/02-lib-and-api.md)。

所以读的顺序是:**先看这里,api 那边当序列化格式查**。逐行对照见 §7。

**三个对象,一层套一层:管理实例 → session → tab。**
页面上的事**全部**在 `Tab` 上做 —— 没有 "agent"、没有 "controller"。

| 文件 | 内容 | 导出成 |
| --- | --- | --- |
| README.md(本文) | 三个对象、`user`、异常、并发 | [api/README.md](../api/README.md) |
| [manager.md](manager.md) | `Webmuxd` —— 建、列、杀 session | [api/server.md](../api/server.md) |
| **[tab/](tab/)** | **句柄、属性、导航、动作、观测** | [api/tabs.md](../api/tabs.md) · [api/act.md](../api/act.md) |
| **[log/](log/)** | 三类日志:动作、tab 生死、session | [api/log.md](../api/log.md) |
| [session.md](session.md) | `Session` —— 端口、runtime、分享、reset | [api/README.md](../api/README.md) |

`tab/` 下面按用途分:[README](tab/README.md) 拿句柄和读属性、
[navigate](tab/navigate.md) 走到哪、[input](tab/input.md) 往里做、
[read](tab/read.md) 往外看。
`log/` 下面按类型分:[tab](log/tab.md) 动作、[session](log/session.md) tab 生死和 session 事件。

## 1. 三个对象

```python
from webmuxd import Webmuxd

web  = Webmuxd()                                   # ① 管理实例:空壳,不起任何浏览器
sess = web.session(id="work", api_port=7900,           # ② 一个 session = 一个 kasm 容器
                   view_port=6901, runtime="container")
tab  = sess.open("https://shop.example.com")       # ③ 一个 tab = 一个页面句柄

tab.click("登录", user="claudecode")
print(tab.url, tab.title)
```

| | 是什么 | 详见 |
| --- | --- | --- |
| **`Webmuxd`** | **管理实例**。持有若干 session,自己不跑浏览器 | [manager.md](manager.md) |
| **`Session`** | **一个 kasm 容器**:一块 VNC 屏 + 一个 Chromium + 一份日志 | [session.md](session.md) |
| **`Tab`** | **一个页面的句柄**,所有页面操作都在它上面 | [tab/](tab/) |

**`Webmuxd()` 是个空壳。** 构造它不起容器、不占端口 —— 它只是"我要开始管 session 了"。
**每 `session()` 一个新 id 才起一个 kasm。**

`session()` 是**幂等**的:同一个 `id` 永远给你同一个 session,连 Python 对象都是同一个。
`port` / `view_port` / `runtime` 只在第一次(需要新建时)有意义,而且
**端口必须你给,我们不自动分配**([manager.md §1](manager.md#1-session--拿一个-session))。

```python
web = Webmuxd()                  # 纯管理实例,走本机 socket
web = Webmuxd(port=7800)         # 顺便把管理面暴露出去(远程 CLI / 别的语言要用时)
web = Webmuxd("https://browser.internal:7800", token=TOKEN)   # 连一个远端的
```

`port` 是**管理面自己的口**,和 session 的口无关 —— 每个 session 有它自己的两个
([works/01 §1](../works/01-container.md#1-一张图))。不给 `port` 就只走 socket,
靠文件权限鉴权,不占网络端口。

## 2. 层级和 CLI、api 是对齐的

| lib | CLI | api |
| --- | --- | --- |
| `Webmuxd()` | server(按需自启) | `/api/sessions` `/api/server` |
| `web.session(id=)` `web.sessions()` `web.kill()` | `new` `ls` `kill` | `POST` `GET` `DELETE /api/sessions` |
| `sess.open()` `sess.log()` | `new-tab` `log` | `/api/tabs` `/api/log` |
| `tab.click()` | `click` | `POST /api/act` |

**三边没有谁多谁少。** 早先 lib 里没有管理这一层,那时 `webmuxd ls` 是 CLI 独有的;
现在不是了。

## 3. tab 的状态在内存里

**`tab.url` 是读内存,不发请求。**

每个 `Session` 连着一条 `WS /api/events`,`tab.created` / `tab.updated` /
`tab.activated` / `tab.closed` 四个事件加起来就是一份完整的 tab 表。这份表本来就是
为了让**外挂的 tab 条和地址栏**能画出来而设计的
([works/04](../works/04-chrome-ui-externalization.md)),lib 就是那个 client。

界线很干净:

| 在内存里(读属性,0 往返) | 要发请求 |
| --- | --- |
| `url` `title` `loading` `favicon` | `screenshot()` 那一刻的页面、`text()` 正文 |
| `active` `index` `security` `crashed` | `text()` 页面正文 |
| `can_go_back` `can_go_forward` `opener` | `screenshot()` |
| 整张 `sess.tabs` 表 | `log()` 操作日志 |

**外挂 UI 画得出来的东西在内存里,画不出来的要请求。** 截图和元素表太大,
不能塞进推送,所以右边那一列没法省。

左边那一列**人在画面里操作也会更新** —— 他点个 `target=_blank` 的链接,
你内存里就多一个 tab。怎么做到的见 [works/06](../works/06-tab-sync.md)。

### 动作的响应也回灌内存

`POST /api/act` 的响应带 `after.url` 和 `after.new_tabs`,lib 拿到就直接更新内存 ——
所以 `click()` 返回的那一刻 `tab.url` 已经是新的,**不用等 WS 那条 `tab.updated` 追上来**。

### 旧了会告诉你

```python
sess.stale        # WS 断了 → True,内存不保证新鲜
sess.sync()       # 手动重新拉全量
```

**WS 断开期间属性读会退化成直接 GET**(慢,但不骗你),同时后台一直在重连。
lib 内部替你守着那几条:字段级合并、丢了通知就自动重新拉全量
([works/06 §5](../works/06-tab-sync.md#5-推给客户端)),**你碰不到也不需要碰**。

`sess.active` **不是观测出来的,是 sessiond 记的**
([api/tabs.md §5](../api/tabs.md#5-当前是哪个-tab是-sessiond-说了算))——
不会慢半拍,唯一会漂的是人按 `Ctrl+Tab`,下次有人进来或下次 `activate` 就对齐回来。

## 4. `user` —— 署名

```python
tab.click("登录", user="claudecode")
sess.open(url, user="human")

web  = Webmuxd(user="claudecode")               # 设默认,底下所有 session 继承
sess = web.session(id="w2", api_port=7901, view_port=6902,
                   user="cursor")              # 也能按 session 覆盖
```

**它是署名,不是身份,也不是锁。** 安全边界是 token:
拿着同一个 token 就能自称任意 `user`,lib 和服务端都不校验。

它解决的是**多个 agent 和人共用一个浏览器时,回看分不清谁干的**。
署名会进操作日志和事件流,所以:

```python
sess.log(user="claudecode")      # 只看它干了什么
```

默认值:不传 → 构造时的 `user=` → 再没有就是 `"api"`;
人在 VNC 里手动点的,服务端记 `"human"`。

`user` **要导出到 HTTP**(它进日志,是行为不是客户端便利),
对应 `POST /api/act` 的 `user` 字段和日志条目的 `user` 列。

## 5. 异常

一个错误码一个类。码表在两处:[api/README §4](../api/README.md#4-错误)(session 内的)
和 [api/server.md §5](../api/server.md#5-错误)(起停的)。

```
WebmuxdError
├─ ActionError        这一步没做成,你能自愈 —— 换个写法或重试
│  ├─ NotFound        not_found      .candidates
│  ├─ NotClickable    not_clickable
│  ├─ Timeout         timeout
│  ├─ NavFailed       nav_failed     .net_error
│  ├─ TabGone         tab_gone       .reason(closed/evicted)、.final_url
│  ├─ Busy            busy           .retry_after_ms
│  └─ BusyHuman       busy_human     .retry_after_ms
├─ PlatformError      这个 session 出事了 —— 该告警,别盲目重试
│  ├─ ChromiumGone      chrome_gone
│  ├─ SessionDead     session_dead
│  ├─ RuntimeUnavailable  runtime_unavailable   .hint
│  └─ PortInUse       port_in_use       你给的端口被占了
└─ UsageError         你代码写错了 —— 重试多少次都一样
   ├─ BadRequest      bad_request
   ├─ BlockedURL      blocked_url    特权页面,见 [tab/README.md](tab/README.md)
   ├─ ReadOnly        read_only
   ├─ SessionExists   session_exists    `create()` 重名
   └─ SessionNotFound session_not_found `get()` / `kill()` 找不到
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

**一个 session 同时只跑一个动作。** 并发调会拿到 `Busy`,不排队、不交错
([api/README §1](../api/README.md#1-约定))。`user` 不改变这条 —— 署名不是锁,
两个 agent 同时点,照样是一个 `Busy`。

**但 session 之间是真并行的** —— 它们是各自独立的容器:

```python
web = Webmuxd()
sessions = [web.session(id=f"w{i}", api_port=7900+i, view_port=6901+i)
            for i in range(4)]
with ThreadPoolExecutor(4) as pool:
    pool.map(run_one, sessions)          # 一个线程一个 session
```

`Session` 实例**不是线程安全的**,别跨线程共用一个。
(它内部有一个后台线程在收事件维护 §3 那份内存,那是 lib 自己的,和你的线程无关。)
`Webmuxd` 本身只做管理,`create()` / `sessions()` 这些是安全的。

要真并发就多开几个 session,这也是 tmux 的答案:多开几个。
**上限是机器** —— 每个 session 是一个容器、一个 Chromium、两个端口
([works/05 §2](../works/05-server-session-runtime.md#2-对照表))。

人在 VNC 里操作时会收到 `BusyHuman`,带 `.retry_after_ms`
([api/README §5](../api/README.md#5-人在操作时的让路))。**lib 不自动等**:

```python
except BusyHuman as e:
    time.sleep(e.retry_after_ms / 1000)   # 要等你自己等
```

## 7. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `Webmuxd()` / `Webmuxd(port=)` | socket / `<host:port>/api`,见 [manager.md](manager.md) |
| `web.session(id=, api_port=, view_port=)` | `GET /api/sessions/{id}`,404 就 `POST` |
| `web.sessions()` `web.kill()` | `GET` `DELETE /api/sessions[/{id}]` |
| `web.info()` `web.shutdown()` | `GET /api/server` `POST /api/server/shutdown` |
| `sess.open(url)` | `POST /api/tabs {url}` |
| `sess.tabs` `sess.active` `tab.url` `tab.title` | **不请求** —— 内存,由 `WS /api/events` 维护 |
| `sess.sync()` | `GET /api/tabs` + `GET /api/status` |
| `tab.click/type/key/...`、`tab.act()` | `POST /api/act`(带 `tab`、`user`) |
| `tab.text()` `tab.screenshot()` | `GET /api/text` `/api/screenshot` |
| `sess.log()` `tab.log()` `sess.bundle()` | `GET /api/log[?tab=]` `/api/log/bundle`,见 [log/](log/) |
| `sess.status()` `sess.viewport()` `sess.reset()` | `GET /api/status` `/api/viewport` `POST /api/reset` |
| `sess.share()` `sess.view_url` `sess.api_url` | `POST /api/live-token` |
| 内存表的维护 | 内部订 `WS /api/events`,**不暴露** |

**没导出去的**:三个对象本身、内存里那份表、异常树、`with` 自动清理、按标题找 tab。
这些在 HTTP 上要么没法表达、要么表达出来也没人用 —— 不导出是对的,不是缺口。

反过来 **api 有而这里没有的东西不该存在**,现在一处也没有了。
