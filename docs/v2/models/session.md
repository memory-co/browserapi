# session

**一个 session = 一个浏览器 + 一份画面 + 一条流水。**
它是 [tab](tab.md) / [page](page.md) / [frame](frame.md) 的容器。

## 1. HTTP

### `GET /api/sessions` → `SessionRow[]`
### `POST /api/sessions` → `SessionRow`
### `DELETE /api/sessions/{sid}`

**列表页、`webmuxd ls`、这个端点用的是同一份**
([k §3](../works/k-one-server.md#3-那个口上看到什么))。
`webmuxjs/client/src/api.ts` 里有个同名 interface —— **这是第二处跨语言的形状**。

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `id` | `id` | |
| `runtime` | `runtime` | `process` / `remote` |
| `tabs` | `tabs` | 几个 tab |
| `active_tab` | `active_tab` | |
| `view` | `view` | 三个词之一 |
| `available` | `available` | 这台**能切到**哪几种 |
| `uptime_s` | `uptime_s` | |
| `notes` | `notes` | 起的时候要说的话(比如"沙箱是关着的") |
| — | **`url`** | `@property`,`/s/<id>/`。**只有一处拼它** |
| — | **`view_label`** | `@property`,界面上那个词 |

最后两个是**只在 JSON 那一侧存在的派生字段**:它们不是数据,是
"别让界面自己再拼一遍"。`from_json` 不读它们 —— 读回来也是算得出的。

### `GET /s/{sid}/api/status`

session 的现状。它不是一个 dataclass,是现拼的 dict —— **这是个待办**:
按[规矩 1](README.md#4-三条规矩),线上的形状该有定义。

## 2. 事件流 `WS /s/{sid}/api/events`

**服务端单向推**。session 级的五种:

| 事件 | 什么时候 |
| --- | --- |
| `human.active` | 人在画面里动了 —— 让路窗口开了 |
| `chrome.restarted` | 浏览器崩过又起来了。**收到它要重新拉全量** |
| `log.appended` | 流水多了一条 |
| `auth.required` | 站点要 HTTP 认证,页面停住了 |
| `permission.changed` | 权限被授予/撤销 |

每条都带 `seq` / `at` / `type`,**`seq` 和流水共用一个计数器** ——
所以事件和日志能按编号对齐。

断线重连带 `?after=<seq>` 补;补不齐先发一条 `gap`:

> **收到 `gap` 就该重新拉全量,不要假装没丢。**

## 3. 落盘 `log.jsonl` → `LogEntry`

| 字段 | JSON | 说明 |
| --- | --- | --- |
| `seq` | `seq` | **跨重启不回退** |
| `at` | `at` | |
| `kind` | `kind` | 九类,**闭集**,有测试守着 |
| `tab` `user` `note` | 同名,**空的不写** | `user` 是**谁做的**:`api` / `cli` / `human` |
| `fields` | **展开进顶层** | 那一类自己的字段 |

`fields` 那一条是这几张表里最特别的:

> **它不作为一个键出门,而是 `out.update(self.fields)`。**

理由:一条 `action` 和一条 `download` 共同的只有上面那几样,剩下的按类不同 ——
全列成字段等于让这个类跟着每一个动词一起长。`from_json` 反过来:
**除了那六个已知键,剩下的全收进 `fields`。**

所以这个 DTO 是**开放**的:线上多一个键不会让它读不回来。
但 `kind` 本身是闭集 —— 开放的是内容,不是分类。

九类里 `diag` 和前八类不是一回事:前八类回答"谁做了什么",它回答"出了什么问题"。
**同一条流、同一套 `seq`**,所以排查只看一个地方就够 ——
这条是拿事故换来的([works/session 那段](../works/i-agent-surface.md))。

`GET /api/log` 回 JSON,`GET /api/log.txt` 回渲染好的文本 ——
**CLI 和网页下载共用同一份渲染**(`logfmt.py`),
两处各写一遍的下场是人拿到的两份日志长得不一样。

## 4. 画面下行:`Hello`

它是 session 级的,所以在这一篇。**连上来第一条,权限只在这时候说一次** ——
鼠标移动一秒几十个事件,逐个回 403 等于自己 DoS 自己。

| 字段 | JSON | TS |
| --- | --- | --- |
| `writable` | `writable` | ✔ |
| `transport` | `transport` | ✔ |
| `protocol` | `protocol` | **没声明,而且两边都没人读**(见 [frame §3](frame.md#3-hello-那个-protocol--28-没人读)) |
| `w` `h` | `w` `h`(`w` 非零才写) | ✔ 可选 |
| `extra` | **展开进顶层** | 没声明 |

## 5. 不出门:`SessionInfo`

runtime 产出的那个把柄:`kind` / `id` / `detail`。**没有 `to_json`。**

`detail` 是 `dict[str, Any]`,今天里面装着:

```
cdp  cdp_port  work  browser  transport  display
xpra_ws  xpra_ws_port  xpra_log  view  pids  notes     ← 十二个是数据
_xpra                                                   ← 一个活的 Popen
```

```python
sess = handle.detail["_xpra"]
sess.proc.poll()          # 在"只有数据"那一层里 poll 一个子进程
```

**它不是形状,是把柄。** 要收拾得先回答:那十二个能不能写成字段,
以及那个进程对象该由谁拿着。

## 6. ↔ 别处

| | |
| --- | --- |
| 一个 server 一个口 | [k](../works/k-one-server.md) |
| 那条流水 | [api/log](../../v1/api/log.md) · [`tests/the_scrollback/`](../../../tests/the_scrollback/) |
| 事件流的补发规矩 | [api/events](../../v1/api/README.md) |
