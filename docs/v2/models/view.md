# view · 下行消息,和 `messages.ts` 逐条对

**这一组是唯一一处"同一个形状写了两遍"的地方。**

```
webmuxd/models.py                          ← Python 这份
webmuxjs/client/src/protocol/messages.ts   ← TS 那份
webmuxjs/server/protocol/frames.md §4      ← 契约
```

两遍不一致的后果**不是报错,是静默**:TS 那边读到 `undefined`,画面就那么停着,
而两边各自的测试都是绿的。所以下面这张表的最后一列比别处都重要。

## 1. 逐条

| 消息 | Python 发的键 | TS interface | 对得上吗 |
| --- | --- | --- | --- |
| `Hello` | `type` `writable` `protocol` `transport` `w` `h` + `**extra` | `Hello { type writable transport w? h? }` | **`protocol` 没声明**(见 §2)、`extra` 里那些也没有 |
| `Cast` | `type` `tab` `w` `h` `format` `quality` `dsf` | `Cast { type tab? w h format? quality? }` | **`dsf` 没声明**(见 §3) |
| `Meta` | `type` `frame_w` `frame_h` `css_w` `css_h` | **没有** | **整条消息 TS 不认**(见 §4) |
| `QualityChanged` | `type` `quality` `every_nth` | `QualityMsg` | ✔(类名不同) |
| `ModeInfo` | `mode` `label` `available` `why` `was` | `ModeMsg { type mode label why? available? }` | ✔ —— 但 `type` 由 `as_message()` 加(见 §5) |
| `ModeError` | `type` `message` `hint` | `ModeError` | ✔ |
| `CursorChanged` | `type` `cursor` | `Cursor` | ✔(类名不同) |
| — | **没有 DTO**,`serve.py:746` 手写 | `Pong { type t }` | **反过来缺**(见 §6) |
| `FrameHeader` | 28 字节定长,不是 JSON | `protocol/frame.ts` | ✔,由 fixture 对拍 |

`to_json` 全有,`from_json` **一个都没有** —— 这是对的:
**下行是单向的**,服务端写、TS 读,Python 永远不需要读回来。
给 `Hello` 加一个 `from_json` 是纯粹的死代码。

## 2. `Hello.protocol = 28` 没人读

Python 侧发它,TS 侧没声明也没读,Python 自己也没有第二处引用它。

**一个没人核对的版本号,比没有版本号更坏** —— 它让人以为有兼容性检查。
两条路选一条:要么观看端连上时核对、对不上就明说;要么删掉它。

## 3. `Cast.dsf` TS 没声明

Python 在 `dsf is not None` 时会发它。TS 那边 `Cast` 里没有这个字段 ——
读得到(JS 不在乎),但**类型上不存在**,所以没人会想起来用它。

而 `dsf` 恰恰是有用的:`session-view.ts` 和 `screen/fit.ts` 的注释里都写着
"`dsf>1` 时帧是 2x 的,不写死会整个画面大一倍"。它们今天是**自己从解码出来
那张图算的**,而不是读这个字段。

## 4. `Meta` —— 服务端在发,观看页不认

`screen.py:342` 会发:

```python
await self._send_all(models.Meta(size[0], size[1], …))
```

而 `session-view.ts` 那个 switch 里只有
`pong` / `hello` / `cast` / `quality` / `mode` / `mode_error` / `cursor`
—— **没有 `case "meta"`**,`messages.ts` 里没有这个 interface,
`Downstream` 联合类型里也没有它。

它每次都被静默丢掉。

而 `Meta` 要说的正是"帧的真实尺寸和 CSS 尺寸不是一回事":

> `dsf=2` 时 CDP 报 1024×768 而图是 2048×1536 —— 观看端算"有效缩放"
> 只信解码出来的那个,这条只是把两边都说出来。

客户端确实只信解码出来那个(所以功能没坏),但那意味着**这条消息今天是纯浪费**:
要么让 TS 认它、省掉客户端那段自己算的逻辑,要么删掉它。
**不能停在"发了但没人要"。**

## 5. `ModeInfo` 有两种出门形状

```python
to_json()     → {mode, label, available, why, was}          给 /api/mode
as_message()  → {"type": "mode", **to_json()}               给 WS
```

**是有意的**:HTTP 那条本来就有 URL 说明它是什么,不需要 `type`;
WS 那条是一条流,必须自带类型。

但这件事今天只有读代码才知道 —— 它值得写在这儿,因为
**"同一个 DTO 在两条路上形状不同"是最容易被抄错的一类**。

`label` 那个键是 `@property` 算出来的(`label(self.mode)`),不是字段 ——
所以它只出现在 JSON 这一侧。**界面不该自己再写一遍这些字。**

## 6. `pong` 反过来缺

TS 有 `Pong { type: "pong"; t: number }`,Python 侧是
`serve.py:746` 手写的:

```python
await v.send({"type": "pong", "t": m.get("t")})
```

按 [README §2 第 1 条](README.md#2-三条规矩)("凡是出现在线上的形状,
必须在这儿定义一次"),它该有一个 DTO。今天没有,所以它是**唯一一条
不在这张表里、却真的在线上跑**的下行消息。

它本身很简单(原样把时间戳送回去,**两边的钟不用对齐,减的是同一个钟上的
两个读数**),但简单不是例外的理由 —— 例外一开就会有第二个。

## 7. `ViewMode` —— 唯一一处字段名和键名不一样

| 字段 | JSON |
| --- | --- |
| `name` `label` `blurb` `when` | 同名 |
| `headed` | **`needs_headed`** |
| `impl` | — **不出门**:`screencast` / `xpra` / `rrweb` 是实现名,[不出现在使用者面前](../works/c-view.md#91-使用者看到的是三个词) |

改名是对的(`needs_headed` 比 `headed` 说得清),但**它没写在任何地方** ——
照着 Python 字段名去读 JSON 的人会踩空。

## 8. ↔ 别处

| | |
| --- | --- |
| 线上格式逐字段 | [e1](../works/e1-wire-format.md) |
| 观看端怎么用 | [e](../works/e-client.md) |
| 降质那套 | [c1](../works/c1-quality.md) |
| 两份实现对拍 | [`tests/two_implementations/`](../../../tests/two_implementations/) |
