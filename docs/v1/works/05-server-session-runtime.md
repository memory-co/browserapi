# 05 · server / session / runtime

## 1. 一句话

**webmux 就是 tmux,只是 pane 里渲染的不是 tty 字符,是浏览器像素。**

这句话是整个设计的定盘星。凡是拿不准的地方,先问"tmux 在这儿是怎么做的",
除非有明确理由,否则照抄。下面先给完整对照,再只讲**不一样的地方**。

## 2. 对照表

| tmux | webmux | 说明 |
| --- | --- | --- |
| server | **server** | 按需自启,持有全部 session |
| session | **session** | 一整套 kasm + Chrome + muxd |
| window | **tab** | 浏览器标签页 |
| pane | — | **不做**,理由见 §5 |
| client | 观看页面 / CLI / lib | 都是 client |
| `/tmp/tmux-$UID/default` | `$XDG_RUNTIME_DIR/webmux/default.sock` | 控制 socket |
| `tmux -L name` / `-S path` | 同 | 换 socket = 换一套独立的 server |
| attach / detach | 打开 / 关掉观看页面 | |
| scrollback | 操作日志 | |
| `~/.tmux.conf` | `~/.webmux.conf` | 同样的 `set -g` 写法 |
| `send-keys` | `click` / `type` / `key` | |
| `capture-pane` | `capture` / `observe` | |
| fork + exec 一个 shell | **runtime** | **唯一多出来的概念**,见 §4 |

## 3. server

### 3.1 和 tmux 一样的部分

- **按需自启。** 第一次 `webmux new` 时自动拉起,永远不用手敲 `start-server`
  (有这个命令,但和 tmux 一样几乎用不到)。
- **持有全部 session。** session 列表、名字、endpoint 都由它维护。
- **一个 socket 一套 server。** 默认 `default.sock`;`-L ci` 或 `-S /path/x.sock`
  开出互不可见的另一套,和 tmux 完全一致。
- **`kill-server` 干掉一切。**
- **client 是薄的。** CLI 只是把命令递给 server,自己不持有状态。

### 3.2 和 tmux 不一样的部分

**① 它要管 runtime。** tmux 拉 pane 就是 fork+exec,一种方式;
webmux 拉 session 有三种(容器 / 进程 / 远端),server 负责挑一个并记住用了哪个。

**② 容器 session 能在 server 重启后被重新收养。**

| session 的 runtime | server 挂了会怎样 |
| --- | --- |
| `process` | **跟着死**——它们是 server 的子进程,和 tmux 的 pane 一样 |
| `container` | **活着**。server 重启后按 `webmux.session` label 重新发现并接管 |
| `remote` | **活着**,本来就不归它管 |

这个不对称是故意的,而且是好事:生产用 `container`,server 升级重启不影响正在跑的任务;
开发用 `process`,`kill-server` 一把清干净。**但要在 `webmux ls` 里明确显示 runtime**,
不然人不知道自己的 session 抗不抗得住 server 重启。

**③ 它可以听 TCP,并代理到各个 session。**

```
              ┌─────────────────────────────────────────┐
              │  webmux server        :7800             │
 CLI ────────►│                                         │
 浏览器 ──────►│  /api/sessions      管理               │
 lib ────────►│  /s/work/           → session work     │──► :7900
              │  /s/scrape/         → session scrape   │──► :7901
              └─────────────────────────────────────────┘
```

**一个地址通到所有 session**,不用记一堆端口,远程访问也只开一个口。
session 自己的端口仍然直连得到,但平时不用。

管理接口见 [api/server.md](../api/server.md)。

### 3.3 server 不做什么

这里要划清界线。tmux 的 server 是**本机的 session 持有者**,不是编排平台。
webmux 的 server 同样:

- ❌ 不做多租户、RBAC、配额
- ❌ 不做数据库 —— 状态就是 `~/.webmux/` 下几个 json,崩了靠现场探活重建
- ❌ 不做容器池、预热、调度
- ❌ 不做跨机器编排 —— 要多机就多开几个 server

**判断标准还是那句:tmux 的 server 会做这个吗?** 不会就别加。

## 4. runtime —— 唯一多出来的概念

tmux 里 pane 就是 fork+exec 一个 shell,只有一种拉法,所以它不需要这层。
浏览器这一套(X + VNC + Chrome + muxd)重得多,拉起方式有真实的分歧,所以要抽象。

