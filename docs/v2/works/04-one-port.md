# 04 · 一个口

**一句话**:画面和 API 落在同一个 HTTP 端口上。`view_port` 退役,
`api_port` 改叫 `port`,VNC 的用户名口令换成 webmuxd 自己的 token。

> **加了 xpra 之后仍然是一个口。** xpra 自己的 ws 只绑在回环上,
> 由 sessiond 反代成 `WS /xpra`,token 在我们这儿校验一次
> ([11 §2.2](11-xpra.md#22-那条-xpra-连接要不要经过我们))——
> 人拿到的还是一个地址。
>
> **落地在** [`serve/app.py`](../../../webmuxd/serve/app.py) ·
> [`view/relay.py`](../../../webmuxd/view/relay.py),
> 测试在 [`tests/one_endpoint/`](../../../tests/one_endpoint/) ·
> [`tests/the_http_face/`](../../../tests/the_http_face/)。

## 1. 两个口塌成一个

v1 的 session 有两个口([v1/sdk/session.md §1](../../v1/sdk/session.md#1-一个-session-两个口)):
6901 是 KasmVNC 的,7900 是我们的 API。那不是设计选择,是**没得选** ——
画面是别人的服务,只能另开一个口。

```python
# v1
sess = web.session(id="work", api_port=7900, view_port=8090)
sess.view_url        # https://127.0.0.1:8090   ← 别人的服务
sess.api_url         # http://127.0.0.1:7900    ← 我们的

# v2
sess = web.session(id="work", port=7900)
sess.view_url        # http://127.0.0.1:7900/   ← 同一个
sess.api_url         # http://127.0.0.1:7900/api/
```

一个口之后的路由:

| 路径 | 给谁 |
| --- | --- |
| `GET /` | 人 —— 内置的观看页面(画面 + 我们画的 tab 条和地址栏) |
| `WS /api/view` | 画面帧下行 + ack / 输入上行([02](02-frame-protocol.md)) |
| `WS /api/events` | tab 增删改事件,和 v1 一样 |
| `/api/…` | 代码 —— 和 v1 **完全一致**的那套 |

v1/sdk/session.md 里那句"**这是和 tmux 差别最大的一处**:tmux 一个 socket 复用所有 session,
kasm 不行 —— 每个 session 自带一块屏,端口没法复用" —— **这条差别在 v2 里减半了**:
每个 session 仍然一个端口(因为每个 session 一个浏览器,[07](07-runtime.md)),
但不再是每个 session 两个端口。

## 2. `GET /` 是内置的,但它不是"界面"

v1 的[「明确不做」](../../v1/works/README.md#明确不做)里有一条"**不带界面** —— 画面和 API
两个干净的口,怎么摆是上层的事"。v2 内置了一个页面,要说清楚这是不是违约。

**不是。** 区别在于这个页面**没有产品决策在里面**:

- 它是画面 + 一条 tab 条 + 一个地址栏,**没有会话列表、没有登录页、没有设置面板、没有仪表盘**
- 它存在的唯一理由是**「跑起来之后用浏览器打开这个地址,链路通没通一眼就看出来」**
  —— 这正是 README 现在推荐的验证方式,v1 里那一眼看的是 kasm 的前端
- 上层要自己画,照旧:`WS /api/view` 拿帧,`/api/tabs` 拿 tab 表,
  和内置页面用的是**同一组接口,没有私货**

判据还是那句:**tmux 会做这个吗?** ttyd 带一个默认前端,tmux 自己不带 ——
而 v2 里 ttyd 那一半是我们的,所以带一个默认前端是本分。

## 3. 读和写是两个 token

v1 的 `share()` 已经是"默认只读"([v1/sdk/session.md §3](../../v1/sdk/session.md#3-分享链接)),
但那个只读**只覆盖得了 API 那一半**:

> 只读链接能看画面、能读 `GET`,所有写操作在对面返回 `403 read_only`。

画面那一半做不到 —— VNC 的口令只有"给不给",给了就是全权,而我们不在 RFB 链路上,
没有任何位置能拦下一次鼠标点击。**"默认只读"在 v1 是个半截承诺。**

v2 里输入通道是我们自己的,于是只读变成一行判断:

```
观看者的 WS 连接
  ├─ 帧下行           两种 token 都发
  └─ 上行 input.*     写 token → 翻译成 CDP Input.*
                      读 token → 丢弃,不回报错(见下)
```

三条要求:

- **服务端丢弃,不是前端 disable。** 前端把按钮变灰是给人看的,不是安全边界。
  拿到只读 token 的人自己写个 WS 客户端直接发 `input` 帧,必须被服务端挡住。
- **丢弃时不逐事件回报错。** 鼠标移动一秒几十个事件,逐个回 `403` 等于自己 DoS 自己。
  连接建立时告知一次权限,之后静默丢弃。
- **默认只读。** 和 v1、和 ttyd(`-W` 才可写)一致。lib 不做"代码里方便所以更宽松"。

```python
sess.view_url                        # 你自己,完整权限
sess.share()                         # 给别人,默认只读,1 小时
sess.share(writable=True, ttl=3600)  # 可操作 —— 能碰你所有登录态
```

`share()` 的签名和 v1 **一模一样**,变的只是它现在真的做到了。

## 4. 认证:token 在 URL 里,不在 header

画面页面是人用浏览器打开的,粘一个 URL 就得能进 —— 所以 token 只能在 query 里:

```
http://host:7900/?t=<token>
```

页面拿到之后自己带着它连 `WS /api/view?t=<token>`。这有个已知代价:
**token 会进浏览器历史、进 Referer、进反代日志**。三条缓解:

- 短 TTL,默认 1 小时(和 v1 `share()` 一致)
- 页面加载后 `history.replaceState` 把 query 抹掉
- 程序化调用走 `Authorization: Bearer`,URL 里那条**只给人用**

v1 的 VNC 口令(`VNC_PW`,kasm 还要求 ≥6 位、用户名写死 `kasm_user`)整个退役 ——
那是镜像的规矩,不是我们的。`sess.view_login` / `sess.view_password` 两个字段一并删掉,
`sess.view_url` 直接带 token。

## 5. 端口是你给的,这条不变

v1 的[「端口必须你给」](../../../README.md)不变,理由也不变:
**端口是部署决定的,替你猜一个只会让配置和实际对不上。**

变的只是从两个减成一个 —— 而这恰恰让那条规矩更好守:v1 里要同时想清两个端口
(还得知道 kasm 默认 6901、jlesage 默认 5800 这类镜像细节),v2 里只有一个数字。

## 5.1 绑哪个地址:默认只绑回环

**`--bind`,不是 `--host`。** 这个 CLI 里 `-H/--host` 已经占着"连哪台机器"
(客户端侧)的意思了,再拿它表示"绑哪个地址"必然打架。所以服务端那一侧
统一叫 `--bind`,`sessiond` 那边也一样(旧名 `--host` 留作别名)。

```bash
webmuxd new --id work --port 7900                  # 只绑 127.0.0.1
webmuxd new --id work --port 7900 --bind 0.0.0.0   # 对外,而且会警告
```

**默认必须是回环,而且这条在 v2 里比 v1 更要紧:**

| | v1 | v2 |
| --- | --- | --- |
| sessiond 默认绑 | `0.0.0.0` | **`127.0.0.1`** |
| 那个 `0.0.0.0` 是谁的 | **容器内的** —— 外面还有 `docker -p` 决定暴不暴露 | **真的 0.0.0.0**,没有容器了 |
| 那个口上有什么 | 纯 API | **画面口 —— 打开就能直接操作浏览器** |

v1 那个默认在当时是安全的(容器挡了一层);v2 把容器删掉之后
**前提没了,而默认值当时忘了跟着改** —— 直到有人问"这默认绑 0.0.0.0 吗"
才发现。要对外是你的决定,但得显式说,而且我们会警告:

```
⚠ 画面口绑在 0.0.0.0 —— **这台机器网络能到的人,拿到 token 就能操作这个浏览器**
```

## 6. ↔ 别处

| | |
| --- | --- |
| 帧和输入在这条 WS 上的格式 | [02](02-frame-protocol.md) · [03](03-input.md) |
| 一个 session 一个浏览器,所以一个端口 | [07 §5](07-runtime.md#5-起浏览器就是起一个进程) |
| v1 的 session 形状 | [v1/sdk/session.md](../../v1/sdk/session.md) |
| 哪些字段被删了 | [08 §1](08-migration.md#1-变了的东西) |
