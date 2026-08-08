# SDK · 观测与动作

对应 [api/agent.md](../api/agent.md)。**看**(`observe`)、**做**(`act`)、
**回看**(`log`)三件事,SDK 这一层的价值是把它们变成对象,让 agent 循环写起来短。

## 1. 看:`b.observe()`

```python
obs = b.observe()          # 一次调用拿到喂给模型的全部东西

obs.screenshot             # bytes,图上已经画好 [12] [13] 编号(Set-of-Mark)
obs.plain_screenshot       # bytes,没标注的那版
obs.elements               # [Element]
obs.tabs                   # [Tab] —— 让模型知道有哪些 tab
obs.page.url, obs.page.title, obs.page.scroll
obs.text                   # 正文,默认 digest
obs.notes                  # ["页面有 3 个 iframe,其中 1 个跨域读不到", ...]
obs.id                     # obs_01J9X... —— 按编号定位时要带上
```

参数和 API 同名:`b.observe(tab=, annotate=, viewport_only=, max_elements=, text=)`。

**`obs.notes` 要往 prompt 里放。** 它写的是这次观测的盲区;不给模型看,
模型会把"没看见"当成"不存在",然后自信地做错决定
([api/agent.md §1.2](../api/agent.md#12-notes-是刻意的))。

### `as_prompt()`

```python
print(obs.as_prompt())
# [12] button  "提交订单"
# [13] textbox "优惠码" = ""
# [14] link    "返回购物车"        (需下滑)
# [15] button  "删除"              (禁用)
```

纯排版,不请求网络。这是 API 元素表的紧凑表示
([api/agent.md §1.3](../api/agent.md#13-给模型的紧凑表示)),直接进 prompt。

### `Element`

```python
el = obs[12]                          # 按编号
el = obs.find(role="button", name="提交订单")
el.id  el.role  el.name  el.value  el.bbox
el.in_viewport  el.enabled  el.affords  el.hint

b.click(el)      # → {"element": 12, "observation": "obs_01J9X..."}
```

`b.click(el)` 会自动带上 `observation` id —— 页面变了就抛 `NotFound`,
而不是点到编号相同的另一个东西。

## 2. 做:`b.act()` 和快捷方法

```python
b.click("提交订单")                  # 可见文字(最常用)
b.click(role="button", name="登录")  # role + 名字,消歧
b.click(el)                          # observe() 拿到的元素对象
b.click(css="#pay")                  # CSS 选择器,逃生舱
b.click(at=(890, 632))               # 坐标,最后手段
b.click("下一页", nth=1)             # 多个匹配时指定第几个
```

定位语义定死在服务端([api/agent.md §4](../api/agent.md#4-定位)):
精确匹配优先 → 子串 → 大小写不敏感 → 仍然多于一个就抛 `NotFound` 并列出全部候选,
**绝不随便挑一个**。

一串动作一次往返,串行执行、遇错即停:

```python
r = b.act([
    {"type": "click", "text": "登录"},
    {"type": "type",  "label": "手机号", "text": "13800000000"},
    {"type": "key",   "key": "Enter"},
], settle={"strategy": "network_idle", "timeout_ms": 5000},
   note="购物车里已有一张票,现在去确认支付")
```

### `act()` 不抛异常,快捷方法抛

这是 SDK 里唯一一处**故意不一致**的地方,理由在 §4 那个循环里:

| | 定位失败时 |
| --- | --- |
| `b.click(...)` `b.type(...)` 等 | 抛 `NotFound`(带 `.candidates`) |
| `b.act([...])` | 返回 `r`,`r.ok is False`,`r.candidates` 拿候选 |

```python
r.ok             # 全部成功才 True
r.results        # 每个动作一条:.ok .ms .hit .after .shot
r.failed         # 第一个失败的那条,没有则 None
r.candidates     # = r.failed.candidates,方便直接喂回模型
r.log_from       # 这批动作在操作日志里的起始 seq
r.raise_()       # 想要异常语义时显式调用
```

写脚本用快捷方法(错了就该炸),写 agent 循环用 `act()`(错了要把候选喂回模型)。

### 动作表

`b.act()` 的 `actions` 原样透传 [api/agent.md §3](../api/agent.md#3-动作表) 的动作表。
其中这些有快捷方法:

| 动作 | SDK |
| --- | --- |
| `goto` `back` `forward` `reload` `stop` | `b.goto(url)` `b.back()` … |
| `click` `hover` | `b.click(...)` `b.hover(...)` |
| `type` `clear` | `b.type(loc, text, clear=)` `b.clear(loc)` |
| `key` | `b.key("Enter")` `b.key("a", modifiers=["Control"])` |
| `select` `check` | `b.select(loc, value=)` `b.check(loc, checked=)` |
| `scroll` `drag` | `b.scroll(dy=400)` `b.scroll(to=el)` `b.drag(a, b)` |
| `wait_for` | `b.wait_for(text=/css=/url_contains=/ms=)` |
| `extract` | `b.extract(loc, mode="table")` |
| `screenshot` `observe` | `b.screenshot()` `b.observe()` |
| `upload` | `b.upload(loc, path)` —— 见 §3 |
| `tab_new` `tab_activate` `tab_close` | 见 [tabs.md](tabs.md) |
| `js` | `b.js(expr)` —— 逃生舱,日志标黄 |

`$new` 占位符(上一个动作新开的 tab)只在 `act()` 的动作串里有,
快捷方法拿不到 —— 那种场景本来就该用一次 `act()` 走完
([api/agent.md §5](../api/agent.md#5-tab-和-agent-的接缝))。

## 3. 凭证和文件

```python
b.type("密码", secret="vault/shop/pwd")     # → text_ref: "secret://vault/shop/pwd"
```

明文只在 sessiond 内部出现一次,日志、事件、截图里一律 `••••••`。
`input[type=password]` 自动打码,不用你标。

```python
fid = b.upload_file("/local/id.png")        # POST /api/upload → file_id
b.upload("身份证", fid)                      # 动作里用
b.upload("身份证", "/local/id.png")          # 也接受路径,内部先传再用

b.download("report.xlsx", to="/tmp/")       # GET /api/download/{name}
```

## 4. 回看:`b.log()`

```python
for e in b.log(limit=100, after=42, only="failed"):
    print(e.seq, e.at, e.note, e.action, e.hit, e.ok, e.after.changed, e.actor)

b.bundle("out.zip")     # 日志 + 截图 + 离线 HTML
```

字段就是 [api/agent.md §6](../api/agent.md#6-get-apilog--回看它干了什么) 的日志条目。
`actor == "human"` 的条目是人在 VNC 里干的 —— **这是完整的操作路径**,
不是只有 SDK 干过的事。

## 5. 典型的 agent 循环

```python
from webmuxd import Browser
b = Browser("http://localhost:7900", token=TOKEN)

b.goto("https://shop.example.com")

while True:
    obs = b.observe()                       # 标注截图 + 元素表 + tab 列表

    decision = my_llm(                      # ← 你的大脑,webmuxd 不掺和
        goal=goal,
        image=obs.screenshot,               # 图上已经画好 [12] [13] 编号
        elements=obs.as_prompt(),
        tabs=obs.tabs,                      # 让它知道有哪些 tab
        notes=obs.notes,                    # 让它知道这次看不见什么
        history=b.log(limit=5),
    )

    if decision.done:
        break

    r = b.act(decision.actions,
              note=decision.thought)        # ← 思考进日志
    if not r.ok:
        feedback = r.candidates             # 喂回模型自我纠正
        continue
```

`b.act()` 一次往返执行一串动作,`note` 把这一步的思考挂上去。
webmuxd 不产生思考,但它提供一个思考与后果对齐的存放位置 ——
跑的时候在观看页面里能实时看着它点。

## 6. ↔ API 对照

| SDK | API |
| --- | --- |
| `b.observe(...)` | `GET /api/observe` |
| `obs.as_prompt()` `obs[12]` `obs.find()` | 纯客户端,不请求 |
| `b.act(actions, settle=, note=, idempotency_key=)` | `POST /api/act` |
| `b.click/type/key/select/...` | `POST /api/act`,一个动作 |
| `b.click(el)` | `{"element": id, "observation": obs.id}` |
| `b.type(loc, secret=)` | `text_ref: "secret://..."` |
| `b.screenshot()` `b.text()` | `GET /api/screenshot` `/api/text` |
| `b.status()` `b.viewport()` `b.reset()` | `GET /api/status` `/api/viewport` `POST /api/reset` |
| `b.log()` `b.bundle()` | `GET /api/log` `/api/log/bundle` |
| `b.upload_file()` `b.download()` | `POST /api/upload` `GET /api/download/{name}` |

**对不上的地方**只有三处,都在客户端:`as_prompt()` 的排版、
`upload()` 接受本地路径(帮你先传一次)、以及 §2 那个 `act()` 不抛异常的取舍。
