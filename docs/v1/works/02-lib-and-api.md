# 02 · Python lib 与 HTTP API

**lib 是主体。** 定位、观测、动作、日志这些行为**定义在 lib 里**,
HTTP API 是把它导出去的一层壳,为两件事而加:**调试**,和**非 Python 的集成**。

不是「lib 封装了 API」,顺序反过来:**API 是 lib 的导出面**。

这条决定了两件很具体的事:

- **新能力先落在 lib 里**,HTTP 那层机械地跟着导出。不存在「API 有但 lib 没有」。
- **语义只定义一次**:定位规则、元素筛选、`candidates`、`settle`、日志格式,
  都是 lib 的行为。[`api/`](../api/) 那几篇**描述**它们,但不**拥有**它们。

> **后来推翻了。** `observe` 整个砍了 —— 读只剩「一张图和正文」两个口子,
> 元素表跟着定位走,不单独开口子。见
> [api/act.md §1](../api/act.md#1-读--一张图和正文)。

## 1. 为什么是 lib 而不是 API

写 agent 的地方是 Python。主体放在这儿,循环才短、错误才能是异常、
观测才能是个能 `obs[12]` 的对象。

反过来把 HTTP 当主体,坏处是**表达力更弱的那层会倒灌进设计**:
JSON 里没有对象、没有异常、没有惰性求值,于是 `favicon` 只能是个 URL 字符串、
定位失败只能是个错误码。让它当主体,lib 就只能跟着变成一堆 `dict` 搬运。

但也**不能只有 lib**,三个理由,每个都成立:

| 为什么还要 HTTP | 具体是什么 |
| --- | --- |
| 浏览器不在你的进程里 | 它在容器里、或另一台机器上,中间总得有个线上格式 |
| 别的语言要用 | TypeScript 写的前端要画 tab 条,Go 写的调度器要拉 session |
| 出事要能 curl | `curl localhost:7900/api/status` 比 import 一个包快得多 |

所以 HTTP 是**必须有**的,只是它不是设计的起点。

## 2. lib 在哪儿运行

核心跑在 **session 里面**,紧挨着 Chromium,握着 CDP 连接。sessiond 就是它加一层 HTTP 壳:

```
   你的代码
      │  import webmuxd
      ▼
   Session ──────────HTTP─────────►┌─ sessiond ───────────────┐
   (远程 transport + 内存里那份     │  HTTP 壳(导出面)       │
    tab 表)      ◄───WS 事件───────│      ↓ 同名方法          │
                                    │  webmuxd 核心 ──CDP──► Chromium
   curl / TS / Go ──────HTTP───────►└──────────────────────────┘
```

同一个包的两层:

- **核心** —— 定位引擎、可访问性树筛选、动作执行、操作日志。跑在 sessiond 里。
- **`Session`** —— 你从 `Webmuxd().create()` 拿到的那个。每个方法对应核心的同名方法,
  远程时经 HTTP 转一道;另外它订着事件流,**tab 表和每个 tab 的 url / 标题就在本地内存里**,
  读它们不发请求
  ([sdk/README §3](../sdk/README.md#3-tab-的状态在内存里))。

**HTTP 壳里没有业务逻辑**,它只做序列化和鉴权。所以 `/api/openapi.json`
能从核心的方法签名生成 —— 一份东西,不是两份([api/README §6](../api/README.md#6-版本))。

这也解释了为什么 API 曾经长成那个样子:`observe` 返回一大坨而不是拆成五个端点,
是因为它在 lib 里本来就是一次调用。

## 3. 用起来什么样

```bash
pip install webmuxd
```

```python
from webmuxd import Webmuxd

web  = Webmuxd()                            # 管理实例 —— 空壳,不起任何浏览器
sess = web.session(id="work", api_port=7900, view_port=6901)   # 起一个 kasm
tab  = sess.open("https://shop.example.com", user="human")
tab.click("登录", user="claudecode")       # 按可见文字找
tab.type("手机号", "13800000000")          # 按标签找输入框
tab.type("密码", "hunter2")
tab.click(role="button", name="登录")      # 说不清的时候加 role
tab.wait_for(url_contains="/home")

print(tab.url, tab.title)                  # 读内存,不发请求
print(tab.text())                          # 页面正文,这个要请求
rows = tab.extract(".cart-item", mode="table")
tab.screenshot("cart.png")
```

三件事在这段里定了型,都是 HTTP 推导不出来的:

- **三层:管理实例 → session → tab。** `Webmuxd()` 是空壳,不起任何浏览器;
  `create()` 才起一个 kasm,一个 session 占两个端口(kasm 复用不了端口,这点和 tmux 不同)。
- **tab 是句柄** —— 不需要「不传就作用在当前 tab」那条规则,那是线上才需要的。
- **`user` 是署名** —— 多个 agent 和人共用一个浏览器,回看时分得清谁干的。
  它不是鉴权也不是锁,边界仍然是 token。

### 定位元素

按能用就行的顺序:

```python
tab.click("提交订单")                  # 可见文字(最常用)
tab.click(role="button", name="登录")  # role + 名字,消歧
tab.click(cand)                        # 定位失败回的候选里的一项
tab.click(css="#pay")                  # CSS 选择器,逃生舱
tab.click(at=(890, 632))               # 坐标,最后手段
```

匹配规则(精确 → 子串 → 大小写不敏感 → 仍然多于一个就报错)**是 lib 的规则**,
HTTP 那边只是把它暴露出去。找不到不会静默失败,抛 `NotFound` 并**附上最像的 3 个候选**:

```python
try:
    tab.click("提交订单")
except NotFound as e:
    print(e.candidates)   # [button "提交订单(2)", link "订单", button "提交"]
```

**异常是 lib 的原生表达**,HTTP 那边只能退化成错误码 + JSON,见 §6。

### 给 Agent 用

```python
img = tab.screenshot()     # 一张图;正文是 tab.text()

obs.screenshot             # PNG bytes,已经在图上标好了元素编号
obs.elements               # 元素列表
print(obs.as_prompt())
# [3]  button   "提交订单"
# [4]  textbox  "优惠码" = ""
# [5]  link     "返回购物车"   (需下滑)

action = my_llm(goal, image=obs.screenshot, elements=obs.as_prompt())
tab.click(obs[action.index])        # 按模型给的编号点
```

当时 `observe()` 做的事:抓可访问性树 → 筛出能交互又看得见的元素 → 编号 → 拍一张。
这是让多模态模型能直接用的最小观测层,不需要你自己解析 DOM。

**图上不画框。** 编号在 `el.id`、位置在 `el.bbox` —— 要一张 Set-of-Mark 图,
拿这两样自己叠。以前是在活页面上铺一层框再拍,而那会让正在看的人看到一闪
([issue](../../v2/issues/标注层会被人看见.md))。

`obs[12]` 这种下标、`obs.notes` 这种字段,在 JSON 里都会退化成数组和字符串 ——
**这就是为什么主体在 lib**。

## 4. 导出面

所有路径在 `/api` 下。每一条都对着 lib 的一个方法 ——
但**不是一一对应**:`tab.url` 一个端点都不占(读内存),而 `tab` 句柄在线上只是个 `{id}`。
导出面比 lib 碎,因为 HTTP 没有句柄也没有本地状态。

| lib | HTTP |
| --- | --- |
| `sess.status()` | `GET /api/status` |
| `tab.act([...])` | `POST /api/act` |
| `tab.screenshot()` | `GET /api/screenshot` |
| `tab.screenshot()` | `GET /api/screenshot` |
| `tab.text()` | `GET /api/text` |
| `sess.log()` | `GET /api/log` |
| 内存表的维护 | 内部订 `WS /api/events`,不暴露给调用方 |
| `sess.upload_file()` | `POST /api/upload` |
| `sess.download()` | `GET /api/download/{name}` |
| `sess.reset()` | `POST /api/reset` |

```jsonc
// POST /api/act —— 就是 tab.act([...]) 的线上形态
{ "actions": [
    { "type": "click", "text": "登录" },
    { "type": "type",  "label": "手机号", "text": "13800000000" },
    { "type": "key",   "key": "Enter" }
] }

// → 200
{ "results": [
    { "ok": true, "ms": 412,
      "hit": { "role": "button", "name": "登录", "bbox": [820,612,140,40] },
      "after": { "url": "/home", "changed": "出现『欢迎回来』" } },
    { "ok": true, "ms": 88 },
    { "ok": true, "ms": 1240, "after": { "url": "/home" } }
] }
```

串行执行,遇错即停。完整规格在 [api/](../api/),Python 侧在 [sdk/](../sdk/)。

## 5. 动作表

lib 的方法在前,因为那是定义的地方:

| lib | 动作 `type` | 参数 |
| --- | --- | --- |
| `tab.goto(url)` | `goto` | `url` |
| `tab.back()` `tab.forward()` `tab.reload()` | `back` / `forward` / `reload` | — |
| `tab.click(...)` | `click` | 定位 + `button`, `count` |
| `tab.hover(...)` | `hover` | 定位 |
| `tab.type(...)` | `type` | 定位 + `text`, `clear` |
| `tab.key("Enter")` | `key` | `key`, `modifiers` |
| `tab.select(...)` | `select` | 定位 + `value` |
| `tab.check(...)` | `check` | 定位 + `checked` |
| `tab.upload(...)` | `upload` | 定位 + `file_id` |
| `tab.scroll(...)` | `scroll` | `dy` 或定位(滚到某元素) |
| `tab.wait_for(...)` | `wait_for` | `text` / `css` / `url_contains` / `ms` |
| `tab.extract(...)` | `extract` | 定位 + `mode`(text/html/table/attr) |
| `tab.screenshot()` | `screenshot` | `full_page` |
| `tab.screenshot()` | `screenshot` | — |
| `sess.open()` `tab.activate()` `tab.close()` | `tab_new` / `tab_activate` / `tab_close` | |
| `tab.js(...)` | `js` | `expression` |

`js` 和坐标点击是逃生舱:能用,但日志里会标黄 —— 因为回看的时候,
「执行了一段 JS」和「在 (890,632) 点了一下」都是看不出干了什么的。

## 6. 错误

**异常是主体,错误码是它的序列化。** 一个 code 一个类,二分成「你能自愈」和「该告警」:

| lib 异常 | 序列化成 | 意思 |
| --- | --- | --- |
| `NotFound` | `not_found` | 找不到元素(带候选) |
| `NotClickable` | `not_clickable` | 找到了但被挡住/禁用 |
| `Timeout` | `timeout` | 等超时 |
| `NavFailed` | `nav_failed` | 页面打不开 |
| `ChromiumGone` | `chrome_gone` | Chromium 崩了(会自动重启) |

前四个你自己重试或换个写法;`ChromiumGone` 说明容器出事了。
完整的异常树见 [sdk/README §3](../sdk/README.md#5-异常),码表见
[api/README §4](../api/README.md#4-错误)。

**`.candidates` 这种东西在 lib 里是异常上的属性,在 HTTP 里只能塞进 `details`。**
又一次:主体在 lib。

## 7. 并发

**一个 session 同时只跑一个动作。** 并发调会拿到 `Busy`(HTTP 上是 `409 busy`),
不排队、不交错 —— 排队会让「谁先点」变得不可预测,不如直接拒绝。

要真并发?起多个 session。这也是 tmux 的答案:多开几个。

```python
sessions = [web.session(id=f"w{i}", api_port=7900+i, view_port=6901+i)
            for i in range(4)]
```

`Session` 实例不是线程安全的,一个线程一个。

## 8. 明确不做

- ❌ **不做第二套实现** —— HTTP 壳里不写业务逻辑。它多写一行判断,就是漂移的开始。
- ❌ **API 不加 lib 没有的行为** —— 反过来可以:lib 有些东西(`with` 自动清理、
  按标题找 tab)是纯客户端的,不必导出。
- ❌ **不做 async lib** —— v1 只有同步。要并发就多起 session,理由同 §7。
- ❌ **不为了「API 优先」把 lib 变成 dict 搬运工** —— 那正是这份文档要避免的东西。
