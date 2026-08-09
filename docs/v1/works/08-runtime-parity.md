# 08 · 两个 runtime,一样的东西

`process` 和 `container` 差别只有一件事:**谁把浏览器拉起来。**
拉起来之后,从 sessiond 往上,所有代码一行都不区分它们。

## 1. 分界线画在哪

runtime 这一层的职责,是把一台机器变成**同一个形状**:

```
一个 CDP 端点     http://127.0.0.1:<port>      ← 给代码
一个画面端口       <host>:<port>                ← 给人
```

就这两样。`ContainerRuntime.start()` 和 `ProcessRuntime.start()` 都返回同一个
`Handle`,里面就是这两个口。往上是 sessiond,它只知道:

```bash
python3 -m webmuxd.serve --cdp http://127.0.0.1:59213 --port 7900
```

**这条命令两种 runtime 下完全一样**,连端口号的来源都一样(挑一个空闲的)。
`core/` 的 CDP 客户端、tab 表、定位、观测、日志,`serve/` 的路由,
`client/` 的三个对象,CLI 的每一条子命令 —— **没有任何一处 `if runtime ==`**。

所以这篇要论证的不是"我们努力让它们像",而是:**它们本来就在同一条线以下分岔,
线以上根本不知道下面发生了什么。**

## 2. `process` 怎么变成那个形状

```
chromium --remote-debugging-port=<free>   →  127.0.0.1:<free>   CDP
Xvnc :N -rfbport <vnc_port>               →  127.0.0.1:<vnc>    画面
python -m webmuxd.serve --cdp …           →  sessiond
```

三个进程,都是 server 的子进程,`kill-server` 跟着死(works/05 §3.2)。
没有 Xvnc 就只有 API 没有画面 —— **这件事要说出来**,装作有画面比没画面更糟。

## 3. `container` 怎么变成那个形状

难的是 CDP 那一半。**Chromium 不肯把调试口交出容器。**

### 3.1 它是写死的,不是配置问题

