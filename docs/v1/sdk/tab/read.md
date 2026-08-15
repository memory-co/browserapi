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

## 2. 截图

**四种截图,别搞混:**

| 拿哪个 | 是什么 | 什么时候用 |
| --- | --- | --- |
| `tab.screenshot()` | **现拍一张**,干净的 | 存档、给人看、diff |
| `obs.screenshot` | observe 那次拍的,**画了 `[12]` 编号** | 喂多模态模型 |
| `obs.plain_screenshot` | observe 那次拍的,没画编号 | 想要同一时刻的干净版 |
| `e.shot` | **每个动作后自动拍的**,在日志里 | 回看当时长什么样,见 [../log.md](../log/) |

```python
png = tab.screenshot()                    # → bytes
tab.screenshot("cart.png")                # 给路径就写文件
tab.screenshot(full_page=True)            # 整个滚动区域,不只视口
```

**`full_page` 拍的不是人看到的东西。** 它把整页滚下来拼一张,超出视口的部分人在
VNC 画面上并没有看见。要"人看到的就是这张"就别加 `full_page` ——
这也是为什么不用 `Emulation.setDeviceMetricsOverride`
([works/01 §3](../../works/01-container.md#3-镜像)):视口就是屏幕分辨率,不做第二套。

## 3. 要像素就得切到前台

**这条同时管 `screenshot()` 和 `observe()`。**

Chromium **不渲染后台 tab**。所以对非激活 tab 要像素时,lib 会**先把它切到前台**,
拍完就在那儿(不切回去 —— 切回去等于又一次画面跳)。

```python
sess.tab("t_7").click("确认")     # 输入:不用切,人看不见,日志标 background
sess.tab("t_7").observe()         # 像素:先切过去,画面会跳,active 变成 t_7
```

**为什么不静默拍**:后台 target 拍出来大概率是空白或上一帧,
而"截图和人看到的画面对不上"正是这东西最不能出的错。

这是对早先说法的一处收窄:**「对非激活 tab 操作是可以的」只对输入成立**,
对 `observe` / `screenshot` 不成立。

## 4. 其余的读

```python
tab.text()                                # 页面正文
tab.extract(".cart-item", mode="table")   # text | html | table | attr
```

两个都发请求,**不需要切到前台**(读的是 DOM,不是像素)。
要一次拿齐就用 `observe()`,别拼三次。

## 5. 怎么和模型接起来

webmuxd 不产生思考,它只提供手和眼。循环长这样:

```python
web  = Webmuxd(user="claudecode")
sess = web.session(id="work", port=7900, view_port=6901)
tab  = sess.open("https://shop.example.com")

while True:
    obs = tab.observe()

    decision = my_llm(                      # ← 你的大脑,webmuxd 不掺和
        goal=goal,
        image=obs.screenshot,               # 图上已经画好编号
        elements=obs.as_prompt(),
        tabs=sess.tabs,                      # 免费,内存里就有
        notes=obs.notes,                    # 让它知道这次看不见什么
        history=sess.log(limit=5),
    )
    if decision.done:
        break

    r = tab.act(decision.actions, note=decision.thought)
    if not r.ok:
        feedback = r.candidates             # 喂回去自我纠正
```

`note` 把这一步的思考挂进日志([../log.md](../log/))。
跑的时候上层那个画面里能实时看着它点,人随时可以自己上手 ——
那些操作会以 `user="human"` 进同一份日志。

## 6. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `tab.observe(...)` | `GET /api/observe?tab=` |
| `obs.as_prompt()` `obs[12]` `obs.find()` | 纯客户端,不请求 |
| `tab.text()` | `GET /api/text` |
| `tab.screenshot(full_page=)` | `GET /api/screenshot?full_page=` |
| `obs.screenshot` / `obs.plain_screenshot` | `GET /api/observe/{id}/screenshot[?annotate=false]` |
| `e.shot` | `GET /api/log/{seq}/shot`,见 [../log.md](../log/) |
| 要像素时自动切前台 | 客户端做的:先 `POST /api/tabs/{id}/activate` |
| `tab.extract(loc, mode=)` | `POST /api/act` 的 `extract` 动作 |

**没导出去的**:`as_prompt()` 的排版、`obs[12]` 下标、`obs.find()`。
