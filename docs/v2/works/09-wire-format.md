# 09 · 线上格式:一帧到底长什么样

**一句话**:一条 WebSocket,下行是「28 字节定长头 + 图片裸字节」的二进制帧,
外加几种文本控制消息;上行是 JSON。
**ack 独立发、立即发、带帧号** —— 这一条和 BrowserBox 不一样,理由在 §6.3。

> **范围:这一篇逐字节讲的是 screencast 那条。** xpra 那条是另一套线格式
> (8 字节头、`packet index` 把大块二进制拆出 rencode),
> 和这里的 28 字节头逐项对照写在 [12 §2](12-xpra-client.md#2-线上长什么样8-字节头)。

这一篇把三家的帧**逐字节**摆出来:ttyd(终端那一族的参照物)、
demo 和 BrowserBox(我们抄的那两家)、以及我们自己。
最后指出一个空缺:**xterm.js 在我们这儿对应的东西还不存在**(§7)。

## 0. 先分清两层,不然整篇都会串

「用 WebSocket 吗」和「用 JSON 吗」听起来像二选一,其实是**两层**:

| | 管什么 | ttyd | demo | BrowserBox | webmuxd |
| --- | --- | --- | --- | --- | --- |
| **传输** | 消息怎么送过去 | WebSocket | WebSocket | WebSocket **+ WebRTC** | WebSocket |
| **载荷** | 消息里装什么字节 | 二进制,1 字节头 | 二进制 28 字节头 / 文本 JSON | 同 demo | 同 demo |

四家的传输层都是 WebSocket。**区别全在"一帧里怎么摆字节"。**

另外注意:CDP 协议本身也跑在 WebSocket 上,所以链路里至少有两条 WS ——
一条连 Chromium,一条连观看者。这两条经常被混成一条来讨论。

## 1. 一帧长什么样,怎么发出去

### 1.1 ttyd:**一个字节**

ttyd 的每条 WebSocket 消息就是「1 字节 opcode + 载荷」:

```
┌────────┬───────────────────────────────────────────┐
│ 1 字节 │  载荷(长度由 WebSocket 帧自己界定)        │
│ opcode │                                           │
└────────┴───────────────────────────────────────────┘
```

opcode 的值是 `src/server.h` 里的 `#define`,**是可打印字符不是 0x00**:

| 方向 | 值 | 名字 | 后面跟着什么 |
| --- | --- | --- | --- |
| 服务端 → 客户端 | `'0'` | `OUTPUT` | **pty 的裸字节**(里面混着 ANSI 转义序列) |
| | `'1'` | `SET_WINDOW_TITLE` | 标题字符串 |
| | `'2'` | `SET_PREFERENCES` | 一坨 JSON |
| 客户端 → 服务端 | `'0'` | `INPUT` | 要写进 pty 的裸字节 |
| | `'1'` | `RESIZE_TERMINAL` | `{"columns":80,"rows":24}` |
| | `'2'` / `'3'` | `PAUSE` / `RESUME` | **什么都没有** |
| | `'{'` | `JSON_DATA` | 整条消息就是 JSON(认证 token、初始尺寸) |

`protocol.c` 里取 opcode 就一行:

```c
const char command = pss->buffer[0];
```

最后那个 `'{'` 值得单独说:**它既是 opcode 又是 JSON 的第一个字符**。
所以"整条消息是 JSON"这件事是自证的 —— 不用为它另分配一个 opcode,
也不用在 JSON 外面再包一层。这是个很省的设计。

### 1.2 我们这一族:**28 个字节**

demo、BrowserBox、webmuxd 三家的下行帧头**布局完全一致**,7 个 uint32
小端,共 28 字节:

| 偏移 | 长度 | 字段 | 值从哪来 |
| --- | --- | --- | --- |
| 0 | 4 | `castSessionId` | 每次 `Page.startScreencast` 递增 |
| 4 | 4 | `frameId` | 单调递增,一帧一个 |
| 8 | 4 | `targetId[0:8]` | CDP `targetId` 的 32 个 hex 字符,**切成 4 段** |
| 12 | 4 | `targetId[8:16]` | |
| 16 | 4 | `targetId[16:24]` | |
| 20 | 4 | `targetId[24:32]` | |
| 24 | 4 | 保留 | 恒 0 |
| 28 | … | **图片裸字节** | JPEG / PNG / WebP,不做 base64 |

demo 的 `buildHeader` 就是照着这张表写的:

```js
const header = Buffer.alloc(HEADER_BYTE_LEN);       // 28,alloc 会清零
header.writeUInt32LE(castSessionId >>> 0, 0);
header.writeUInt32LE(fid >>> 0, 4);
header.writeUInt32LE(parseInt(targetId.slice(0, 8), 16) >>> 0, 8);
header.writeUInt32LE(parseInt(targetId.slice(8, 16), 16) >>> 0, 12);
header.writeUInt32LE(parseInt(targetId.slice(16, 24), 16) >>> 0, 16);
header.writeUInt32LE(parseInt(targetId.slice(24, 32), 16) >>> 0, 20);
```

注意它**没有显式写偏移 24 那 4 个字节** —— `Buffer.alloc` 已经清零了。
我们这边是 `struct.Struct("<7I")` 一次打包,第 7 个参数传 0,效果一样。

### 1.3 一帧真的长这样

从我们自己的实现里生成的,`castSessionId=3`、`frameId=41`、
`targetId=7bfd57343e2275ba552b717881c42c22`,载荷是一段 JPEG 开头:

```
0000  03 00 00 00 29 00 00 00   ....)...     castSessionId=3  frameId=41(0x29)
0008  34 57 fd 7b ba 75 22 3e   4W.{.u">     ← targetId,注意字节序
0010  78 71 2b 55 22 2c c4 81   xq+U",..
0018  00 00 00 00 ff d8 ff e0   ........     保留 4 字节 ┃ JPEG 从这儿开始
0020  00 10 4a 46 49 46 00 01   ..JFIF..     ← SOI(ff d8)+ APP0 "JFIF"
0028  01 01 00 60 00 60 00 00   ...`.`..
```

**第 28 个字节(偏移 `0x1c`)一定是 `ff`,第 29 个一定是 `d8`** —— JPEG 的 SOI。
写客户端时这是个免费的自检:对不上就说明头长度算错了。

### 1.4 一个一眼看不出来的坑:targetId 不是按字节序存的

对照上面那份 hexdump:

```
targetId 原文   7bfd5734 3e2275ba 552b7178 81c42c22
头里的字节      34 57 fd 7b  ba 75 22 3e  78 71 2b 55  22 2c c4 81
                ↑ 每 4 字节整个反过来
```

因为每 8 个 hex 字符被当成一个 **uint32 写成小端**,不是把 16 个字节原样搬进去。
**照着 hexdump 猜格式的人一定会写错**,而且错得很隐蔽 —— 帧照样能显示,
只是 targetId 对不上,于是切 tab 时该丢的残帧丢不掉。

解的时候要反着来,读 4 个 uint32 再拼回 hex:

```js
let s = "";
for (let i = 0; i < 4; i++)
  s += dv.getUint32(8 + i * 4, true).toString(16).padStart(8, "0");
```

那个 `padStart(8, "0")` 不能省 —— `targetId` 里出现前导零的段是常事
(比如 `00a3f1b2`),不补齐就会短一位,整条对不上。

### 1.5 一帧就是一整张图,不切片

CDP 的 `Page.screencastFrame` 每次给的是**一整张编码好的图**。我们 base64 解码之后
原样转发,所以:

- **一条 WS 二进制消息 = 28 字节头 + 一张完整的 JPEG**
- 没有分片,没有增量帧,没有 P 帧 / B 帧那种东西
- 前一帧和后一帧之间**没有任何关系** —— 丢掉任意一帧,后面的照样能显示

**最后这条是整个设计的地基。** 正因为帧之间无关,才敢「留最新丢最旧」、
才敢在切 tab 时直接丢残帧、才敢在没额度时把中间几帧整批扔掉。
一旦引入帧间压缩这些全都不成立 —— 丢一个关键帧后面全花。
这是 [02 §6](02-frame-protocol.md#6-以后可以再优化的) 把 H.264 排在最后的**隐藏成本**:
它换来的不只是编码复杂度,还有整套丢弃策略要重写。

**要不要自己切片?不要。** 因为 WebSocket 是**消息导向**的,不是字节流:

```
一次 ws.send(bytes)  →  对面 onmessage 收到的就是完整的一条
```

RFC 6455 里的分片由库和浏览器处理,应用层看不见。这是它和裸 TCP 的关键差别 ——
**裸 TCP 上必须自己加长度前缀来划边界,WebSocket 上不用**。

所以我们的头里**没有长度字段**,也不需要:载荷长度 = 消息总长 − 28。

### 1.6 那一条消息能有多大

两端的上限都要**显式放开**,否则大帧会被库砍掉或者直接断连:

| 在哪 | 设置 | 为什么 |
| --- | --- | --- |
| CDP 那条(`core/cdp.py`) | `max_size=None` | 帧是 base64 之后再包一层 JSON,dsf=2 的 PNG 能到几 MB |
| 观看者那条(`serve/app.py`) | `max_msg_size=0` | 同上;这条是我们自己发,自己知道多大 |

demo 那边同理:`new WebSocket(wsUrl, { maxPayload: 256 * 1024 * 1024 })`。

实测的单帧大小,供估算:

| 场景 | 一帧 |
| --- | --- |
| 1024×768 JPEG q80,example.com(本轮实测) | **16 KB** |
| 1280×800 JPEG q80(demo 实测) | 55 KB |
| 同上,dsf=2 | 154 KB |
| 1280×800 PNG q100,扁平 UI 页 | 96 KB |

都远在任何合理上限之下 —— **上限存在的意义是防意外,不是常态**。

### 1.7 ack:额度制,不是一问一答

**不是"一次 ack 换一张图"。** 是一个窗口为 2 的滑动窗口:

```
初始额度 2
发一帧   → 额度 −1
收 ack   → 额度 +1(封顶 2)
额度为 0 → 新帧进缓冲(长度 3),满了丢最旧的
收 ack 时缓冲里有东西 → 只取最新那帧发出去,其余全丢
```

`view/viewer.py` 就是这几行:

```python
if self.credit > 0:
    await self._write(frame)          # 有额度,直接发
    return
if len(self._buf) == BUFFER:
    self.frames_dropped += 1          # 丢最旧的,deque(maxlen) 自动做
self._buf.append(frame)
```

**为什么是 2,不是 1?**

额度 1 就是严格乒乓 —— 每帧都要等一个完整往返才能发下一帧,吞吐被钉死在
`1 / RTT`。本机几毫秒无所谓,但 50ms 的链路上那就是 **20 fps 的天花板**,
而且画质调再高也没用。额度 2 允许"上一帧还在路上,下一帧已经发出",
吞吐翻倍,代价最多是一帧的延迟。再往上加收益递减,却让客户端手上的过期帧变多。

**为什么缓冲是 3,不是 0?**

缓冲 0 意味着没额度时直接丢掉**当前**这帧 —— 而它恰恰是最新的那张,最该留。
留 3 个再"取最新、丢其余",等于给了一个小的重排窗口,不至于因为额度刚好
用完的一个瞬间就把最新画面扔了。

**额度制顺带管住了内存。** 没有它,一个慢客户端会让发送队列无限长 ——
每帧 16 KB、10 fps,一分钟就是 10 MB 堆在进程里。有额度之后
**每个客户端最多占住 2 + 3 = 5 帧**,上限是死的。

**两个 ack 环别混。** 上面说的全是**环 B**(客户端 → 我们)。
发给 Chromium 的 `Page.screencastFrameAck` 是**环 A**,收到帧就无条件立刻回,
和客户端回不回毫无关系([02 §2](02-frame-protocol.md#2-ack-背压两个独立的环))。
**所以一个卡死的观看者不会让 Chromium 停止产帧**,只会让它自己掉帧 ——
这也是 `pixels_on_a_wire` 那一项("不回 ack 的客户端被卡住而正常的那个不受影响")
在测的东西。

## 2. 为什么 ttyd 一个字节够,我们要二十八个

不是我们啰嗦,是**载荷的性质不同**。

**ttyd 的载荷是自描述的。** pty 吐出来的字节流里,控制信息是**带内**的 ——
ANSI 转义序列:

```
"hello"                          普通字符,照打
"\x1b[31m"                       后面的字变红
"\x1b[2J"                        清屏
"\x1b[10;5H"                     光标挪到第 10 行第 5 列
```

"这段字节属于哪个窗口、是第几屏、要不要丢弃" —— **这些问题在终端里不存在**。
一个连接就是一个 pty,字节流是连续的、有序的、无状态边界的。
所以外层只需要区分"这是 pty 数据还是别的",一个字节绰绰有余。

**我们的载荷是不透明的。** 一段 JPEG 字节自己说不出任何事:

| 我们必须知道 | 为什么 | 靠什么 |
| --- | --- | --- |
| 这帧属于哪个 tab | 切 tab 的瞬间管道里还有旧 tab 的帧,不丢会闪一下 | `targetId` |
| 属于哪一轮 screencast | `stopScreencast` 之后的残帧要丢 | `castSessionId` |
| 是第几帧 | ack 要按号回,才能算准 RTT(§6.3) | `frameId` |

**JPEG 里没有地方放这些**,而且也不该放 —— 那是传输层的账,不是图像的。
所以只能加一个带外的定长头。

一句话:**终端的控制信息在流里,画面的控制信息只能在流外。**
这也解释了为什么终端有 VT100 这种跨了几十年的标准,而画面这边每家都在自造格式。

## 3. demo 的上行和控制消息

**下行两种**:

```
binary   28 字节头 + JPEG 裸字节            ← §1.2
text     {"type":"hello"|"meta"|"cursor"|"stats", …}
```

`hello` 连上时发一次(尺寸、dsf、格式、画质、当前 URL、当前光标),
`meta` 是这些值变了时重发,`cursor` 是光标形状,`stats` 是每秒一次的 kbps / RTT。

客户端分流就一行,**靠类型判,不靠 opcode**:

```js
ws.onmessage = (e) => {
  if (typeof e.data === 'string') return handleJson(JSON.parse(e.data));
  handleFrame(e.data);
};
```

WebSocket 本身就区分 text 和 binary 帧,所以**不需要 ttyd 那个 opcode 字节** ——
ttyd 全都用 binary 帧发,才必须自己标类型。

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

## 4. BrowserBox 的上行

它的形状是被两件事逼出来的:**双通道**,和**上行要能收响应**。

下行的帧头和 demo 逐字段一致,但可能从 WS 也可能从 WebRTC 到,
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

## 5. 四家对照

| | ttyd | demo | BrowserBox | webmuxd |
| --- | --- | --- | --- | --- |
| 下行帧头 | **1 字节 opcode** | 28 字节 | 28 字节 | 28 字节 |
| 载荷 | pty 裸字节(带内控制) | 图片裸字节 | 图片裸字节 | 图片裸字节 |
| 怎么分类型 | opcode 字节 | **WS 的 text/binary** | 同左 | 同左 |
| 上行消息种类 | 5 种(opcode) | 4 种(JSON `type`) | **1 种**,靠字段区分 | 5 种 |
| 逐帧 ack | **没有**。流控是 `PAUSE`/`RESUME` 两个 opcode + TCP 反压 | 独立消息,带 frameId | **搭在输入上** | 独立消息,**目前不带号**(§8) |
| 没输入时的 ack | — | 照常发 | 造空事件 + 1.618 退避 | 照常发 |
| 丢帧自愈 | — | 无 | **3 秒无条件补** | **无**(§8) |
| 上行要不要响应 | 不要 | 不要 | **要**,`messageId` + `waiting` 表 | 不要 |
| 通道 | 一条 WS | 一条 WS | WS + WebRTC 赛跑 | 一条 WS |

**ttyd 那一列的空格不是它简陋。** 它也有流控,只是形状完全不同:
`PAUSE` / `RESUME` 是**开关**,客户端喊停,服务端就不再从 pty 读;
加上 TCP 自己的反压,够了。

为什么够?因为终端里**没有"过期的字符"这回事** —— 每个字节都要送到,
少一个字画面就错了,所以只能"慢下来",不能"丢"。
画面正相反:**过期的帧毫无价值,丢掉才对**。

所以我们要的不是开关,是**额度 + 缓冲 + 丢弃策略**(留最新丢最旧,
[02 §2](02-frame-protocol.md#2-ack-背压两个独立的环))。
一个"能丢"的流控,和一个"只能停"的流控,不是同一个东西。

## 6. 我们怎么定

### 6.1 下行:二进制帧 + 文本控制,靠 WS 的类型分流

帧走 binary,控制消息走 text。**不学 ttyd 加 opcode 字节** ——
WebSocket 已经分了 text/binary,再加一个字节是重复。

**不把控制消息塞进二进制头**:`hello` / `cast` / `meta` / `quality` / `cursor`
一秒最多几条,省那点字节换来的是自己发明一套 TLV 和配套解析器。

**也不把帧塞进 JSON**:base64 膨胀 33%,每帧多两次编解码
([02 §1](02-frame-protocol.md#1-为什么是二进制头不是-json))。

### 6.2 帧头 28 字节,逐字段照抄

布局见 §1.2,和 demo / BrowserBox 一致。照抄的好处很实在:
**拿它们的客户端代码对照调试时不用换算**,那两家的解析函数可以直接跑我们的帧。

保留的 4 字节先空着。真要用的时候,§9 里那个"带发送时刻"是第一顺位。

### 6.3 ack 独立发、立即发、带帧号

**这是本篇唯一需要论证的决定**,因为它和 BrowserBox 分歧。

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
  且不会自愈 —— 这是当前实现的一个 bug,见 §8

### 6.4 三秒补一个 ack

照抄 BrowserBox 那条,**理由完全一样**:推模型下 ack 断了就是永久卡死。

```
每收到一帧 → 重置 3 秒定时器
3 秒没帧   → 无条件补一个 ack(带手上最新的 frameId)
```

它和「静止页面不产帧」不冲突:静止时服务端本来就没帧要发,补 ack 只是把额度
还回去,不会让 Chromium 多产一帧。**它花的是每 3 秒几十字节。**

### 6.5 输入批量,ack 不批量

两件事分开:

| | 节奏 |
| --- | --- |
| `mousemove` / `wheel` | 攒 25ms 一批,**同批里只留最后一个 mousemove** |
| `mousedown` / `mouseup` / `key` / `text` | **立即发**,不进批 |
| `ack` | **立即发**,永远不进批(§6.3) |

按下抬起不能等 —— 25ms 的延迟在点击上是感觉得到的,而且 `mousedown` 和
`mouseup` 之间插进 25ms 会让某些页面把它判成长按。

### 6.6 上行不做 RPC

BrowserBox 的 `messageId` + `waiting` 表是为了从上行拿数据回来。**我们不需要**:
输入是 fire-and-forget,而所有要响应的事情(开 tab、导航、观测、回填对话框)
**走 REST**,那儿本来就有请求-响应、有状态码、有错误信封。

**在 WS 上再造一套 RPC,等于把 `/api/` 那一整套重新发明一遍。**
线画在:**WS 只走"高频、单向、不要回执"的东西** —— 帧、输入、ack、光标。

## 7. 那个缺掉的客户端

### 7.1 xterm.js 在我们这儿不是渲染器

ttyd 的前端是 xterm.js,因为终端传的是**语义**(§2 那些转义序列),
客户端必须有个东西把语义重新渲染成像素 —— 解析 VT 状态机、维护屏幕缓冲、
画字形、处理选区。xterm.js 那几万行干的就是这个。

我们传的是**已经渲染好的像素**,浏览器天生会解 JPEG。所以我们不需要渲染器,
`<img>` 就是。

**但 xterm.js 那个位置不是空的,它换了内容**:

| | ttyd | webmuxd |
| --- | --- | --- |
| 客户端要做什么 | 解 VT 序列 → 画字形 | 解 28 字节头、丢残帧、回 ack、心跳、输入归一化、IME、光标 |
| 有没有现成的 | **`npm i xterm`** | **没有** |

而且我们的格式是自造的,没有第三方实现可用 —— 这一点和终端不同,
终端有 VT100 这个几十年的标准,xterm.js 才可能存在(§2 末尾那句)。

### 7.2 所以要发一个协议客户端

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
包括 §6.5 那套批量规则。调用方不碰这些。

**不包的**:tab 条、地址栏、原生 UI 的卡片、任何 REST 调用。
它不认识 `/api/tabs`,一个字节都不发到那儿去。

### 7.3 0.7.0:那个位置**已经有一个客户端了**,但不是这一个

xpra 那条画面路要自己解协议,于是写了
[`static/xpra.js`](../../../webmuxd/view/static/xpra.js)(协议 + 解码 + 上画)和
[`static/rencode.js`](../../../webmuxd/view/static/rencode.js)(包编码)——
去掉注释三百来行,**正是这一节说的那个"没有现成的"的东西**
([12 §5](12-xpra-client.md#5-结论自写约-500-行--实际三百出头))。

所以现在的状态是**一半**:

| | 协议客户端在哪 | 打包发出去了吗 |
| --- | --- | --- |
| xpra 那条 | 独立模块 `xpra.js` + `rencode.js` | 没有,跟着 sessiond 一起发 |
| screencast 那条 | **还埋在 `index.html` 里** | 没有 |

`xpra.js` 的形状恰好验证了下面那三条自律里的第 ②、③ 条(零依赖、单文件 ESM、
版本跟着格式走),但第 ① 条还没做到 —— 内置页面用的是它,可它没有独立发出去,
外面的人拿不到。**`@webmuxd/client` 仍然欠着**,而且现在欠的是两个而不是一个。

### 7.4 三条自律

**① 内置页面必须是它的第一个用户。** 不是"顺便也用一下" ——
如果内置页面走的是另一条实现,库会腐烂,而且腐烂的时候没人发现。

**② 零依赖、单文件 ESM。** 要能被 `<script type=module>` 直接引,也要能进 npm。
严格 CSP 的地方(比如嵌进别人的页面)也得能跑。

**③ 版本跟着格式走,不跟着 webmuxd 走。** 帧头或上行消息集合变了才升版本;
webmuxd 加一个 REST 端点和它无关。

## 8. 当前实现欠了什么

写这篇的时候对着代码核过,`view/viewer.py` 和 `static/index.html` 有三处
和上面定的不一致 —— **都是我实现时偷懒,不是设计变了**:

| 欠的 | 后果 | 状态 |
| --- | --- | --- |
| ack 不带 `frameId`,服务端弹最旧的时间戳 | 漏一个 ack 就**永久错位**,RTT 全错,自适应降质凭错数据动作 | **已修** |
| 没有 3 秒补 ack | 丢一帧就**永久卡死**,没有自愈 | **已修** |
| 输入一个事件一条消息,没批量、没丢旧 mousemove | 上行往返多,量级不大 | **还欠着**(优化,不是 bug) |
| screencast 的协议客户端还埋在 `index.html` 里 | 外面的人拿不到,只能自己重写 | **还欠着**(§7.3) |

两条 bug 已经按 §6.3 / §6.4 修掉:服务端改成 `dict[frame_id, sent_at]` 按号查表,
**额度无条件恢复、RTT 只在号对得上时才算**;客户端每收一帧重置一个 3 秒定时器,
到点补一发 `{"type":"ack","frameId":<手上最新的>}`。

心跳那条**只能拿真浏览器验** —— Python 的测试盖不到 `index.html` 里的 JS。
实测:静止页面(不产帧)静置 8 秒,**0 帧、2 个 ack**,正好落在 t=3s 和 t=6s。

第三条按 [02 §0](02-frame-protocol.md#0-这一篇的地位照抄不重新设计) 的姿态可以先放着 ——
它是优化,不是正确性问题。

## 9. 以后可能动的

和 [02 §6](02-frame-protocol.md#6-以后可以再优化的) 一样,列出来是为了标明它们是
**已知选项,不是遗漏**,每条带触发条件:

| | 能换到什么 | 什么时候动 |
| --- | --- | --- |
| **保留的 4 字节拿来放发送时刻** | 服务端不用维护 `Map<frameId, sentAt>`,RTT 变成无状态的回显 | 想简化服务端记账时。代价:头不再和 demo / BrowserBox 逐字段对齐,它们的解析器跑不了我们的帧 |
| **上行也二进制** | 省几 KB/s | **基本不会** —— 上行本来就只有几 KB/s,而 JSON 的可调试性值这个价 |
| **`ackEvery` 旋钮**(每 N 帧 ack 一次) | 上行流量减少 N 倍,RTT 精度变粗 | 上行成为瓶颈时。BrowserBox 有这个旋钮,默认 1 |
| **第二条通道(WebRTC)** | 抗队头阻塞 —— **但要配 unreliable 才有**,BrowserBox 自己那条是 reliable ordered,和 TCP 一样阻塞 | 见 [02 §6](02-frame-protocol.md#6-以后可以再优化的):真到那天直接上 H.264,而不是再送一路 JPEG |

## 10. ↔ 别处

| | |
| --- | --- |
| 帧头怎么用、ack 背压、RTT 自适应 | [02](02-frame-protocol.md) |
| 输入怎么翻译成 `Input.*` | [03](03-input.md) |
| 内置页面为什么不算"界面" | [04 §2](04-one-port.md#2-get--是内置的但它不是界面) |
| 切 tab 时残帧怎么丢 | [05 §3](05-active-tab.md#3-切-tab-是把-screencast-搬过去) |
| ttyd 的 opcode 定义 | `tsl0922/ttyd` 的 `src/server.h`,`protocol.c` 里 `pss->buffer[0]` |
