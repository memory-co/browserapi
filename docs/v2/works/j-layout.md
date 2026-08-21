# j · 代码摆在哪

**一句话**:顶层先分**服务端**和**客户端** —— 客户端一定是 JS,服务端今天是
Python、以后可能有 JS 版;服务端有两种用法,**命令行**和**代码里 import**。
往下每个目录的名字都必须回答"它是什么",不能是 `core` / `view` 这类
"填什么都对"的词。

这一篇只管**代码摆在哪**,不改任何行为。

## 1. 现在的问题不是"乱",是"名字不承载信息"

逐条摆出来,每一条都能对着代码验:

| | 毛病 |
| --- | --- |
| `core/` | **连 docstring 都没有** —— 不是忘了写,是"核心"本来就没法写。里面装着 CDP 连接、tab 表、动作执行、元素定位、页面观测、注入探针、操作日志 —— 七样东西的唯一共同点是"都挺重要" |
| `client/` | **它是 Python SDK。** 而这个项目里"客户端"指的是浏览器里那一半([e](e-client.md))—— **同一个词指着两样东西**,这是最坏的一种命名 |
| `view/static/` | **唯一真正的客户端(`index.html` / `xpra.js` / `rencode.js`)埋在服务端目录往下三层。** 它是这个项目里唯一的 JS,却藏得最深 |
| `view/` | 里面混着 `input.py` 和 `cursor.py`。而设计稿的接缝恰恰是**画面可以有多条、输入永远只有一条**([c §7](c-view.md#7-接缝切在哪))—— 目录把这条接缝糊掉了 |
| `native/` | "原生"什么?那六样(对话框 / 下载 / 文件选择 / 权限 / 认证)的共同点是**浏览器自己弹出来、挡在页面前面、必须有人应答** |
| `runtime/` | 这个词在别处指语言运行时。而它自己的 `base.py` 第一行写着:"**只回答一个问题:这个 session 的 CDP 端点从哪来**" —— 名字该说这个 |
| `serve/` | 和 server 撞词。它其实就是 sessiond,文档里一直这么叫 |

还有一处腐烂:**docstring 大面积指向 `docs/v1/` 和已经删掉的编号篇**
(`works/06`、`works/07`、`works/11`)。指向不存在的设计稿比不指更坏 ——
它看着像依据。

## 2. 顶层:服务端 / 客户端

```
webmuxd/                     ← 仓库根
├── client/                  ← 浏览器里跑的那一半。**只有这里是 JS**
├── server/
│   └── python/              ← 今天唯一的实现
└── docs/
```

**为什么这一刀要切在最外面。** 这两半之间只有协议,没有共享代码 ——
客户端只经 `/channel/*`(帧、事件)和 `/api/*`(REST)说话
([e §6](e-client.md#6-通道模型))。既然连接口都只有协议,那就不该混在一个目录树里。

**`server/python/` 而不是 `server/`。** 以后可能有 `server/node/` ——
把语言写进路径,是为了那一天不用再动一次目录。今天只有一个实现,
但这一层现在加是免费的,以后加要动打包配置。

> 代价说清楚:Python 包从仓库根挪到 `server/python/` 之后,
> `pyproject.toml` 要跟着搬,CI 里的路径也要改。**这是一次性的**,
> 而且换来的是"打开仓库就知道有哪两半"。

## 3. 服务端里面:先按"两种用法"分,再按"对谁做事"分

```
server/python/webmuxd/
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
└── web/            client/ 的构建产物,sessiond 拿它当静态文件
```

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

今天三种画面的代码是这么分布的:JPG 在 `cast.py` 里(和编排混在一起)、
VNC 在 `xpra.py` + `relay.py`、DOM 在 `dom.py`。**同一类东西三种摆法。**

拆成 `source/jpg.py` · `source/vnc.py` · `source/dom.py`,编排留在 `screen.py`。
好处很具体:**"加第四条腿要动哪些文件"变成一个能一眼回答的问题**
—— 加一个 `source/*.py`,在 `modes.py` 那张表里加一行。

## 4. 客户端里面:按通道分

```
client/
├── src/
│   ├── channel/         一条通道一个文件 —— 和服务端的 /channel/* 一一对应
│   │   ├── cdp.js       帧(28 字节头)+ 输入上行 + 光标 + tab
│   │   ├── xpra.js      8 字节头 + rencodeplus + 按区域绘制
│   │   └── rrweb.js     事件流喂给 Replayer,**只下行**
│   ├── screen.js        三种画面各自往哪画;切换
│   ├── input.js         DOM 事件 → 上行消息(25ms 聚批在这儿)
│   └── viewer.html      内置那个页面 —— **不是产品界面,是验链路的**
└── dist/                构建产物 → 拷进 server/python/webmuxd/web/
```

**一条通道一个文件,和服务端路由一一对应。** 通道模型的三个问题
([e §6.6](e-client.md#66-这个模型是用来想清楚的不是插件框架))落到目录上,
就是"加一条通道 = 加一个 `channel/*.js`"。

**`rrweb.js` 里不许有 `send`。** 那条通道结构上没有上行 —— 服务端 handler
里根本没有接收端。客户端这一侧也用同样的方式守:文件里没有发送函数,
不是"发之前判断一下"。

## 5. 依赖方向:这才是不再腐烂的那条

```
cli/ ──┐
       ├──▶ sdk/ ──HTTP──▶ sessiond/ ──▶ screen/  input/  browser_ui/
       │                                    └──────┴──────┴──▶ browser/  launch/  record/
client/ ──协议──▶ (sessiond 的 /channel/* 和 /api/*)
```

四条硬规矩:

1. **`sdk/` 不 import `sessiond/`** —— 否则连不了远程的那一个(§3.1)
2. **`screen/` 不 import `input/`** —— 那是接缝,不是分层(§3.2)
3. **`browser/` / `launch/` / `record/` 不 import 上面任何一层** —— 它们是被用的,不是用人的
4. **`client/` 和服务端不共享一行代码** —— 只有协议

**这四条要有测试守。** 目录改名是一次性的,依赖方向不守住就会慢慢长回来 ——
今天的 `core/` 就是这么来的。

## 6. 每个包必须能用一句话说清自己

`core/__init__.py` 和 `serve/__init__.py` 今天是空的。改完之后:

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
| `view/static/` | 顶层 `client/src/` | 它是这个项目里唯一的 JS |
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
5. `pyproject.toml` 搬到 `server/python/`,**验 wheel 里的东西一样不少**
   —— 这项目栽过一次(`.js` 没进包)
6. 干净 venv 装一遍再发

**包名不变。** 外面 `import webmuxd` 不受影响,`pip install webmuxd` 不受影响,
CLI 名字不变,HTTP 路径不变。**这一次只动代码摆在哪。**

## 9. 这次不做的

- ❌ **不改行为。** 每一步都该是"测试照样绿",不绿就是搬坏了
- ❌ **不重写。** 搬完之后文件内容和现在逐字一样(除了 import 和那句 docstring)
- ❌ **不做 JS 版服务端。** 只是把位置留出来,`server/node/` 今天不存在
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
