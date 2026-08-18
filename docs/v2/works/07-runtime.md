# 07 · 浏览器从哪来

**一句话**:runtime 这个词收缩到只剩一件事 —— 浏览器从哪来。
**本机起一个进程,或者你给一个 CDP 端点。容器不在里面。**

## 1. 契约只剩一条

```
v1:  一个画面端口 <host>:<port>  +  一个 CDP 端点 http://<host>:<port>
v2:  一个 CDP 端点 http://<host>:<port>
```

**产出这一样的东西就够了。** 画面不再是外面的义务 —— 它是 webmuxd 用这个端点自己产的([01](01-frame-source.md))。

v1 [works/08 §1](../../v1/works/08-browser-runtime.md#1-分界线runtime-之上没有一行-if)
那条"runtime 之上没有一行 `if runtime ==`"继续成立,而且**几乎不用再论证了** ——
线以下只剩两种情况,而且它们的区别只是"这个 CDP 端点是我起的还是你给的"。

```
        ┌── 本机起一个   install 下来的 chrome --headless=new
runtime ┤
        └── remote      别人已经把 CDP 端点给你了
                              │
        ───────────────────────┼──────  ← 边界:一个 CDP 端点
                              │
                      webmuxd 自己产画面
```

## 2. 容器不要了

v1 的容器背着三个理由。v2 里逐个清账:

| v1 为什么要容器 | v2 |
| --- | --- |
| 里面有现成的浏览器 **+ 桌面 + VNC(画面)** | 画面自己产,桌面根本不要([01](01-frame-source.md)) |
| 用户不用自己装 chromium | **`webmuxd install` 下一个**(§3) |
| 隔离 | **剩这一条 —— 而它不是 webmuxd 的活** |

### 判据还是那一句

v1 的[「明确不做」](../../v1/works/README.md#明确不做)结尾写着:

> 判断新功能该不该加,问一句:**tmux 会做这个吗?** 不会就别加。

tmuxd 不会 `docker run` 一个 tmux。**姿态要反过来**:

```
v1:  webmuxd  ──docker run──>  容器(浏览器在里面)
v2:  你 ──docker run──> 容器(webmuxd 和浏览器都在里面) ── 我们一个字都不用写
```

要隔离就**把 webmuxd 整个放进容器里跑**,一行 `docker run` 是你的部署决定,
不是我们的参数。v1 那份「明确不做」里本来就有一条
"控制面 / 会话编排 / 容器池 —— **你要多个就 `docker run` 多次**",
v2 只是把它推到底:**连一次都不 run**。

### 跟着一起消失的

| 消失的东西 | 它本来是干嘛的 |
| --- | --- |
| `runtime="container"` | 三分法塌成两种 |
| `image=` / `--image` | 指定用哪个镜像 |
| 镜像的 `webmuxd.*` 标签那套机制 | 描述**别人的**镜像长什么样 —— 现在没有别人的镜像了 |
| `network="host" / "bridge"` | 选 netns —— 没有容器就没有第二个 netns |
| `~/.webmuxd.json` 里的 `docker` 键 | 探 docker 在不在 |
| `docker/` 下的两个 wrapper 镜像 | 补 CDP 转发、翻译端口变量名(随 v1 存档) |
| `discover()`(按 label 认回容器) | 容器活得比 server 久,能认回来 —— 现在没有容器可认 |

**代码上是删掉 `runtime/container.py`** —— 563 行,`runtime/` 里最大的一个文件。

### 老实说清楚:隔离是真的没了

`process` 之外没有别的本地跑法,所以**页面就跑在你自己机器上**,
没有网络隔离,也没有文件系统隔离。这一条和[没有音频](01-frame-source.md#4-代价老实写)
一样,是 v2 相对 v1 的**净损失**,不因为"你可以自己套容器"就说得轻一点。

要隔离有两条路,都在 webmuxd 之外:**把 webmuxd 装进容器**,或者
**让浏览器待在别处、只给我们 CDP**(§5)。

## 3. 顺带删掉了 v1 最难的那一半

v1 [works/08 §3](../../v1/works/08-browser-runtime.md#3-难的是-cdp-那一半)是整个 v1
论证最重的一节:**Chromium 拒绝把调试口交出去**。`--remote-debugging-address`
根本没被读(地址硬编码 `127.0.0.1`,上游还准备删掉这个 flag),而 `docker -p`
是 DNAT 到容器的 eth0,**"DNAT 到另一个 namespace 的 loopback"这条规则写不出来**。
于是要两种搬法叠着用:镜像里垫一跳转发(`cdp-relay.py` / socat)+ 共享 netns。

**这个问题的前提是「webmuxd 和 Chromium 在不同的 network namespace 里」。**
没有容器,前提就没了 —— Chromium 绑在 `127.0.0.1`,而我们**就在那个 `127.0.0.1` 上**。

所以整条论证链一起作废:那一跳转发、`--network host`、
KasmVNC 抽象 socket 撞名([works/08 §6.2](../../v1/works/08-browser-runtime.md#62---network-host--默认的跑法))、
kasm 启动脚本死等 `eth*` 网卡 —— **一条都不用再读了**。

> 上一轮那两个实测(host netns 下宿主机直连容器里的 CDP、三个 headless chromium
> 容器共享 netns 零冲突)**现在用不上了,但存档有用**:它们证明了即使你自己
> 把 webmuxd 和浏览器塞进容器,CDP 这一段也不会碍事。

**这是本轮最大的一笔删除。v1 最难的那一半不是被解决了,是被删掉了。**

## 4. `webmuxd install` 下一个浏览器

v1 [works/08 §7](../../v1/works/08-browser-runtime.md#7-边界之外webmuxd-不碰什么) 写着:

> **不发镜像。** 我们用别人的原厂镜像,一个字节都不加。

这条规矩想防的是**我们去维护别人的产品**。v1 后期它已经松动了(`docker/` 下那两个
wrapper 就是我们发的),而 v2 一度看起来只能进一步松:既然只要 headless chromium,
那就发一个几百 MB 的瘦镜像 —— 可那还是在发镜像。

**第三条路 playwright 已经走通了:浏览器不是镜像的内容,是一个下载物。**

> 它那套机制拆开看在 [10](10-install.md) —— 包括一条我们欠着的:
> `INSTALLATION_COMPLETE` 标记文件,不然解压到一半被打断会**看起来像装好了**。

```bash
webmuxd install         # 探依赖 → 下一个钉死版本的浏览器 → 记进 ~/.webmuxd.json
```

于是"不发镜像"这条规矩**原样保留**,而且比 v1 更彻底 —— 既不发镜像,也不 `docker run`
别人的镜像,更不要求你本机装 chromium 或碰系统的包管理器。浏览器落在我们自己的
缓存目录里,和 playwright 的 `~/.cache/ms-playwright/` 是同一个姿态。

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
v2 只是把粒度从镜像 tag 换成了浏览器版本号 —— **而且少一层**:
镜像 tag 背后的 Chromium 是几版,得去问镜像作者。

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

**国内那条必须是一等公民**,不是补丁 —— 这个项目本来就同时发 ghcr 和 CNB。
用 `WEBMUXD_BROWSER_MIRROR` 换下载源,像 npm 换 registry 一样。

**但不用你去挑:`install` 并发探一遍,自己选最快的那个。**

```console
  下载源        探测中…
     官方               1.8 MB/s     ✓
     npmmirror        0.4 MB/s
     npmmirror cdn    0.3 MB/s
```

三条讲究:

- **探的是真实那个文件的头 256 KB**,不是首页也不是 ping —— 首页快不代表大文件快,
  CDN 的回源路径经常不一样
- **量吞吐,不量 RTT** —— 我们要下的是 150 MB,握手快 20ms 一文不值
- **传进来的赢**:显式给了 `--mirror` 或 `WEBMUXD_BROWSER_MIRROR` 就不探了。
  探测是"这台机器上哪个快"的**事实**,而你指定哪个是你的**选择** ——
  和 [v1/cli/install.md](../../v1/cli/install.md) 那条"它不是配置文件"是同一条规矩

全都探不通就退回官方,**让真正的下载去报错** —— 那儿的原因(DNS 不通 / 403 /
超时)比一句"探测失败"有用得多,而且要**整句打出来不截断**。

两个附带的决定:

**① 下完整的 `chrome`,不下 `chrome-headless-shell`。** 后者小很多,但它是老 headless
实现的独立二进制,行为和真实浏览器有差 —— 而 webmuxd 的承诺是"程序驱动的和人看见的
是同一个浏览器"。用完整二进制跑 `--headless=new`,体积代价认了。

**② 但 codec 不是选它的理由。** 这里本来写着"Chrome for Testing 带 H.264/AAC,
视频能放了",**那是把一个边角问题放大成了选型依据,删掉。**

v1 README 的原话是有分寸的:

> 镜像里是 **Chromium 不是 Chrome**:Chrome 是专有软件、再分发受限。
> 代价是不带 H.264 / AAC,**少数**只有这两种编码的视频放不了。

「少数」这个词是准的。主流站点给 Chromium 发的是 VP9/AV1,根本不走 H.264 ——
**demo 用系统的 chromium 在 YouTube 上实测能放,而且比 kasm 更流畅**
([01 §4.1](01-frame-source.md#41-但更费带宽--更不流畅))。这条路上没有 codec 障碍。

所以选 Chrome for Testing 的理由**只有一条,就是 §4.1 的钉死版本**:
官方托管、有稳定的版本索引、不会自己升级。codec 那条按 v1 原样保留 ——
少数站点放不了,如实写着,不当卖点也不当缺陷。

> **仍然要确认**:CfT 的条款把它定位成测试/自动化用的构建,webmuxd 的用法
> 算不算落在里面,要读一遍条款再定。
> 但**赌注比原先小**:codec 不再是理由之后,退到纯 BSD 的 Chromium 构建
> 不损失任何功能,只是版本索引要自己解决(snapshots 按 commit position 编号,
> 老构建会被清理)。

### 有一个看着像镜像但不是的

`https://mirrors.aliyun.com/google-chrome/` 看起来正是我们要的东西,**但它不是**:

| | CfT(我们要的) | 阿里云那个 |
| --- | --- | --- |
| 产物 | `chrome-linux64.zip` | `.deb` / `.rpm` **系统包** |
| 是什么 | Chrome for Testing | Google Chrome **稳定版 / beta** |
| 版本 | 每个都在,能钉 | 只有 `current`,历史版本停在 112 那一带 |

**关键是最后一行:它没有版本可钉。** 拿它当源等于把 §4.1 那条
"每个 release 钉一个版本、升级前先跑 `chrome_facts`"整个作废掉 ——
而那是选 Chrome for Testing 的**唯一理由**。

所以候选源那张表里**只放真的托管 CfT 的**,`tests/installing` 有一条专门守着它。
真想用系统装的 Chrome,那是另一条路:`--browser /usr/bin/google-chrome`,
显式、看得见、不假装自己是钉死的那一版。

### 4.3 系统依赖和字体,照抄 playwright 的姿态

**这一节的分量变重了** —— 以前镜像替用户扛掉的那些依赖,现在落到了裸机上。

裸服务器上下下来跑不起来,缺一堆 `.so`;能跑起来的也会撞上
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
**两个问题都换了**:系统依赖齐吗、这个网络环境下得到那个浏览器吗。
docker 那一问**整个消失** —— webmuxd 不再关心机器上有没有 docker。

[v1/cli/install.md](../../v1/cli/install.md) 的每一条规矩原样继承:

| 规矩 | 在 v2 里的样子 |
| --- | --- |
| **幂等**,"检查"和"安装"是同一个命令,不需要 `doctor` | 已经下过就校验版本后直接跳过,`--force` 重下 |
| **探不到就不写那个键** | 下不到浏览器就不写 `default_browser`,而不是留个假路径 |
| **信记录,但别替它兜底,也不静默重探** | 用户 `rm -rf` 了缓存目录,起 session 时报错并提示重跑 `install` |
| **它不是配置文件**,记的是机器的事实 | `default_browser` 是"这台机器上有哪个",**你想用哪个**永远是 `session(browser=…)` 说了算 |
| **没装过也能用**,`Webmuxd()` 不要求先跑 CLI | 没记录就现探;探到系统里有合适的 chromium 也能直接用 |

记录长这样 —— **比 v1 短**:

```jsonc
{
  "version": 2,
  "at": "2026-08-17T05:20:00Z",
  "default_browser": {
    "path": "~/.cache/webmuxd/chrome-152.0.7977.42/chrome",
    "version": "152.0.7977.42",
    "source": "chrome-for-testing"
  }
}
```

## 5. 起浏览器就是起一个进程

```bash
<install 下来的 chrome> --headless=new --remote-debugging-port=<free> --user-data-dir=<profile>
```

一个进程,秒起。它是 server 的子进程,`kill-server` 跟着死
([v1/works/05 §3.2](../../v1/works/05-server-session-runtime.md))。

v1 的 `process` runtime 有两个尴尬([works/08 §6.1](../../v1/works/08-browser-runtime.md#61-process--本机三个进程)):
**要本机装 chromium**,以及

> 没有 Xvnc 就只有 API 没有画面 —— **这件事要说出来**,装作有画面比没画面更糟。

两个都消掉了:画面来自 CDP,浏览器来自 `install`。于是它从"开发和 CI 凑合用的那个"
变成了**唯一的本地跑法** —— 不是"默认",是没有别的。

### root 下自动关沙箱 —— 这条推翻了 v1 的姿态

v1 [works/08 §5.1](../../v1/works/08-browser-runtime.md) 记着 BrowserBox 那个数组
直接叫 `MISC_STABILITY_RELATED_FLAGS_THAT_REDUCE_SECURITY`(装着 `--no-sandbox`),
默认不启用;我们照抄了那个姿态:**默认不加,需要时 `WEBMUXD_NO_SANDBOX=1`**。

**v2 改了:检测到 root 就自动加,并且说出来。** 两个理由:

**① root + 沙箱没有能跑的配置。** Chromium 硬拒绝:

```
ERROR:zygote_host_impl_linux.cc:102] Running as root without --no-sandbox
is not supported. See https://crbug.com/638180.
```

这不是"你可以选"的事。报错让人自己去查,等于**把一个无解的选择丢回去** ——
而且那个开关的名字他不可能猜到。

**② 我们自己推荐的隔离路子默认就是 root。** §2 说"要隔离就把 webmuxd 放进容器",
而那三行 Dockerfile 跑出来就是 root。如果 root 一律拒绝,等于我们推荐的做法
自己走不通。

**但"不静默关掉安全特性"这条留着** —— 它变成一条必须打印的警告:

```
⚠ 你是 root —— Chromium 在 root 下必须 --no-sandbox 才起得来(crbug 638180),
  已经替你加上了。**沙箱是关着的**;想要它就换个非 root 用户跑
```

### 起不来的时候,把浏览器自己那句话带出来

0.5.2 之前,浏览器的 stderr 是 `DEVNULL`,于是起不来时我们只能说
「手工跑一遍看报什么」—— **等于把排查工作原样退回去**,而答案本来就在我们手里。

现在 stderr 落到 `<work>/chrome.log`,失败时把最后几行**去掉前缀**塞进报错:

```
✗ runtime_unavailable: 浏览器起来了但 CDP 没监听:Running as root without
  --no-sandbox is not supported. See https://crbug.com/638180.
  完整日志在 /tmp/webmuxd-x-…/chrome.log
```

去前缀那步不能省。Chromium 每行都长这样:

```
[206402:206402:0818/205945.649553:ERROR:content/browser/zygote_host/zygote_host_impl_linux.cc:102] 真正的话
```

**前面那一坨对使用者没有任何意义,留着只会把真正那句话挤出屏幕。**

### 一个 session 一个浏览器

| | |
| --- | --- |
| 一个 session | 一个浏览器进程、一个 profile、一个 CDP 端点、一个对外端口 |
| 要两个 | 起两个。profile 目录不同就互不相干,没有共享的东西 |

Chromium 的单实例锁是 `user-data-dir` 里的**文件系统** socket,给不同的 profile
目录就行 —— v1 那条"kasmweb 一台机器只能跑一个"的限制**不存在了**,而且不需要
任何论证,因为造成它的 KasmVNC 已经不在链路上。

这和 tmux 的差别仍在(tmux 一个 socket 复用所有 session),原因也仍然是
[v1/works/05 §2](../../v1/works/05-server-session-runtime.md#2-对照表) 那条:
**浏览器不是终端,一个浏览器进程就是一个隔离单位**(cookie、登录态、缓存都在 profile 里)。

## 6. `remote` —— 隔离要的话在这儿

不起任何东西,只把一个 CDP 端点记下来:

```python
sess = web.session(id="cloud", port=7900,
                   runtime="remote", cdp="wss://chrome.example.com?token=…")
print(sess.view_url)      # http://127.0.0.1:7900/  ← 我们产的画面,连的是他们的浏览器
```

v1 的 `remote` 要求对面**同时**给出画面口和 CDP。而云浏览器服务基本只给 CDP
(browserless、Browserbase、各家的 `wss://…?token=…`),画面那半要么没有、
要么是他们自己的产品界面。**v2 只要一个 CDP 端点,画面由我们产** ——
给一个只有 CDP 的云浏览器配上人能看能上手的画面,这是 v1 做不到的。

它同时是 §2 那条"隔离没了"的出口。对 webmuxd 来说这些**是同一件事**,
因为它只看见一个 CDP 端点:

- 云浏览器服务
- 同事机器上开着的那个 Chrome
- **你自己 `docker run` 起来的一个 chromium** ← 隔离在这儿,由你决定

所以隔离并没有从世界上消失,它换了位置:**从 webmuxd 的一个参数,
变成部署的一个选择。** 这正是我们想要的边界。

`stop` 的语义不变:只删本地记录,不动对面。

需要留意这条链路的 RTT 明显更长(帧和输入都要跨公网两次),
所以 [02 §3](02-frame-protocol.md#3-rtt-自适应画质) 那套自适应降质在 `remote` 上
才真正开始工作 —— 本机跑的时候它几乎不会触发。

## 7. 边界之外,webmuxd 仍然不碰

v1 [§7](../../v1/works/08-browser-runtime.md#7-边界之外webmuxd-不碰什么) 那份清单,
逐条对照 v2:

| v1 的条目 | v2 |
| --- | --- |
| 不代理画面 | **失效** —— 画面就是我们的,谈不上代理([01](01-frame-source.md)) |
| 不解析画面协议 | **失效** —— 我们定义它 |
| 不管镜像里的桌面 | **成立**,而且更彻底:没有镜像也没有桌面 |
| 不替 Chromium 做进程守护 | **成立**。它崩了我们报 `chrome_gone` |
| 不发镜像 | **成立**,而且更彻底:也不 `docker run` 别人的镜像(§2) |

只有画面那两条失效了,而它们失效的理由是同一个:**那半边现在归我们**。
其余三条不但没动,**都比 v1 更严格**。

v2 自己再加一条:

- **不碰容器编排。** 不起容器、不认容器、不探 docker。要隔离,你把我们放进去(§2)。

## 8. ↔ 别处

| | |
| --- | --- |
| 为什么画面归我们 | [01](01-frame-source.md) |
| 一个端口 | [04](04-one-port.md) |
| v1 的 runtime 契约(三分法、容器、netns) | [v1/works/08](../../v1/works/08-browser-runtime.md) —— **存档,不再适用** |
| server / session 三层 | [v1/works/05](../../v1/works/05-server-session-runtime.md) —— 原样有效 |
