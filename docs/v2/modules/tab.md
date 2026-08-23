# tab · 那张表

**一句话**:tab 表就是浏览器的 target 表,**没有第二份账本** ——
而 0.18.0 之前 `active` 是唯一的例外,那次事故就从那个例外里长出来。

## 1. 今天散在哪

| 今天 | 干什么 |
| --- | --- |
| `tabs.py` (442) | 那张表:`t_N` 不复用、`reason` 靠 `openerId` 分、挤 tab、`front_is` |
| `models.py` 里 `TabInfo` (55) | 形状 |
| `sessions.py` 里 `_on_foreground` `_confirm_front` `_ask_front` `_prepare_tab` (~90) | **前台是谁** |
| `serve.py` 里 `h_tabs` `h_tab_one` `h_tab_new` `h_tab_close` `h_tab_activate` `h_reorder` `h_history` | HTTP |
| `api.py` 里 `Tab` (310) | SDK 那个句柄 |
| `cli.py` 里 `cmd_tabs` `cmd_new_tab` `cmd_select_tab` `cmd_kill_tab` | 命令 |

**六处。** 0.18.0 那次改"前台是谁",实际动了其中五个 —— 而它只是**一个概念**。

## 2. 该长成什么样

```
tab/
  README.md    一句话
  shape.py     TabInfo —— 字段和 `chrome.tabs` 对齐,便于直接映射
  table.py     那张表:发号、认爹、挤、关
  front.py     **前台是谁** —— 观测、确认、等回流
  http.py      /api/tabs*
  sdk.py       `Tab` 那个活句柄
  cli.py       tabs / new-tab / select-tab / kill-tab
```

`front.py` 单独一个文件是有理由的:它是这个域里**唯一一处要和页面往返**的东西
(页面报 `visibilityState`,我们等它),而别的都是本地记账。
把它和 `table.py` 混在一起,就是 0.18.0 之前那个样子。

## 3. 三条硬规矩

1. **`t_N` 是我们分配的,关掉不复用。** CDP 的 targetId 一重启就全变,
   而日志里那个 `t_7` 必须永远指同一个东西。
2. **`active` 是观测值,不是账。** 我们的命令只是发个信号,
   要等那一页自己报回来才记账 —— **没有例外,包括我们自己发的命令**
   ([f §3](../works/f-tabs.md))。
3. **同时开着的有上限,超了挤掉最不活跃的。** 当前的不挤、正在跑动作的不挤、
   先建后挤。

第 2 条只有一个写入口:`front_is()`。这一点值得在文件层面看得见 ——
`table.py` 里那个字段只许 `front.py` 改。

## 4. `Tab` 和 `TabInfo` 的区分要保住

> **数据叫 `TabInfo`,能操作的那个叫 `Tab`。**

后者带着 `.click()`、通过 HTTP 干活;它**持有** `TabInfo`,不重新定义一份 ——
对应 requests 里 `Session` 和 `Response` 的关系。

按域分之后这两个住进同一个目录(`shape.py` 和 `sdk.py`),**离得更近了,
但仍然是两个文件** —— 因为规矩 2 说 `sdk.py` 属于 face,只许认 `shape.py`。

## 5. ↔ 别处

| | |
| --- | --- |
| 外挂的 bar 和真的那张表是同一份数据 | [f](../works/f-tabs.md) |
| 前台是谁 | [`tests/who_is_in_front/`](../../../tests/who_is_in_front/) |
| 表本身 | [`tests/tab_identity/`](../../../tests/tab_identity/) |
