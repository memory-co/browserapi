# 08 · 浏览器 runtime:两个端点就是全部契约

webmuxd 对"浏览器从哪来"只提两个要求:

```
一个画面端口     <host>:<port>              ← 给人:打开就能看,能上手
一个 CDP 端点    http://<host>:<port>       ← 给代码:webmuxd 订阅它
```

**产出这两样的东西,就是一个 runtime。** 是不是容器、里面跑的是 KasmVNC 还是
TigerVNC、镜像谁做的、甚至在不在这台机器上 —— 都不在契约里。

这篇讲的就是这条边界:**它划在哪、为什么划在这儿、新的东西怎么进来。**

## 1. 分界线:runtime 之上没有一行 `if`

runtime 的职责是把一台机器变成上面那个形状。之后 sessiond 只知道:

```bash
python3 -m webmuxd.serve --cdp http://127.0.0.1:59213 --port 7900
```

**这条命令在所有 runtime 下完全一样。** `core/` 的 CDP 客户端、tab 表、定位、观测、
日志,`serve/` 的路由,`client/` 的三个对象,CLI 的每一条子命令 ——
**没有任何一处 `if runtime ==`**。

所以这篇要论证的不是"我们努力让几种 runtime 长得像",而是:
**它们本来就在这条线以下分岔,线以上根本不知道下面发生了什么。**

```
        ┌── process     本机拉起 chromium + Xvnc
        │
runtime ┼── container   docker run 一个现成的浏览器镜像
        │
        └── remote      别人已经把两个端点给你了
                                    │
        ─────────────────────────────┼──────  ← 边界:两个端点
                                    │
                                sessiond
                                    │
                    core / serve / client / cli   ← 全都不知道下面是什么
```

## 2. 判据:哪一半在契约里

> **CDP 在契约里,画面不在。**

这条判据和 tmuxd 那条是同一条(见 tmuxd `works/06 §1`:*ttyd 是实现细节,
tmux 是契约的一部分*)。判的不是"谁更重要" —— 两样都缺不得,少一个这东西就不成立。
判的是另一件事:**用户会不会直接碰到它。**

**CDP 是契约。** webmuxd 开篇那句承诺是"tab 表就是浏览器的 target 表,不是黑盒":
`reason` 分得清是你点的还是代码开的,靠的是 `targetInfo.openerId`;
逃生舱是**你自己拿 DevTools 连上去**,看到的和我们看到的是同一份。
这些全都建立在"webmuxd 的浏览器和你的浏览器是同一个"之上。
换掉 CDP,等于换掉 webmuxd。

**画面不在契约里。** webmuxd 对那个端口做的唯一一件事,是**把 URL 报出来**:

```python
sess.vnc_url        # https://127.0.0.1:8090
sess.vnc_user       # 谁能进去,是起的时候定的
sess.vnc_password
```

它不代理、不转发、不解析里面一个字节,也不知道那边是 WebSocket 还是 WebRTC。
所以**换一个 VNC 实现,webmuxd 一行都不用改** —— 这正是 §5 能成立的原因。

这条判据带来一个直接后果:**画面那一半可以按体验挑,CDP 那一半只能按能不能用挑。**

## 3. 难的是 CDP 那一半

画面天生就是给外面看的,做镜像的人一定会把它暴露好。CDP 恰恰相反 ——
**Chromium 拒绝把调试口交出去。**

[`chrome/browser/devtools/remote_debugging_server.cc`](https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/remote_debugging_server.cc)
里 `TCPServerSocketFactory::CreateLocalHostServerSocket`:

```cpp
if (socket->ListenWithAddressAndPort("127.0.0.1", port, kBackLog) == net::OK)
  return socket;
if (socket->ListenWithAddressAndPort("::1", port, kBackLog) == net::OK)
  return socket;
```

