# session · session、流水、挡着页面的那几样

`SessionRow` `LogEntry` `Download` `Pending`,加上不出门的 `SessionInfo`。

## 1. `SessionRow` —— server 上那一行

**列表页、`webmuxd ls`、`GET /api/sessions` 用的是同一份**
([k §3](../works/k-one-server.md#3-那个口上看到什么))。
它也是**跨语言**的:`webmuxjs/client/src/api.ts` 里有个同名 interface。

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `id` | `id` | |
| `runtime` | `runtime` | `process` / `remote` |
| `tabs` | `tabs` | 几个 tab |
| `active_tab` | `active_tab` | |
| `view` | `view` | 三个词之一 |
| `available` | `available` | 这台能切到哪几种 |
| `uptime_s` | `uptime_s` | |
| `notes` | `notes` | 起的时候要说的话(比如"沙箱是关着的") |
| — | **`url`** | `@property`,`/s/<id>/`。**只有一处拼它** |
| — | **`view_label`** | `@property` 算的,界面上那个词 |

后两个是**只在 JSON 那一侧存在的派生字段** —— 它们不是数据,是"别让界面
自己再拼一遍"。`from_json` 不读它们,因为读回来也是算得出的。

## 2. `LogEntry` —— 流水里的一行

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `seq` | `seq` | **跨重启不回退**,和事件流共用一个计数器 |
| `at` | `at` | |
| `kind` | `kind` | 九类之一 |
| `tab` `user` `note` | 同名,**空的不写** | `user` 是**谁做的**:`api` / `cli` / `human` |
| `fields` | **展开进顶层** | 那一类自己的字段 |

`fields` 那一条是这张表里最特别的:

> **它不作为一个键出门,而是 `out.update(self.fields)`。**

理由写在类里:一条 `action` 和一条 `download` 共同的只有上面那几样,
剩下的按类不同 —— 全列成字段等于让这个类跟着每一个动词一起长。
`from_json` 反过来:**除了那六个已知键,剩下的全收进 `fields`。**

所以这个 DTO 是**开放的**:线上多一个键不会让它读不回来。九类之外
真要加东西,加在 `fields` 里就行 —— 但 `kind` 本身是**闭集**,
有测试守着([`the_scrollback/`](../../../tests/the_scrollback/))。

## 3. `Pending` —— 挡着页面的那件事

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `id` `kind` `tab` `at` | 同名 | `kind` 是五类:对话框 / 下载 / 文件选择 / 权限 / 认证 |
| `info` | **展开进顶层** | 那一类自己的字段 |

和 `LogEntry.fields` 一样的手法。但**它没有 `from_json`** ——
按 [README §2 第 3 条](README.md#2-三条规矩),这是个待办:
SDK 那边今天读的是裸 dict。

这几样为什么必须进得了流水:

> **没有桌面之后,它们是"页面为什么停住"的唯一解释** ——
> 不进 scrollback 的话,现象就只剩"页面一直没变,而且不知道为什么"
> ([g](../works/g-native-ui.md))。

## 4. `Download`

`id` `file` `url` `bytes` `total` `state` `path` —— **七个字段全出门**,
一一对应,没有派生也没有隐藏。这份表里最规矩的一个。

没有 `from_json`(同 `Pending`)。

## 5. `SessionInfo` —— 不出门,而且它不该是 DTO

runtime 产出的那个把柄:`kind` / `id` / `detail`。

`detail` 是 `dict[str, Any]`,今天里面装着:

```
cdp  cdp_port  work  browser  transport  display
xpra_ws  xpra_ws_port  xpra_log  view  pids  notes     ← 十二个是数据
_xpra                                                   ← 一个活的 Popen
```

```python
sess = handle.detail["_xpra"]
sess.proc.poll()          # 在"只有数据"的那一层里 poll 一个子进程
```

**它不是形状,是把柄。** 要收拾的话得先回答:那十二个能不能写成字段,
以及那个进程对象该由谁拿着。

## 6. ↔ 别处

| | |
| --- | --- |
| 一个 server 一个口 | [k](../works/k-one-server.md) |
| 流水 | [api/log](../../v1/api/log.md) |
| 挡着页面的那五类 | [g](../works/g-native-ui.md) |
