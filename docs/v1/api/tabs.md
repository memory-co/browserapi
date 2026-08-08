# tab bar 接口

给"在外面自己画一条 tab 条和地址栏"用的全部接口。
形状对齐 `chrome.tabs` 扩展 API —— 写过 Chrome 扩展的人零学习成本。

背景见 [works/04](../works/04-chrome-ui-externalization.md):Chrome 自带的 tab 条和地址栏
被 iframe 裁掉了,这套接口是它们的替代品。

## 1. Tab 对象

```jsonc
{
  "id": "t_3",                                   // 稳定,tab 活着就不变
  "index": 0,                                    // 在 tab 条里的位置
  "active": true,
  "url": "https://shop.example.com/cart",
  "title": "购物车",
  "loading": false,
  "security": "secure",                          // secure | insecure | neutral | broken
  "can_go_back": true,
  "can_go_forward": false,
  "favicon": "/api/tabs/t_3/favicon",            // null 表示还没拿到
  "opener": null,                                // 从哪个 tab 开出来的
  "created_at": "2026-08-08T14:22:01.402Z",
  "crashed": false
}
```

字段够画一条完整的 tab 条和地址栏了。**两个拿不到的**:

- **加载进度百分比** —— CDP 没有。只能画转圈,画不了进度条。
- **是否在放声音 / 静音** —— CDP 没有直接支持,v1 不做。

## 2. 读

### `GET /api/tabs`

```jsonc
{ "tabs": [ /* Tab × N,按 index 排好 */ ], "active": "t_3" }
```

### `GET /api/tabs/{id}`

单个 Tab 对象。不存在返回 `404 tab_gone`。

### `GET /api/tabs/{id}/history`

画"后退按钮长按弹出历史列表"用的:

```jsonc
{ "entries": [
    { "index": 0, "url": "https://shop.example.com/",     "title": "首页" },
    { "index": 1, "url": "https://shop.example.com/list", "title": "商品列表" },
    { "index": 2, "url": "https://shop.example.com/cart", "title": "购物车" }
  ],
  "current": 2 }
```

跳到某一条用 `POST /api/tabs/{id}/goto` 带 `history_index`。

### `GET /api/tabs/{id}/favicon`

直接返回图片字节(`Content-Type` 按实际,带 `ETag` 和 `Cache-Control`)。还没拿到时 `404`。

由 **sessiond 在容器内代抓**并缓存,不是让外面的 UI 自己去抓——
目标站点可能只有容器访问得到(内网、要登录态、走代理)。

## 3. 写

### `POST /api/tabs` 新建

```jsonc
{ "url": "https://example.com",   // 可选,默认 about:blank
  "active": true,                 // 建完是否切过去,默认 true
  "index": 2,                     // 插在第几个,默认末尾
  "opener": "t_3" }               // 可选,标记来源
```
→ `201` + Tab 对象

### `POST /api/tabs/{id}/activate` 切换

切过去,**VNC 画面随之切**。→ `200` + Tab 对象

### `DELETE /api/tabs/{id}` 关闭

关最后一个 tab 时:Chrome 会连窗口一起关掉,所以 sessiond **会自动先建一个 `about:blank`**,
保证永远至少有一个 tab。响应里会带上新建的那个:

```jsonc
{ "closed": "t_7", "created": { /* Tab */ }, "active": "t_9" }
```

### `POST /api/tabs/{id}/goto` 导航

```jsonc
{ "url": "https://example.com",
  "wait": "load",              // none | domcontentloaded | load | networkidle,默认 load
  "timeout_ms": 15000 }
```
也可以用 `{ "history_index": 1 }` 跳到历史里的某条。

失败返回 `502 nav_failed`,带 `details.net_error`(如 `ERR_NAME_NOT_RESOLVED`)。

**特权页面被禁掉**,返回 `400 blocked_url`:

```
chrome://  chrome-untrusted://  devtools://  chrome-extension://  view-source:
```

`about:blank` 是允许的(新建 tab 的默认页)。

理由不是技术上做不到,是**不该做**:`chrome://settings` 里的东西该用容器的启动参数配,
让 agent 跑去点它,等于让它在你背后改浏览器配置。`devtools://` 和 `view-source:`
同理,对调用方没有价值。

### `POST /api/tabs/{id}/back` `/forward` `/reload` `/stop`

无 body。`reload` 接受 `{ "ignore_cache": true }`。
没得后退时 `back` 返回 `400 bad_request`,不是静默无操作——
这样你的按钮禁用状态和实际行为不会对不上。

### `POST /api/tabs/reorder` 拖拽排序

```jsonc
{ "order": ["t_7", "t_3", "t_9"] }
```
必须是当前全部 tab 的一个排列,少了多了都返回 `400`。