### 4.1 接口

一个 runtime 只实现四件事:

```python
class Runtime:
    def start(spec) -> Handle    # 拉起一套,返回 {id, endpoint}
    def stop(handle)
    def alive(handle) -> bool
    def list() -> [Handle]       # 用于 server 重启后重新发现
```

**这条线以上全部一样。** CLI、lib、观看页面、`/api/*` 拿到的都只是一个 endpoint,
不知道也不关心背后是容器还是进程。所以加一种 runtime 不动任何上层代码。

### 4.2 三种

| | `container`(默认) | `process` | `remote` |
| --- | --- | --- | --- |
| 怎么拉 | `docker run` | 本机拉 Xvnc + Chrome + muxd | 不拉,接现成的 |
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

`webmux new` 没给 `--runtime` 时:配置里的 `set -g runtime` → 没配就 `container` →
**docker 不可用则报错并提示 `--runtime process`**。

不自动降级。静默降级会让人以为自己有隔离,而实际上没有。

## 5. 为什么不做 pane

tmux 的 pane 是分屏。webmux 不做,原因很具体:
**一块 VNC 屏幕同时只显示一个 tab**——Chrome 的多个 tab 共用一个窗口。

要做真正的分屏(几个 tab 并排各自独立看、独立点),得放弃 VNC 改用
CDP 的 screencast 逐 target 出帧。那是另一个产品形态,v1 不做。

想并排看两个页面?**开两个 session,把两个观看页面并排放。** 这也是 tmux 的答案之一。

## 6. 状态存哪

| | container | process |
| --- | --- | --- |
| Chrome profile | 卷 `webmux-<name>:/data/profile` | `~/.webmux/<name>/profile` |
| 操作日志 | `/data/log.jsonl` | `~/.webmux/<name>/log.jsonl` |
| 截图 | `/data/shots/` | `~/.webmux/<name>/shots/` |
| 下载 | `/data/downloads/` | `~/.webmux/<name>/downloads/` |

**muxd 只认一个 `--data-dir`,完全不知道自己跑在容器里还是进程里。**
这是两种 runtime 行为一致的关键。

server 自己的状态:

```
~/.webmux/
├── server.json              # 监听地址、启动时间
├── sessions/<name>.json     # 名字、runtime、endpoint、handle
└── <name>/                  # process runtime 的数据目录
```

这些文件是**线索,不是真相**。`webmux ls` 每次都调 `alive()` 现场核实,
死掉的标 `dead` 并提示清理:

```console
$ webmux ls
work    container  7900  3 tabs  shop.example.com/cart   ●
dev     process    7901  1 tab   localhost:3000
prod    remote     -     5 tabs  intranet.corp/dash
stale   process    7903  dead — webmux kill -t stale 清掉
```

## 7. 和 tmux 故意不一样的地方

除了 §3.2 §4 §5 之外,还有几处刻意偏离,都记在这:

| | tmux | webmux | 为什么 |
| --- | --- | --- | --- |
| 无 `-t` 又有多个 session | 挑最近的 | **报错** | 点错浏览器比敲错终端代价大 |
| 多 client 同时输入 | 字符交错 | 人操作后 3 秒内 API 让路(`busy_human`) | 同上 |
| 快捷键前缀 `C-b` | 有 | **无** | 没有终端键盘可劫持,命令都是子命令 |
| 状态栏 | `status-line` | 外面自己画 tab 条 | 见 [04](04-chrome-ui-externalization.md) |
| 复制模式 | `copy-mode` | `capture` / `extract` | |

## 8. 用起来

```bash
webmux new -s work                                    # container,server 自动起
webmux new -s dev  --runtime process
webmux new -s prod --runtime remote --endpoint https://browser.internal:7900
webmux ls
webmux click -t dev "登录"                            # runtime 对用起来不可见
webmux kill-server                                    # process 的死,container 的活
```

```python
from webmux import Session

s = Session.new("work")                                # container
s = Session.new("dev", runtime="process")
s = Session.connect("https://browser.internal:7900")   # remote
s = Session.attach("work")                             # 接上已存在的

s.click("登录")
```

**runtime 只在创建时出现一次,之后所有代码都一样。** 这是这层抽象的全部意义。
