# k · 一个 server 一个口,session 住在它下面

**一句话**:端口从 session 上收回到 server 上 —— `webmuxd start --port 7900`
起服务,`webmuxd new --id demo` 加一个 session。
这不是新架构,是**把一个早就该拆掉的历史包袱拆掉**。

## 1. 为什么现在是"一个 session 一个端口"

因为 v1 的画面来自 kasm 那个容器镜像,而**它的 web 口不归我们控制**。
v1 自己把这条写在了对照表里
([v1/works/05 §2](../../v1/works/05-server-session-runtime.md#2-对照表)):

> **端口那条是硬约束,也是和 tmux 差别最大的一处。**
> tmux 的 server 用一个 socket 承载所有 session;kasm 不行 ——
> 每个 session 自带一块 VNC 屏,而且 webmuxd 的 API 是另一个口。

于是 v1 设计了一个 `:7800` 的 server,存在意义之一就是
"**对外只开一个口**,按名字把两个都代理进去"。

**v2 把 kasm 换掉了**([c](c-view.md)):画面是我们自己产的,
观看端是我们自己写的([e](e-client.md) · `webmuxjs/client/`)。
**那条硬约束没有了,而那个形状留了下来** —— 而且连那个 server 都没建,
只剩一个文件登记簿在冒充它。

## 2. 目标形状

```
webmuxd start --port 7900          # 一个 server,一个口
    └─ 打开 http://127.0.0.1:7900/ → "暂无 session"

webmuxd new --id demo              # 不带 --port 了
    └─ 刷新 → 列表里有了 demo,点进去就是那个浏览器

webmuxd new --id scrape
    └─ 两个 session,同一个口
```

对照 tmux,这一步之后**对得上了**:

| tmux | 现在 | 之后 |
| --- | --- | --- |
| 一个 server 持有全部 session | 没有 server,一个文件登记簿 | **一个 server 持有全部 session** |
| `tmux new -s demo` 不给端口 | `webmuxd new --port 7900` | `webmuxd new --id demo` |
| `tmux ls` 问 server | 读那个文件再逐个探活 | 问 server |
| `tmux kill-server` | 逐个 kill | 真的 kill-server |

## 3. 那个口上看到什么

**它就是 ttyd 那个口,只是前面多一层"选哪个"。**

```
GET /                → session 列表(空的时候一句"暂无 session",带上怎么建)
GET /s/demo/         → demo 的观看页,和今天的一模一样
```

列表页是[内置页](e-client.md)的一部分 —— 同样的定位:
**验链路的,不是产品界面**。一行一个 session:名字、几个 tab、画面走哪条、活着没有。

> **不做仪表盘。** 判据还是那句:tmux 会做这个吗?
> `tmux ls` 就是一行一个,没有 CPU 曲线。

## 4. 路由:`/s/<id>/` 前缀

今天 `serve.py` 里所有 handler 拿 session 都走同一个入口:

```python
def _s(request):  return request.app["session"]        # 35 处调用全走它
```

所以这一步是**加前缀 + 换那一个函数**:

```python
r.add_get("/s/{sid}/api/tabs", h_tabs)     # 路由多一段
def _s(request):  return request.app["sessions"][request.match_info["sid"]]
```

WS 那三条通道同理:`/s/demo/channel/cdp`。
观看端那边 `api.ts` 已经是唯一拼地址的地方,加一个 base 前缀就够
(`webmuxjs/client/src/api.ts`)。

**认不出的 sid 回 404,不猜。**

## 5. 一个进程,还是每个 session 一个进程

**一个进程。** server 里 N 个 `Session` 对象,每个下面挂自己的 chrome 子进程。

另一条路是"server 代理到每个 session 自己的 sessiond",但那样**每一帧多一跳** ——
而帧是热路径,那 28 字节定长头存在的全部意义就是别在这条路上花钱
([e1](e1-wire-format.md))。为一个我们并不需要的隔离度付这个,不值。

代价说清楚:**server 挂了,所有 session 的连接和 tab 表一起没**。
和 tmux 一样(`process` 的 pane 是 server 的子进程)。

> chrome 进程本身其实活着 —— v1 设想过"重启后按 label 重新收养"
> ([v1/works/05 §3.2](../../v1/works/05-server-session-runtime.md))。
> **这次不做**,但结构上没有挡住它。

## 6. CLI

```
webmuxd start   --port 7900 [--bind 127.0.0.1]   起 server
webmuxd new     --id demo [--transport vnc]      加一个 session
webmuxd ls                                       问 server 要列表
webmuxd kill    -t demo                          关一个
webmuxd kill-server                              全关
```

**`start` 是显式的,不按需自启。** tmux 能自启是因为它用 socket,
没有端口要挑;我们有,而[那条规矩](h-runtime.md#6-端口由你给)是
"端口由你给,替你猜一个只会让配置与实际不符"。

所以没起 server 时 `webmuxd new` **报错并说该跑哪一行**,不偷偷起一个:

```
没有在跑的 server —— 先 `webmuxd start --port 7900`
```

`-L name` / `-S path` 那套换 socket 的做法照抄 tmux:**换 socket = 换一套独立的 server**。
今天的文件登记簿正好在 `$XDG_RUNTIME_DIR/webmuxd/<name>/`,位置不用动,
里面从"session 表"变成"server 在哪个口上"。

## 7. SDK

```python
web  = Webmuxd(port=7900)            # ← 端口在这儿
sess = web.session(id="demo")        # ← 不再要端口
tab  = sess.open("https://example.com")
```

`Webmuxd()` 今天是个"空壳管理实例",`session()` 才起东西。之后它变成
**一个 server 的客户端** —— 而这正是 [v1/sdk](../../v1/sdk/README.md) 里
`Webmuxd()` ↔ server 那一行原本的意思。

不带 `port` 就去读那份记录("server 在 7900 上"),读不到就报错说去 `start`。
**显式传入优先**,和[配置那条老规矩](d-install.md)一致。

## 8. 这次不做的

- ❌ **不做多租户 / 配额 / 计费。** tmux 不做
- ❌ **不做 session 之间共享浏览器。** 一个 session 一个 chrome,不变
- ❌ **不做重新收养。** §5 那条,结构上留着口子
- ❌ **不改画面、输入、动作、日志。** 这一步只动"谁持有 session、地址长什么样"

## 9. 有多大

| 动什么 | 估计 |
| --- | --- |
| `serve.py` 路由加前缀 + `_s()` 换一句 | 小 —— 35 处调用都不用改 |
| server 进程:持有 N 个 session、建、找、关 | `sessions.py` 已经有单个的编排,加一层表 |
| 列表页 + `/s/<id>/` 路由 | `webmuxjs/client/` 加一个视图 |
| CLI:`start` / `new` 去掉 `--port` / `ls` 改成问 server | 中 |
| 文件登记簿:从"session 表"变成"server 在哪" | 变简单了 |
| 文档:v1 的 cli/sdk/api 里所有"一个 session 一个端口" | 中 |

**没有一处是重写。** 最大的那块是 CLI 和文档。

## 10. ↔ 别处

| | |
| --- | --- |
| 为什么当初是一个 session 一个端口 | [v1/works/05 §2](../../v1/works/05-server-session-runtime.md#2-对照表) |
| 端口由你给 | [h §6](h-runtime.md#6-端口由你给) |
| 观看端那一层 | [e](e-client.md) · `webmuxjs/client/` |
| 目录怎么摆 | [j](j-layout.md) |
