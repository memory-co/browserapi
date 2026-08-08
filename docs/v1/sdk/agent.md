# lib · 观测与动作

导出成 [api/agent.md](../api/agent.md)。**看**(`observe`)、**做**(`act`)、
**回看**(`log`)三件事都定义在这儿 —— 观测是个能下标的对象、失败是个带候选的异常,
agent 循环才写得短。到了 HTTP 那边它们退化成 JSON 和错误码。

页面级的东西都挂在 tab 句柄上([tabs.md](tabs.md));日志是整个 session 的,挂在 `web` 上。

## 1. 看:`tab.observe()`

```python
obs = tab.observe()        # 一次调用拿到喂给模型的全部东西

obs.screenshot             # bytes,图上已经画好 [12] [13] 编号(Set-of-Mark)
obs.plain_screenshot       # bytes,没标注的那版
obs.elements               # [Element]
obs.tabs                   # [Tab] —— 让模型知道有哪些 tab
obs.page.url, obs.page.title, obs.page.scroll
obs.text                   # 正文,默认 digest
obs.notes                  # ["页面有 3 个 iframe,其中 1 个跨域读不到", ...]
obs.id                     # obs_01J9X... —— 按编号定位时要带上
```

参数:`tab.observe(annotate=, viewport_only=, max_elements=, text=)`。

