# wire · 跨语言的那一份

**一句话**:这一份**有第二个实现** —— 改它要两边一起改,而改错了**不报错**。

四类边界里只有这一类是这样,所以它值得一个自己的文件
([README §2](README.md#2-边界是四种东西))。

## 1. 里面有什么

下行六种消息,加一个帧头:

| | 什么时候发 | 另一头 |
| --- | --- | --- |
| `Hello` | 连上来第一条 —— **权限只在这时候说一次** | `messages.ts` 的 `Hello` |
| `Cast` | 开始/重开一轮:尺寸变了、切了 tab | `Cast` |
| `Meta` | 帧的真实尺寸和 CSS 尺寸不是一回事(`dsf=2` 时差一倍) | — |
| `QualityChanged` | 降质/抽帧 —— 先降画质再抽帧([c1](../works/c1-quality.md)) | `QualityMsg` |
| `ModeInfo` / `ModeError` | 切画面,以及**切不了的原因** | `ModeMsg` / `ModeError` |
| `CursorChanged` | 远端光标形状 | `Cursor` |
| `FrameHeader` | 28 字节定长头(不是 JSON) | `protocol/frame.ts` |

`Hello` 那条"权限只说一次"是有原因的:鼠标移动一秒几十个事件,
**逐个回 403 等于自己 DoS 自己**。

## 2. 为什么它必须和别的分开

**它是这个项目里唯一一处"同一个形状被写了两遍"的地方。**

```
webmuxd/models.py            ← Python 这份
webmuxjs/client/src/protocol/messages.ts   ← TS 那份
webmuxjs/server/protocol/frames.md  §4     ← 契约文档
```

两遍不一致的后果**不是报错,是静默**:字段名改了,TS 那边读到 `undefined`,
画面就那么停着 —— 而两边各自的测试都是绿的。这项目在这个坑里栽过,
`targetId` 的字节序当初是靠人肉发现的([j §4.2](../works/j-layout.md))。

所以 [`two_implementations/`](../../../tests/two_implementations/) 拿
fixture 对拍:**Python 编出来的和 TS 编出来的必须逐字节一样**。
那套对拍只对这一类有意义 —— `TabInfo` 没有第二个实现,对拍它是对拍自己。

> 换个说法:**别的三类改了会有人喊,这一类改了没人喊。**
> 单独一个文件,是让"要改两边"这件事在打开文件的那一刻就被看见。

## 3. 「单向」是这一份的特权

全文 18 个类有 `to_json`,只有 8 个有 `from_json`。
**这个不对称对下行消息是对的** —— 服务端写、TS 读,Python 永远不需要读回来。
给 `Hello` 加一个 `from_json` 是纯粹的死代码。

但今天**从文件里看不出哪个缺失是设计、哪个是漏**。`ActionResult` 没有
`from_json`,是因为它也单向,还是因为写的时候没想到 SDK 要读回来?
得去翻调用方才知道。

拆开之后这件事自己就说清楚了:

> **`wire.py` 里一律没有 `from_json`;别处一律成对。**

这条能直接变成一句断言([README §4](README.md#4-拆完之后那三条规矩第一次有东西守着))。

## 4. 上行不在这儿

上行那张白名单在 [`frames.py`](../../../webmuxd/frames.py),**它是安全边界**,
和这些不是一回事:

- **上行**:观看者**能表达什么** —— 白名单,不是黑名单([b](../works/b-input.md))
- **下行**:我们**会告诉观看者什么**

两者放一起会让人以为它们对称。不对称是有意的。

## 5. `FrameHeader` 并回 `frames.py`

它今天在 models,而它的编解码(`build_header` / `parse_header` / `pack_target`)
在 `frames.py` —— **形状和编解码分两个文件,是把一件事切成了两半**。
而且 `frames.py` 为此要 `from webmuxd.models import FrameHeader`,
搬完就不用了,顺带少一条依赖。

搬完之后 `wire.py` 里只剩 JSON 那六种,名字和内容也就对上了:
**`wire.py` 是"我们会说什么",`frames.py` 是"怎么把它变成字节"。**

## 6. ↔ 别处

| | |
| --- | --- |
| 线上格式逐字段 | [e1](../works/e1-wire-format.md) |
| 观看端怎么用 | [e](../works/e-client.md) |
| 降质那套 | [c1](../works/c1-quality.md) |
