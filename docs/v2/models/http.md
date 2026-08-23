# http · 跨 HTTP 的那一份

**一句话**:别人说 "models" 的时候,指的就是这一堆 —— **最大的一类,
也是唯一一类"另一头是人写的代码"**。

## 1. 里面有什么

| | 是什么 |
| --- | --- |
| `Element` `Snapshot` `Size` | 这一页上有什么 —— 带 `@e1` 的那张元素表([i §3](../works/i-agent-surface.md)) |
| `TabInfo` | 一个 tab。字段和 `chrome.tabs` 对齐,便于直接映射([f §2.1](../works/f-tabs.md)) |
| `ActionResult` `PageDigest` | 做完一下之后的回话 |
| `LogEntry` `LOG_KINDS` | 那条流水的一条([log](../../v1/api/log.md)) |
| `Download` `Pending` | 挡着页面的那几样([g](../works/g-native-ui.md)) |
| `Locator` | 怎么找一个元素 —— 它同时是 CLI 的参数形状 |
| `SessionRow` | `webmuxd ls` 的一行 |

## 2. 它和别的三类差在哪

**另一头是人写的代码,而那些代码我们看不见。**

- 跨语言那份([wire](wire.md))另一头是我们自己写的 TS,改了可以一起改
- 落盘那份([facts](facts.md))另一头是上一次的自己,可以**整份作废**
- 三个词([words](words.md))另一头是我们自己的三层

只有这一类,另一头是**别人**:用 SDK 的、用 CLI 抓 `--json` 的、
照 [api](../api/) 自己画 UI 的。**少一个字段,他们那边是 `KeyError`,
而我们这边一切正常。**

所以这一类的规矩最保守:**只加不减,加的字段必须有默认值。**

## 3. 一条容易混的区分

> **数据叫 `TabInfo`,能操作的那个叫 `Tab`。**

后者带着 `.click()`、通过 HTTP 干活,住在 [`api.py`](../../../webmuxd/api.py);
它**持有** `TabInfo`,不重新定义一份 —— 对应 requests 里 `Session` 和
`Response` 的关系。

这条区分是这个文件存在的理由的一半。在它之前,同一个 tab 记录服务端一份、
SDK 一份,改一个字段要**记得**改另一边 —— 而"记得"从来不是一种机制。

## 4. `to_json` / `from_json` 必须成对

和 [wire](wire.md#3-单向是这一份的特权) 相反:这一类是**双向**的。

- `to_json` —— 服务端发出去
- `from_json` —— **SDK 收回来**([`api.py`](../../../webmuxd/api.py) 靠它把 JSON 变回对象)

所以这一份里出现"有 `to_json` 没 `from_json`"就是个信号:
要么它其实是下行消息(该搬去 `wire.py`),要么 SDK 那边今天在手搓 dict。
`ActionResult` 和 `Pending` 今天就是这样,**拆的时候要逐个问一遍**。

## 5. `Size` 为什么在这儿

它只被 `locate.py` 用,看着像"只在一个模块里活着的"。但它是
`Snapshot.viewport` 的类型,**跟着快照一起出门**。

判据不是"谁 import 它",是"它有没有出现在某个 `to_json()` 的结果里"。

## 6. ↔ 别处

| | |
| --- | --- |
| 这些形状在线上长什么样 | [api](../api/) |
| 读的那一面为什么是这三样 | [i §3](../works/i-agent-surface.md#3-读的那一面一张图正文和一张元素表) |
| `@e1` 的规矩 | [`tests/v2_refs/`](../../../tests/v2_refs/) |