[`chrome/browser/devtools/remote_debugging_server.cc`](https://github.com/chromium/chromium/blob/main/chrome/browser/devtools/remote_debugging_server.cc)
里 `TCPServerSocketFactory::CreateLocalHostServerSocket`:

```cpp
if (socket->ListenWithAddressAndPort("127.0.0.1", port, kBackLog) == net::OK)
  return socket;
if (socket->ListenWithAddressAndPort("::1", port, kBackLog) == net::OK)
  return socket;
```

地址是硬编码的,这个文件里**根本没有读 `kRemoteDebuggingAddress`**。
上游态度见 [crbug 41487252](https://issues.chromium.org/issues/41487252):
这个 flag "presents a security issue and should not be used",准备删掉。

实测印证(两个 build,跨发行版跨 libc,参数都确认出现在 `/proc/<pid>/cmdline` 里):

| Chromium | 环境 | 给了 `--remote-debugging-address=0.0.0.0` | 实际绑 |
| --- | --- | --- | --- |
| 139 | Ubuntu / kasmweb | 是 | `127.0.0.1` |
| 124 | Alpine musl | 是 | `127.0.0.1` |

同一趟 `APP_ARGS` 进去的 `--remote-debugging-port` **生效了**,
`--remote-debugging-address` 没有 —— 因为它俩根本不在同一段代码里。

### 3.2 `-p` 也够不着

`docker -p` 是 DNAT:把宿主端口的包改写目的地址成**容器的 eth0**。
而 Chromium 在容器的 **lo** 上听。

`127.0.0.0/8` 每个 network namespace 各自一份,内核只允许它从本 namespace 的
lo 进出;别的路径来的 127.x 包会被当 martian 丢掉。所以"DNAT 到另一个
namespace 的 loopback"这条规则**写不出来**,不是 docker 偷懒。

实测:`-p 127.0.0.1:19222:9222` → `000`(连 TCP 都建不起来)。

### 3.3 于是垫一跳

```
容器内:  eth0:9223  ←── 二十行 python ──→  127.0.0.1:9222  Chromium
             ↑
        docker -p 够得到这儿了
```

用 `python3 -c` 把源码从命令行喂进去,**不落文件、不装包、不依赖镜像里有什么** ——
这是"镜像完全原厂"的前提。

> Chromium 还会校验 Host 头防 DNS rebinding。实测**IP 字面量放行、域名拒绝**
> (`Host: 127.0.0.1:<任意口>` → 200,`Host: evil.com` → 500)。我们从
> `127.0.0.1` 连,不受影响。
>
> 另:`webSocketDebuggerUrl` **照抄请求的 Host 头**
> (`Host: 127.0.0.1:9999` → `ws://127.0.0.1:9999/devtools/…`),
> 所以 `CDP._browser_ws` 里那段 netloc 改写是防御性的,不是这条链路能通的原因。

**中继在分界线以下。** sessiond 拿到的还是 `http://127.0.0.1:<port>` ——
和 `process` 一模一样。这就是 §1 那句话的全部意思。

## 4. 第二件事:宿主机的 `localhost` 要能进去

调试用的浏览器,得能打开你自己机器上跑着的页面。

**`host.docker.internal` 不够。** 它指向宿主机的 docker0 地址,而开发服务器
常常**只绑 `127.0.0.1`** —— 那上面没人听。实测:一个绑死 loopback 的服务,
容器经 `host-gateway` 访问是 `000`。

所以又是两跳,方向相反:

```
容器 lo:3000  ──→  host.docker.internal:3000  ──→  宿主 lo:3000
   ↑ 浏览器写的                 ↑ 宿主机上垫的那跳
     localhost:3000
```

1. **宿主机这跳**听 `172.17.0.1:<port>` → `127.0.0.1:<port>`,专为只绑
   loopback 的服务准备。那个口上已经有人听(服务本来就绑了 `0.0.0.0`)就跳过。
2. **容器里这跳**必须绑**容器的 lo** —— 不然浏览器里写 `localhost:3000` 还是不对。

两种情况都实测通过:

| 宿主服务绑在 | 单跳(只有容器内) | 两跳 |
| --- | --- | --- |
| `0.0.0.0`(如 Next dev) | ✓ | ✓ |
| 只绑 `127.0.0.1` | ✗ `000` | ✓ 页面正常渲染 |

代价:第 1 跳把那个本来只在 loopback 的服务,暴露给了 docker0 上的**所有**容器。
session 停了就撤。

**这两件事用的是同一段转发代码**,只是监听和目标不同 —— CDP 那跳是
"把容器里的东西放出来",localhost 这跳是"把外面的东西放进去"。

### 4.1 端口是事先不知道的(待定)

上面那套要求**开 session 的时候就列出端口**。但真实情况是:人在画面里手敲一个
`localhost:8787`,或者代码临时决定去看某个口 —— 那时候 session 早就起来了。
预先列一串端口,等于把"我等下会看哪个页面"这个问题提前问了一遍,而它没有答案。

三条路:

**(a) 预留一段范围。** `--forward 3000-3010`。实现最简单,但要么开一堆没人用的
监听,要么还是猜不准。**只是把问题挪了个地方。**

**(b) 按需挂 —— 倾向这条。** `--forward` 降级成"预热提示",真正的机制是:
需要的时候现挂。两个触发点覆盖两类用户:

- **代码走的**:`goto()` / `open()` 里看到 `localhost:<port>`,导航之前先确保
  那一跳在。两次 `docker exec`,几十毫秒,而且幂等 —— 挂过就跳过。
- **人手敲的**:CDP 能看到导航失败。落在 `localhost:<port>` 上的失败,
  挂好转发**重试一次**,只重试一次,并且在日志里记一条
  (`tab` 类,`event: forwarded`)—— 自愈可以,但不能悄悄自愈。

代价是多了一条"自动重试"的路径,得防住重试风暴;好处是**调用方什么都不用先说**。

**(c) 让 loopback 走代理,一劳永逸。** 给 Chromium 一个 PAC:`localhost` /
`127.0.0.1` 走宿主机上的一个 SOCKS 代理,其余 `DIRECT`。这样**任何端口都天然通**,
不需要任何"挂"的动作。

看着最干净,但有两个没验过的点,不能凭想象写进设计:Chromium **默认就 bypass
loopback**,要靠 `--proxy-bypass-list=<-loopback>` 掰回来,而它和 PAC 能不能共存
得实测;另外它会和调用方自己的 `proxy=` 参数打架 —— 一个 Chromium 只有一个
代理配置。

**先按 (b) 做,(c) 作为后续可能的简化 —— 但要先把那两个点测掉再说。**

### 4.2 `localhost` 在容器里可能不是 127.0.0.1

容器的 `/etc/hosts` 里 `localhost` 同时映到 `127.0.0.1` 和 `::1`,而 Chromium
**优先走 IPv6**。我们那一跳只绑了 `127.0.0.1` —— 于是 `http://localhost:3000`
先撞 `[::1]:3000`,没人听,才回落到 IPv4。回落是有的,但那是一次白等的连接失败,
而且不同版本的回落行为不一样。

**两跳都绑上 `::1`**,别指望回落。这是那种"平时看不出来、偶尔慢一拍、
换个环境直接不通"的问题。

### 4.3 转发是有寿命的,而且死得很安静

两跳都是进程,都会死:

| 死的是 | 症状 | 谁发现 |
| --- | --- | --- |
| 容器里那跳 | `localhost:3000` 连不上,浏览器显示"无法访问" | 没人 —— 看着就像服务挂了 |
| 宿主机那跳 | 同上,而且只影响绑 loopback 的那些 | 没人 |
| 宿主服务本身 | 同上 | 没人 |

三种原因、一个症状,这是最难查的那类。所以:

- **每次连接才去连目标**,不预连。宿主服务后起、重启,转发都不用重挂 ——
  三种原因里最常见的那个自愈了。
- **转发进程记进 `Handle.detail`**,`webmuxd info` 能看到挂了哪些口、还活着没有。
  查的时候第一眼就能排除掉两个。
- **session 停就撤。** 宿主机那一跳尤其 —— 见 §4.4。

### 4.4 代价:任何页面都能碰到你的 `localhost`

这是这个特性最该说清楚的一条,比端口怎么挂重要得多。

映射做完之后,**容器里打开的任何网页**都能对 `http://localhost:3000` 发请求。
CORS 拦得住"读到响应",拦不住"请求已经发出去了" —— 一个 `<img>`、一个表单
POST、一个 `fetch(..., {mode:'no-cors'})` 都是真实的副作用。而这个浏览器的用途
恰恰是**打开不受信任的页面**。

三条限制,不是可选项:

1. **只转调用方点名的端口。** 不扫描、不猜、不"顺手把常见的都挂上"。
   §4.1 选 (b) 按需挂,也是按**访问到的那个**挂,不是按"可能会用的那些"。
2. **不转 CDP 自己的口。** 转了等于让页面反过来控浏览器 —— 那是彻底的越权,
   不是权限大小的问题。
3. **宿主机那一跳只在 session 活着的时候在。** 它把一个本来只在 loopback 的服务
   暴露给了 docker0 上的**所有**容器,包括别人的。session 停了不撤,
   就是留了一个谁都不记得的口子。

**默认一个都不转。** 要 `localhost` 能进去,是调用方明确说出来的事。

## 5. 为什么不是 `--network host`

`--network host` 让两个 netns 合成一个,于是容器里的 `127.0.0.1` **就是**你的
`127.0.0.1` —— 中继不用了,`localhost` 天然就通。看起来更简单,而且实测确实
跑得起来。

**但它一台机器只能跑一个 session。** 三条实测,一条比一条硬:

**(a) kasm 的启动脚本死等 `eth*` 网卡。** `vnc_startup.sh` 里:

```bash
for interface in $interfaces; do
    if [[ $interface == eth* && -z $KASM_SVC_EGRESS ]]; then return; fi
done
sleep 1        # 认不出就永远转下去
```

bridge 下 docker 正好把网卡叫 `eth0`;host 下容器看到的是宿主机的真实网卡
(`ens4` / `enp0s3` / …,现代 Linux 基本都不叫 eth0),于是 Xvnc、Chromium
一个都起不来。**这条能绕**:把脚本抠出来改一行再挂回去。

**(b) `@KasmVNCSock<pid>` —— 这条绕不过去。** KasmVNC 建的这个抽象 unix socket,
名字里的数字就是 **Xvnc 在容器内的 PID**(`pgrep Xvnc` → 68,socket 名
`@KasmVNCSock68`,对得上)。而抽象 socket **归 network namespace 管**。

每个 kasm 容器启动流程一样 → Xvnc 拿到的 PID 也一样 → host 网络下两个 session
抢同一个名字,第二个死在 `vncExtInit: failed to bind socket: Address already
in use`。偶尔两个都能起来,是 PID 恰好错开成 67 和 68 —— **撞大运,不是设计**。

**(c) `--pid host` 能让名字唯一,但会砸掉别的。** PID 全局唯一之后 socket 名确实
分开了(`917881` / `918260`),两个画面都起来了 —— 但第二个的 **Chromium 起不来**:
kasm 用 `pgrep chromium` 判断进程活没活,共享 PID 空间之后第二个容器看见了
第一个的 chromium,以为自己已经在跑,就再也不拉起来。

还有两条附带的:host 网络下 `-p` 失效,KasmVNC 的 `-interface 0.0.0.0` 是写死的,
**画面口一起来就是全网可见**(把它 patch 成变量会触发 (b),因为指定具体地址会让
Xvnc 去绑那个每 session 相同的 socket);kasm 的 4901-4905 也直接占宿主机的口。

**结论:host 网络省掉的那一跳,代价是一机一 session、没有网络隔离、画面口必然对外。
而它省的那一跳,恰好在分界线以下 —— 上面根本看不见。不值。**

## 6. 对照

| | `process` | `container` |
| --- | --- | --- |
| sessiond 拿到的 CDP | `http://127.0.0.1:<port>` | **一样** |
| 画面 | Xvnc(没有就没画面) | KasmVNC,自签名 https |
| 浏览器跑在哪 | 你机器上 | 容器里,原厂 `kasmweb/chromium` |
| 宿主 `localhost` | 本来就是同一个 | 两跳映射进去 |
| 一机多 session | ✓ | ✓ |
| 网络隔离 | 没有 | ✓ |
| `kill-server` 之后 | 跟着死 | 容器活着,sessiond 死 |
| 额外代码 | 无 | 两处转发,共二十行 |

## 7. 还剩哪儿不一样

不假装完全对齐:

- **画面这一半天生不同。** `process` 是裸 Xvnc(要自己拿 VNC 客户端连),
  `container` 是 KasmVNC(浏览器直接开,自签名 https,有用户名密码)。
  统一它意味着在 `process` 里塞一个 web VNC —— 不值得。
- **`discover()` 只有 `container` 有。** 容器活得比 server 久,能按 label 认回来;
  `process` 的子进程跟着 server 一起没了,没有可认的东西。
  而且认回来的只有容器 —— **sessiond 在调用方那边,得重新起一个**。
- **`kill` 的语义不同。** `process` 杀三个进程;`container` 杀容器 + 宿主机上的
  sessiond 和转发进程。手工 `docker rm` 会留下孤儿 sessiond 占着端口 ——
  下次 `new` 会撞上 `port_in_use`,而报错指向端口,不指向孤儿。
  **这条要修:`alive()` 该看 API 通不通,不只看容器在不在。**
- **接管回来的 session 没有转发。** `discover()` 只认容器,而两跳转发一跳在
  宿主机进程里、一跳是 `docker exec` 出去的 —— 前者跟着上一个 server 死了。
  接管的一方要么重挂,要么明说"这个 session 的 localhost 映射没了"。

## 8. ↔ 别处

| | |
| --- | --- |
| runtime 是什么 | [works/05 §4](05-server-session-runtime.md#4-runtime--唯一多出来的概念) |
| 容器怎么起的 | [works/01](01-container.md) |
| `install` 探什么 | [cli/install.md](../cli/install.md) |