**`obs.notes` 要往 prompt 里放。** 它写的是这次观测的盲区;不给模型看,
模型会把"没看见"当成"不存在",然后自信地做错决定
([api/agent.md §1.2](../api/agent.md#12-notes-是刻意的))。

`observe()` **一定发请求** —— 元素表和截图不在内存里,事件流不塞大字段
([README §3](README.md#3-tab-的状态在内存里))。

### `as_prompt()`

```python
print(obs.as_prompt())
# [12] button  "提交订单"
# [13] textbox "优惠码" = ""
# [14] link    "返回购物车"        (需下滑)
# [15] button  "删除"              (禁用)
```

纯排版,不请求网络。`elements` 压成这样直接进 prompt
(线上形态见 [api/agent.md §1.3](../api/agent.md#13-给模型的紧凑表示))。

### `Element`

```python
el = obs[12]                          # 按编号
el = obs.find(role="button", name="提交订单")
el.id  el.role  el.name  el.value  el.bbox
el.in_viewport  el.enabled  el.affords  el.hint

tab.click(el)      # → {"element": 12, "observation": "obs_01J9X..."}
```

`tab.click(el)` 会自动带上 `observation` id —— 页面变了就抛 `NotFound`,
而不是点到编号相同的另一个东西。

## 2. 做:`tab.act()` 和快捷方法

```python
tab.click("提交订单")                  # 可见文字(最常用)
tab.click(role="button", name="登录")  # role + 名字,消歧
tab.click(el)                          # observe() 拿到的元素对象
tab.click(css="#pay")                  # CSS 选择器,逃生舱
tab.click(at=(890, 632))               # 坐标,最后手段
tab.click("下一页", nth=1)             # 多个匹配时指定第几个
```

定位语义定死在引擎里(跟 Chrome 一起跑在 session 内,
[api/agent.md §4](../api/agent.md#4-定位)):精确匹配优先 → 子串 → 大小写不敏感 →
仍然多于一个就抛 `NotFound` 并列出全部候选,**绝不随便挑一个**。

一串动作一次往返,串行执行、遇错即停:

```python
r = tab.act([
    {"type": "click", "text": "登录"},
    {"type": "type",  "label": "手机号", "text": "13800000000"},
    {"type": "key",   "key": "Enter"},
], settle={"strategy": "network_idle", "timeout_ms": 5000},
   note="购物车里已有一张票,现在去确认支付",
   user="claudecode")
```

`user` 是署名,`note` 是这一步的思考,两个都进日志。见 §4。

### `act()` 不抛异常,快捷方法抛

这是 lib 里唯一一处**故意不一致**的地方,理由在 §5 那个循环里:

| | 定位失败时 |
| --- | --- |
| `tab.click(...)` `tab.type(...)` 等 | 抛 `NotFound`(带 `.candidates`) |
| `tab.act([...])` | 返回 `r`,`r.ok is False`,`r.candidates` 拿候选 |

```python
r.ok             # 全部成功才 True
r.results        # 每个动作一条:.ok .ms .hit .after .shot
r.failed         # 第一个失败的那条,没有则 None
r.candidates     # = r.failed.candidates,方便直接喂回模型
r.new_tabs       # [Tab] —— 这批动作开出来的新 tab,是句柄不是 id
r.log_from       # 这批动作在操作日志里的起始 seq
r.raise_()       # 想要异常语义时显式调用
```

写脚本用快捷方法(错了就该炸),写 agent 循环用 `act()`(错了要把候选喂回模型)。

**响应会回灌内存**:`after.url` 和 `new_tabs` 落进那份 tab 表,
所以动作返回之后 `tab.url` 立刻是新的([README §3](README.md#3-tab-的状态在内存里))。

### 动作表

`act()` 的 `actions` 原样透传 [api/agent.md §3](../api/agent.md#3-动作表) 的动作表。
其中这些有快捷方法:

| 动作 | lib |
| --- | --- |
| `goto` `back` `forward` `reload` `stop` | `tab.goto(url)` `tab.back()` … |
| `click` `hover` | `tab.click(...)` `tab.hover(...)` |
| `type` `clear` | `tab.type(loc, text, clear=)` `tab.clear(loc)` |
| `key` | `tab.key("Enter")` `tab.key("a", modifiers=["Control"])` |
| `select` `check` | `tab.select(loc, value=)` `tab.check(loc, checked=)` |
| `scroll` `drag` | `tab.scroll(dy=400)` `tab.scroll(to=el)` `tab.drag(a, b)` |
| `wait_for` | `tab.wait_for(text=/css=/url_contains=/ms=)` |
| `extract` | `tab.extract(loc, mode="table")` |
| `screenshot` `observe` | `tab.screenshot()` `tab.observe()` |
| `upload` | `tab.upload(loc, path)` —— 见 §3 |
| `tab_new` `tab_activate` `tab_close` | `web.open()` `tab.activate()` `tab.close()` |
| `js` | `tab.js(expr)` —— 逃生舱,日志标黄 |

`$new` 占位符(上一个动作新开的 tab)只在 `act()` 的动作串里有:

```python
tab.act([
    {"type": "click", "text": "查看帮助"},
    {"type": "tab_activate", "id": "$new"},
    {"type": "click", "text": "联系客服"},
    {"type": "tab_close"},
])
```

快捷方法拿不到 `$new`,但也不需要 —— `r.new_tabs[0]` 直接就是句柄。
`$new` 省的是往返,那种场景本来就该一次 `act()` 走完
([api/agent.md §5](../api/agent.md#5-tab-和-agent-的接缝))。

## 3. 凭证和文件

```python
tab.type("密码", secret="vault/shop/pwd")     # → text_ref: "secret://vault/shop/pwd"
```

明文只在 sessiond 内部出现一次,日志、事件、截图里一律 `••••••`。
`input[type=password]` 自动打码,不用你标。

```python
fid = web.upload_file("/local/id.png")        # POST /api/upload → file_id
tab.upload("身份证", fid)                      # 动作里用
tab.upload("身份证", "/local/id.png")          # 也接受路径,内部先传再用

web.download("report.xlsx", to="/tmp/")       # GET /api/download/{name}
```

## 4. 回看:`web.log()`

日志是**整个 session 的**,不分 tab,所以挂在 `web` 上:

```python
for e in web.log(limit=100, after=42, only="failed"):
    print(e.seq, e.at, e.user, e.note, e.action, e.hit, e.ok, e.after.changed)

web.log(user="claudecode")     # 只看某个署名干了什么
web.log(tab="t_7")             # 只看某个 tab
web.bundle("out.zip")          # 日志 + 截图 + 离线 HTML
```

字段就是 [api/agent.md §6](../api/agent.md#6-get-apilog--回看它干了什么) 的日志条目。
`e.user == "human"` 的是人在 VNC 里干的 —— **这是完整的操作路径**,
不是只有你的代码干过的事。

`note` 那一列是这套东西的核心:webmuxd 不产生思考,但它提供一个
思考与后果对齐的存放位置。

```
14:22:06 💭 claudecode:购物车里已有一张票,现在去确认支付
         click "提交订单" → 命中 button "取消订单"    ← 一眼看出认错了元素
         → /cancel  出现『订单已取消』
```

**`log()` 一定发请求**,它不在内存里。

## 5. 典型的 agent 循环

```python
from webmuxd import Webmuxd

web = Webmuxd(port=12345, token=TOKEN, user="claudecode")
tab = web.open("https://shop.example.com")

while True:
    obs = tab.observe()                     # 标注截图 + 元素表 + tab 列表

    decision = my_llm(                      # ← 你的大脑,webmuxd 不掺和
        goal=goal,
        image=obs.screenshot,               # 图上已经画好 [12] [13] 编号
        elements=obs.as_prompt(),
        tabs=web.tabs,                      # 免费,内存里就有
        notes=obs.notes,                    # 让它知道这次看不见什么
        history=web.log(limit=5),
    )

    if decision.done:
        break

    r = tab.act(decision.actions,
                note=decision.thought)      # ← 思考进日志
    if not r.ok:
        feedback = r.candidates             # 喂回模型自我纠正
        continue
```

一次 `act()` 往返执行一串动作。跑的时候在观看页面里能实时看着它点 ——
人随时可以自己上手点两下,那些操作会以 `user="human"` 进同一份日志。

## 6. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `tab.observe(...)` | `GET /api/observe?tab=` |
| `obs.as_prompt()` `obs[12]` `obs.find()` | 纯客户端,不请求 |
| `tab.act(actions, settle=, note=, user=, idempotency_key=)` | `POST /api/act` |
| `tab.click/type/key/select/...` | `POST /api/act`,一个动作 |
| `tab.click(el)` | `{"element": id, "observation": obs.id}` |
| `tab.type(loc, secret=)` | `text_ref: "secret://..."` |
| `r.new_tabs` | 由响应的 `after.new_tabs` 转成句柄 |
| `tab.text()` `tab.screenshot()` | `GET /api/text` `/api/screenshot` |
| `web.log(user=, tab=, only=)` | `GET /api/log?user=&tab=&only=` |
| `web.bundle()` | `GET /api/log/bundle` |
| `web.upload_file()` `web.download()` | `POST /api/upload` `GET /api/download/{name}` |

**没导出去的**:`as_prompt()` 的排版、`upload()` 接受本地路径(帮你先传一次)、
`r.new_tabs` 是句柄而不是 id、以及 §2 那个 `act()` 不抛异常的取舍。
