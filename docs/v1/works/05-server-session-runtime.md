# 05 · server / session / runtime

## 1. 定位

**webmuxd ≈ tmux + ttyd,只是 pane 里渲染的不是 tty 字符,是浏览器像素。**

这句话是整个设计的定盘星。拆开看是三块能力:

| 来自 | 能力 | 在 webmuxd 里 |
| --- | --- | --- |
| **tmux** | 多路复用 + 持久化 + attach/detach | server / session / tab,关掉网页只是 detach |
| **ttyd** | 把它暴露成一个网页,能看能操作能分享 | KasmVNC 那个口,token 分享,只读模式 |
| **webmuxd 自己加的** | 程序化操作 + 给智能体的观测层 | `/api/act`、`/api/observe`、操作日志 |

终端世界里这两件事是分开的,经典用法是 `ttyd tmux new -A -s work` 把它们拼起来。
webmuxd 把它们合成一个,**因为浏览器的渲染层本来就是网页——暴露不是可选项,是本体**。

这带来一个直接后果:**HTTP 监听永远开着**,不然你根本没法看。
安全控制点是绑定地址和 token,不是"开不开"([api/server.md §1](../api/server.md))。

第三块是终端世界没有的:tmux 有 `send-keys` 和 `capture-pane`,但没人把它们做成
给程序和模型用的接口。`/api/act` 和 `/api/observe` 大致就是这两个命令的 HTTP 版本,
外加一层专门为多模态模型准备的元素表。

凡是拿不准的地方,先问"tmux 或 ttyd 在这儿是怎么做的",除非有明确理由,否则照抄。
下面先给完整对照,再只讲**不一样的地方**。

## 2. 对照表

| tmux / ttyd | webmuxd | 说明 |
| --- | --- | --- |
| tmux server | **server** | 按需自启,持有全部 session |
| tmux session | **session** | 一整套 kasm + Chrome + sessiond |
| tmux window | **tab** | 浏览器标签页 |
| tmux pane | — | **不做**,理由见 §5 |
| client | 上层 UI / CLI / lib | 都是 client |
| `/tmp/tmux-$UID/default` | `$XDG_RUNTIME_DIR/webmuxd/default.sock` | 控制 socket |
| `tmux -L name` / `-S path` | 同 | 换 socket = 换一套独立的 server |
| attach / detach | 连上 / 断开画面 | |
| scrollback | 操作日志 | |
| `~/.tmux.conf` | `~/.webmuxd.conf` | 同样的 `set -g` 写法 |
| `send-keys` | `click` / `type` / `key` / `POST /api/act` | |
| `capture-pane` | `capture` / `observe` / `GET /api/observe` | |
| fork + exec 一个 shell | **runtime** | **唯一多出来的概念**,见 §4 |
| 一个 socket 复用全部 session | **一个 session 两个端口** | kasm 复用不了,见表下 |
| **ttyd** `-p PORT` | server `:7800` / session `:6901`+`:7900` | |
| **ttyd** 默认只读,`-W` 才可写 | `share` 默认只读,`--writable` 才可写 | 同款默认,见 §3.4 |
| **ttyd** `-c user:pass` | `WEBMUXD_TOKEN` | |
| **ttyd** `-b base-path` | `/s/<id>/` 代理路径 | |
| **ttyd** `-t` 客户端选项 | 上层自己决定怎么裁、怎么画([04](04-chrome-ui-externalization.md)) | |
| **ttyd** 一个进程一个命令 | 一个 session 一个浏览器 | |
| **ttyd** `-m` 最大客户端 | 多人同看一个 session | |