## 4. 事件

一条 WS 推全部,详见 [events.md](events.md)。tab 相关的四个:

```jsonc
{ "seq": 118, "type":"tab.created",   "tab": { /* Tab */ },
  "reason": "link_target_blank" }

{ "seq": 119, "type":"tab.updated",   "id":"t_7",
  "changed": { "title":"订单确认", "loading":false, "can_go_back":true } }

{ "seq": 120, "type":"tab.activated", "id":"t_7", "previous":"t_3" }

{ "seq": 121, "type":"tab.closed",    "id":"t_7", "active":"t_3" }
```

`tab.updated` **只发变化的字段**,外面做局部更新,不要整条替换(会闪)。

### `reason` —— 这个 tab 怎么冒出来的

| reason | 场景 |
| --- | --- |
| `api` | 你自己调 `POST /api/tabs` 建的 |
| `link_target_blank` | 页面里点了 `target="_blank"` 的链接 |
| `window_open` | 页面调了 `window.open()` |
| `ctrl_click` | 人在 VNC 里 Ctrl+点击 |
| `user_ctrl_t` | 人在 VNC 里按了 Ctrl+T |
| `restored` | Chrome 崩溃重启后恢复的 |
| `unknown` | 判不出来 —— 比如 `rel="noopener"` 的链接,它没有 `opener`,和人按 Ctrl+T 长得一样 |

**这个字段是为你的 tab 条设计的。** 比如:`api` 建的不自动切过去(脚本自己会切),
`link_target_blank` 自动切过去(符合人的预期),`user_ctrl_t` 高亮一下提示"这是人开的",
`unknown` 按不切处理 —— **判不出来时给 `unknown`,不猜**,猜错的代价是替用户切了不该切的 tab。

怎么判出来的见 [works/06 §2](../works/06-tab-sync.md#2-out--人点了-a-target_blank)。

`opener` 配合 `reason` 能画出"从哪来的"——想做成子 tab 缩进、或者加个来源小箭头都行。

## 5. 「当前是哪个 tab」是 sessiond 说了算

**不观测,记账。** CDP 不发"tab 被激活了"这种事件(Target 域只有 created /
destroyed / infoChanged / crashed,`TargetInfo` 里根本没有"是不是当前"这一项)——
所以别去猜,直接反过来:**`active` 是 sessiond 自己的一个字段,由它改,再把 Chrome 拽过来对齐。**

改它的只有三种情况,每种 sessiond 都当场知道:

| 什么时候变 | 怎么知道的 |
| --- | --- |
| `POST /api/tabs/{id}/activate` | 就是它自己执行的 |
| 新 tab 前台打开 | `Target.targetCreated`,按 `reason` 决定切不切(`ctrl_click` 不切) |
| 当前 tab 被关掉 | `Target.targetDestroyed`,焦点按规则落到邻居 |

每次变完,以及**每次有观看者接进来**(查看页面一加载就开 `WS /api/events`,
那就是"有人进来了"),sessiond 发一次 `Target.activateTarget` 把画面对齐到记录上。
已经对着就是个空操作。

这跟 tmux 是一个路子:current window 是 server 记的,client 渲染 server 说的那个,
没人去问终端"你现在显示的是哪个"。

### 会漂,但会自愈

人按 `Ctrl+Tab` / `Ctrl+1..9`,Chrome 换了 tab 而我们不知道 —— 记录说 A、画面是 B。

- **人点不到 Chrome 自己的 tab 条**(被裁在可视区外,连命中测试都进不去),
  所以漂移只来自键盘快捷键,以及绕开查看页面直连 VNC 端口的人(那种情况下
  Chrome 的原生 UI 是完整可见可点的)
- **下一次有人进来、或下一次 `activate`,就对齐回来了**

拿这点漂移换掉了一整套注入监听 `visibilitychange` 的机制,划算。

> `chrome://` 那类特权页面仍然禁(§3),但**理由不再是"注入不进去"** ——
> 是 agent 不该去改浏览器设置,那些东西该在容器启动参数里配。

新 tab 怎么被感知到,见 [works/06](../works/06-tab-sync.md)。

## 6. client

同一套东西的另外两个壳:

- **Python** —— [sdk/tabs.md](../sdk/tabs.md):tab 是**活的句柄**,而且
  `tab.url` / `web.tabs` **读内存不发请求**(靠订这条事件流维护)
- **命令行** —— [cli/tabs.md](../cli/tabs.md):`webmuxd tabs`、`select-tab`、`-F` 格式化

两边都没有本文的全部内容(favicon 字节、history、`stop` 只在 API 这层),
各自的对照表里写了缺什么。
