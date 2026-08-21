# 页面上的动作与读

**做**是 `POST /api/act`;**读**只有两个口子,而且都直接回字节,不是 JSON。
三个都是**页面级**的,接受可选的 `tab` 参数([README §2](README.md#2-一条贯穿全局的规则tab-参数))。

操作日志在 [log.md](log.md)。Python 侧这几件事都挂在 `Tab` 上 ——
[sdk/tab/input.md](../sdk/tab/input.md) 和 [sdk/tab/read.md](../sdk/tab/read.md)。

## 1. 读 —— 一张图和正文

```
GET /api/screenshot?tab=t_3&full_page=false     → image/webp
GET /api/text?tab=t_3                           → text/plain
```

就这么多。

> **这儿以前是 `GET /api/observe`**:一次调用回一整包 —— 筛过的元素表、
> 编好的号、一次观测的 id、盲区 notes、页面信息、截图、正文。砍了。
>
> 判据是这项目那句老话:**tmux 会做这个吗?** 它有 `capture-pane`,
> 就是这两样;它没有"把屏幕上的东西筛一遍编上号再给你"。那是一套
> **关于 agent 该怎么用浏览器的意见** —— 意见该留在调用方那边。
>
> 元素表没消失,它在**定位**那一侧(§4):`{"text": "登录"}` 就是拿它做的。
> **它是动作的一部分,不是一个读的口子。**

### 1.1 出图的两个地方

| 端点 | 是什么 |
| --- | --- |
| `GET /api/screenshot?full_page=` | **现拍一张** |
| `GET /api/log/{seq}/shot` | 每个动作后自动拍的,见 [log.md](log.md) |

`full_page` 拍的是整个滚动区域,**不是人在画面上看到的东西** ——
要"所见即所得"就别带它。

### 1.2 要像素就得切到前台

Chromium **不渲染后台 tab**,所以 `screenshot` 对非激活 tab 会**先切过去**。
`text` 不用切(读的是 DOM,不是像素)。

> 它一声不吭地切,而且不和 `act` 排队 ——
> 已知的口子,见 [issue](../../v2/issues/读一眼会改状态却不排队.md)。

## 2. `POST /api/act` —— 做

```jsonc
{
  "tab": "t_3",                    // 可选,默认当前激活的 tab
  "actions": [
    { "type": "click", "text": "登录" },
    { "type": "type",  "label": "手机号", "text": "13800000000" },
    { "type": "key",   "key": "Enter" }
  ],
  "settle": { "strategy": "network_idle", "timeout_ms": 5000 },
  "note": "购物车里已有一张票,现在去确认支付",    // ← 见 §6
  "user": "claudecode"                            // ← 署名,见 §6.1
}
```

**串行执行,遇错即停。** 返回每个动作的独立结果:

```jsonc
{ "results": [
    { "ok": true, "ms": 412,
      "hit": { "role": "button", "name": "登录", "bbox": [820,612,140,40],
               "hint": "header > 登录按钮" },
      "after": { "url": "https://shop.example.com/login",
                 "changed": "出现『请输入手机号』",
                 "new_tabs": [] },
      "shot": "/api/log/42/shot" },
    { "ok": true, "ms": 88 },
    { "ok": true, "ms": 1240, "after": { "url": ".../home" } }
  ],
  "log_from": 42 }                  // 这批动作在操作日志里的起始 seq
```

出错时那一条:

```jsonc
{ "ok": false, "error": "not_found", "message": "找不到「提交订单」",
  "candidates": [ { "role":"button", "name":"提交订单(2)", "hint":"..." },
                  { "role":"link",   "name":"订单" } ] }
```

**`candidates` 是刻意设计的**:定位失败时把最像的三个塞回来,
模型有机会自我纠正,排查时也能一眼看出是页面变了还是识别错了。

### 2.1 `after.changed` 是一句人话

「出现『订单已提交』」比「DOM 变了 34 个节点」有用一百倍。
由启发式生成:新出现的最大文本块 / 消失的表单 / 新的 `role=alert`。
它是日志里最有信息量的一列。

### 2.2 `settle` —— 动作完成后等多久

| strategy | 含义 |
| --- | --- |
| `none` | 不等,立刻返回 |
| `dom_idle` | DOM 300ms 没变化 |
| `network_idle` | 在飞请求数为 0 **且** DOM 静默(默认) |
| `selector` | 等某个选择器出现,配 `wait_for` |

等太短会拍到加载中的白屏(日志全是白图),等太长吞吐塌陷。默认上限 5s。

## 3. 动作表

| 动作 | 参数 | 说明 |
| --- | --- | --- |
| `goto` | `url`, `wait` | 也可用 tabs 接口 |
| `back` / `forward` / `reload` / `stop` | — | |
| `click` | 定位 + `button`, `count`, `modifiers` | |
| `hover` | 定位 | |
| `type` | 定位 + `text` \| `text_ref`, `clear`, `delay` | |
| `key` | `key`, `modifiers` | `"Enter"` `"Escape"` `"Control+a"` |
| `clear` | 定位 | |
| `select` | 定位 + `value` \| `label` | 下拉框 |
| `check` | 定位 + `checked` | 勾选框 / 单选 |
| `upload` | 定位 + `file_id` | 配 `POST /api/upload` |
| `scroll` | `dy` \| `to`(定位) | 滚动或滚到某元素 |
| `drag` | `from`, `to` | |
| `wait_for` | `text` / `css` / `url_contains` / `ms` | |
| `extract` | 定位 + `mode`:`text`/`html`/`table`/`attr` | 取数据 |
| `screenshot` | `full_page` | 非激活 tab 会先被切到前台 |
| `tab_new` / `tab_activate` / `tab_close` | `url` / `id` | **见 §5** |
| `js` | `expression` | 逃生舱,日志标黄 |

### 3.1 凭证

```jsonc
{ "type": "type", "label": "密码", "text_ref": "secret://vault/shop/pwd" }
```
明文只在 sessiond 内部出现一次。**日志、事件、截图里一律 `••••••`**。
`input[type=password]` 里输入的内容自动打码,不用你标。

## 4. 定位

按能用就行的顺序,五种写法:

```jsonc
{ "text": "提交订单" }                          // 可见文字,最常用
{ "role": "button", "name": "登录" }            // role + 名字,消歧
{ "label": "手机号" }                           // 表单标签找输入框
{ "css": "#pay" }                               // 选择器,逃生舱
{ "point": [890, 632] }                         // 坐标,最后手段
```

**文字匹配语义**(定死,不猜):精确匹配优先 → 没有则子串匹配 → 大小写不敏感 →
仍然多于一个就返回 `404 not_found` 并列出全部候选,**绝不随便挑一个**。
要指定第几个就加 `"nth": 1`。

**没有"按编号定位"。** 编号只在一次快照里成立,而快照是每次 `act` 自己抓的、
不对外 —— 拿上一次的编号来点,点到的可能是另一个东西,**而且不报错**。
候选里回的 `role` + `name` 才是**跨快照仍然成立**的说法,重试拿那两样。

> 以前有 `{"element": 12, "observation": "obs_..."}`,靠"这个编号是哪次观测的"
> 来挡陈旧编号。`observe` 砍掉之后没有"一次观测"了,那道挡板没了落点 ——
> **留着键而挡不住,比没有这个键更坏。**

### 4.0 元素表怎么筛

定位要先有一张元素表。不能把整棵可访问性树倒给模型(几千节点,又贵又吵),
所以有这几条 —— **它们现在只服务定位,不再出现在任何响应里**:

1. **可交互优先**:role 属于 button / link / textbox / checkbox / radio / combobox /
   menuitem / tab / slider…,或挂了 click 监听,或 `contenteditable`
2. **看得见**:bbox 非零、没被 `display:none`/`visibility:hidden`/零透明度藏起来、没被完全遮挡
3. **去噪**:只套一层的嵌套可点击容器合并成最内层有名字的那个;名字和 value 都空的纯装饰元素丢掉。
   **但这条只管靠"可聚焦"混进来的东西** —— 真正的表单控件(checkbox / textbox / 这类
   role 明确的)即使没有标签也留着,一个裸 checkbox 你照样得能勾它
4. **上限 150**,超出按"视口内 → 离视口远近"排序截断

> 这套规则是整个系统**最容易出质量问题的地方**。它有版本号,
> 每条日志都记录用的哪个版本 —— 否则筛选规则一升级,历史日志里的编号就对不上了。

### 4.1 `text` 什么时候是定位,什么时候是内容

**这两种用法撞在同一个键上**,实现时才发现规格没点破:

```jsonc
{ "type": "click", "text": "提交订单" }                      // text = 点哪个
{ "type": "type",  "label": "手机号", "text": "13800000000" } // text = 输什么
```

**规则:`type` 动作的 `text` 是内容,不参与定位**,它的定位只看
`label` / `role`+`name` / `css` / `point`。其余动作的 `text` 是定位。

一个动作要是既需要定位又需要文本内容,就只能这么切 —— 换个键名(比如 `value`)
会和 `select` 的 `value` 再撞一次。

`js` 和 `point` 是逃生舱:能用,但日志里会标黄——因为回看时
"执行了一段 JS"和"在 (890,632) 点了一下"都看不出到底干了什么。

## 5. 动作和 tab 的接缝

tab 的增删和页面动作在这儿咬合。

**观测里带 `tabs` 数组**,所以调用方每一步都知道有哪些 tab。
点了个 `target=_blank` 的链接之后,下一次 `GET /api/tabs` 里就会多一个,
`after.new_tabs` 也会当场告诉你:

```jsonc
{ "ok": true, "hit": { "name": "查看帮助" },
  "after": { "url": "...", "new_tabs": [ { "id":"t_7", "url":"...", "title":"帮助中心" } ] } }
```

**动作串里可以切 tab**,不用拆成多次请求:

```jsonc
{ "actions": [
    { "type": "click", "text": "查看帮助" },       // 冒出新 tab
    { "type": "tab_activate", "id": "$new" },      // $new = 上一个动作新开的
    { "type": "click", "text": "联系客服" },       // 在新 tab 里点
    { "type": "tab_close" },                        // 关掉,回到原来那个
] }
```

`$new` 这个占位符省掉了"先请求一次拿到 id 再发第二次请求"的往返。
没有新 tab 时用 `$new` 会返回 `400 bad_request`。

**对非激活 tab 的输入是允许的**(CDP 输入投给 target,不走屏幕焦点),
但 VNC 画面只显示激活的那个,所以人看不见。这类动作在日志里标 `background: true`。

**要像素的不行**:Chromium 不渲染后台 tab。`GET /api/screenshot`
以及动作串里的 `screenshot` 指向非激活 tab 时,**先切前台再拍**,
响应带 `activated: true`。见 [README §2](README.md#2-一条贯穿全局的规则tab-参数)。

## 6. 一个典型的循环

两个端点交替,不需要第三个:

```
GET  /api/screenshot         → 一张图        GET /api/text → 正文
      ↓  喂给模型(图 + as_prompt 排版 + tabs + notes + 最近几条 log)
POST /api/act  { actions, note, user }
      ↓  ok:继续下一轮
         !ok:把 candidates 喂回模型自我纠正(拿 role + name 重试)
```

`note` 带上这一步的思考,`user` 带上是谁在动,两个都落进操作日志([log.md](log.md))。
一次 `act` 执行一串动作,省掉每个动作一次往返。

写成代码见 [sdk/tab/read.md §3](../sdk/tab/read.md#4-怎么和模型接起来)。
跑的时候上层那个画面里能实时看着它点。
