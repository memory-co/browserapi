# lib · Tab · 读

**往外看,只有两样:一张图,和正文。**

```python
tab.screenshot()      # bytes —— 那一刻的页面
tab.text()            # str   —— 正文
```

导出成 `GET /api/screenshot` 和 `GET /api/text`
([api/act.md §1](../../api/act.md#1-读--一张图和正文))。

> **这儿以前有个 `observe()`**:一次调用回一整包 —— 筛过的元素表、编好的号、
> 一次观测的 id、盲区 notes、页面信息、截图、正文。砍了。
>
> 判据是这项目那句老话:**tmux 会做这个吗?** 它有 `capture-pane`,
> 就是这两样;它没有"把屏幕上的东西筛一遍编上号再给你"。
> 那是一套**关于 agent 该怎么用浏览器的意见** —— 意见该留在调用方那边,
> 不该长在这个库里。
>
> 元素表没消失,它在定位那一侧:`click("登录")` 就是拿它做的。
> **它是动作的一部分,不是一个读的口子。**

## 1. 截图

**三种,别搞混:**

| 拿哪个 | 是什么 | 什么时候用 |
| --- | --- | --- |
| `tab.screenshot()` | **现拍一张** | 存档、给人看、diff、喂多模态模型 |
| `e.shot` | **每个动作后自动拍的**,在日志里 | 回看当时长什么样,见 [../log.md](../log/) |
| 观看页那条流 | 连续的画面 | 人在看 |

```python
img = tab.screenshot()                    # → bytes(WebP)
tab.screenshot("cart.webp")               # 给路径就写文件
tab.screenshot(full_page=True)            # 整个滚动区域,不只视口
```

**WebP 不是 PNG** —— 同样画质小一半,而这条流量要走网络。

**`full_page` 拍的不是人看到的东西。** 它把整页滚下来拼一张,超出视口的部分人在
画面上并没有看见。要"人看到的就是这张"就别加 `full_page`。

## 2. 正文

```python
tab.text()                                # 页面正文
tab.extract(".cart-item", mode="table")   # text | html | table | attr
```

取的是 `innerText`,**不是 `textContent`** —— 后者会把 `<script>` 里的代码和
`display:none` 的东西一起给你。

`extract` 是[动词表](../../../v2/works/i-agent-surface.md#2-动词表)里的一个动作,
所以它走 `POST /api/act`,进日志。`text()` 不进。

## 3. 要像素就得切到前台

**这条管 `screenshot()`,不管 `text()`。**

Chromium **不渲染后台 tab**。所以对非激活 tab 要像素时,会**先把它切到前台**,
拍完就在那儿(不切回去 —— 切回去等于又一次画面跳)。

```python
sess.tab("t_7").click("确认")       # 输入:不用切,人看不见,日志标 background
sess.tab("t_7").screenshot()        # 像素:先切过去,画面会跳,active 变成 t_7
```

**为什么不静默拍**:后台 target 拍出来大概率是空白或上一帧,
而"截图和人看到的画面对不上"正是这东西最不能出的错。

> **它一声不吭地切,而且不排队。** 这是个已知的口子,
> 见 [issue](../../../v2/issues/读一眼会改状态却不排队.md)。

## 4. 怎么和模型接起来

webmuxd 不产生思考,它只提供手和眼。循环长这样:

```python
web  = Webmuxd(user="claudecode")
sess = web.session(id="work", port=7900)
tab  = sess.open("https://shop.example.com")

while True:
    decision = my_llm(                      # ← 你的大脑,webmuxd 不掺和
        goal=goal,
        image=tab.screenshot(),             # 一张图
        text=tab.text(),                    # 和正文
        tabs=sess.tabs,                     # 免费,内存里就有
        history=sess.log(limit=5),
    )
    if decision.done:
        break

    r = tab.act(decision.actions, note=decision.thought)
    if not r.ok:
        feedback = r.candidates             # 喂回去自我纠正
```

**按人看得见的文字点。** `click("提交订单")` —— 不需要先拿一张元素表再按编号点。
歧义时不会替你挑一个,而是回候选:

```python
try:
    tab.click("订单")
except NotFound as e:
    e.details["candidates"]     # [{"id":1,"role":"button","name":"提交订单",...}, ...]
    tab.click(e.details["candidates"][0])       # 拿 role + name 重试
```

**候选里那个 `id` 别拿去点。** 编号只在一次快照里成立,而快照是每次
`act` 自己抓的 —— 拿上一次的编号点,点到的可能是另一个东西。
**能跨快照成立的是 `role` + `name`**(必要时加 `nth`),
所以 `tab.click(候选)` 只取那两样。

`note` 把这一步的思考挂进日志([../log.md](../log/))。
跑的时候上层那个画面里能实时看着它点,人随时可以自己上手 ——
那些操作会以 `user="human"` 进同一份日志。

## 5. ↔ API 对照

| lib | 导出成 |
| --- | --- |
| `tab.screenshot(full_page=)` | `GET /api/screenshot?full_page=` |
| `tab.text()` | `GET /api/text` |
| `tab.extract(loc, mode=)` | `POST /api/act` 的 `extract` 动作 |
| `e.shot` | `GET /api/log/{seq}/shot`,见 [../log.md](../log/) |
| 要像素时自动切前台 | 服务端做的:`screenshot` 之前先 activate |