地址硬编码,这个文件里**根本没有读 `kRemoteDebuggingAddress`**。上游态度见
[crbug 41487252](https://issues.chromium.org/issues/41487252):这个 flag
"presents a security issue and should not be used",准备删掉。

实测印证(两个 build,跨发行版跨 libc,参数都确认出现在 `/proc/<pid>/cmdline` 里):

| Chromium | 环境 | 给了 `--remote-debugging-address=0.0.0.0` | 实际绑 |
| --- | --- | --- | --- |
| 139 | Ubuntu / kasmweb | 是 | `127.0.0.1` |
| 124 | Alpine musl | 是 | `127.0.0.1` |

同一趟参数进去的 `--remote-debugging-port` **生效了**,`address` 没有 ——
因为它俩根本不在同一段代码里。

而 `docker -p` 是 DNAT 到容器的 **eth0**,`127.0.0.0/8` 每个 network namespace
各自一份且只能从本 namespace 的 lo 进出(别的路径来的 127.x 包会被当 martian 丢掉)。
**"DNAT 到另一个 namespace 的 loopback"这条规则写不出来**,不是 docker 偷懒。

### 3.1 所以 runtime 的真正工作,是把 CDP 搬到一个能连的地方

只有三种搬法,**穷尽了**:

| | 做法 | 现状 |
| --- | --- | --- |
| **A** | 容器里垫一跳:`0.0.0.0:<外> → 127.0.0.1:<内>` | **在用** —— 但这一跳属于**镜像**,不属于 runtime |
| **B** | 共享 network namespace(`--network host`),两个 loopback 合成一个 | **在用** —— 见 §6.2,这是唯一的跑法 |
| **C** | 把订阅方搬进去,CDP 一步不出容器 | 弃了 —— 要求镜像里装 webmuxd |

**A 和 B 是叠着用的,而且分工很清楚:**

- **A 在镜像里。** 我们给两个底座各加了一层 wrapper([docker/](../../../docker/)):
  底座自带转发就打开它(jlesage 的 socat),没有就补一个(kasm,用镜像自带的
  `python3`)。它只要求镜像里有个能监听转发的东西,**不要求装我们的代码**。
- **B 在 runtime 里。** 有了 A,CDP 已经听在容器的 `0.0.0.0` 上;B 让那个
  `0.0.0.0` 就是宿主机的 —— 于是连 `-p` 都不需要了。

**runtime 因此什么都不用 exec**,它只在宿主机上等那个口。

> Chromium 还会校验 Host 头防 DNS rebinding。实测**IP 字面量放行、域名拒绝**
> (`Host: 127.0.0.1:<任意口>` → 200,`Host: evil.com` → 500)。我们从
> `127.0.0.1` 连,不受影响。
>
> `webSocketDebuggerUrl` **照抄请求的 Host 头**,所以 `CDP._browser_ws` 里那段
> netloc 改写是防御性的,不是链路能通的原因。

## 4. 画面那一半:三种实现,实测排名

同一台机器、同一个公网端口、同一条链路、同一个页面(维基百科长条目)对比:

> **KasmVNC > TigerVNC > Selkies**

| | KasmVNC | TigerVNC + noVNC | Selkies |
| --- | --- | --- | --- |
| 代表镜像 | `kasmweb/chromium` | `jlesage/chromium` | `linuxserver/chromium` |
| 传输 | 自有编码,按区域重传 | 经典 RFB 图块 | **WebRTC** 视频流 |
| 体验 | **最好** | 其次 | 最弱(疑似带宽/编码取向) |
| 画面口 | 6901 https | 5800 http/https | 3001 https(3000 那个 http 口不可用) |
| 认证 | `VNC_PW`,用户名写死 `kasm_user` | `WEB_AUTHENTICATION_*`(要同时 `SECURE_CONNECTION=1`) | `CUSTOM_USER` + `PASSWORD` |
| 注入浏览器参数 | `APP_ARGS` | `CHROMIUM_CUSTOM_ARGS` | `CHROME_CLI` |
| CDP 转发 | 无,wrapper 补一个 | **内置**,wrapper 只是打开它 | 无 |

**Selkies 那条要注意的是**:它的前端要 secure context,http 口只会回一句
"This application requires a secure connection (HTTPS)"。

**画面排名和契约无关。** 按 §2 的判据,这一列全是实现细节 —— 所以它可以随时按体验
换,而**换的时候 webmuxd 不动**。

## 5. 一个新镜像怎么进来

接一个没见过的浏览器镜像,只需要回答**五个问题**。答得出来就能接,答不出来就接不了。

| | 问题 | kasmweb | jlesage | linuxserver |
| --- | --- | --- | --- | --- |
| ① | 画面在哪个端口,怎么改 | 6901 / `-p` | 5800 / `WEB_LISTENING_PORT` | 3001 / `-p` |
| ② | 怎么设访问口令 | `VNC_PW`(**≥6 位**) | `WEB_AUTHENTICATION_*` | `CUSTOM_USER`+`PASSWORD` |
| ③ | 怎么往 Chromium 塞参数 | `APP_ARGS` | `CHROMIUM_CUSTOM_ARGS` | `CHROME_CLI` |
| ④ | 启动页怎么给 | `LAUNCH_URL` | **没有**(见下) | 和参数同一个变量 |
| ⑤ | CDP 怎么出来 | wrapper 补一跳 | 内置 socat,wrapper 打开它 | 要自己挂 |

④ 那格 jlesage 是**故意留空的**:它只有 `CHROMIUM_APP_URL`,而那个映射到
`--app=`(无边框应用窗口),不是普通启动页。与其用错模式,不如不声明 ——
webmuxd 连上之后自己 `open()` 就是了。**profile 里宁可缺一项,也不填一个语义不对的。**

这五个问题就是一份 **profile** 的全部内容,而且它已经**做成机器可读的了** ——
写在镜像的 `webmuxd.*` 标签里,`docker inspect` 就能读到,所以
**加一个新镜像不用改 webmuxd 的代码**(见 [docker/README](../../../docker/README.md))。

它是一张**事实表**,不是配置项:
描述的是"这个镜像长什么样",不是"你想怎么用"。webmuxd 没有配置文件,
参数从 lib 传([cli/README §5](../cli/README.md));profile 是对**外部世界**的描述。

**默认是 `kasmweb/chromium`** —— §4 那个体验排名说了算,而画面就是这东西的全部意义。
`--image` 指别的镜像时,得同时能说清它的 profile。

### 5.1 接之前要先量三件事

镜像的文档常常没写,而这三件都在现场咬过人:

**① 它把 Chromium 的调试口开在哪,是不是真的开了。** 别信参数名 ——
先 `docker exec ... cat /proc/net/tcp`,看 `0100007F:2406` 在不在。
我在 kasm 上按 `CHROME_ARGS` 写过一次,那个变量镜像里根本不认,**被静默忽略**:
容器起得好好的,参数悄无声息地丢了,看着像生效了。

**② 它有没有用带名字的抽象 unix socket。** 这决定了它能不能共享 netns ——
见 §6.2。`docker exec <cid> grep -oE '@[^ ]+' /proc/net/unix` 一眼就能看出来。

**③ 它的启动脚本假设了什么。** kasm 的 `vnc_startup.sh` 死等一张叫 `eth*` 的网卡,
在 bridge 下永远成立(docker 正好这么命名),换个网络模式就死循环 ——
而症状是"容器 Up,日志停住,没有任何报错"。

## 6. 不是容器也行

契约里没有"容器"两个字,所以这些都是合法的 runtime:

### 6.1 `process` —— 本机三个进程

```
chromium --remote-debugging-port=<free>   →  127.0.0.1:<free>   CDP
Xvnc :N -rfbport <vnc_port>               →  127.0.0.1:<vnc>    画面
```

秒起,**但没有隔离**(页面跑在你自己机器上),而且没有 Xvnc 就只有 API 没有画面 ——
**这件事要说出来**,装作有画面比没画面更糟。

它是 server 的子进程,`kill-server` 跟着死([works/05 §3.2](05-server-session-runtime.md))。

### 6.2 `--network host` —— 这是唯一的跑法

共享 netns 之后,容器里的 `127.0.0.1` **就是**你的 `127.0.0.1`。这买到的是
**调试用的浏览器能打开你自己机器上跑着的页面** —— 而开发服务器常常只绑 loopback,
bridge 下根本够不着(`host-gateway` 走的是 eth0,那儿没人听)。

为它做端口转发是一整套机制:要么开 session 时预先列端口(而那个问题没有答案),
要么按需挂 + 导航失败自愈重试。**共享 netns 把这套机制整个消掉了** ——
所以 `--forward` 那条路砍了,不留开关。

代价两条,**都不绕**:

- **没有网络隔离。** 容器里那个 Chromium 和宿主共用网络栈。
- **能不能一机多开取决于镜像** —— 支持的就支持,不支持就不支持,
  标签 `webmuxd.host_network` 如实写着。硬前提是:**那个镜像不能用带名字的
  抽象 unix socket。**

抽象 socket(`sun_path[0] == '\0'`)**归 network namespace 管**,不是文件系统。
两个容器共享 netns,就共享这个命名空间。

**KasmVNC 一机只能一个。** [`TcpSocket.cxx:661`](https://github.com/kasmtech/KasmVNC):

```c
sprintf(sockname, ".KasmVNCSock%u", getpid());
...
addr.sun_path[0] = '\0';                 // ← 抽象命名空间
if (bind(internalSocket, ...)) throw SocketException("failed to bind socket", errorNumber);
```

名字就是 **Xvnc 的容器内 PID**。而每个 kasm 容器启动流程完全一样 → PID 也一样 →
第二个 session 死在 `vncExtInit: failed to bind socket: Address already in use`。
(报错文案能精确定位:TCP 那次 bind 失败的文案是
`failed to bind socket, is someone else on our -websocketPort?`,而我们看到的是
**光秃秃的那句** —— 所以冲突在 AF_UNIX 上,给独立 `rfbport` 一点用都没有。)

这不是疏忽。issue #45(2021)标题就是 *Add pid to the internal socket name*,
正文一句:*Allows multiple instances of KasmVNC to run at the same time on different ports.*
—— **`getpid()` 正是为多实例引入的唯一性标识**,在普通主机上完全成立。
没料到的是容器把"同一个 netns"和"同一个 pidns"这个隐含前提拆开了。
[issue #363](https://github.com/kasmtech/KasmVNC/issues/363) 报的就是这个,至今 open。

`--pid host` 能让 PID 唯一,但会砸掉另一头:kasm 用 `pgrep chromium` 判断浏览器活没活,
共享 PID 空间后第二个容器看见第一个的 chromium,**再也不拉起自己那个**。
解开一个就绑住另一个 —— 所以**不绕**,就是一机一个。

(kasm 在 host 网络下还有第二个坎:它的启动脚本死等一张叫 `eth*` 的网卡,
而宿主机的网卡叫 `ens4` 之类。这个坎**在 wrapper 镜像里补掉了** ——
底座镜像本身不动,见 [docker/](../../../docker/)。)

**TigerVNC 过得去。** jlesage 给 Xvnc 的参数:

```
Xvnc -nolisten tcp -nolisten local -listen unix \
     -rfbunixpath=/tmp/vnc.sock -rfbport=<配置来的> ... :0
```

**决定成败的只有 `-nolisten local`** —— 它关掉 X 的抽象 socket;RFB 又走
**文件系统**上的 socket(`-rfbunixpath`)。于是抽象命名空间里只剩内核给的匿名
autobind(`@f0fa9` 这种五位十六进制,天生各不相同),**一个自己起名字的都没有**。

> `-rfbport` 不在这条判据里。早先这里写的是 `-rfbport=-1`(RFB 完全不开 TCP),
> 那只是某一次配置下的取值 —— 实测也见过 `-rfbport=5900`。**但它不影响结论**:
> 一个 TCP 端口撞了顶多是端口冲突,改一下就好;抽象 socket 的名字撞了是没得改的。

实测两个容器共享 host netns 同时跑,画面和 CDP 都 200,零冲突;宿主机上
**只绑 loopback** 的服务在容器里用 `http://localhost:3456/` 直接打开。

**所以"能不能用 host 网络"是 profile 的第六个字段,不是全局开关。**

### 6.3 `remote` —— 别人给你两个端点

不 `start` 任何东西,只把两个 URL 记下来。`stop` 什么都不做 ——
**只删本地记录,不动对面**。云浏览器服务、同事机器上开着的那个 Chrome,
只要肯给出这两个端点,就是合法 runtime。

## 7. 边界之外,webmuxd 不碰什么

明确列出来,免得下次有人往里加:

- **不代理画面。** 不做 `/s/<id>/vnc/` 这类自己发明的路径,不做 302,不 tee 一份流。
  上层要怎么组织展示是上层的事([works/03](README.md))。
- **不解析画面协议。** 不知道也不需要知道那边是 RFB 还是 WebRTC。
- **不管镜像里的桌面。** 窗口管理器、右键菜单、剪贴板、音频、文件上传 ——
  那些是镜像作者的产品,不是我们的。
- **不替 Chromium 做进程守护。** 它崩了我们报 `chrome_gone`,拉起来是 runtime 的事。
- **不发镜像。** 我们用别人的原厂镜像,一个字节都不加
  ([works/01](01-container.md))。

## 8. 还剩哪儿不一样

不假装完全对齐:

- **画面这一半天生不同。** `process` 是裸 Xvnc(要自己拿 VNC 客户端连),
  容器那边是浏览器直接开的 web 客户端。统一它意味着在 `process` 里塞一个 web VNC ——
  不值得。
- **`discover()` 只有容器有。** 容器活得比 server 久,能按 label 认回来;
  `process` 的子进程跟着 server 一起没了,没有可认的东西。而且认回来的只有容器 ——
  **sessiond 在调用方那边,得重新起一个**。
- **`kill` 的语义不同。** `process` 杀三个进程;容器那边杀容器 + 宿主机上的 sessiond。
  手工 `docker rm` 会留下孤儿 sessiond 占着端口,下次 `new` 报的是 `port_in_use`、
  **指向端口不指向孤儿**。这条要修:`alive()` 该看 API 通不通,不只看容器在不在。

## 9. ↔ 别处

| | |
| --- | --- |
| 容器具体怎么起 | [works/01](01-container.md) |
| runtime 在三层概念里的位置 | [works/05 §4](05-server-session-runtime.md#4-runtime--唯一多出来的概念) |
| tab 表为什么就是 CDP 的 target 表 | [works/06](06-tab-sync.md) |
| `install` 探什么 | [cli/install.md](../cli/install.md) |
| 同一条判据在 tmuxd 里的样子 | tmuxd `works/06 §1` —— *ttyd 是实现细节,tmux 是契约的一部分* |
