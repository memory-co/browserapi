# frame

**一个 session 一份画面**,所有观看者看同一个 tab
([f §6](../works/f-tabs.md#6-一个-session-一份画面))。
它**跟着**前台那个 [tab](tab.md) 走,但不属于任何一个 tab。

这一组是**唯一一处"同一个形状写了两遍"**的地方:

```
webmuxd/models.py                          ← Python 这份
webmuxjs/client/src/protocol/messages.ts   ← TS 那份
webmuxjs/server/protocol/frames.md §4      ← 契约
```

两遍不一致的后果**不是报错,是静默**:TS 那边读到 `undefined`,
画面就那么停着,而两边各自的测试都是绿的。所以下面那一列 TS 比别处都重要。

## 1. 画面下行 —— 二进制

`WS /s/{sid}/channel/cdp` 上,**28 字节定长头 + 图片裸字节**,不是 JSON。
(CDP 给的是 base64,原样塞进 JSON 转发要多花 33% 体积和两次编解码。)

```
0–3    castSessionId   每次 startScreencast 递增 —— 用来丢弃切 tab 前的残帧
4–7    frameId         单调递增
8–23   targetId        32 个 hex 字符切成 4 个 uint32 LE
24–27  保留
```

`FrameHeader` 三个字段一一对应。它由
[`two_implementations/`](../../../tests/two_implementations/) 拿 fixture
**逐字节对拍** —— 这项目在字节序上栽过一次,靠人肉发现的。

`castSessionId` 那一条是"残帧必须丢弃"的落点:`stopScreencast` 之后管道里
可能还有旧 tab 的帧,**客户端对不上就丢弃**,不能让上一个 tab 的画面闪一下。

## 2. 画面下行 —— JSON,六条

| 消息 | Python 发的键 | TS interface | 对得上吗 |
| --- | --- | --- | --- |
| `Cast` | `type` `tab` `w` `h` `format` `quality` `dsf` | `Cast { type tab? w h format? quality? }` | **`dsf` 没声明**(§5) |
| `Meta` | `type` `frame_w` `frame_h` `css_w` `css_h` | **没有** | **整条不认**(§4) |
| `QualityChanged` | `type` `quality` `every_nth` | `QualityMsg` | ✔(类名不同) |
| `ModeInfo` | `mode` `label` `available` `why` `was` | `ModeMsg` | ✔ —— 但 `type` 由 `as_message()` 加(§6) |
| `ModeError` | `type` `message` `hint` | `ModeError` | ✔ |
| `CursorChanged` | `type` `cursor` | `Cursor` | ✔(类名不同) |
| — | **没有 DTO**,`serve.py:746` 手写 | `Pong { type t }` | **反过来缺**(§7) |

`Hello` 也走这条,但它是 session 级的 —— 在
[session §4](session.md#4-画面下行hello)。

**`to_json` 全有,`from_json` 一个都没有** —— 这是对的:
下行是单向的,服务端写、TS 读,Python 永远不需要读回来。
给 `Cast` 加一个 `from_json` 是纯粹的死代码。

几条各自要说的事:

- `Cast` —— 开始/重开一轮:尺寸变了、切了 tab、重新 `startScreencast`
- `QualityChanged` —— **先降画质再抽帧**([c1](../works/c1-quality.md))
- `ModeError` —— **切不动要说清为什么、以及怎么才能有**,不静默留在原来那种
- `CursorChanged` —— 值**已经过白名单**:页面能把 `cursor` 设成任意字符串,
  原样透传等于让被隔离的页面指使客户端去拉任意 URL

## 3. `Hello` 那个 `protocol = 28` 没人读

Python 侧发它,TS 侧没声明也没读,Python 自己也没有第二处引用。

> **一个没人核对的版本号,比没有版本号更坏** —— 它让人以为有兼容性检查。

两条路选一条:观看端连上时核对、对不上就明说;或者删掉它。

## 4. `Meta` —— 服务端在发,观看页不认

`screen.py:342` 会发:

```python
await self._send_all(models.Meta(size[0], size[1], …))
```

而 `session-view.ts` 那个 switch 里只有
`pong` / `hello` / `cast` / `quality` / `mode` / `mode_error` / `cursor`
—— **没有 `case "meta"`**;`messages.ts` 里没有这个 interface,
`Downstream` 联合类型里也没有它。**每次静默丢掉。**

而它要说的正是"帧的真实尺寸和 CSS 尺寸不是一回事":

> `dsf=2` 时 CDP 报 1024×768 而图是 2048×1536 —— 观看端算"有效缩放"
> 只信解码出来的那个,这条只是把两边都说出来。

客户端确实只信解码出来那个(所以功能没坏),但那意味着**这条今天是纯浪费**。
要么让 TS 认它、省掉客户端那段自己算的逻辑,要么删掉它 ——
**不能停在"发了但没人要"**。

## 5. `Cast.dsf` TS 没声明

Python 在 `dsf is not None` 时会发。TS 那边读得到(JS 不在乎),
但**类型上不存在**,所以没人会想起来用它。

而它恰恰有用:`session-view.ts` 和 `screen/fit.ts` 的注释里都写着
"`dsf>1` 时帧是 2x 的,不写死会整个画面大一倍"。
它们今天是**自己从解码出来那张图算的**,而不是读这个字段。

## 6. `ModeInfo` 有两种出门形状

```python
to_json()     → {mode, label, available, why, was}       给 GET/POST /api/view/mode
as_message()  → {"type": "mode", **to_json()}            给 WS
```

**是有意的**:HTTP 那条本来就有 URL 说明它是什么;WS 那条是一条流,
必须自带类型。

但这件事今天只有读代码才知道 —— 而**"同一个 DTO 在两条介质上形状不同"
是最容易被抄错的一类**,所以它必须写在这儿。

`label` 是 `@property` 算出来的,不是字段,所以只出现在 JSON 那一侧。
`available` 里每一项是一个 `ViewMode`:

| 字段 | JSON |
| --- | --- |
| `name` `label` `blurb` `when` | 同名 |
| `headed` | **`needs_headed`** ⚠ 字段名和键名不一样,没写在别处 |
| `impl` | — **不出门**:`screencast` / `xpra` / `rrweb` 是实现名,[不出现在使用者面前](../works/c-view.md#91-使用者看到的是三个词) |

## 7. `pong` 反过来缺

TS 有 `Pong { type: "pong"; t: number }`,Python 侧是手写的:

```python
await v.send({"type": "pong", "t": m.get("t")})
```

按[规矩 1](README.md#4-三条规矩),它该有一个 DTO。今天没有,
所以它是**唯一一条不在这张表里、却真的在线上跑**的下行消息。

它本身很简单(原样把时间戳送回去,**两边的钟不用对齐,减的是同一个钟上的
两个读数**),但简单不是例外的理由 —— 例外一开就会有第二个。

## 8. 画面上行 —— 白名单,九种

同一条 WS,反方向。**它是安全边界**:

> 观看者能表达的全部意图就这些,和坐在真实浏览器前的人**完全等价,不多不少**
> ([b](../works/b-input.md))。

| 上行 | 干什么 |
| --- | --- |
| `ack` | 收到一帧。**同时是 RTT 探针**,而 RTT 是自适应降质的唯一输入 |
| `mouse` `wheel` `key` `text` | 输入 —— 翻译成 `Input.*` 四个命令 |
| `resize` | 改视口 |
| `tab` | 切 tab([tab §3](tab.md#3-画面上行typetabidt_3)) |
| `mode` | 换一种画面 —— **只换画面来源,不碰别的** |
| `ping` | 量延迟 |

**上行和下行不对称,而且是有意的**:下行是"我们会告诉观看者什么",
上行是"观看者**能表达**什么"。放一起会让人以为它们对称。

上行那张表也由 fixture 对拍(`upstream.json`)。

`mouse` 那条带 `modifiers` 和 `button`,不是凑数的 ——
**普通左键是前台开、Ctrl+左键和中键是后台开**,那个判断归 Chromium,
而它要靠这两个字段才判得出来([f §3](../works/f-tabs.md))。

## 9. 不出门:`Quality`

一档画质:`quality` / `every_nth`。出门的是 `QualityChanged`,不是它。

## 10. ↔ 别处

| | |
| --- | --- |
| 线上格式逐字段 | [e1](../works/e1-wire-format.md) |
| 三条腿 | [c](../works/c-view.md) |
| 降质 | [c1](../works/c1-quality.md) |
| 输入收口在哪 | [b](../works/b-input.md) |
| 两份实现对拍 | [`tests/two_implementations/`](../../../tests/two_implementations/) |
