# models · DTO 对齐

**一句话**:这儿逐条列**跨边界那些数据到底长什么样** —— Python 的字段名、
线上的 JSON 键名、TS 那边声明的 interface,三者对不对得上。

落地在 [`webmuxd/models.py`](../../../webmuxd/models.py) 和
[`webmuxjs/client/src/protocol/messages.ts`](../../../webmuxjs/client/src/protocol/messages.ts)。

## 1. 怎么读这几张表

每张表四列:

| 列 | 意思 |
| --- | --- |
| **字段** | Python 那个 dataclass 上的名字 |
| **JSON** | `to_json()` **真的**会吐出来的键。空 = **不出门** |
| **回得来** | 有没有 `from_json()` —— 有才说明 SDK 能把它读回对象 |
| **TS** | `messages.ts` 里对应的字段。只有下行消息那一组有这列 |

**"JSON"那一列是跑出来的,不是照着源码抄的。** 有几个 `to_json()`
是条件写键(`if v: out[k] = v`),照源码读会读错 —— 这份表是把每个类
造一个实例、真的调一次 `to_json()` 得到的。

## 2. 三条规矩

1. **一个概念一处定义。** 同一个 tab 记录不许服务端一份、SDK 一份 ——
   要 JSON 的自己 `to_json()`,不重新写一份形状。
2. **不出门的字段要写明为什么。** `backend_node_id` 是 CDP 句柄、
   `target_id` 是 CDP 句柄、`touched_at` 是 LRU 内部 —— 它们**不上线**,
   而"为什么不上线"必须在表里说得出来。
3. **`from_json` 缺失只允许出现在下行消息上。** 下行是单向的:服务端写、
   TS 读,Python 永远不需要读回来。**别处缺 `from_json` 就是 SDK 读不回来。**

## 3. 今天对不齐的地方

量出来的,不是猜的。**四条,全部验实**:

| # | 哪儿 | 什么情况 |
| --- | --- | --- |
| ① | `Meta` | **服务端在发,观看页不认。** `screen.py:342` 会发 `{"type":"meta",…}`,而 `session-view.ts` 那个 switch 里**没有 `case "meta"`**,`messages.ts` 里也没有这个 interface、`Downstream` 联合类型里也没有它 |
| ② | `pong` | **反过来:TS 有 interface,Python 没有 DTO。** `serve.py:746` 手写 `{"type": "pong", "t": …}` |
| ③ | `Hello.protocol` | 发了 `protocol: 28`,**两边都没有人读它**。一个没人核对的版本号 |
| ④ | `Cast.dsf` | Python 会发,`messages.ts` 的 `Cast` 里**没声明** |

还有两处**改名**,不算错但没写在任何地方:

| 字段 | JSON 键 |
| --- | --- |
| `ViewMode.headed` | `needs_headed` |
| `MachineFacts.browser` | `default_browser` |

以及一处**同一个 DTO 两种出门形状**:`ModeInfo.to_json()` 没有 `type`
(给 `/api/mode` 用),`ModeInfo.as_message()` 才加上 `{"type": "mode"}`
(给 WS 用)。是有意的,但只有读代码才知道。

## 4. 五张表

| | 里面有什么 |
| --- | --- |
| [tab](tab.md) | `TabInfo` |
| [page](page.md) | `Element` `Snapshot` `Size` `Locator` `ActionResult` `Ref` `PageDigest` |
| [view](view.md) | 下行那六条 + `FrameHeader` + `ViewMode` —— **和 `messages.ts` 逐条对** |
| [session](session.md) | `SessionRow` `SessionInfo` `LogEntry` `Download` `Pending` |
| [facts](facts.md) | `MachineFacts` `BrowserFact` `XpraFact` `RrwebFact` |

## 5. 不跨 JSON 的那几个

`models.py` 里有几个类**一个 `to_json` 都没有** —— 按第 2 条的判据,
它们没跨过 JSON 那条边界:

| | 为什么它在 models 里 |
| --- | --- |
| `Ref` `RefTable` | `@e1` 那套号。**`RefTable` 有状态、会抛四种 `NotFound`** —— 它是服务,不是 DTO |
| `SessionInfo` | runtime 产出的把柄。`detail` 是 `dict[str, Any]`,**里面装着活的子进程** |
| `PageDigest` | 只为算 `after.changed`,不出门 |
| `Quality` | 一档画质,出门的是 `QualityChanged` |
| `PackageFamily` | 装包时用的表 |

它们各自的去处见对应那张表。
