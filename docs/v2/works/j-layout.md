# j · 代码摆在哪

**一句话**:顶层按**语言**分成两棵树 —— `webmuxd/` 是 Python 的全部,
`webmuxjs/` 是 JS 的全部;JS 那棵里再分服务端和客户端,
**服务端不实现,只放协议文档**,客户端是真正在浏览器里跑的那一半。
Python 树里往下,每个目录的名字都必须回答"它是什么",
不能是 `core` / `view` 这类"填什么都对"的词。

`webmuxjs/client/` 按前端工程搞(分层、构建、测试),**产物直接打进 wheel** ——
`pip install` 的人不需要 Node。

这一篇只管**代码摆在哪**,不改任何行为。

## 1. 为什么要动

三句话,不展开:

- `core/` `view/` 这类名字**填什么都对**,没法用一句话说清里面是什么
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

## 3. `webmuxd/` 里面:先按"两种用法"分,再按"对谁做事"分

Python 这一份有**两种用法**:命令行,和代码里 `import`。
两个入口平级,往下走到同一处。

```
webmuxd/
├── cli/            用法一:命令行(webmuxd new / install / log …)
├── sdk/            用法二:代码里 import(Webmuxd / Session / Tab)
├── sessiond/       一个 session 一个进程 —— HTTP 壳 + 编排
│
├── launch/         浏览器从哪来:本机起一个,或者你给一个 CDP 端点
├── browser/        对浏览器做事:CDP 连接、tab 表、动作、定位、观测、探针
├── browser_ui/     浏览器自己弹的那些:对话框、下载、文件选择、权限、认证
├── screen/         画面:三种来源 + 编排 + 画质
│   └── source/     jpg.py · vnc.py · dom.py —— **一种画面一个文件**
├── input/          输入翻译 + 光标同步 —— **和 screen 分开,那是接缝**
├── record/         log.jsonl:做过的事记下来
└── web/            webmuxjs/client 的构建产物,sessiond 拿它当静态文件
```

> `web/` 里是**构建产物,不是源码** —— 源码在 `webmuxjs/client/src/`。
> 发布时拷进来,这样 wheel 自带客户端、装完就能用。
> **不要在这个目录里改东西**,下次构建会盖掉。

### 3.1 为什么 `sdk/` 和 `cli/` 是平级的两个入口

它们是**两种用法,不是两层**。`cli` 不该是 `sdk` 的壳,`sdk` 也不该知道
`cli` 存在。两个都往下走到同一处:起一个 session、然后经 HTTP 跟它说话。

**`sdk/` 不许 import `sessiond/`。** 这条不是洁癖 —— SDK 要能连一个
**别的机器上**的 sessiond,一旦它 import 了进程内的实现,那条路就断了。
今天它走 HTTP(`sdk/transport.py`),这条规矩把它钉住。

### 3.2 为什么 `screen/` 和 `input/` 必须分开

