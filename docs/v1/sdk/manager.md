# lib · `Webmuxd` 管理实例

导出成 [api/server.md](../api/server.md)。

**`Webmuxd()` 是个空壳。** 构造它不起容器、不占端口、不跑任何浏览器 ——
它只是"我要开始管 session 了"。**每 `session()` 一次才起一个 kasm。**

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
| `port` | 不开 | **管理面自己的口**,和 session 的两个口无关 |
| `token` | 读 `WEBMUXD_TOKEN` | 走 socket 时不需要;走 TCP 必须有 |
| `socket` / `name` | `default` | 换一套互不可见的管理实例,语义同 tmux |
| `user` | `"api"` | 默认署名,底下所有 session 继承([README §4](README.md#4-user--署名)) |

**不给 `port` 就不占网络端口**,管理走 unix socket、靠文件权限鉴权
([api/server.md §6](../api/server.md#6-鉴权))。要让远端 CLI 或别的语言来管,才给它一个口。

## 1. `session()` —— 拿一个 session

**只有一个入口,幂等:同一个 `id` 永远给你同一个 session。**

```python
sess = web.session(id="work", api_port=7900, view_port=6901, runtime="container")
sess = web.session(id="work")            # 已经有了 → 同一个,后面的参数都不用再给
```

四个参数决定一个 session:**它叫什么、占哪两个口、怎么被拉起来。**

没有 `create()`,也没有 `get()` —— "建"和"取"是同一件事,像 `tmux new -A -s`。
不用先判断存不存在,也不会因为并发建两次。

**同一个 `id` 返回的是同一个 Python 对象:**

```python
web.session(id="work") is web.session(id="work")   # True
```

这不只是省事:每个 `Session` 背后有一条 WS 和一份内存里的 tab 表
([README §3](README.md#3-tab-的状态在内存里))。给你两个对象就是两条连接、
两份可能不一致的表。

### 端口必须你给

```python
web.session(id="work")                    # ✗ 这个 id 还不存在 → BadRequest,缺 port
web.session(id="work", api_port=7900, view_port=6901)   # ✓
```

**不自动分配。** 端口是**部署决定**的 —— compose 或 k8s 里映射写死在配置文件里,
我们在这边"从 7900 往上找空闲"只会让配置和实际对不上,而且你得再问一次才知道分到了哪。
一个 session 还占**两个**口([session.md §1](session.md#1-一个-session-两个口)),
自动分配还得替你猜第二个。

**已经存在时端口可以不给**;给了但对不上就抛 `BadRequest`,不静默忽略 ——
你写了 7900 结果连到 7901 上,是那种查半天的错。

### `runtime` —— 怎么把它拉起来

```python
web.session(id="work", api_port=7900, view_port=6901, runtime="container")  # 默认
web.session(id="dev",  api_port=7901, view_port=6902, runtime="process")
web.session(id="prod", runtime="remote", endpoint="https://browser.internal:7800")
```

| runtime | 是什么 | 什么时候用 |
| --- | --- | --- |
| `container` | `docker run` 一个 kasm 镜像 | **默认**。要隔离、要能扛 server 重启 |
| `process` | 直接在本机拉 Xvnc + Chromium + sessiond | 没 docker、想秒起、**不要隔离也行** |
| `remote` | 接一个已经在别处跑着的 | 浏览器在另一台机器上 |

**这是三层概念里的第三层**([works/05 §4](../works/05-server-session-runtime.md#4-runtime--唯一多出来的概念))——
也是**唯一一处 tmux 没有的东西**。它只在这一次出现:**拿到 `sess` 之后,
所有代码对三种 runtime 完全一样**,这是这层抽象的全部意义。

`process` 和 `container` 的差别在 `kill-server` 之后才看得出来:
`process` 是 server 的子进程,跟着死;`container` 活着,server 重启后自动重新接管
([cli/server.md §5](../cli/server.md#5-kill-server-之后会怎样))。

### 其余参数

```python
sess = web.session(id="work", api_port=7900, view_port=6901,
                   url="https://example.com", window_size="1024x768",
                   volume="webmuxd-work", proxy="http://egress:3128")
```

**上面这些(含 `runtime`)只在需要新建时有意义** —— 已经存在就直接返回那个,
不会拿去改它。想换配置就 `kill()` 了重来。

## 2. 列和杀

```python
web.sessions()                 # [Session] —— 每次都现场探活,不是读缓存
web.kill("work")               # 停掉并清理
web.info()                     # version / listen / sessions / runtimes / default_runtime
web.shutdown()                 # 等价 kill-server
```

`sessions()` **每次都现场探活** —— 文件只是线索,`alive()` 才是真相
([works/05 §6](../works/05-server-session-runtime.md))。想知道某个 id 在不在,
看这个列表就行,没有单独的 `has()`。

```python
with web.session(id="tmp", api_port=7901, view_port=6902) as sess:
    tab = sess.open("https://example.com")
# 退出时 kill —— 但只有这次调用真的把它建起来时才 kill
```

**接管到一个已经在跑的,`with` 退出时不动它** —— 拿到手不等于有权杀。

## 3. runtime 不可用时抛,不降级

```python
try:
    sess = web.session(id="work", api_port=7900, view_port=6901)
except RuntimeUnavailable as e:
    print(e.hint)     # "改用 runtime=process,但那样没有隔离"
```

docker 不通时**不会静默换成 `process`** —— 那等于把页面偷偷挪到你自己机器上跑,
没有隔离([api/server.md §3](../api/server.md#3-session-管理))。
想先看一眼再决定就查 `web.info().runtimes`,那是探测结果。

`kill-server` 之后谁死谁活取决于 runtime:`process` 跟着死,`container` 和 `remote` 活着
([cli/server.md §5](../cli/server.md#5-kill-server-之后会怎样))。

## 4. 多开就是多要几个 id

```python
web = Webmuxd()
sessions = [web.session(id=f"w{i}", api_port=7900+i, view_port=6901+i)
            for i in range(4)]                 # 四个容器,四个 Chromium,八个端口
```

**session 之间是真并行的**,一个 session 内部才是一次一个动作
([README §6](README.md#6-并发))。上限是机器。

## 5. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `Webmuxd()` | unix socket,不经 HTTP |
| `Webmuxd(port=)` / `Webmuxd(url, token=)` | `<host:port>/api` |
| `web.session(id=, api_port=, view_port=, ...)` | `GET /api/sessions/{id}`,404 就 `POST /api/sessions` |
| `web.sessions()` | `GET /api/sessions` |
| `web.kill(id)` | `DELETE /api/sessions/{id}` |
| `web.info()` | `GET /api/server` |
| `web.shutdown()` | `POST /api/server/shutdown` |

**没导出去的**:幂等语义(线上是 `GET` 探一下、没有再 `POST`,两步)、
同 id 返回同一个对象、`with` 自动清理。都是客户端组合。
