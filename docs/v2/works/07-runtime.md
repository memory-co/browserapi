# 07 · runtime 变薄

**一句话**:契约从两个端点减成**一个 CDP 端点**。镜像从 4.4 GB 的桌面减成
几百 MB 的 headless chromium,`process` 不再残废,`remote` 第一次自带画面。

## 1. 契约只剩一条

```
v1:  一个画面端口 <host>:<port>  +  一个 CDP 端点 http://<host>:<port>
v2:  一个 CDP 端点 http://<host>:<port>
```

**产出这一样的东西,就是一个 runtime。** 画面不再是 runtime 的义务 ——
它是 webmuxd 用这个端点自己产的([01](01-frame-source.md))。

v1 [works/08 §1](../../v1/works/08-browser-runtime.md#1-分界线runtime-之上没有一行-if)
那条"runtime 之上没有一行 `if runtime ==`"继续成立,而且**更容易成立了**:
少一个端点就少一类差异,`process` 和 `container` 在画面这一半上第一次**完全一样**。

```
        ┌── process     本机拉起 chromium --headless=new
        │
runtime ┼── container   docker run 一个只有 chromium 的瘦镜像
        │
        └── remote      别人已经把 CDP 端点给你了
                                    │
        ─────────────────────────────┼──────  ← 边界:一个 CDP 端点
                                    │
                            webmuxd 自己产画面
```

## 2. CDP 搬运问题被 host 网络消掉了

v1 [works/08 §3](../../v1/works/08-browser-runtime.md#3-难的是-cdp-那一半)花了很大篇幅
论证"Chromium 拒绝把调试口交出去"(`--remote-debugging-address` 根本没被读,
地址硬编码 `127.0.0.1`),结论是要两种搬法叠着用:

- **A** 容器里垫一跳 `0.0.0.0:<外> → 127.0.0.1:<内>` —— 这一跳在**镜像**里
  (kasm 用 `cdp-relay.py`,jlesage 打开自带的 socat)
- **B** `--network host` 共享 netns

**A 在 v2 里不用了。** 本轮实测(2026-08-17):

```
docker run -d --network host --entrypoint sh <镜像> -c \
  '/usr/bin/chromium --headless=new --no-sandbox --remote-debugging-port=9345 …'

宿主机:curl http://127.0.0.1:9345/json/version
        → {"Browser":"Chrome/151.0.7922.108", …}      ✓ 零转发
```

共享 netns 之后容器里的 `127.0.0.1` **就是**宿主机的 `127.0.0.1`,Chromium 绑哪儿
我们就从哪儿连。v1 里之所以还要 A,是因为 kasm 那个底座在 host 网络下起不来
(启动脚本死等 `eth*` 网卡),不得不同时支持 bridge。**瘦镜像没有这个包袱。**

于是 `docker/` 下那两个 wrapper 的**全部理由**(补 CDP 转发、统一端口变量名、
绕开底座的启动脚本假设)一起消失。

## 3. 一机多开天然成立

v1 最疼的一条限制:**kasmweb 一台机器只能跑一个**。原因在
[works/08 §6.2](../../v1/works/08-browser-runtime.md#62---network-host--默认的跑法):
KasmVNC 用 `.KasmVNCSock<pid>` 作为**抽象命名空间**的 socket 名,而抽象 socket
归 netns 管;共享 netns 的两个容器启动流程完全一样 → PID 一样 → 第二个死在
`failed to bind socket`。

v2 里没有 KasmVNC,也没有 X。本轮实测:

```
三个 headless chromium 容器,全部 --network host,各自 --user-data-dir 和 CDP 端口
  9341 → Chrome/151.0.7922.108  ✓
  9342 → Chrome/151.0.7922.108  ✓
  9343 → Chrome/151.0.7922.108  ✓
```

**零冲突。** Chromium 的单实例锁是 `user-data-dir` 里的**文件系统** socket,
不是抽象 socket —— profile 目录不同就互不相干。

所以"要多个 session 就多起几个浏览器"是 v2 的正常用法,不是权宜之计:

| | |
| --- | --- |
| 一个 session | 一个浏览器实例、一个 profile、一个 CDP 端点、一个对外端口 |
| 要两个 | 起两个,没有共享的东西,也没有互相踩的地方 |

这和 tmux 的差别仍在(tmux 一个 socket 复用所有 session),
原因也仍然是 [v1/works/05 §2](../../v1/works/05-server-session-runtime.md#2-对照表) 那条:
**浏览器不是终端,一个浏览器进程就是一个隔离单位**(cookie、登录态、缓存都在 profile 里)。
但代价从"一台机器只能一个"降到了"一个 session 一个进程",这是量级的差别。

## 4. 我们要不要自己发镜像

v1 [works/08 §7](../../v1/works/08-browser-runtime.md#7-边界之外webmuxd-不碰什么) 写着:

> **不发镜像。** 我们用别人的原厂镜像,一个字节都不加。

这条其实在 v1 后期就已经松动了 —— `docker/` 下那两个 wrapper 就是我们发的
(在别人的底座上加一层)。**v2 把话说清楚:我们发一个自己的瘦镜像。**

姿态的变化是有理由的,不是妥协:

| | v1 的 wrapper | v2 的瘦镜像 |
| --- | --- | --- |
| 里面有什么 | **别人的产品**(kasm / jlesage 的整套桌面 + VNC)+ 我们加的一层 | chromium + 字体 |
| 我们改了别人什么 | 补转发、翻译变量名、绕开启动脚本 | **什么都没改**,apt 装一个 chromium |
| 底座换版本 | 我们的适配层可能碎 | 无所谓 |
| 大小 | 4.4 GB / 1.4 GB | 几百 MB |

"不发镜像"这条规矩想防的是**我们去维护别人的产品**。瘦镜像里没有别人的产品,
所以它防的东西不存在。

镜像内容清单(尽量短,每一项都要有理由):

| | 为什么 |
| --- | --- |
| `chromium` | 本体 |
| `fonts-noto-cjk` | **裸服务器渲染中文全是豆腐块**(demo 实测)。任何跑 RBI 的机器都会撞上 |
| 其它字体 / emoji | 按需,能省则省 |
| ~~X / 窗口管理器 / VNC / 音频~~ | headless 一个都不要 |

镜像标签沿用 v1 的 `webmuxd.*` 机制([docker/README](../../../docker/README.md)):
**webmuxd 读标签认镜像,不认名字**,自己 build 的打上标签就能用,没标签就报错不猜。
标签内容要跟着契约缩水 —— `webmuxd.view.*` 那几项全部退役,只剩 CDP 和启动参数相关的。

## 5. `process` 不再残废

v1 的 `process` runtime 有个尴尬([works/08 §6.1](../../v1/works/08-browser-runtime.md#61-process--本机三个进程)):

> 没有 Xvnc 就只有 API 没有画面 —— **这件事要说出来**,装作有画面比没画面更糟。

v2 里画面来自 CDP,所以 **`process` 天然有画面**,而且和容器里的**完全一样**:

```bash
chromium --headless=new --remote-debugging-port=<free> --user-data-dir=<tmp>
```

一个进程,秒起,零依赖(除了 chromium 本身)。它现在是**开发和 CI 的正经选择**,
不是"凑合能用"。剩下的唯一差别是老差别:**没有隔离**,页面跑在你自己机器上。

默认仍然是 `container`(隔离 + 不用你本机装 chromium),但 `process` 第一次
是个完整的东西。

## 6. `remote` 第一次真正好用

v1 的 `remote` 要求对面**同时**给出画面口和 CDP 端点。而云浏览器服务基本只给 CDP
(browserless、Browserbase、各家的 `wss://…?token=…`),画面那半要么没有、
要么是他们自己的产品界面。

v2 只要一个 CDP 端点 —— **于是画面由我们产**:

```python
sess = web.session(id="cloud", port=7900,
                   runtime="remote", cdp="wss://chrome.example.com?token=…")
print(sess.view_url)      # http://127.0.0.1:7900/  ← 我们产的画面,连的是他们的浏览器
```

**给一个只有 CDP 的云浏览器配上人能看能上手的画面**,这是 v2 白捡的一个能力,
v1 做不到。`stop` 的语义不变:只删本地记录,不动对面。

需要留意的是这条链路的 RTT 明显更长(帧和输入都要跨公网两次),
所以 [02 §3](02-frame-protocol.md#3-rtt-自适应画质) 那套自适应降质在 `remote` 上
才真正开始工作 —— 本机跑的时候它几乎不会触发。

## 7. 边界之外,webmuxd 仍然不碰

v1 [§7](../../v1/works/08-browser-runtime.md#7-边界之外webmuxd-不碰什么) 那份清单,
逐条对照 v2:

| v1 的条目 | v2 |
| --- | --- |
| 不代理画面 | **失效** —— 画面就是我们的,谈不上代理([01](01-frame-source.md)) |
| 不解析画面协议 | **失效** —— 我们定义它 |
| 不管镜像里的桌面 | **仍然成立**,而且更彻底:没有桌面([06](06-no-desktop.md)) |
| 不替 Chromium 做进程守护 | **仍然成立**。它崩了我们报 `chrome_gone`,拉起来是 runtime 的事 |
| 不发镜像 | **改了**,理由见 §4 |

## 8. ↔ 别处

| | |
| --- | --- |
| 为什么画面归我们 | [01](01-frame-source.md) |
| 一个端口 | [04](04-one-port.md) |
| v1 的 runtime 契约 | [v1/works/08](../../v1/works/08-browser-runtime.md) |
| 镜像标签机制 | [docker/README](../../../docker/README.md) |
