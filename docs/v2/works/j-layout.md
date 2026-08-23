# j · 代码摆在哪

**一句话**:顶层按**语言**分成两棵树 —— `webmuxd/` 是 Python 的全部,
`webmuxjs/` 是 JS 的全部;JS 那棵里再分服务端和客户端,
**服务端不实现,只放协议文档**,客户端是真正在浏览器里跑的那一半。
Python 那棵照 requests **平铺**:一个文件一件事,文件名就是那件事 ——
没有 `core` / `view` 这类"填什么都对"的目录。

`webmuxjs/client/` 按前端工程搞(分层、构建、测试),**产物直接打进 wheel** ——
`pip install` 的人不需要 Node。

这一篇只管**代码摆在哪**,不改任何行为。

## 1. 为什么要动

三句话,不展开:

- `core/` `view/` 这类名字**填什么都对**,没法用一句话说清里面是什么
- **数据结构散在五个模块里**,`Tab` 还有两份定义(服务端记录一份、SDK 一份)
- **起进程的代码有两套**(chrome 一套、xpra 一套),各写各的"起、等、收" ——
  这一轮真漏过一百多个进程
- `client/` 是 Python SDK,而"客户端"在这个项目里指浏览器那一半 —— **一个词两个意思**
- 唯一的 JS 埋在 `view/static/`,而 `view/` 里还混着输入 ——
  **目录把"画面可以多条、输入只有一条"那条接缝糊掉了**

下面全是目标。

## 2. 顶层:两棵树,按语言分

```
仓库根
├── webmuxd/          ← Python 的全部。**包名不变,位置不动**
├── webmuxjs/         ← JS 的全部
│   ├── client/       浏览器里跑的接收端 —— 一个前端工程(§4),产物打进 wheel
│   ├── sidecar/      **注进被控页面里的那一段** —— 同上,产物也打进 wheel(§4.4)
│   └── server/       另一个服务端实现 —— **不实现**,只放完整的协议文档
└── docs/
```

**为什么按语言分,而不是按"服务端 / 客户端"分。**
先按角色分的话会出现 `server/python/webmuxd/` 这种路径 ——
中间那两层什么信息都没多给:`webmuxd` 本来就是 Python 的,
`webmuxjs` 本来就是 JS 的。**语言已经写在名字里了,不用再写一遍目录。**

