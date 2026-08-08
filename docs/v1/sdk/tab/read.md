# lib · Tab · 观测

**往外看。** `observe()` 是这里的主角 —— 一次调用拿到能直接喂给多模态模型的全部东西。
导出成 `GET /api/observe`([api/act.md §1](../../api/act.md#1-get-apiobserve--看))。

## 1. `tab.observe()`

```python
obs = tab.observe()

obs.screenshot             # bytes,图上已经画好 [12] [13] 编号(Set-of-Mark)
obs.plain_screenshot       # bytes,没标注的那版
obs.elements               # [Element]
obs.tabs                   # [Tab]
obs.page.url, obs.page.title, obs.page.scroll
obs.text                   # 正文,默认 digest
obs.notes                  # ["页面有 3 个 iframe,其中 1 个跨域读不到", ...]
obs.id                     # obs_01J9X... —— 按编号定位时要带上
```

参数:`tab.observe(annotate=, viewport_only=, max_elements=, text=)`。

**一定发请求。** 元素表和截图不在内存里 —— 事件流不塞大字段
([../README.md §3](../README.md#3-tab-的状态在内存里))。

### `obs.notes` 要往 prompt 里放

它写的是**这次观测的盲区**:跨域 iframe 读不到、元素被截断、页面还在加载。
不给模型看,它会把"没看见"当成"不存在",然后自信地做错决定
([api/act.md §1.2](../../api/act.md#12-notes-是刻意的))。

### `as_prompt()`

```python
print(obs.as_prompt())
# [12] button  "提交订单"
# [13] textbox "优惠码" = ""
# [14] link    "返回购物车"        (需下滑)
# [15] button  "删除"              (禁用)
```

纯排版,不请求网络。

### `Element`

```python
el = obs[12]                          # 按编号
el = obs.find(role="button", name="提交订单")
el.id  el.role  el.name  el.value  el.bbox
el.in_viewport  el.enabled  el.affords  el.hint

tab.click(el)
```

`tab.click(el)` 会自动带上 `observation` id —— **页面变了就抛 `NotFound`**,
而不是点到编号相同的另一个东西。

## 2. 只要一部分

```python
tab.text()                       # 页面正文
tab.screenshot("cart.png")       # 截图;full_page=True 要整页
tab.extract(".cart-item", mode="table")   # text | html | table | attr
```

三个都发请求。要一次拿齐就用 `observe()`,别拼三次。

## 3. 怎么和模型接起来

webmuxd 不产生思考,它只提供手和眼。循环长这样:

```python
web = Webmuxd(port=12345, token=TOKEN, user="claudecode")
tab = web.open("https://shop.example.com")

while True:
    obs = tab.observe()

    decision = my_llm(                      # ← 你的大脑,webmuxd 不掺和
        goal=goal,
        image=obs.screenshot,               # 图上已经画好编号
        elements=obs.as_prompt(),
        tabs=web.tabs,                      # 免费,内存里就有
        notes=obs.notes,                    # 让它知道这次看不见什么
        history=web.log(limit=5),
    )
    if decision.done:
        break

    r = tab.act(decision.actions, note=decision.thought)
    if not r.ok:
        feedback = r.candidates             # 喂回去自我纠正
```

`note` 把这一步的思考挂进日志([../log.md](../log.md))。
跑的时候在观看页面里能实时看着它点,人随时可以自己上手 ——
那些操作会以 `user="human"` 进同一份日志。

## 4. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `tab.observe(...)` | `GET /api/observe?tab=` |
| `obs.as_prompt()` `obs[12]` `obs.find()` | 纯客户端,不请求 |
| `tab.text()` | `GET /api/text` |
| `tab.screenshot()` | `GET /api/screenshot` |
| `tab.extract(loc, mode=)` | `POST /api/act` 的 `extract` 动作 |

**没导出去的**:`as_prompt()` 的排版、`obs[12]` 下标、`obs.find()`。
