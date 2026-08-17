# 07 · runtime 变薄

**一句话**:契约从两个端点减成**一个 CDP 端点**。浏览器不再靠镜像带进来,
`webmuxd install` 照着 playwright 的样子下一个钉死版本的 —— 于是 `process` 成了默认,
容器只剩隔离一个理由,`remote` 第一次自带画面。

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
        ┌── process     跑 install 下来的那个 chrome --headless=new   ← 默认
        │
runtime ┼── container   同一个二进制,装在容器里 —— 只为隔离
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
(启动脚本死等 `eth*` 网卡),不得不同时支持 bridge。**自己那三行 Dockerfile 没有这个包袱**(§4.5)。

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

## 4. 浏览器从哪来:`webmuxd install` 下一个

v1 [works/08 §7](../../v1/works/08-browser-runtime.md#7-边界之外webmuxd-不碰什么) 写着:

> **不发镜像。** 我们用别人的原厂镜像,一个字节都不加。

这条规矩想防的是**我们去维护别人的产品**。v1 后期它已经松动了(`docker/` 下那两个
wrapper 就是我们发的),而 v2 一度看起来只能进一步松:既然只要 headless chromium,
那就发一个几百 MB 的瘦镜像 —— 可那还是在发镜像。

**但还有第三条路,而且 playwright 已经把它走通了:浏览器不是镜像的内容,是一个下载物。**

```bash
webmuxd install         # 探依赖 → 下一个钉死版本的浏览器 → 记进 ~/.webmuxd.json
```

于是"不发镜像"这条规矩**原样保留** —— 我们既不发镜像,也不要求你本机装 chromium,
更不碰系统的包管理器。浏览器落在一个我们自己的缓存目录里,和 playwright 的
`~/.cache/ms-playwright/` 是同一个姿态。

### 4.1 钉死版本,这是重点

playwright 的 install 最有价值的一点不是"帮你下载",是**每个 release 钉死一个 revision**。

对 webmuxd 尤其如此:`tests/chrome_facts/` 那一整个场景的定义是
「我们对 CDP 的假设逐条量过」,README 里配的说明是「**换 Chromium 大版本先跑它**」。
浏览器版本不确定的时候,这句话是没法执行的 —— 你不知道自己现在跑的是哪一版。

钉死之后这件事变成可执行的:

| | |
| --- | --- |
| 版本谁定 | **webmuxd 的每个 release 钉一个**,写在包里 |
| 升级流程 | 改钉死的版本号 → **跑一遍 `chrome_facts`** → 过了才发版 |
| 用户看到的 | `webmuxd install` 下的永远是这一版,机器之间完全一致 |

v1 的 `--image <tag>` 起的也是这个作用(「tag 跟着底座走,不用 `latest`」),
v2 只是把粒度从镜像 tag 换成了浏览器版本号。

### 4.2 下什么、从哪下

**Chrome for Testing。** Google 官方为自动化维护的构建,有稳定的版本索引 JSON,
不会自己升级 —— puppeteer 就是用它。本轮实测两个下载点都通(2026-08-17):

```
https://googlechromelabs.github.io/chrome-for-testing/last-known-good-versions.json
   → {"Stable":{"version":"152.0.7977.42","revision":"1669021"}, …}          200

https://storage.googleapis.com/chrome-for-testing-public/<版本>/linux64/chrome-linux64.zip
                                                                            206 ✓
https://cdn.npmmirror.com/binaries/chrome-for-testing/<版本>/linux64/chrome-linux64.zip
                                                                            206 ✓  ← 国内
```

**国内那条必须是一等公民**,不是补丁 —— 这个项目本来就同时发 ghcr 和 CNB
([docker/README](../../../docker/README.md))。用 `WEBMUXD_BROWSER_MIRROR` 换下载源,
像 npm 换 registry 一样。

两个附带的决定:

**① 下完整的 `chrome`,不下 `chrome-headless-shell`。** 后者小很多,但它是老 headless
实现的独立二进制,行为和真实浏览器有差 —— 而 webmuxd 的承诺是"程序驱动的和人看见的
是同一个浏览器"。用完整二进制跑 `--headless=new`,体积代价认了。

**② 这一下顺手把 v1 的一个已知缺陷消掉了。** v1 的 README 写着:

> 镜像里是 **Chromium 不是 Chrome**:Chrome 是专有软件、再分发受限。
> 代价是不带 H.264 / AAC,少数只有这两种编码的视频放不了。

Chrome for Testing 带 H.264/AAC,**视频能放了**。而"再分发受限"那条也不再适用 ——
我们不分发它,是 `webmuxd install` 让用户自己从 Google 下,和 playwright / puppeteer
同一个姿态。

> **必须确认**:Chrome for Testing 的条款把它定位成测试/自动化用的构建。
> webmuxd 的用法(程序驱动 + 人接管同一个浏览器)算不算落在里面,**要读一遍条款再定**。
> 如果不算,退路是纯 BSD 的 Chromium 构建,代价就是把上面那条缺陷收回来。
> **在确认之前不要把"视频能放"写进 README。**

### 4.3 系统依赖和字体,照抄 playwright 的姿态

裸服务器上下下来也跑不起来,缺一堆 `.so`;能跑起来的也会撞上
**中文全是豆腐块**(demo 实测,任何跑 RBI 的机器都会撞上)。

playwright 的做法是分成 `install` 和 `install-deps`,后者要 root、只支持
Debian/Ubuntu,别的发行版**只打印缺什么**。照抄这个姿态,理由是它和 v1 的
install 规矩本来就一致:

> **键在 = 探到了,键不在 = 没探到。** 就这一条规矩,没有 `ok: false` 这种带着理由的空壳。
> —— [v1/cli/install.md §3](../../v1/cli/install.md#3-记录长什么样)

所以:**能装就装,装不了就明说缺哪些包、给出那行 apt 命令,绝不静默**。
字体和 `.so` 一样对待 —— 缺 `fonts-noto-cjk` 是一条**警告**,不是"看起来正常"。

### 4.4 install 的形状:内容换掉,规矩全留

v1 的 install「只回答两个问题:docker 能用吗、这个网络环境拉得到那个镜像吗」。
v2 换成:**系统依赖齐吗、这个网络环境下得到那个浏览器吗**。

[v1/cli/install.md](../../v1/cli/install.md) 的每一条规矩原样继承:

| 规矩 | 在 v2 里的样子 |
| --- | --- |
| **幂等**,"检查"和"安装"是同一个命令,不需要 `doctor` | 已经下过就校验版本后直接跳过,`--force` 重下 |
| **探不到就不写那个键** | 下不到浏览器就不写 `default_browser`,而不是留个假路径 |
| **信记录,但别替它兜底,也不静默重探** | 用户 `rm -rf` 了缓存目录,起 session 时报错并提示重跑 `install` |
| **它不是配置文件**,记的是机器的事实 | `default_browser` 是"这台机器上有哪个",**你想用哪个**永远是 `session(browser=…)` 说了算 |
| **没装过也能用**,`Webmuxd()` 不要求先跑 CLI | 没记录就现探;探到系统里有合适的 chromium 也能直接用 |

记录长这样:

```jsonc
{
  "version": 2,
  "at": "2026-08-17T05:20:00Z",
  "default_browser": {
    "path": "~/.cache/webmuxd/chrome-152.0.7977.42/chrome",
    "version": "152.0.7977.42",
    "source": "chrome-for-testing"
  },
  "docker": "/usr/bin/docker"          // 键在 = 探到了,container runtime 可用
}
```

`docker` 那个键留着,因为 `container` runtime 还在(§4.5)——
但它**不再是能不能用 webmuxd 的前提**。

### 4.5 那容器还要不要

要,但它的理由只剩**一个**:**隔离**。

v1 的容器背着三个理由:现成的浏览器 + 桌面/VNC(画面)、隔离、不用用户装 chromium。
v2 里第一个和第三个都被 install 接走了,剩下隔离 —— 那是容器本来就该干的事。

而且它现在**不需要我们发镜像**:

```dockerfile
FROM python:3.12-slim
RUN pip install webmuxd && webmuxd install --with-deps
```

三行,用户自己 build,没有底座适配层,没有 `webmuxd.*` 标签那套认镜像的机制
(那套机制存在是因为要描述**别人的**镜像长什么样,现在镜像是你自己那三行)。

## 5. `process` 成了默认

v1 的 `process` runtime 有两个尴尬([works/08 §6.1](../../v1/works/08-browser-runtime.md#61-process--本机三个进程)):
**要本机装 chromium**,以及

> 没有 Xvnc 就只有 API 没有画面 —— **这件事要说出来**,装作有画面比没画面更糟。

v2 把两个都消掉了:画面来自 CDP(和容器里的完全一样),浏览器来自 `install`(不要求你装)。

```bash
<install 下来的 chrome> --headless=new --remote-debugging-port=<free> --user-data-dir=<profile>
```

一个进程,秒起。**所以默认从 `container` 换成 `process`**:

| | v1 默认 `container` 的理由 | v2 |
| --- | --- | --- |
| 用户不用装浏览器 | 镜像里带着 | **`install` 下一个**,不用容器也成立 |
| 有画面 | VNC 在镜像里 | **CDP 自己产**,不用容器也成立 |
| 隔离 | 容器给的 | **只剩这一条** |

要隔离的人显式 `runtime="container"`,和 v1 里要多开的人显式
`network="bridge"` 是同一种做法 —— **默认不等于唯一**,只是"多数时候你要的是哪个"。

剩下的差别还是老差别,写在明处:`process` **没有网络和文件系统隔离**,
页面跑在你自己机器上。这一条不能因为默认了就说得轻一点。

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
| 不发镜像 | **原样成立** —— 浏览器改成 `webmuxd install` 下一个,连镜像都不用发(§4) |

只有画面那两条失效了,而它们失效的理由是同一个:**那半边现在归我们**。
其余三条一条没动。

## 8. ↔ 别处

| | |
| --- | --- |
| 为什么画面归我们 | [01](01-frame-source.md) |
| 一个端口 | [04](04-one-port.md) |
| v1 的 runtime 契约 | [v1/works/08](../../v1/works/08-browser-runtime.md) |
| 镜像标签机制 | [docker/README](../../../docker/README.md) |