**两棵树之间只有协议,没有共享代码。** 客户端只经 `/channel/*`(帧、事件)
和 `/api/*`(REST)说话([e §6](e-client.md#6-通道模型))。

### 2.1 `webmuxjs/server/` 为什么是空的,却要留着

它是**协议文档的去处**。

`webmuxjs/server/protocol/` 那几篇写的是**契约** —— 不是"JS 版怎么设计",
而是两边都得满足的东西。`webmuxd/` 已经实现了它。这么摆是为了将来:
**要写 JS 版服务端的人,照着那几篇实现就行,不用去读 Python 代码反推。**

> 有一处得说清楚,否则会腐烂:**契约由 Python 那份先实现,却放在 JS 那棵树下。**
> 规矩是 —— **两边不一致时以文档为准**;文档写错了就改文档,
> 不允许实现悄悄跑偏。一份对不上实现的契约,比没有契约更坏。

至于要不要真写 JS 版服务端:今天**不写**。判据还是那句 ——
**tmux 会做这个吗?** 它不会为了"也许有人喜欢别的语言"维护两份实现。
`server/TODO.md` 里记什么时候才值得做,以及真要做时从哪一步开始。

## 3. `webmuxd/` 里面:一个文件一件事

参考 [requests](https://github.com/psf/requests):**平铺,一个文件一件事,
文件名就是那件事。** 没有子包 —— 子包是用来藏东西的,而这儿没有要藏的东西。

```
webmuxd/
│  ── 谁都要用的 ──────────────────────────────────────────
├── models.py       **所有跨边界的数据结构。唯一的定义处**(§3.1)
├── exceptions.py   异常树(今天叫 errors.py)
│
│  ── 对外部世界做事 ────────────────────────────────────
├── processes.py    **所有进程都归它**:起、等、看活、收干净(§3.2)
├── config.py       **读**那份路径表(`~/.webmuxd.json`)—— 只有 `install.py` 写(§3.3)
├── cdp.py          一条到 Chromium 的连接
├── log.py          `log.jsonl`
│
│  ── 对浏览器做事 ──────────────────────────────────────
├── tabs.py         tab 表 —— sessiond 那份唯一真相
├── act.py          动作执行
├── locate.py       元素定位
├── capture.py      读一眼:一张图,和正文
├── sidecar.py      页面里那一段:装 + 那个唯一的 binding(JS 在 webmuxjs/sidecar/)
│
├── browser_ui.py   浏览器自己弹的那五类:对话框 / 下载 / 文件选择 / 权限 / 认证
│
│  ── 画面(一条腿一个文件)──────────────────────────
├── screen.py       编排:跟 tab、管观看者、背压、切换
├── jpg.py          JPG 那条:`Page.startScreencast`
├── xpra.py         VNC 那条:起 xpra + 8 字节头协议 + 上行白名单
├── rrweb.py        DOM 那条:注入记录器 + 事件流 + 资源转发
├── frames.py       28 字节头、上行消息白名单
├── quality.py      RTT 自适应
│
│  ── 输入(接缝的另一侧,§3.4)────────────────────────
├── input.py        DOM 事件 → `Input.*`
├── cursor.py       光标同步 + 白名单
│
│  ── 会话与服务 ────────────────────────────────────────
├── sessions.py     **所有会话都归它**:建、找、关;一个 session 的编排(§3.3)
├── serve.py        **真正对外那个口** —— 人打开的网页、画面、`/api/*`
│
│  ── 给人用的两个面 ────────────────────────────────────
├── api.py          `Webmuxd()` / `Session` / `Tab` —— 代码里 import 的门面,**HTTP 也在这儿**
├── cli.py          命令行 + **只有 CLI 用的那套调用代码**(§3.5)
├── install.py      `webmuxd install` —— 探、下、装、写记录,**包名表也在这儿**
│
├── _client/        浏览器端那份的构建产物 —— **不在 git 里**(§4.3)
└── _sidecar/       页面里那段的构建产物 —— 同上(§4.4)
```

### 3.1 `models.py`:所有跨边界的数据,在这儿定义一次

**判据只有一条:它会不会跨过一条边界。**
跨 HTTP、跨 WS、跨进程、跨语言的,都在这儿;只在一个模块里活着的,不在。

| | 是什么 |
| --- | --- |
| `TabInfo` | 一个 tab 的记录:id / url / title / active / opener |
| `Element` `Observation` | 一次观测,以及里面那些控件 |
| `ActionResult` | 一批动作的结果 |
| `ViewMode` | JPG / VNC / DOM —— 名字、体感、要不要有头 |
| `FrameHeader` | 28 字节头:castSessionId / frameId / targetId |
| `LogEntry` | `log.jsonl` 里的一行 |
| `Pending*` | 挡着页面的那些:对话框 / 下载 / 文件选择 / 权限 / 认证 |
| `SessionInfo` | 一个 session:id / port / 状态 / 能切哪几种画面 |

**为什么非要集中。** 现在同一个概念有两份定义 ——
服务端的 tab 记录在 `core/tabs.py`,SDK 的 `Tab` 在 `client/tab.py`,
**又是一个词两个意思**。集中之后:

- **一个概念一处定义**,改字段时不会漏掉另一份
- **协议文档有了 Python 对应物** —— `webmuxjs/server/protocol/` 里写的形状,
  就是 `models.py` 里的类,两边对不上是能测出来的(§4.2)
- 想知道"这系统里流动的是什么",看这**一个**文件

三条规矩:

1. **只有数据,没有行为。** 序列化 / 校验可以有;
   一旦它开始 import `cdp.py`,它就不再是模型层了
2. **不 import 本项目任何东西**(除 `exceptions`)—— 保证它永远在最底下
3. **凡是出现在 HTTP / WS 上的形状,必须在这儿定义一次**,别处只 `import`

> 最容易混的那条区分:**数据叫 `TabInfo`,能操作的那个叫 `Tab`。**
> 后者带着 `.click()`,通过 HTTP 干活,住在 `api.py`;
> 它**持有** `TabInfo`,不重新定义一份 —— 对应 requests 里 `Session` 和 `Response`。

### 3.2 `processes.py`:所有进程都归它

chrome、xpra、sessiond —— **凡是我们拉起来的进程,都从这一个文件出去**。

它买到的是一件很具体的事:**孤儿进程只有一个地方会漏。**
今天起进程的代码散在 `runtime/process.py` 和 `xpra.py` 两处,
各写各的"起、等端口、看活、收拾" —— 而这一轮做例子的时候真漏过:
一百多个 chrome 留在机器上,把 CDP 压到连不上。

**它不知道 chrome 是什么。** 它只会:

```
起一个 → 等它就绪(端口 / HTTP / 日志)→ 看它还活着吗 → 收干净(含子进程)
```

**"要起什么命令"由调用方给** —— kiosk 那套在 `xpra.py`(它是"VNC 那条怎么起"
的一部分),无头那几个参数在 `sessions.py` 建会话的地方;可执行文件的路径
从 `config.py` 读(§3.3)。

**这条分开之后,"怎么收进程"只有一份实现,补一次所有人都补上。**

### 3.3 `install.py` 写配置,`config.py` 读配置 —— 没有"browser.py"

**装完之后,"浏览器在哪"就是配置里的一行。** 谁要起它,从配置读路径就行 ——
不需要一个模块专门代表"浏览器"这个概念。

原来那个 `browser.py` 拆开看全是安装期的事,**归 `install.py`**:

- 版本钉死、镜像表、**并发测速挑最快的源**(量吞吐不量 RTT)
- 下载、解压、写 `INSTALLATION_COMPLETE` 标记(**标记是最后一步** ——
  目录里有个 `chrome` 不代表装完了)
- 中文字体探测和提示

剩下唯一可能留住它的是"拼 chrome 的命令行"。这条也不成立:
**无头那套和 kiosk 那套本来就是分开的,而且是有意的** ——
今天 `xpra.py` 里写着"不复用 `process.BASE_ARGS`,硬凑只会让两边都看不懂"。
所以 kiosk 那套留在 `xpra.py`(它是"VNC 那条怎么起"的一部分),
无头那几个参数跟着起它的地方走。

一个例外要说清楚:**"浏览器在哪 / 这台机器缺什么"跟着 `config.py` 走**,
不跟 `install.py`。因为起进程的 `processes.py` 是第 1 层,而 `install.py` 在第 5 层 ——
让第 1 层去 import 第 5 层就是反向依赖。而这几样(缓存目录、可执行文件路径、
`ldd` 缺不缺、有没有中文字体)本来就是**这台机器的事实**,正是 config 的题目。
`install.py` 留的是**安装期**那半:镜像表、并发测速、下载解压、写完成标记。

`config.py` 只做一件事:**读**。三条老规矩不变 ——

> **键在 = 探到了,键不在 = 没探到**(不写 `ok:false` 一类空值);
> **显式传入优先**(命令行给了路径就不读记录);
> **记录会撒谎**(缓存目录被删了它不知道),所以按记录去起、起不来就报错
> **并提示重跑 install**,不静默重探。

名字从 `env.py` 换成 `config.py` —— 大家会去找的就是这个词。
但它**不是给人手写的设置**,是 `install` 探完写下来的事实;这条要留在 docstring 里。

### 3.4 `sessions.py`:所有会话都归它

建一个、找一个、关一个;以及**一个 session 内部的编排** ——
把 tab 表、动作执行、画面、原生 UI 那几块接起来。

"浏览器从哪来"这个决定也在这儿:本机起一个(叫 `processes.py`),
还是你给一个 CDP 端点(直接连)。**它不值得单独一个文件** ——
那就是一个 if,而且只有 `sessions.py` 会问这个问题。

### 3.5 什么时候拆成两个文件

只有两条理由,别的一律合在一起:

**① 它们是"选一个"的关系。** `jpg.py` / `xpra.py` / `rrweb.py` ——
任何时刻只有一条在跑,**分开才能换**;它们互不 import,就是并列的证据。

**② 它是纯逻辑,能单独测。** `frames.py`(编解 28 字节头)、
`quality.py`(RTT → 画质)不碰 CDP、不碰网络,是普通函数 ——
这类东西单独一个文件,是为了让它有自己的测试。

**"全都要"的合在一起。** `browser_ui.py` 里那五类是**同时全开**的,
没有"换一类"这回事,而且它们共用一套规矩(今天那个 `native/base.py` 就是证据)。
拆成五个文件只会让共用的部分无家可归 —— 要么再开一个 `base.py`
(等于承认它们本来是一件事),要么复制。

> 体量不构成理由:那五类合起来约六百行,和 `act.py`(675)同量级。
> **真长到读不动了再拆,那时会有真实的信号,而不是现在猜。**

**还有一条实用的信号:有几个调用方。**
只有一个调用方、又没有自己的测试的文件,基本都该并掉 ——
`deps.py`、`transport.py`、`browser.py` 三个都是这么并的。

反过来 `locate.py` 留着:它有**两个**调用方(`act.py` 拿它解析目标、
`act.py` 是**唯一**的调用方)。留着不是因为调用方多,是因为
"把一句人话变成一个元素"本身就是一件事,而 `act.py` 已经六百多行。

### 3.6 为什么 `screen.py` 和 `input.py` 仍然必须是两个文件

设计稿里最硬的一条:**画面来源可以有多条,输入永远只有一条**
([b §1](b-input.md#1-收口在哪) · [c §7](c-view.md#7-接缝切在哪))。
三种画面已经验过 —— 画面整个换成 rrweb 重排的 DOM 之后,输入那一侧一个字没改。

**文件要让这条接缝看得见。** 混在一起的时候,
"加一条画面来源"和"加一种输入意图"看起来是同一类改动 ——
而后者是安全边界,前者不是。

这一条是 §3.5 那两条理由之外的**第三条**,而且只此一条:
**接缝两侧不合并,哪怕它们"全都要"。**
`cursor.py` 也留着不并进 `input.py` —— 一个是观看端往页面去,
一个是页面往观看端来,**方向相反**。

### 3.7 `install.py` 一个文件够了

今天分成 `install.py`(流程)和 `deps.py`(发行版包名)两个。合起来 ——
按 §3.5 那两条判据它一条都不占:不是"选一个",也不是纯逻辑
(`apply()` 直接跑 subprocess 装包)。而且 **`deps.py` 只有一个调用方,
也没有任何测试单独 import 它**;合起来 395 行,比 `browser_ui.py` 和 `act.py` 都小。

合的时候要顺手修一处:**包名现在有两份。**
`deps.py` 里有完整的发行版表,而 `xpra.py` 的报错里又硬写了一遍
("Debian/Ubuntu:`xvfb`;RHEL:`xorg-x11-server-Xvfb`")。

这两份没法靠 import 消掉 —— `xpra.py` 在第 2 层,`install.py` 在第 5 层,
往上 import 是违规的(§5)。**正确的分法是按层切:**

```
xpra.py     报"缺 Xvfb"                        ← 它只知道自己要哪个可执行文件
install.py  说"apt 装 xvfb / yum 装 xorg-x11-server-Xvfb"  ← 只有它认识包管理器
```

**低层报缺什么,高层说怎么装。** 这样包名只有一处,而且方向和依赖层一致。

### 3.8 `serve.py` 和 `cli.py`:两个面,一个服务端

- **`serve.py` 是唯一的服务端** —— 人打开的那个网页、画面、`/api/*` 全在它上面。
  这条不能动:**一个 session 一个口**,画面和 API 在同一个口上,是既定的
- **`cli.py` 里放它自己那套调用代码**,不再抽一个"共享的 API 客户端" ——
  **只有 CLI 会用它**,而 CLI 的需要和 SDK 不一样(它要打印、要退出码、要人话报错)

> 这里有一处我按理解定的,写出来好让人纠:**不为 CLI 再起第二个 HTTP 服务。**
> 再起一个就违反"一个口"那条。所以是"CLI 自己那套**请求**代码住在 `cli.py`",
> 不是"CLI 的服务端住在 `cli.py`"。

**两个面各写各的 HTTP 调用,不抽公共层。** SDK 那一侧在 `api.py`,
CLI 那一侧在 `cli.py` —— 共用一层的话,CLI 要的人话报错和 SDK 的异常树
会互相拉扯。

> 顺带回答一个容易问的:**`serve.py` 不能"顺便"把调用那侧也管了。**
> 它们是同一根线的两头 —— 一个收,一个发。而且第 3 条依赖规矩就是为这个存在的:
> SDK 要能连**别的机器上**的服务端,一旦它 import 了 `serve.py`,
> 那条路就断了(还会把服务端那套依赖拖进 SDK)。

至于要不要给"调用 HTTP"单独一个文件(今天的 `client/transport.py`):**不要**。
它 95 行、唯一的调用方就是 `api.py`、没有测试单独 import 它,
而且 §3.5 那两条判据一条都不占。**异常映射本来就不在它里面** ——
`from_response()` 住在 `exceptions.py`,那才是它该在的地方。

> requests 把 `adapters.py` 分开,是因为**适配器可插拔**(能 `mount()` 一个自己的)。
> 我们没有这个需求 —— 就一个传输。**照抄它的文件清单而不照抄它的理由,就是 cargo cult。**

## 4. `webmuxjs/client/`:按前端工程搞

它不是"几个脚本",是**实现了协议的那一份代码**。所以有源码分层、有构建、有测试。

**构建产物直接打进 wheel** —— `pip install` 的人不需要 Node,Node 只在发版时要。

```
webmuxjs/client/
├── package.json
├── vite.config.ts
├── src/
│   ├── protocol/      纯逻辑。**不碰 DOM,不碰 WebSocket**
│   │   ├── frame.ts       28 字节头:编 / 解 / targetId 的 4×uint32 LE
│   │   ├── messages.ts    上行白名单与构造
│   │   └── xpra/          rencode.ts · packet.ts(8 字节头、draw、damage-sequence)
│   ├── flow/          节奏与背压,也是纯逻辑
│   │   ├── ack.ts         额度 2 / 缓冲 3 / 留新丢旧 / 3 秒心跳
│   │   └── batch.ts       输入 25ms 聚批、同批只留最后一个 move、滚轮累加
│   ├── channel/       **唯一碰 WebSocket 的一层**,一条通道一个文件
│   │   ├── cdp.ts  xpra.ts  rrweb.ts
│   ├── input/         DOM 事件 → 消息;IME 组字在这儿收口
│   ├── screen/        三种画面各自往哪画、怎么切
│   ├── api.ts         `/api/*` 的封装
│   └── viewer/        内置那个页面 —— **不是产品界面,是验链路的**
├── test/              vitest
└── fixtures/          和 Python 对拍的 golden 文件(§4.2)
```

### 4.1 分层的判据是"能不能在 node 里测"

`protocol/` 和 `flow/` **不碰浏览器**,所以它们就是普通函数,可以直接测。
而这两层恰恰是最容易出**静默错误**的地方:字节序、额度环、丢帧策略 ——
错了不会报错,只会"偶尔卡住"或者"画面对不上"。

这条分层不是审美。**今天这些逻辑埋在 `index.html` 一整块 inline `<script>` 里,
根本没法单独测。**

`channel/` 是唯一碰 WebSocket 的一层,一条通道一个文件,和服务端路由一一对应 ——
加一条通道 = 加一个 `channel/*.ts`([e §6.6](e-client.md#66-这个模型是用来想清楚的不是插件框架))。

**`rrweb.ts` 里不许有 `send`。** 那条通道结构上没有上行 ——
服务端 handler 里根本没有接收端,客户端这一侧也用同样的方式守:
文件里没有发送函数,不是"发之前判断一下"。

### 4.2 和 Python 对拍

协议有两个实现(今天是一个半),**光靠各自的测试守不住"两边一致"**。

```
Python 侧测试 → 写 fixtures/*.json(给定输入 → 期望的字节)
JS 侧测试     → 读同一份,断言自己编出来一样、解出来也一样
```

覆盖 28 字节头、xpra 的 8 字节头和 `draw` 包、上行消息集合。
**任何一边改了格式,两边一起红。**

这项目在这个坑里栽过 —— `targetId` 的字节序当初是靠人肉发现的。
类型拦不住它,对拍能。

### 4.3 构建怎么接进 wheel

```
npm run build → webmuxjs/client/dist/ → 打包时拷进 webmuxd/_client/ → 进 wheel
```

**`webmuxd/_client/` 不需要在 git 里。** 它是构建产物 ——
打包前由构建脚本建出来,`package-data` 是在**打包那一刻**去匹配的,
所以仓库里根本不用有这个目录。git 里只有 `webmuxjs/client/src/` 一份,
**漂移不可能发生**。

> 名字:下划线说"这是生成的,别手改";`client` 说"浏览器端那份"。
> 上一版叫 `web/` —— 那个名字既没说它是产物,也没说它是什么。

**为什么产物非得落在包里面。** 装完之后机器上只有 `webmuxd` 这一个包,
`webmuxjs/` 不存在 —— sessiond 要读得到,就只能在包内。

三件配套的事:

- **开发时不用先构建**:`_client/` 不在就回退读 `webmuxjs/client/dist/`;
  再不在就提示跑 `npm run dev`(Vite 把 `/api` 和 `/channel` 代理到本机 sessiond)
- **守卫**:`_client/` 缺失、或者比 `src/` 旧 → **测试红**。
  这项目栽过一次 `.js` 没进 wheel,**不能靠"记得先构建"**
- 发布前验 wheel 里那几个文件在(现在的发布流程已经这么做了)

用 TypeScript —— Vite 原生支持,几乎不额外要什么;类型管 API 面,
**边界仍然要运行时校验**(类型过不了网络)。

### 4.4 `webmuxjs/sidecar/`:注进被控页面里的那一段

和 `client/` 平级,同一套工具链,**同一条"产物打进 wheel"的路**:

```
npm run build → webmuxjs/sidecar/dist/sidecar.js → 打包时拷进 webmuxd/_sidecar/ → 进 wheel
```

Python 那边只剩一个 `sidecar.py`:装(`addScriptToEvaluateOnNewDocument`
+ 对当前文档 `evaluate`)、以及那个唯一的 binding 名。**它不写 JS。**

**为什么值得单开一棵。** 原来这些是四段 Python 字符串字面量,散在
`probe.py` 和 `cursor.py` 里,各自把 `addBinding` +
`addScriptToEvaluateOnNewDocument` + `evaluate` 那套仪式走一遍。
两个问题,后一个更要命:

1. **四份一样的仪式,就是四次犯同一个错的机会。** 那个错犯过两次
   (`Runtime` 域没开 → binding 装上了、页面调了、服务端一条收不到、
   而且不报错),两次的表现都是"什么都没发生,也没有错"。
2. **那是全项目唯一一块没有类型检查、没有单元测试的代码 ——
   而它跑在别人的页面里。** 密码明文进日志那次就是从那儿漏出去的:
   一行 `innerText || value`,而 `value` 在密码框上就是明文。

搬过来之后 `tsc` 管类型、`vitest` 管行为、`vite` 打成一段干净的 IIFE
(不留全局,只留一个幂等标记)。里面装四样:popup 转 tab、
人在动没在动、光标形状、**这一页是不是浏览器的前台**
([f §3.1](f-tabs.md))。

两条跨语言的接缝各有一条测试盯着,因为它们错起来都不报:

| 接缝 | 错了会怎样 | 盯着它的 |
| --- | --- | --- |
| binding 名两边写了两遍 | 页面照样调、服务端一条收不到 | `the_layout_holds` |
| 探针读了表单的 `value` | 明文进 `log.jsonl`,`bundle` 带得走 | `pixels_on_a_wire`(读**建出来那份**)+ `sidecar/test/label.test.ts` |

### 4.5 这一层不做的

- ❌ **不发 npm。** [e §9](e-client.md#9-该发出去的是哪一层) 说协议层将来该能单独发,
  但那是另一个决定 —— 今天只往 wheel 里打
- ❌ **不引前端框架。** 内置页是验链路的调试页,框架买不到任何东西
- ❌ **不上 monorepo 工具。** 两个工程各自 `npm install`,各自一份锁 ——
  加一层工具管两个包,买到的比付出的少

## 5. 依赖方向:扁平之后,层要靠规矩守

没有子目录了,所以"谁能 import 谁"不再有目录挡着 —— **只能靠规矩,而规矩要有测试。**

```
第 0 层   models.py  exceptions.py          谁都能用;它们谁都不用
第 1 层   processes.py  config.py  cdp.py  log.py               对外部世界做事
第 2 层   tabs.py  act.py  locate.py  capture.py  sidecar.py   对浏览器做事
          browser_ui.py
          frames.py  quality.py  input.py  cursor.py
          jpg.py  xpra.py  rrweb.py
第 3 层   screen.py  sessions.py            编排
第 4 层   serve.py                          对外那个口
第 5 层   api.py  cli.py  install.py                          给人用的
```

五条硬规矩:

1. **只能往下 import,不能往上。** `cdp.py` 不认识 `sessions.py`
2. **`models.py` 不 import 本项目任何东西**(除 `exceptions`)—— 它永远在最底下
3. **`api.py` / `cli.py` 不 import `serve.py`** ——
   SDK 要能连**别的机器上**的服务端,一旦 import 了进程内的实现,那条路就断了
4. **`screen.py` 不 import `input.py`** —— 那是接缝,不是分层(§3.6)
5. **`jpg.py` / `xpra.py` / `rrweb.py` 互不 import** —— 三条并列的腿,
   谁也不是谁的基础;一旦串起来,"换一条"就不再是换一条

**这五条要有测试守**,而且很好写:用 `ast` 扫一遍 import 就行 ——
就是 [`tests/the_layout_holds/`](../../../tests/the_layout_holds/)。
扁平结构的代价就在这儿 —— 目录不再帮你挡,那就让测试挡。

一条例外写进测试里:**`if TYPE_CHECKING:` 里的不算。**
那些只为类型标注存在,运行时不发生,也就不构成依赖 ——
`browser_ui.py` 标注 `Session` 就是这一种。

## 6. 每个文件必须能用一句话说清自己

- 每个 `.py` **必须有 docstring**,第一行说"它是什么" ——
  文件名说了一半,另一半在这句话里
- 里面引用的设计稿**必须存在** —— 指向已删掉的编号篇比不指更坏,它看着像依据

第二条值得加一条测试守着。

> 曾经有个 `the_docs_are_true/` 守文档里的链接和锚点,后来删了 ——
> **那是给文档做的 lint,不是给这个项目做的测试**:它红的时候多半是
> 有人改了个标题,而不是代码错了。要守的是"代码里指的设计稿还在不在",
> 那是另一件事。

> 这条在扁平结构下更要紧:三十来个文件平铺,**docstring 第一行就是目录**。

## 7. 搬去哪

| 现在 | 搬去 | 一句话 |
| --- | --- | --- |
| `client/manager.py` `session.py` `tab.py` | `api.py` | 给人 import 的那一面,连同它自己那套 HTTP 调用 |
| `client/transport.py` | **`api.py`**(并进去) | 唯一调用方就是它;异常映射本来就在 `exceptions.py`(§3.8) |
| `core/tabs.Tab` · `runtime/base.Handle` · `view/modes.py` **整个** | **`models.py`** | 跨边界的数据集中一处 —— 今天散在五个模块,`Tab` 还有两份(§3.1) |
| `client/mirror.py` | **`api.py`** | 它是带后台线程的 WS 订阅,不是数据 —— 里面装的才是 `TabInfo` |
| `errors.py` | `exceptions.py` | 跟 requests 的叫法;`unavailable()` 这个构造函数也跟过去 —— 它只是造一个异常,留在 `processes.py` 会让 `xpra.py` 反向 import |
| `runtime/process.py` 里起进程那部分 + `xpra.py` 里起进程那部分 | **`processes.py`** | 两处各写一套"起、等、看活、收" —— 合成一份(§3.2) |
| `runtime/` 剩下的:`ProcessRuntime` / `RemoteRuntime` / 选哪个 | `sessions.py` | 「要 VNC 就先起 xpra」是**会话的编排**;`processes.py` 是第 1 层,不该认识 `xpra.py` |
| `serve/session.py` | `sessions.py` | 会话的编排本来就该和会话在一起 |
| `serve/app.py` `serve/__main__.py` | `serve.py` | 对外那个口 |
| `cli/__main__.py` `cli/registry.py` | `cli.py` | 连同它自己那套调用代码(§3.5) |
| `cli/install.py` + `cli/deps.py` | **`install.py` 一个文件** | 只有一个调用方,没有单独的测试(§3.7) |
| `core/cdp.py` `tabs.py` `act.py` `locate.py` | 同名平铺 | |
| `core/observe.py` | **`capture.py`**,而且只剩两个函数 | 那一包东西砍了 —— 读只剩「一张图和正文」([v2/api](../api/)) |
| `core/shim.py` | `sidecar.py` | 它是页面里的探针,`shim` 说的是手段不是身份。<br>0.18.0 起 JS 那半搬进 `webmuxjs/sidecar/`(§4.4),这边只剩"装" |
| `core/log.py` | `log.py` | |
| `browser.py` | **`install.py`**(下载 / 镜像 / 测速)+ **`config.py`**(路径在哪 / 这台机器缺什么) | 装完之后"浏览器在哪"就是配置(§3.3)。**探测那半要跟着配置走**,因为第 1 层的 `processes.py` 要用它,而 `install.py` 在第 5 层 |
| `env.py` | `config.py` | 大家会去找的就是这个词;**只有 install 写,别人只读** |
| `native/` 整个包(六个文件) | **`browser_ui.py` 一个文件** | 五类是"全都要"不是"选一个",而且共用一套规矩(§3.5) |
| `view/cast.py` | `screen.py` + `jpg.py` | 编排和"JPG 那条"是两件事(§3.4) |
| `view/relay.py` + `xpra.py` | `xpra.py` | **一个协议一个文件** |
| `view/dom.py` | `rrweb.py` | 同上 |
| `view/protocol.py` | `frames.py` | 它是帧头和上行白名单,不是"协议"这么大 |
| `view/viewer.py` | `screen.py` | 观看者和背压是编排的一部分 |
| `view/modes.py` | **`models.py` 整个** | 本来想把 `canon()` 这些放 `screen.py`,但 `processes.py`(第 1 层)也要用 —— 那就成了反向依赖。而它们本来就只是**关于 `ViewMode` 这份数据的命名和归一**,归 models 正好 |
| `view/input.py` `cursor.py` | `input.py` `cursor.py` | 平铺,**和 screen 分开** |
| `view/quality.py` | `quality.py` | |
| `view/static/` | `webmuxjs/client/src/` | 这项目唯一的 JS,不该埋在服务端目录下 |

**设计稿跟着对齐两处**:`g-native-ui.md` 现在对应五个平铺文件;
`h-runtime.md` 对应 `processes.py` + `sessions.py` 里那个 if —— 篇名该跟着改。

## 8. 怎么搬

**一次搬完,不要渐进。** 渐进的代价是两套名字并存 ——
而"两套名字并存"正是今天这个毛病的来源(`client/` 既是 SDK 又该是浏览器端)。

顺序:

1. `git mv` 全部到位,**只动位置不动内容**(这一步的 diff 应该全是路径)。
   要拆的(`cast.py` → `screen.py` + `jpg.py`)先原样搬过去,**下一步再拆**
2. 修 import,跑全套测试
3. 拆该拆的、合该合的(`processes.py` 那两份合一份是重点)
4. 补每个文件那句 docstring;加 §5 五条依赖规矩的测试、§6 两条的测试
5. 把客户端搬到 `webmuxjs/client/` 并按 §4 拆开;`npm run build` 的产物
   落到 `webmuxd/_client/`(**不进 git**),加上那条"缺失或过期就红"的守卫
6. **验 wheel 里的东西一样不少** —— 这项目栽过一次(`.js` 没进包);
   然后干净 venv 装一遍再发

**搬完之后回头看,第 1 步那个"只动位置"是对的。**
真正花时间的不是搬,是搬完暴露出来的**反向依赖**:`processes.py` 要起 xpra、
要找浏览器,而这两样一个在第 2 层一个在第 5 层。子目录一直在替这些遮丑 ——
`runtime/` import `xpra.py` 看着毫无问题,摊平之后才发现它是从第 1 层往上够。

三处因此挪了位(§7 表里都记了):`ProcessRuntime` 去了 `sessions.py`、
浏览器探测去了 `config.py`、`unavailable()` 去了 `exceptions.py`。
**这三处都不是为了好看,是为了让那条测试能过** ——
规矩没有测试守就不是规矩。

**`pyproject.toml` 不用动。** Python 包还在仓库根,位置和包名都没变 ——
这是按语言分树换来的:比 `server/python/` 那个方案少一整类打包风险。

**包名不变。** 外面 `import webmuxd` 不受影响,`pip install webmuxd` 不受影响,
CLI 名字不变,HTTP 路径不变。**这一次只动代码摆在哪。**

> **搬完了**(2026-08-21):`webmuxd/` 26 个文件平铺,`webmuxjs/client/`
> 是一个真的前端工程(vite + vitest + 和 Python 对拍的 fixture),
> 构建接在 `build_wheel` 之前。
>
> 一并记下**验的时候才发现的两件事**:
>
> - 真浏览器抓到一个所有单测都碰不到的 bug:`setTimeout` 当裸函数传进构造器,
>   浏览器里是 `Illegal invocation` —— **环 B 整个死掉**。
>   单测总喂假定时器,那条默认路径一次都没走过
> - **DOM 那条画面其实早就死了**,而且旧代码同样死
>   ([issue](../issues/dom-binding-不活过导航.md))——
>   搬代码本身没碰它,是"搬完之后拿真浏览器跑一遍"这个动作把它照出来的

## 9. 这次不做的

- ❌ **不改行为。** 每一步都该是"测试照样绿",不绿就是搬坏了
- ❌ **不重写。** 搬完之后文件内容和现在逐字一样(除了 import 和那句 docstring)
- ❌ **不做 JS 版服务端。** `webmuxjs/server/` 只放协议文档和一份 TODO
- ❌ **不动公开接口。** 包名、CLI、HTTP 路径、SDK 的类名一个不改

## 10. ↔ 别处

| | |
| --- | --- |
| 整条链路 | [a](a-architecture.md) |
| 输入为什么是接缝的另一侧 | [b §1](b-input.md#1-收口在哪) |
| 三种画面 | [c](c-view.md) |
| 观看端客户端本身的设计 | [e](e-client.md) |
| 浏览器自己的 UI | [g](g-native-ui.md) |
| 浏览器从哪来 | [h](h-runtime.md) |
