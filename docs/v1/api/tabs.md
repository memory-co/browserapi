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

由 **agentd 在容器内代抓**并缓存,不是让外面的 UI 自己去抓——
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

关最后一个 tab 时:Chrome 会连窗口一起关掉,所以 agentd **会自动先建一个 `about:blank`**,
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

**这个字段是为你的 tab 条设计的。** 比如:`api` 建的不自动切过去(脚本自己会切),
`link_target_blank` 自动切过去(符合人的预期),`user_ctrl_t` 高亮一下提示"这是人开的"。

`opener` 配合 `reason` 能画出"从哪来的"——想做成子 tab 缩进、或者加个来源小箭头都行。

## 5. 「当前是哪个 tab」怎么来的

CDP 不发"tab 被激活了"这种事件。人在 VNC 里按 `Ctrl+Tab` 换了 tab,得靠 agentd 自己发现。

做法:用 `Page.addScriptToEvaluateOnNewDocument` 给每个 tab 注入一段监听 `visibilitychange`
的脚本,谁 `visible` 谁就是当前 tab(导航后自动重装)。

**已知盲区**:`about:`、`chrome://`、以及 CSP 严格到拦住注入的页面,脚本进不去。
这些 fallback 到轮询 `Target.getTargets`,延迟约 500ms。
表现是:切到这类页面时,你的 tab 条高亮会慢半拍。

## 6. Python lib

```python
for t in b.tabs():
    print(t.index, t.title, t.url, "●" if t.active else "")

t = b.new_tab("https://example.com")
t.goto("https://example.com/cart")
t.back(); t.reload()
t.activate()
t.close()

b.reorder(["t_7", "t_3"])

# 实时同步你自己的 tab 条
for e in b.watch("tab.*"):
    ui.update(e)
```

跨 tab 操作,`tab()` 拿到的对象上直接调页面动作:

```python
b.tab("t_7").click("确认")      # 对非激活 tab 也有效,但人在画面上看不见
```