设计稿里最硬的一条是:**画面来源可以有多条,输入永远只有一条**
([b §1](b-input.md#1-收口在哪) · [c §7](c-view.md#7-接缝切在哪))。
三种画面已经验过这条 —— 画面整个换成 rrweb 重排的 DOM 之后,输入那一侧一个字没改。

**目录要让这条接缝看得见。** 混在一个 `view/` 里的时候,
"往 screen 里加一条来源"和"往 input 里加一种意图"看起来是同一类改动 ——
而后者是安全边界,前者不是。

### 3.3 `screen/source/` 一种画面一个文件

`source/jpg.py` · `source/vnc.py` · `source/dom.py`,编排留在 `screen.py`。

好处很具体:**"加第四条腿要动哪些文件"变成一个能一眼回答的问题** ——
加一个 `source/*.py`,在 `modes.py` 那张表里加一行。同一类东西一种摆法。

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
npm run build → webmuxjs/client/dist/ → 打包时拷进 webmuxd/web/ → 进 wheel
```

- **`webmuxd/web/` 进 gitignore。** git 里只有 `src/` 一份,漂移不可能发生
- 开发时 `npm run dev`,Vite 把 `/api` 和 `/channel` 代理到本机 sessiond
- **必须加一个守卫**:`webmuxd/web/` 缺失、或者比 `src/` 旧,就让测试红。
  这项目栽过一次 `.js` 没进 wheel,**不能靠"记得先构建"**

用 TypeScript —— Vite 原生支持,几乎不额外要什么;类型管 API 面,
**边界仍然要运行时校验**(类型过不了网络)。

### 4.4 这一层不做的

- ❌ **不发 npm。** [e §9](e-client.md#9-该发出去的是哪一层) 说协议层将来该能单独发,
  但那是另一个决定 —— 今天只往 wheel 里打
- ❌ **不引前端框架。** 内置页是验链路的调试页,框架买不到任何东西
- ❌ **不上 monorepo 工具。** 就一个 JS 工程

## 5. 依赖方向:这才是不再腐烂的那条

```
cli/ ──┐
       ├──▶ sdk/ ──HTTP──▶ sessiond/ ──▶ screen/  input/  browser_ui/
       │                                    └──────┴──────┴──▶ browser/  launch/  record/
webmuxjs/client/ ──协议──▶ (sessiond 的 /channel/* 和 /api/*)
   src/channel/ ──▶ src/protocol/  src/flow/     ← 上面两层不碰浏览器
```

四条硬规矩:

1. **`sdk/` 不 import `sessiond/`** —— 否则连不了远程的那一个(§3.1)
2. **`screen/` 不 import `input/`** —— 那是接缝,不是分层(§3.2)
3. **`browser/` / `launch/` / `record/` 不 import 上面任何一层** —— 它们是被用的,不是用人的
4. **`webmuxjs/` 和 `webmuxd/` 不共享一行代码** —— 只有协议,而协议写在
   `webmuxjs/server/protocol/`

**这四条要有测试守。** 目录改名是一次性的,依赖方向不守住就会慢慢长回来 ——
今天的 `core/` 就是这么来的。

## 6. 每个包必须能用一句话说清自己

- 每个包的 `__init__.py` **必须有 docstring**,第一行说"它是什么"
- 里面引用的设计稿**必须存在** —— 指向已删掉的编号篇比不指更坏,它看着像依据

这两条也加测试。现在已经有 `the_docs_are_true/` 守文档里的链接,
再加一条守代码里的。

## 7. 改名对照表

| 现在 | 改成 | 一句话理由 |
| --- | --- | --- |
| `client/` | `sdk/` | 它是给别人 import 的那套;"客户端"这个词让给浏览器那一半 |
| `core/act.py` `locate.py` `observe.py` `cdp.py` `tabs.py` `shim.py` | `browser/` | 共同点是**对浏览器做事** |
| `core/log.py` | `record/` | 它记的是**做过的事**,和"对浏览器做事"不是一回事 |
| `native/` | `browser_ui/` | 浏览器**自己的** UI —— 六样东西的共同点 |
| `runtime/` | `launch/` | 它自己写着"只回答一个问题:CDP 端点从哪来" |
| `serve/` | `sessiond/` | 它就是那个进程,文档里一直这么叫 |
| `view/cast.py` `dom.py` `relay.py` `modes.py` `quality.py` `viewer.py` `protocol.py` | `screen/` | 画面这一半 |
| `view/input.py` `cursor.py` | `input/` | **接缝的另一侧**(§3.2) |
| `view/static/` | `webmuxjs/client/src/` | 它是这个项目里唯一的 JS,不该埋在服务端目录下 |
| `xpra.py` | `screen/source/vnc.py` 的一部分 | 三种画面摆法要一致(§3.3) |

**设计稿也要跟着对齐两处**:`g-native-ui.md` 对应 `browser_ui/`(名字已经一致),
`h-runtime.md` 对应 `launch/` —— 那一篇的篇名该跟着改。

## 8. 怎么搬

**一次搬完,不要渐进。** 渐进的代价是两套名字并存 ——
而"两套名字并存"正是今天这个毛病的来源(`client/` 既是 SDK 又该是浏览器端)。

顺序:

1. `git mv` 全部到位,**只动位置不动内容**(这一步的 diff 应该全是路径)
2. 修 import,跑全套测试
3. 每个包补 `__init__.py` 的一句话,顺手把指向已删文档的 docstring 修掉
4. 加 §5 那四条依赖规矩的测试、§6 那两条的测试
5. 把客户端搬到 `webmuxjs/client/` 并按 §4 拆开;`npm run build` 的产物
   落到 `webmuxd/web/`,加上那条"缺失或过期就红"的守卫
6. **验 wheel 里的东西一样不少** —— 这项目栽过一次(`.js` 没进包);
   然后干净 venv 装一遍再发

**`pyproject.toml` 不用动。** Python 包还在仓库根,位置和包名都没变 ——
这是按语言分树换来的:比 `server/python/` 那个方案少一整类打包风险。

**包名不变。** 外面 `import webmuxd` 不受影响,`pip install webmuxd` 不受影响,
CLI 名字不变,HTTP 路径不变。**这一次只动代码摆在哪。**

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
