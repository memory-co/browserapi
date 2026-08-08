# lib · session 起停与 runtime

导出成 [api/server.md](../api/server.md)。管的是 session **怎么起来、怎么停**;
浏览器里发生什么在 [tab/](tab/),日志在 [log.md](log/)。

## 1. 构造即"确保在跑"

```python
web = Webmuxd(port=12345, token="changeme", runtime="container")
```

幂等:那个端口上已经有 session 就接管,没有就按 runtime 拉一个起来。
不用先 `has()` 再 `new()`,像 `tmux new -A -s`。

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `port` | 7900 起往上找空闲 | **一个 session 一个端口**,见 §2 |
| `token` | 读 `WEBMUXD_TOKEN` | 没设就不带头 |
| `runtime` | `container` | `container` / `process` / `remote`,见 §3 |
| `user` | `"api"` | 默认署名([README §4](README.md#4-user--署名)) |
| `name` | 端口号 | 给 CLI 和观看页面认的名字 |
| `url` | `about:blank` | 起来先打开哪 |
| `viewport` | `1024x768` | |
| `volume` | 无 | `container` 专用,存 profile |
| `host` | `127.0.0.1` | 连远端时给地址 |

```python
web.status()          # Chrome 活着没、版本、busy
web.view_url          # 拿去浏览器里看,完整权限
web.reset()           # 清 cookie、关多余 tab、回 about:blank
web.kill()            # 停掉并清理

with Webmuxd(port=7901) as web:      # 退出时 kill
    ...
```

**只有这次构造真的拉起来的才会被 `with` 关掉。** 接管到一个已经在跑的,
`with` 退出时不动它 —— 接管方不该有权杀掉不是自己起的东西。

## 2. 一个 session 一个端口

**这是和 tmux 最大的一处不同,而且是硬约束。**

tmux 一个 socket 复用所有 session;kasm 不行 —— 每个 session 自带一块 VNC 屏
和一个 HTTP 口,**端口没法复用**。所以:

```python
webs = [Webmuxd(port=7900 + i) for i in range(4)]
```

lib 里没有「先拿 server 再列 session」那一层。你手里有几个 `Webmuxd` 就是几个 session,
端口就是它们的地址。

这也是为什么 `:7800` 那个 server 存在([api/server.md §2](../api/server.md#2-代理)):
**对外只开一个口,按名字代理到各 session**,免得把 7900~79xx 一片全暴露出去。
写脚本用不上它,观看页面和 CLI 用它。

```python
web = Webmuxd("https://browser.internal:7800", name="work")   # 经 server 代理
```

## 3. runtime 不可用时抛,不降级

```python
Webmuxd(port=7900)                      # container(默认)
Webmuxd(port=7901, runtime="process")   # 不要 docker,秒起,没隔离
Webmuxd("https://browser.internal:7800", runtime="remote", name="prod")
```

```python
try:
    web = Webmuxd(port=7900)
except RuntimeUnavailable as e:
    print(e.hint)     # "改用 runtime=process,但那样没有隔离"
```

docker 不通时**不会静默换成 `process`** —— 那等于把页面偷偷挪到你自己机器上跑,
没有隔离([api/server.md §3](../api/server.md#3-session-管理))。

`kill-server` 之后谁死谁活也取决于 runtime:`process` 跟着死,`container` 和 `remote` 活着
([cli/server.md §5](../cli/server.md#5-kill-server-之后会怎样))。

## 4. 分享链接

```python
web.view_url                                   # 你自己看,完整权限
web.share()                                    # 给别人,默认只读,1 小时
web.share(writable=True, ttl=3600)             # 可操作 —— 能碰你所有登录态
```

`share()` **默认 `read_only=True`**,和 API、CLI、ttyd 的默认一致。
lib 不做"代码里方便所以更宽松"这种事。

只读链接能看画面、能读 `GET`,所有写操作在对面返回 `403 read_only`。

## 5. lib 不管"有哪些 session"

**没有 `Server` 类,故意的。** lib 只有一个入口 `Webmuxd`,
它管的是**你手里这一个**:起来、用、停掉。

「这台机器上跑着哪些 session」「把死掉的都清了」是**运维**,不是写脚本 ——
那是 CLI 的活:

```bash
webmuxd ls
webmuxd kill -t stale
```

要在 Python 里做同样的事,直接打 `GET /api/sessions`([api/server.md §3](../api/server.md#3-session-管理))
或者 `subprocess` 调 CLI。**这是 lib 有意留的一个缺口**,不是忘了 ——
多一个类就多一套生命周期语义(它算不算持有 session?它析构时要不要杀?),
而这套语义只有运维脚本用得上。

同理,server 级事件流(`session.created` / `session.died` / `session.adopted`,
[api/server.md §4](../api/server.md#4-事件))lib 里没有对应方法。
`web.watch()` 只给你这一个 session 的事件。

## 6. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `Webmuxd(port=, runtime=, ...)` | 有就接管;没有就 `POST /api/sessions` |
| `web.status()` | `GET /api/status` |
| `web.reset()` | `POST /api/reset` |
| `web.kill()` | `DELETE /api/sessions/{name}` |
| `web.share(writable=, ttl=)` | `POST /api/live-token` `{read_only, ttl_s}` |
| `web.view_url` | `/s/{name}/` 或直连 `host:port` |

**lib 里没有的**(见 §5,故意的):`GET /api/sessions`、`GET /api/server`、
`POST /api/server/shutdown`、server 级 `WS /api/events`。
这几个是运维接口,用 CLI 或直接 `curl`。

**没导出去的**:构造的幂等语义(线上是 `GET` 探一下、没有再 `POST`,两步)、
`with` 自动清理。都是客户端组合,线上没有"建完就用"这一步。
