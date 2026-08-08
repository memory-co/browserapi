# lib · Tab · 动作

**往页面里做。** 全部导出成 `POST /api/act`([api/act.md](../../api/act.md))。

```python
tab.click("提交订单")
tab.type("手机号", "13800000000")
tab.key("Enter")
```

## 1. 定位:五种写法

按能用就行的顺序:

```python
tab.click("提交订单")                  # 可见文字(最常用)
tab.click(role="button", name="登录")  # role + 名字,消歧
tab.click(el)                          # observe() 拿到的元素对象,见 read.md
tab.click(css="#pay")                  # CSS 选择器,逃生舱
tab.click(at=(890, 632))               # 坐标,最后手段
tab.click("下一页", nth=1)             # 多个匹配时指定第几个
tab.type(label="手机号", text="138…")  # 表单标签找输入框
```

**匹配规则定死在引擎里**(跟 Chrome 一起跑在 session 内,
[api/act.md §4](../../api/act.md#4-定位)):

> 精确匹配优先 → 子串 → 大小写不敏感 → **仍然多于一个就抛 `NotFound` 并列出全部候选**

**绝不随便挑一个。**

```python
try:
    tab.click("提交订单")
except NotFound as e:
    print(e.candidates)   # [button "提交订单(2)", link "订单", button "提交"]
```

`css` 和 `at` 是逃生舱:能用,但日志里会标黄 —— 回看时"在 (890,632) 点了一下"
看不出到底干了什么。

## 2. 方法表

| 方法 | 参数 | 动作 `type` |
| --- | --- | --- |
| `tab.click(loc, button=, count=, modifiers=)` | 定位 | `click` |
| `tab.hover(loc)` | 定位 | `hover` |
| `tab.type(loc, text, clear=, delay=)` | 定位 | `type` |
| `tab.clear(loc)` | 定位 | `clear` |
| `tab.key("Enter")` `tab.key("a", modifiers=["Control"])` | — | `key` |
| `tab.select(loc, value=)` / `(loc, label=)` | 定位 | `select` |
| `tab.check(loc, checked=True)` | 定位 | `check` |
| `tab.scroll(dy=400)` / `tab.scroll(to=el)` | — | `scroll` |
| `tab.drag(a, b)` | 两个定位 | `drag` |
| `tab.upload(loc, path_or_file_id)` | 定位 | `upload`,见 §5 |
| `tab.wait_for(text=/css=/url_contains=/ms=)` | — | `wait_for` |
| `tab.js(expr)` | — | `js`,逃生舱,日志标黄 |

导航类(`goto` `back` `forward` `reload` `stop`)见 [navigate.md](navigate.md),
观测类(`observe` `screenshot` `extract`)见 [read.md](read.md) ——
它们在线上是同一张动作表里的条目,在 lib 里按用途分开放。

## 3. `act()` —— 一次往返一串动作

```python
r = tab.act([
    {"type": "click", "text": "登录"},
    {"type": "type",  "label": "手机号", "text": "13800000000"},
    {"type": "key",   "key": "Enter"},
], settle={"strategy": "network_idle", "timeout_ms": 5000},
   note="购物车里已有一张票,现在去确认支付",
   user="claudecode")
```

**串行执行,遇错即停。** `note` 是这一步的思考,`user` 是署名,两个都进日志
([../log.md](../log.md))。

```python
r.ok             # 全部成功才 True
r.results        # 每个动作一条:.ok .ms .hit .after .shot
r.failed         # 第一个失败的那条,没有则 None
r.candidates     # = r.failed.candidates,方便直接喂回模型
r.new_tabs       # [Tab] —— 这批动作开出来的新 tab,是句柄不是 id
r.log_from       # 这批动作在操作日志里的起始 seq
r.raise_()       # 想要异常语义时显式调用
```

**响应会回灌内存**:`after.url` 和 `new_tabs` 落进那张 tab 表,
所以动作返回之后 `tab.url` 立刻是新的([../README.md §3](../README.md#3-tab-的状态在内存里))。

### `act()` 不抛异常,快捷方法抛

这是 lib 里唯一一处**故意不一致**:

| | 定位失败时 |
| --- | --- |
| `tab.click(...)` `tab.type(...)` 等 | 抛 `NotFound`(带 `.candidates`) |
| `tab.act([...])` | 返回 `r`,`r.ok is False`,`r.candidates` 拿候选 |

**写脚本用快捷方法**(错了就该炸);**喂给模型的循环用 `act()`**
(错了要把候选还回去让它自我纠正,而不是被异常打断)。

### 串里切 tab

```python
tab.act([
    {"type": "click", "text": "查看帮助"},
    {"type": "tab_activate", "id": "$new"},    # $new = 上一个动作新开的
    {"type": "click", "text": "联系客服"},
    {"type": "tab_close"},
])
```

`$new` 只在 `act()` 里有,省的是"先请求拿 id 再发第二次"的往返。
快捷方法不需要它 —— `r.new_tabs[0]` 直接就是句柄。

## 4. `settle` —— 动作完成后等多久

| strategy | 含义 |
| --- | --- |
| `none` | 不等 |
| `dom_idle` | DOM 300ms 没变化 |
| `network_idle` | 在飞请求为 0 且 DOM 静默(默认) |
| `selector` | 等某个选择器出现 |

等太短会拍到加载中的白屏(日志全是白图),等太长吞吐塌陷。默认上限 5s。

## 5. 凭证和文件

```python
tab.type("密码", secret="vault/shop/pwd")     # → text_ref: "secret://vault/shop/pwd"
```

明文只在 sessiond 内部出现一次,**日志、事件、截图里一律 `••••••`**。
`input[type=password]` 自动打码,不用你标。

```python
fid = web.upload_file("/local/id.png")        # POST /api/upload → file_id
tab.upload("身份证", fid)
tab.upload("身份证", "/local/id.png")          # 也接受路径,内部先传再用

web.download("report.xlsx", to="/tmp/")
```

## 6. 一次只能跑一个

**一个 `Webmuxd` 同时只跑一个动作。** 并发调抛 `Busy`,不排队、不交错。
人在 VNC 里操作时抛 `BusyHuman`,带 `.retry_after_ms`,**lib 不自动等**
([../README.md §6](../README.md#6-并发))。

## 7. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `tab.act(actions, settle=, note=, user=, idempotency_key=)` | `POST /api/act` |
| `tab.click/type/key/select/check/scroll/...` | `POST /api/act`,一个动作 |
| `tab.click(el)` | `{"element": id, "observation": obs.id}` |
| `tab.type(loc, secret=)` | `text_ref: "secret://..."` |
| `r.new_tabs` | 由响应的 `after.new_tabs` 转成句柄 |
| `web.upload_file()` `web.download()` | `POST /api/upload` `GET /api/download/{name}` |

**没导出去的**:`upload()` 接受本地路径(帮你先传一次)、`r.new_tabs` 是句柄而不是 id、
以及 §3 那个 `act()` 不抛异常的取舍。