**端口那条是硬约束,也是和 tmux 差别最大的一处。** tmux 的 server 用一个 socket
承载所有 session;kasm 不行 —— 每个 session 自带一块 VNC 屏,而且
webmuxd 的 API 是另一个口([01 §1](01-container.md#1-一张图)):

```
session work    :6901 画面   :7900 API
session scrape  :6902 画面   :7901 API
```

所以 `:7800` 那个 server 存在的意义之一就是**对外只开一个口**,
按名字把两个都代理进去,免得把一片端口全暴露出去。

## 3. server

### 3.1 和 tmux 一样的部分

- **按需自启。** 第一次 `webmuxd new` 时自动拉起,永远不用手敲 `start-server`
  (有这个命令,但和 tmux 一样几乎用不到)。
- **持有全部 session。** session 列表、名字、endpoint 都由它维护。
- **一个 socket 一套 server。** 默认 `default.sock`;`-L ci` 或 `-S /path/x.sock`
  开出互不可见的另一套,和 tmux 完全一致。
- **`kill-server` 干掉一切。**
- **client 是薄的。** CLI 只是把命令递给 server,自己不持有状态。

### 3.2 和 tmux 不一样的部分

**① 它要管 runtime。** tmux 拉 pane 就是 fork+exec,一种方式;
webmuxd 拉 session 有三种(容器 / 进程 / 远端),server 负责挑一个并记住用了哪个。

**② 容器 session 能在 server 重启后被重新收养。**

| session 的 runtime | server 挂了会怎样 |
| --- | --- |
| `process` | **跟着死**——它们是 server 的子进程,和 tmux 的 pane 一样 |
| `container` | **活着**。server 重启后按 `webmuxd.session` label 重新发现并接管 |
| `remote` | **活着**,本来就不归它管 |

这个不对称是故意的,而且是好事:生产用 `container`,server 升级重启不影响正在跑的任务;
开发用 `process`,`kill-server` 一把清干净。**但要在 `webmuxd ls` 里明确显示 runtime**,
不然人不知道自己的 session 抗不抗得住 server 重启。

**③ 它同时是 ttyd —— HTTP 监听是本体,不是可选项。**

tmux 的 server 只有一个 unix socket。webmuxd 的 server 还必须提供 HTTP,
否则画面无处可去。所以:

| | 地址 | 默认 | 说明 |
| --- | --- | --- | --- |
| 控制 socket | `$XDG_RUNTIME_DIR/webmuxd/default.sock` | 开 | CLI 走这个,靠文件权限 |
| HTTP | `127.0.0.1:7800` | **开** | 管理 + 按名字代理到各 session 的两个口 |
| HTTP 对外 | `0.0.0.0:7800` | 关 | `--listen`,**必须配 token** |

**从 `127.0.0.1` 换到 `0.0.0.0` 是这个系统里最需要谨慎的一步操作**——
那是把一个能操作浏览器、且很可能带着登录态的东西放到网上。
没设 `WEBMUXD_TOKEN` 时直接拒绝启动,不给"我待会再加"的机会。

它代理到各个 session:

```
                ┌───────────────────────────────────────────┐
                │  webmuxd server            :7800          │
 CLI ──────────►│                                           │
 上层 UI ──────►│  /api/sessions          管理              │
                │  /s/work/vnc/    → work 的画面           │──► :6901
                │  /s/work/api/    → work 的 API           │──► :7900
                │  /s/scrape/…     → scrape 的两个口       │──► :6902 :7901
                └───────────────────────────────────────────┘

 lib ──────────────────── 直连 ──────────────────────────────► :7900
```

**一个地址通到所有 session**,不用记一堆端口,远程访问也只开一个口。

**lib 不走这条路。** 它手里就是一个 session 的地址,直连那个 API 口 ——
[sdk](../sdk/) 里根本没有"列举 session"这一层(§3.4)。
经 server 代理时它也只是换个 base URL,行为一样。

管理接口见 [api/server.md](../api/server.md)。

### 3.3 server 不做什么

这里要划清界线。tmux 的 server 是**本机的 session 持有者**,不是编排平台。
webmuxd 的 server 同样:

- ❌ 不做多租户、RBAC、配额
- ❌ 不做数据库 —— 状态就是 `~/.webmuxd/` 下几个 json,崩了靠现场探活重建
- ❌ 不做容器池、预热、调度
- ❌ 不做跨机器编排 —— 要多机就多开几个 server

**判断标准还是那句:tmux 的 server 会做这个吗?** 不会就别加。

### 3.4 分享:抄 ttyd 的默认值

ttyd 默认只读,要加 `-W` 才允许客户端敲键盘。这个默认是对的,照抄。
但要分成两件事,不要混:

| | 谁用 | 鉴权 | 权限 |
| --- | --- | --- | --- |
| `webmuxd attach` | **你自己** | 控制 socket(文件权限) | 完整 |
| `webmuxd share` | **给别人** | 一次性 token,带过期 | **默认只读** |

`share` 出来的链接发给同事,他能实时看着你的浏览器跑,但点不了东西。
要可操作得显式 `--writable`,而且 CLI 会打印一行警告。

这个不对称是故意的:一个能操作你带登录态浏览器的链接,不该顺手就发出去。

## 4. runtime —— 唯一多出来的概念

tmux 里 pane 就是 fork+exec 一个 shell,只有一种拉法,所以它不需要这层。
浏览器这一套(X + VNC + Chrome + sessiond)重得多,拉起方式有真实的分歧,所以要抽象。

### 4.1 接口

一个 runtime 只实现四件事:

```python
class Runtime:
    def start(spec) -> Handle    # 拉起一套,返回 {id, endpoint}
    def stop(handle)
    def alive(handle) -> bool
    def list() -> [Handle]       # 用于 server 重启后重新发现
```

**这条线以上全部一样。** CLI、lib、上层 UI、`/api/*` 拿到的都只是一个 endpoint,
不知道也不关心背后是容器还是进程。所以加一种 runtime 不动任何上层代码。

### 4.2 三种

| | `container`(默认) | `process` | `remote` |
| --- | --- | --- | --- |
| 怎么拉 | `docker run` | 本机拉 Xvnc + Chrome + sessiond | 不拉,接现成的 |
| 隔离 | ✅ | ❌ **页面跑在你自己机器上** | 看对面 |
| 启动 | 几秒 | 秒起 | 立即 |
| 依赖 | docker + 镜像 | 宿主机装了 Xvnc/Chrome | 一个 URL |
| server 重启 | 活着,被重新收养 | 跟着死 | 活着 |
| 适合 | 生产 | 开发 / CI / 没 docker | 已经有人部好了 |

`process` runtime 比容器多分配一样东西:**X display 号**。
`:7` 这种要探测空闲(`/tmp/.X11-unix/X7` 不存在才算),和端口一起记进 handle。

> **`process` 不是生产形态。** 页面是不可信内容,拿它跑生产等于把浏览器沙箱之外的
> 隔离全放弃了。`--help` 和文档里都要写明白。

### 4.3 不静默降级

`webmuxd new` 没给 `--runtime` 时:配置里的 `set -g runtime` → 没配就 `container` →
**docker 不可用则报错并提示 `--runtime process`**。

不自动降级。静默降级会让人以为自己有隔离,而实际上没有。

## 5. 为什么不做 pane

tmux 的 pane 是分屏。webmuxd 不做,原因很具体:
**一块 VNC 屏幕同时只显示一个 tab**——Chrome 的多个 tab 共用一个窗口。

要做真正的分屏(几个 tab 并排各自独立看、独立点),得放弃 VNC 改用
CDP 的 screencast 逐 target 出帧。那是另一个产品形态,v1 不做。

想并排看两个页面?**开两个 session,上层把两块画面并排放。** 这也是 tmux 的答案之一。

## 6. 状态存哪

| | container | process |
| --- | --- | --- |
| Chrome profile | 卷 `webmuxd-<name>:/data/profile` | `~/.webmuxd/<name>/profile` |
| 操作日志 | `/data/log.jsonl` | `~/.webmuxd/<name>/log.jsonl` |
| 截图 | `/data/shots/` | `~/.webmuxd/<name>/shots/` |
| 下载 | `/data/downloads/` | `~/.webmuxd/<name>/downloads/` |

**sessiond 只认一个 `--data-dir`,完全不知道自己跑在容器里还是进程里。**
这是两种 runtime 行为一致的关键。

server 自己的状态:

```
~/.webmuxd/
├── server.json              # 监听地址、启动时间
├── sessions/<name>.json     # 名字、runtime、endpoint、handle
└── <name>/                  # process runtime 的数据目录
```

这些文件是**线索,不是真相**。`webmuxd ls` 每次都调 `alive()` 现场核实,
死掉的标 `dead` 并提示清理:

```console
$ webmuxd ls
work    container  6901/7900  3 tabs  shop.example.com/cart   ●
dev     process    6902/7901  1 tab   localhost:3000
prod    remote     -          5 tabs  intranet.corp/dash
stale   process    6904/7903  dead — webmuxd kill -t stale 清掉
```

## 7. 和 tmux 故意不一样的地方

除了 §3.2 §4 §5 之外,还有几处刻意偏离,都记在这:

| | tmux | webmuxd | 为什么 |
| --- | --- | --- | --- |
| 无 `-t` 又有多个 session | 挑最近的 | **报错** | 点错浏览器比敲错终端代价大 |
| 多 client 同时输入 | 字符交错 | 人操作后 3 秒内 API 让路(`busy_human`) | 同上 |
| 快捷键前缀 `C-b` | 有 | **无** | 没有终端键盘可劫持,命令都是子命令 |
| 状态栏 | `status-line` | 外面自己画 tab 条 | 见 [04](04-chrome-ui-externalization.md) |
| 复制模式 | `copy-mode` | `capture` / `extract` | |

## 8. 用起来

```bash
webmuxd new -s work                                    # container,server 自动起
webmuxd new -s dev  --runtime process
webmuxd new -s prod --runtime remote --endpoint https://browser.internal:7800
webmuxd ls
webmuxd click -t dev "登录"                            # runtime 对用起来不可见
webmuxd kill-server                                    # process 的死,container 的活
```

```python
from webmuxd import Webmuxd

web  = Webmuxd()                                          # 管理实例,空壳
sess = web.session(id="work", port=7900, vnc_port=6901)   # container(默认)
sess = web.session(id="dev",  port=7901, vnc_port=6902, runtime="process")
sess = web.session(id="prod", runtime="remote",
                   endpoint="https://browser.internal:7800")

tab = sess.open("https://shop.example.com")
tab.click("登录")
```

**runtime 只在第一次 `session()` 时出现一次,之后所有代码都一样。** 这是这层抽象的全部意义。

### 三层概念,lib 里一个不少

| | lib | CLI | api |
| --- | --- | --- | --- |
| **server** | `Webmuxd()` —— 空壳管理实例,`create` 之前不起任何东西 | 按需自启的 server | `/api/sessions` `/api/server` |
| **session** | `Session` —— 一个 kasm 容器,`web.session(id=)` 拿 | `-t ID` | `/api/*`(session 内) |
| **runtime** | `session(runtime=)`,之后不可见 | `--runtime` | `POST /api/sessions` 的字段 |

**`Webmuxd()` 不占端口也不起浏览器** —— 给它 `port=` 才把管理面暴露出去,
那对应的就是 `webmuxd server --listen`。不给就只走 socket,和 tmux 一样。

页面动作**不挂在 session 上**,挂在 `Tab` 上 —— `sess.open()` 拿句柄,
然后 `tab.click()`([sdk/tab/](../sdk/tab/))。
`sess.click(...)` 这种方法故意不给:一个 session 有多个 tab,"在哪个 tab 上点"
不该靠隐式的当前值。
