# 页面上的动作与观测

两个端点:**看**(`GET /api/observe`)和 **做**(`POST /api/act`)。
两个都是**页面级**的,接受可选的 `tab` 参数([README §2](README.md#2-一条贯穿全局的规则tab-参数))。

设计目标:一次 `observe` 返回的东西**直接能喂给多模态模型**,调用方零解析。

操作日志在 [log.md](log.md)。Python 侧这两件事都挂在 `Tab` 上 ——
[sdk/tab/input.md](../sdk/tab/input.md) 和 [sdk/tab/read.md](../sdk/tab/read.md)。

## 1. `GET /api/observe` —— 看

```
GET /api/observe?tab=t_3&annotate=true&viewport_only=false&max_elements=150
```

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `tab` | 当前激活 | 观测哪个 tab |
| `annotate` | `true` | 截图上是否画元素编号框(Set-of-Mark) |
| `viewport_only` | `false` | 只要视口内的元素,压体积 |
| `max_elements` | `150` | 上限,超出按"视口内 → 离视口远近"排序截断 |
| `text` | `digest` | `none` / `digest`(前 4000 字) / `full` |

```jsonc
{
  "observation_id": "obs_01J9X...",
  "tab": "t_3",
  "at": "2026-08-08T14:22:31.412Z",

  "page": {
    "url": "https://shop.example.com/checkout",
    "title": "结算",
    "loading": false,
    "scroll": { "y": 1240, "max_y": 4820 },
    "viewport": { "w": 1024, "h": 680 }
  },

  "screenshot": {
    "url": "/api/observe/obs_01J9X.../screenshot",   // 标注版
    "plain_url": "/api/observe/obs_01J9X.../screenshot?annotate=false",
    "w": 1024, "h": 680, "format": "webp"
  },

  "elements": [
    { "id": 12,
      "role": "button",              // 可访问性 role
      "name": "提交订单",            // 可访问性名字
      "value": null,
      "bbox": [820, 612, 140, 40],   // 视口坐标 x,y,w,h
      "in_viewport": true,
      "enabled": true,
      "affords": ["click", "hover"], // 这个元素支持哪些动作
      "hint": "form#checkout > 主按钮" // 人可读定位提示,排查时有用
    },
    { "id": 13, "role": "textbox", "name": "优惠码", "value": "",
      "bbox": [420, 560, 260, 36], "in_viewport": true, "enabled": true,
      "affords": ["type", "click"], "hint": "input#coupon" }
  ],

  "text": "结算\n收货地址 ...",

  "tabs": [                          // ← 让 agent 知道有哪些 tab,见 §5
    { "id": "t_3", "index": 0, "active": true,  "title": "结算" },
    { "id": "t_7", "index": 1, "active": false, "title": "帮助中心" }
  ],

  "notes": [
    "页面有 3 个 iframe,其中 1 个跨域读不到",
    "元素被截断:实际 212 个,返回前 150 个"
  ]
}
```

### 1.1 元素表怎么筛

不能把整棵可访问性树倒给模型(几千节点,又贵又吵)。规则:

1. **可交互优先**:role 属于 button / link / textbox / checkbox / radio / combobox /
   menuitem / tab / slider…,或挂了 click 监听,或 `contenteditable`
2. **看得见**:bbox 非零、没被 `display:none`/`visibility:hidden`/零透明度藏起来、没被完全遮挡
3. **去噪**:只套一层的嵌套可点击容器合并成最内层有名字的那个;名字和 value 都空的纯装饰元素丢掉
4. **默认给整页**,但标注 `in_viewport`,让模型知道"这个要滚下去才点得到"
5. **上限 150**,截断了必须在 `notes` 里说清楚截掉了多少

> 这套规则是整个系统**最容易出质量问题的地方**。它有版本号,
> 每条日志都记录用的哪个版本,否则筛选规则一升级,历史日志里的元素编号就对不上了。

### 1.2 `notes` 是刻意的

明确告诉调用方**这次观测的盲区**:跨域 iframe 读不到、元素被截断、页面还在加载。
不说的话,模型会把"没看见"当成"不存在",然后自信地做错决定。

### 1.3 给模型的紧凑表示

`elements` 压成这样直接进 prompt(SDK 的 `obs.as_prompt()`
见 [sdk/tab/read.md §1](../sdk/tab/read.md#1-tabobserve),CLI 的 `webmuxd observe` 也是这个排版):

```
[12] button  "提交订单"
[13] textbox "优惠码" = ""
[14] link    "返回购物车"        (需下滑)
[15] button  "删除"              (禁用)
```

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
| `screenshot` | `full_page` | |
| `observe` | 同 §1 参数 | 在动作串中间插一次观测 |
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
{ "element": 12, "observation": "obs_..." }     // observe() 给的编号
{ "css": "#pay" }                               // 选择器,逃生舱
{ "point": [890, 632] }                         // 坐标,最后手段
```

**文字匹配语义**(定死,不猜):精确匹配优先 → 没有则子串匹配 → 大小写不敏感 →
仍然多于一个就返回 `404 not_found` 并列出全部候选,**绝不随便挑一个**。
要指定第几个就加 `"nth": 1`。

`js` 和 `point` 是逃生舱:能用,但日志里会标黄——因为回看时
"执行了一段 JS"和"在 (890,632) 点了一下"都看不出到底干了什么。

## 5. 动作和 tab 的接缝

tab 的增删和页面动作在这儿咬合。

**观测里带 `tabs` 数组**,所以调用方每一步都知道有哪些 tab。
点了个 `target=_blank` 的链接之后,下一次 `observe()` 里就会多一个,
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

**对非激活 tab 操作是允许的**(CDP 输入投给 target,不走屏幕焦点),
但 VNC 画面只显示激活的那个,所以人看不见。这类动作在日志里标 `background: true`。

## 6. 一个典型的循环

两个端点交替,不需要第三个:

```
GET  /api/observe            → 标注截图 + 元素表 + tab 列表 + notes
      ↓  喂给模型(图 + as_prompt 排版 + tabs + notes + 最近几条 log)
POST /api/act  { actions, note, user }
      ↓  ok:继续下一轮
         !ok:把 candidates 喂回模型自我纠正,不用重新 observe
```

`note` 带上这一步的思考,`user` 带上是谁在动,两个都落进操作日志([log.md](log.md))。
一次 `act` 执行一串动作,省掉每个动作一次往返。

写成代码见 [sdk/tab/read.md §3](../sdk/tab/read.md#3-怎么和模型接起来)。
跑的时候在观看页面里能实时看着它点。
