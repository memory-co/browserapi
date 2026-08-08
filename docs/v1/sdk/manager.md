# lib · `Webmuxd` 管理实例

导出成 [api/server.md](../api/server.md)。

**`Webmuxd()` 是个空壳。** 构造它不起容器、不占端口、不跑任何浏览器 ——
它只是"我要开始管 session 了"。**每 `create()` 一次才起一个 kasm。**

```python
from webmuxd import Webmuxd

web = Webmuxd()                                             # 纯管理实例,走本机 socket
web = Webmuxd(port=7800)                                    # 顺便把管理面暴露出去
web = Webmuxd("https://browser.internal:7800", token=TOKEN) # 连一个远端的
web = Webmuxd(socket="/tmp/x.sock")                         # 换 socket,= CLI 的 -S
web = Webmuxd(name="ci")                                    # = CLI 的 -L ci
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `port` | 不开 | **管理面自己的口**,和 session 的口无关 |
| `token` | 读 `WEBMUXD_TOKEN` | 走 socket 时不需要;走 TCP 必须有 |
| `socket` / `name` | `default` | 换一套互不可见的管理实例,语义同 tmux |
| `user` | `"api"` | 默认署名,底下所有 session 继承([README §4](README.md#4-user--署名)) |

**不给 `port` 就不占网络端口**,管理走 unix socket、靠文件权限鉴权
([api/server.md §6](../api/server.md#6-鉴权))。要让远端 CLI 或别的语言来管,才给它一个口。

## 1. 建、列、杀

```python
sess = web.create(name="work", runtime="container",
                  url="https://example.com", viewport="1280x800",
                  port=7900, volume="webmuxd-work", proxy="http://egress:3128")

web.sessions()                 # [Session] —— 每次都现场探活,不是读缓存
web.get("work")                # Session,没有就抛 SessionNotFound
web.has("work")                # bool
web.kill("work")               # 停掉并清理

web.info()                     # version / listen / sessions / runtimes / default_runtime
web.shutdown()                 # 等价 kill-server
```

`name` 不给就自动生成,像 tmux 的 `0` / `1` / `2`。重名抛 `SessionExists`。
`port` 不给就从 7900 往上找空闲 —— **一个 session 占两个口**
([session.md §1](session.md#1-一个-session-两个口))。

```python
with web.create() as sess:     # 退出时 kill
    tab = sess.open("https://example.com")
```

**只有 `create()` 建的才会被 `with` 关掉。** `web.get("work")` 拿到的是别人建的,
`with` 退出时不动它 —— 拿到手不等于有权杀。

`sessions()` **每次都现场探活** —— 文件只是线索,`alive()` 才是真相
([works/05 §6](../works/05-server-session-runtime.md))。

## 2. runtime 不可用时抛,不降级

```python
try:
    sess = web.create(runtime="container")
except RuntimeUnavailable as e:
    print(e.hint)     # "改用 runtime=process,但那样没有隔离"
```

docker 不通时**不会静默换成 `process`** —— 那等于把页面偷偷挪到你自己机器上跑,
没有隔离([api/server.md §3](../api/server.md#3-session-管理))。
想先看一眼再决定就查 `web.info().runtimes`,那是探测结果。

`kill-server` 之后谁死谁活取决于 runtime:`process` 跟着死,`container` 和 `remote` 活着
([cli/server.md §5](../cli/server.md#5-kill-server-之后会怎样))。

## 3. 多开就是多 create

```python
web = Webmuxd()
sessions = [web.create() for _ in range(4)]     # 四个容器,四个 Chrome,八个端口
```

**session 之间是真并行的**,一个 session 内部才是一次一个动作
([README §6](README.md#6-并发))。上限是机器。

## 4. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `Webmuxd()` | unix socket,不经 HTTP |
| `Webmuxd(port=)` / `Webmuxd(url, token=)` | `<host:port>/api` |
| `web.create(...)` | `POST /api/sessions` |
| `web.sessions()` | `GET /api/sessions` |
| `web.get(name)` / `web.has(name)` | `GET /api/sessions/{name}` |
| `web.kill(name)` | `DELETE /api/sessions/{name}` |
| `web.info()` | `GET /api/server` |
| `web.shutdown()` | `POST /api/server/shutdown` |

**没导出去的**:`with` 自动清理、`has()` 是 `get()` 吞掉 404。
