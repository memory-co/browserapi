# 09 · 线上格式,和那个缺掉的客户端

**一句话**:一条 WebSocket,下行二进制帧 + 文本控制消息,上行 JSON。
**ack 独立发、立即发、带帧号** —— 这一条和 BrowserBox 不一样,理由在 §4.3。
另外这篇要指出一个空缺:**xterm.js 在我们这儿对应的东西还不存在**(§5)。

## 0. 先分清两层,不然整篇都会串

「用 WebSocket 吗」和「用 JSON 吗」听起来像二选一,其实是**两层**:

| | 管什么 | demo | BrowserBox | webmuxd |
| --- | --- | --- | --- | --- |
| **传输** | 消息怎么送过去 | WebSocket | WebSocket **+ WebRTC 数据通道** | WebSocket |
| **载荷** | 消息里装什么字节 | 下行二进制 / 上行 JSON | 同左 | 同左 |

三家的传输层都是 WebSocket,**区别全在上行怎么组织**。而且注意:CDP 协议本身
也跑在 WebSocket 上,所以链路里至少有两条 WS —— 一条连 Chromium,一条连观看者。
这两条经常被混成一条来讨论。

BrowserBox 那条 WebRTC 是**并存赛跑**,不是替代:约 26% 的帧同时走两条路比快慢
(`RACE_SAMPLE = 0.74`),客户端记分,把结论回传给服务端换 `fastest` 通道。
**赛跑的存在本身就是"不知道哪条快"的证据** —— 我们不做,理由在 [02 §6](02-frame-protocol.md#6-以后可以再优化的)。

## 1. demo 的格式

约 700 行的最小实现,格式也最小。

**下行两种**:

```
binary   28 字节头 + JPEG 裸字节
text     {"type":"hello"|"meta"|"cursor"|"stats", …}
```

`hello` 在连上时发一次(尺寸、格式、画质、当前 URL、当前光标),`meta` 是这些值
变了时重发,`cursor` 是光标形状,`stats` 是每秒一次的 kbps / RTT。

**上行四种**:

```jsonc
{"type":"ack",      "frameId": 41}
{"type":"input",    "events": [ … ]}      // 一批,不是一条
{"type":"navigate", "url": "…"}
{"type":"nav",      "action": "back"|"forward"|"reload"}
```

三处值得抄的细节:

**① 输入批量,25ms 一批,按下抬起立即发**:

```js
function push(ev, immediate) {
  queue.push(ev);
  if (immediate) return flush();                    // mousedown/up/keydown 不等
  if (!flushScheduled) { flushScheduled = true; setTimeout(flush, 25); }
}
```

**② 同一批里丢掉旧的 mousemove**:

```js
for (let i = queue.length - 1; i >= 0; i--) {
  if (queue[i].type === 'mousemove') { queue.splice(i, 1); break; }
}
```

和帧缓冲「留最新丢最旧」是同一个道理 —— **过期的鼠标位置没有价值**。

**③ ack 带 frameId**,服务端用 `Map<frameId, sentAt>` 算 RTT,对不上就跳过。

## 2. BrowserBox 的格式

它的形状是被两件事逼出来的:**双通道**,和**上行要能收响应**。

**下行**:同样的 28 字节头 + JPEG,但可能从 WS 也可能从 WebRTC 到,
所以客户端必须处理**乱序** —— 单条 WS 是保序的,两条路赛跑不是:

```js
if ( (frameId - latestFrameId) < 1 ) return;   // 比手上这张旧,丢
```

文本消息带 `messageId`,客户端有一张 `waiting` 表做请求-响应配对
(`transmitReply`)—— 也就是说,**它在 WebSocket 上做了一层 RPC**。

**上行只有一种消息**,所有事情都是它的字段:

```js
senders.so({
  messageId,                                    // 用来配对响应
  zombie: { events },                           // 一批输入,MAX_E = 255
  screenshotAck: noFrameReceived || this.screenshotReceived,   // ← ack 搭车
  fastestChannel: { websocket: true },          // 赛跑结论(偶尔)
  copeer: { signal },                           // WebRTC 信令(偶尔)
})
```

**没有独立的 ack 消息。** ack 是 `{frameId, castSessionId}`,搭在输入消息上。
这带来一个问题:**没有输入的时候谁来载 ack?** 它的答案是造一个空事件:

```js
const BUFFERED_FRAME_EVENT = {
  type: "buffered-results-collection",
  command: { isBufferedResultsCollectionOnly: true, params: {} }
};
```

发送节奏是黄金比例退避,`40ms → 65 → 105 → … → 4000ms`,收到帧就重置回 40ms。
另有一道独立的兜底:

```js
REGULAR_NO_FRAME_ACK_INTERVAL = 3001    // 3 秒没帧就无条件补一个 ack
```

**这条是防死锁的,不是优化** —— 推模型下没有"下一次请求"来重启流程,
所以某一帧丢了、客户端永远不 ack,服务端额度耗尽就是永久卡住。

## 3. 两家对照

| | demo | BrowserBox |
| --- | --- | --- |
| 上行消息种类 | 4 种 | **1 种**,靠字段区分 |
| ack | 独立消息,带 frameId | **搭在输入上**,带 `{frameId, castSessionId}` |
| 没输入时的 ack | 照常发 | 造空事件 + 1.618 退避 |
| 丢帧自愈 | 无 | **3 秒无条件补** |
| 输入批量 | 25ms,丢旧 mousemove | 发送循环 `splice(0, 255)` |
| 上行要不要响应 | 不要 | **要**,`messageId` + `waiting` 表 |
| 通道 | 一条 WS | WS + WebRTC 赛跑 |

**BrowserBox 复杂的那几处都有出处**:RPC 是因为上行要拿数据回来,乱序处理是因为
双通道,搭车是因为它本来就有一条"命令流"可以蹭。**这些前提我们一个都没有。**

## 4. 我们怎么定

### 4.1 下行:二进制帧 + 文本控制,不合并

帧走 binary,控制消息走 text。**不把控制消息也塞进二进制头** ——
`hello` / `cast` / `meta` / `quality` / `cursor` 一秒最多几条,
省那点字节换来的是自己发明一套 TLV 和配套的解析器。

反过来也不做:**不把帧塞进 JSON**。base64 膨胀 33%,每帧多两次编解码
([02 §1](02-frame-protocol.md#1-为什么是二进制头不是-json))。

### 4.2 帧头 28 字节,照抄

`castSessionId` / `frameId` / `targetId(16 字节)` / 保留 4 字节。
布局和 BrowserBox 一致,好处是拿它的客户端代码对照时不用换算。

三个字段各有各的用:切 tab 时靠 `castSessionId` 丢残帧,靠 `targetId` 确认这帧
属于哪个 tab,`frameId` 单调递增给 ack 用。

### 4.3 ack 独立发、立即发、带帧号

**这一条和 BrowserBox 分歧,是本篇唯一需要论证的决定。**

搭车看着很划算:一条通道、人在操作时 ack 免费。但它有个代价:

> **ack 是 RTT 探针,而 RTT 是自适应降质的唯一输入。**
> 一旦搭车,ack 的发出时刻就被输入的批量节奏绑住了 —— 测出来的"RTT"里
> 混着客户端的排队时间,不是网络往返。

BrowserBox 里这个污染是可量的:帧在流动时退避重置到 40ms,所以 RTT 最多虚高
40ms;而它的降质阈值是 725ms、升质 600ms —— 6% 左右,忍得了但确实在。
**我们没有理由为了省一条几十字节的消息去接受它。**

所以:

```jsonc
{"type": "ack", "frameId": 41}     // 收到帧就立刻发,不排队,不搭车
```

`frameId` 必须带。服务端按号查表算 RTT,**对不上就跳过,不污染窗口**:

- 客户端漏回一个 ack(比如那帧解码失败),按号查表只是少一个样本
- 而"弹最旧的时间戳"那种写法会**永久错位**,之后每个 RTT 都算成上一帧的,
  且不会自愈 —— 这是当前实现的一个 bug,见 §6

### 4.4 三秒补一个 ack

照抄 BrowserBox 那条,**理由完全一样**:推模型下 ack 断了就是永久卡死。

```
每收到一帧 → 重置 3 秒定时器
3 秒没帧   → 无条件补一个 ack(带手上最新的 frameId)
```

注意它和「静止页面不产帧」不冲突:静止时服务端本来就没帧要发,补 ack 只是把
额度还回去,不会让 Chromium 多产一帧。**它花的是每 3 秒几十字节。**

### 4.5 输入批量,ack 不批量

两件事分开:

| | 节奏 |
| --- | --- |
| `mousemove` / `wheel` | 攒 25ms 一批,**同批里只留最后一个 mousemove** |
| `mousedown` / `mouseup` / `key` / `text` | **立即发**,不进批 |
| `ack` | **立即发**,永远不进批(§4.3) |

按下抬起不能等 —— 25ms 的延迟在点击上是感觉得到的,而且 `mousedown` 和
`mouseup` 之间插进 25ms 会让某些页面把它判成长按。

### 4.6 上行不做 RPC

BrowserBox 的 `messageId` + `waiting` 表是为了从上行拿数据回来。**我们不需要**:
输入是 fire-and-forget,而所有要响应的事情(开 tab、导航、观测、回填对话框)
**走 REST**,那儿本来就有请求-响应、有状态码、有错误信封。

**在 WS 上再造一套 RPC,等于把 `/api/` 那一整套重新发明一遍。**
这条线画在:**WS 只走"高频、单向、不要回执"的东西** —— 帧、输入、ack、光标。

## 5. 那个缺掉的客户端

### 5.1 xterm.js 在我们这儿不是渲染器

ttyd 的前端是 xterm.js,因为终端传的是**语义**(字符 + 转义序列),客户端必须有个
东西把语义重新渲染成像素。

我们传的是**已经渲染好的像素**,浏览器天生会解 JPEG。所以我们不需要渲染器 ——
`<img>` 就是。

**但 xterm.js 那个位置不是空的,它换了内容**:

| | ttyd | webmuxd |
| --- | --- | --- |
| 客户端要做什么 | 解 VT 序列 → 画字形 | 解帧头、丢残帧、回 ack、心跳、输入归一化、IME、光标 |
| 有没有现成的 | **`npm i xterm`** | **没有** |

而且我们的协议是自造的,没有第三方实现可用 —— 这一点和终端不同,终端有 VT100
这个几十年的标准,xterm.js 才可能存在。

### 5.2 所以要发一个协议客户端

`webmuxd/view/static/index.html` 现在同时干三件事:

1. **协议客户端** —— 帧头、ack、输入、IME、光标
2. tab 条和地址栏 —— 纯 `/api/tabs` 的消费者
3. 对话框卡片和下载 toast —— 纯 `/api/pending` 的消费者

**只有第 1 件是别人没法自己写的。** 2 和 3 用的是公开 REST 接口,谁都能重画,
而且本来就该由上层按自己的产品来画([04 §2](04-one-port.md#2-get--是内置的但它不是界面))。

所以边界切在这儿:**只包第 1 件**。

```js
import { WebmuxdView } from "@webmuxd/client";

const view = new WebmuxdView("ws://host:7900/api/view", { token });
view.attach(document.querySelector("img"));   // 也可以给 canvas

view.on("cast",   ({ tab, w, h }) => …);      // 换 tab / 改尺寸
view.on("cursor", (shape) => …);              // 已过白名单,直接写 style.cursor
view.on("stats",  ({ fps, kbps, rtt, zoom }) => …);
view.on("permission", ({ writable }) => …);   // 只读连接

view.resize(1280, 800);
view.switchTab("t_3");
```

`attach()` 之后**输入就接管了** —— 鼠标、滚轮、键盘、IME、粘贴全在里面,
包括 §4.5 那套批量规则。调用方不碰这些。

**不包的**:tab 条、地址栏、原生 UI 的卡片、任何 REST 调用。
它不认识 `/api/tabs`,一个字节都不发到那儿去。

### 5.3 三条自律

**① 内置页面必须是它的第一个用户。** 不是"顺便也用一下" ——
如果内置页面走的是另一条实现,库会腐烂,而且腐烂的时候没人发现。

**② 零依赖、单文件 ESM。** 它要能被 `<script type=module>` 直接引,
也要能进 npm。artifact 那类严格 CSP 的地方也得能跑。

**③ 版本跟着协议走,不跟着 webmuxd 走。** 帧头和上行消息集合变了才升版本;
webmuxd 加一个 REST 端点和它无关。

## 6. 当前实现欠了什么

写这篇的时候对着代码核过,`view/viewer.py` 和 `static/index.html` 有三处
和上面定的不一致 —— **都是我实现时偷懒,不是设计变了**:

| 欠的 | 后果 | 严重程度 |
| --- | --- | --- |
| ack 不带 `frameId`,服务端弹最旧的时间戳 | 漏一个 ack 就**永久错位**,RTT 全错,自适应降质凭错数据动作 | **bug** |
| 没有 3 秒补 ack | 丢一帧就**永久卡死**,没有自愈 | **bug** |
| 输入一个事件一条消息,没批量、没丢旧 mousemove | 上行往返多,量级不大 | 优化 |

前两条是正确性问题,该修。第三条按 [02 §0](02-frame-protocol.md#0-这一篇的地位照抄不重新设计)
的姿态本可以先放着,但既然已经知道 demo 怎么写的,顺手对齐更省事。

## 7. 以后可能动的

和 [02 §6](02-frame-protocol.md#6-以后可以再优化的) 一样,列出来是为了标明它们是
**已知选项,不是遗漏**,每条带触发条件:

| | 能换到什么 | 什么时候动 |
| --- | --- | --- |
| **帧头里带发送时刻** | 服务端不用维护 `Map<frameId, sentAt>`,RTT 变成无状态的回显 | 想简化服务端记账时。代价:头不再和 BrowserBox 逐字段对齐 |
| **上行也二进制** | 省几 KB/s | **基本不会** —— 上行本来就只有几 KB/s,而 JSON 的可调试性值这个价 |
| **`ackEvery` 旋钮**(每 N 帧 ack 一次) | 上行流量减少 N 倍,RTT 精度变粗 | 上行成为瓶颈时。BrowserBox 有这个旋钮,默认 1 |
| **第二条通道(WebRTC)** | 抗队头阻塞 —— **但要配 unreliable 才有**,BrowserBox 自己那条是 reliable ordered,和 TCP 一样阻塞 | 见 [02 §6](02-frame-protocol.md#6-以后可以再优化的):真到那天直接上 H.264,而不是再送一路 JPEG |

## 8. ↔ 别处

| | |
| --- | --- |
| 帧头布局、ack 背压、RTT 自适应 | [02](02-frame-protocol.md) |
| 输入怎么翻译成 `Input.*` | [03](03-input.md) |
| 内置页面为什么不算"界面" | [04 §2](04-one-port.md#2-get--是内置的但它不是界面) |
| 切 tab 时残帧怎么丢 | [05 §3](05-active-tab.md#3-切-tab-是把-screencast-搬过去) |
