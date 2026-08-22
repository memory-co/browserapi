# v2 · sdk

**主体在这儿。** 三个对象,一层套一层:

```python
from webmuxd import Webmuxd

web  = Webmuxd(port=7900)              # ① 一个 server,一个口
sess = web.session(id="work")          # ② 一个 Chromium + 一份日志
tab  = sess.open("https://example.com")  # ③ 一个页面句柄

tab.click("提交订单")                   # 按人看得见的字,不写选择器
print(tab.text())
```

> **相对 [v1/sdk](../../v1/sdk/) 变了三处**,其余(tab 操作、日志、错误模型)
> 一个字没动,仍以 v1 那份为准:
>
> 1. **端口在 `Webmuxd()` 上,不在 session 上**(§1)
> 2. **`observe()` 没有了**,读只剩 `screenshot()` / `text()`(§3)
> 3. **`Element` / `Observation` 不再暴露**,定位靠人看得见的字(§3)

## 1. 端口在 `Webmuxd()` 上

```python
web = Webmuxd(port=7900)                                     # 本机那个 server
web = Webmuxd("https://browser.internal:7900", token=TOKEN)  # 远端的
web = Webmuxd()                                              # 读那份"server 在哪"的记录
web = Webmuxd(name="ci")                                     # 换一套独立的 server
```

**一个 server 一个口,session 是它下面的 `/s/<id>/`** ——
像 tmux 一个 server 装着全部 session([k](../works/k-one-server.md))。

v1 是 `session(id=, api_port=, view_port=)`;v2 一度收成一个 `port=`;
现在收到 server 上。那个"一个 session 一个端口"从来不是设计,
是 kasm 的 web 口不归我们控制 —— 画面自己产之后那条硬约束就没了。

```python
web.session(id="work", port=7900)      # ✗ BadRequest,并说端口去哪儿了
```

**旧参数不静默吞。** 落进 `**kw` 被丢掉,然后报一个指向别处的错,最糟。

**server 不按需自启。** tmux 能自启是因为它用 socket,没有端口要挑;我们有,
而那条规矩是「端口由你给」([h §6](../works/h-runtime.md#6-端口由你给))。
没起就先 `webmuxd server start --port 7900`。

## 2. `session()` —— 建和取是同一件事

```python
sess = web.session(id="work", runtime="process")
sess = web.session(id="work")     # 已经有了 → 同一个,后面的参数都不用再给

web.session(id="work") is web.session(id="work")   # True
```

幂等,像 `tmux new -A -s`。**同一个 id 返回同一个 Python 对象** ——
每个 `Session` 背后有一条 WS 和一份内存 tab 表,给两个就是两条连接、
两份可能不一致的表。

| runtime | 是什么 |
| --- | --- |
| `process` | 在 server 那台机器上起一个浏览器(**默认**) |
| `remote` | 你给一个 CDP 端点,浏览器不归我们 |

**容器那条 v2 去掉了**([h §2](../works/h-runtime.md)):要隔离就把 webmuxd
整个放进容器里跑 —— 那是部署决定,不是我们的参数。

```python
web.list()          # server 上那张表,每行是 models.SessionRow
web.sessions()      # 每一行都变成能操作的 Session
web.kill("work")
web.kill_server()   # 停 server 和全部 session,一个都不留
```

## 3. 读:一张图,和正文

```python
tab.screenshot()      # bytes    —— 那一刻的页面(WebP)
tab.text()            # str      —— 正文
tab.snapshot()        # Snapshot —— 元素表,每样带一个 @e1
```

**三样,要哪样取哪样。** v1 那个 `observe()` 一次回一整包(元素表、编号、
盲区 notes、页面信息、截图、正文),那个形状没有回来。

`snapshot()` 的旋钮在调用方手上 —— `interactive` / `selector` /
`viewport` / `max_elements`,库不替你定死筛到什么程度。这一版为什么
推翻了上一版"砍掉它"的决定,写在
[i §3](../works/i-agent-surface.md#3-读的那一面一张图正文和一张元素表)。

```python
snap = tab.snapshot(interactive=True)
print(snap.as_prompt())      # @e1   button    "登录"
tab.click(snap[1])           # 或者 tab.click("@e1")
```

定位因此有了最准的一种:

```python
tab.click("@e13")                     # snapshot 给的号,最准
tab.click("提交订单")                  # 按人看得见的字
tab.click(role="button", name="登录")  # 消歧
tab.click(候选里的那一项)               # 有号就用号,没有就 role + name
```

**`@` 打头一律当号。** 真有个按钮叫「@提醒」就写 `tab.click(name="@提醒")`。

```python
try:
    tab.click("订单")
except NotFound as e:
    e.details["candidates"]            # [{"id":1,"role":"button","name":"提交订单"}, ...]
    tab.click(e.details["candidates"][0])
```

**候选里那个 `id` 别拿去点** —— 它是 `act` 内部那次快照的序号,不是 `ref`。
`ref` 只有走过 `snapshot()` 的元素才有,而它**只增不重用**:
拿过期的号去点会报错,不会点到另一个东西
([RefTable](../../../webmuxd/models.py))。没有号的时候,能跨快照成立的说法是
`role` + `name`(必要时 `nth`)。

`tab.extract(loc, mode=)` 仍在,它是[动词表](../works/i-agent-surface.md#2-动词表)
里的一个动作,走 `POST /api/act`,进日志。

## 4. 数据都有形状

跨模块、跨 HTTP、跨语言的东西在 [`webmuxd/models.py`](../../../webmuxd/models.py)
定义一次([j §3.1](../works/j-layout.md#31-modelspy所有跨边界的数据在这儿定义一次)):

| | |
| --- | --- |
| `TabInfo` | 一个 tab 的记录。**能 `.click()` 的那个叫 `Tab`**,它持有前者 |
| `SessionRow` | server 上那一行 —— 列表页 / `webmuxd ls` / `GET /api/sessions` 同一份 |
| `Element` `Snapshot` | 定位用的元素表(**不对外**,见 §3) |
| `ActionResult` `LogEntry` | 一个动作的结果、`log.jsonl` 里的一行 |
| `MachineFacts` | `~/.webmuxd.json` —— install 探出来的路径表 |
| `Hello` `Cast` `ModeInfo` … | 观看端收到的下行消息,和 `protocol/messages.ts` 一一对应 |

## 5. ↔ 别处

| | |
| --- | --- |
| tab 操作、日志、错误模型 | [v1/sdk](../../v1/sdk/) —— 那部分没变 |
| HTTP 那一面 | [api](../api/) |
| 命令行 | [cli](../cli/) |
| 为什么是这个形状 | [works](../works/) |
