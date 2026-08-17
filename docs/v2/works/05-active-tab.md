# 05 · tab 与 active

**一句话**:tab 的外挂模式**一字不改** —— tab 表走 API 出来,tab 条由外面画。
唯一变的是 `active`:它从 sessiond 记的一本账,变成了当前事实。

## 1. 不变的部分

v1 [works/04 §3/§4](../../v1/works/04-chrome-ui-externalization.md#3-外面画-tab-条和地址栏需要什么--cdp-给不给)
那套全部继承,一个字段都不动:

```jsonc
// GET /api/tabs
{ "tabs": [
  { "id":"t_3", "index":0, "active":true,
    "url":"https://shop.example.com/cart", "title":"购物车",
    "loading":false, "security":"secure",
    "can_go_back":true, "can_go_forward":false,
    "favicon":"/api/tabs/t_3/favicon", "opener":null },
  { "id":"t_7", "index":1, "active":false, "opener":"t_3" }
] }
```

```jsonc
// WS /api/events
{ "type":"tab.created",   "tab":{...}, "reason":"page" }
{ "type":"tab.updated",   "id":"t_7", "changed":{ "title":"订单确认" } }
{ "type":"tab.activated", "id":"t_7", "previous":"t_3" }
{ "type":"tab.closed",    "id":"t_7" }
```

形状对齐 `chrome.tabs`,`reason` 分得清是 API 开的、页面开的还是人开的,
`opener` 来自 `targetInfo.openerId`。**tab 表就是浏览器的 target 表**这句承诺
([v1/works/06](../../v1/works/06-tab-sync.md))在 v2 里完全一样地成立 ——
因为它本来就只依赖 CDP,和画面从哪来无关。

## 2. `active` 从两份真相合成一份

v1 [works/04 §4.1](../../v1/works/04-chrome-ui-externalization.md#41-当前是哪个-tab不去观测直接记账)
的原话:

> CDP 没有"tab 被激活了"这种事件。但也不用为此发明观测手段 —— **反过来做**:
> `active` 是 sessiond 自己的字段,它改完用 `Target.activateTarget` 把 Chromium 拽过来对齐。
> …所以漂移只可能来自键盘快捷键,下次进入时自愈。

这个方案是对的,但它承认了两件事:**存在两份真相**,以及**它们会漂移**。
漂移的后果在 v1 里还很隐蔽 —— API 说 active 是 A,VNC 画面上显示的是 B,
你得盯着屏幕才发现。

v2 里这个问题不是被解决了,是**不存在了**:

> **`active` 就是 screencast 挂在哪个 target 上。**

本轮实测(2026-08-17,Chromium 151,`--headless=new`):

| 量的是什么 | 结果 |
| --- | --- |
| A / B / C 三个 tab 同时 `Page.startScreencast`,前台是 C | 2 秒内 A=0 帧,B=0 帧,**C=41 帧** |
| 对后台的 A 开着 screencast 干等 | 1 秒 **0 帧** |
| 然后 `Target.activateTarget(A)` | 后续 1 秒 **20 帧** |

**后台 tab 不产帧**。这不是缺陷,是正确行为 —— 没人看的东西不该占带宽,
v1 的 VNC 是整块屏一直在那儿,想省都省不掉。

由此:

- 没有 activate 就没有帧,**帧本身就是 active 的证据**
- 漂移在物理上不可能:真漂了就是**黑屏**,立刻可见,而不是悄悄不一致
- v1 §4.1 那套"下次进入时对齐一次"的自愈逻辑,连同它的注释一起删掉

`Target.activateTarget` 仍然要发 —— 它从"把记的账同步给 Chromium"变成了
"**让帧流起来的那条命令**"。同一个调用,完全不同的地位。

## 3. 切 tab 是把 screencast 搬过去

```
Page.stopScreencast(旧 target)
Target.activateTarget(新 target)
Page.startScreencast(新 target)
```

本轮实测的首帧延迟:

| 切换 | 首帧 |
| --- | --- |
| C → A | 39 ms |
| A → B | 22 ms |
| B → C | 24 ms |
| C → B | 14 ms |

**14 – 39 ms**,人感觉不到。

### 为什么不用"常开"那种写法

还有一种更省事的写法:所有 tab 的 screencast 一直开着,切 tab 只发 `activateTarget`,
反正后台不产帧。实测它也成立,延迟一样是 16 – 30 ms,旧 tab 最多漏一帧尾巴。

**但还是选显式 stop/start**,理由只有一条:

> 常开那种写法把正确性**押在"后台 tab 不产帧"这条实现细节上**。
> 那是 Chromium 的渲染器节流策略,不是 CDP 的契约 —— 它变了,我们会同时收到几路帧,
> 而且是静默地多花带宽。显式 stop/start 在那种情况下依然正确。

延迟没有差别,那就选不押注的那个。

### 残帧要丢

`stopScreencast` 之后管道里还可能有旧 tab 的帧。这就是 [02 §1](02-frame-protocol.md#1-为什么是二进制头不是-json)
里 28 字节头带 `targetId` 和 `castSessionId` 的用处:**客户端对不上就丢**,
不能让上一个 tab 的画面闪一下。

## 4. popup 不再是特殊情况

v1 有一整篇 [works/07](../../v1/works/07-popup-windows.md) 讨论 `window.open` 开出来的
popup —— 在 VNC 桌面里它是一个**独立的 X 窗口**,不在 tab 条上,画面上会盖住主窗口,
要不要"转化成 tab"是个没有好答案的问题。

v2 里 popup 就是一个 `type=page` 的 target:有 `openerId`,能 attach,能 activate,
能 screencast。**和普通 tab 没有任何区别**,它进 tab 表,`reason` 是 `page`,
`opener` 指向开它的那个。窗口这个概念在 headless 里根本不存在。

> **待验**:本轮探针写到这一项时收工了。落地前要确认三件事 ——
> `window.open` 出来的 target 类型确实是 `page`、`openerId` 确实指向 opener、
> 对它 `startScreencast` 确实能拿到帧。前两条 v1 已经在用(`opener` 字段),
> 第三条是新的。

## 5. 一个 session 一份画面

不做"每个观看者各看各的 tab"。

它技术上可行(每个观看者一条 screencast),但代价很高:`active` 立刻退回成
per-观看者的状态,tab 条要按观看者渲染,`tab.activated` 事件要带上是谁切的,
`Target.activateTarget` 只有一个前台却要服务多个观看者 —— 而后台不产帧,
第二个观看者只能看黑屏。**要绕过这条就得回到"押注后台产帧"那条路上。**

所以:**一个 session 一份画面,所有观看者看同一个 tab**,和 v1 的 VNC 一样,
和 tmux 多个 client attach 同一个 session 一样。要各看各的,就开两个 session
—— 那本来就是两件不同的工作([07 §3](07-runtime.md#3-一机多开天然成立))。

## 6. ↔ 别处

| | |
| --- | --- |
| tab 的一进一出 | [v1/works/06](../../v1/works/06-tab-sync.md) —— **原样有效** |
| 被删掉的那节 | [v1/works/04 §4.1](../../v1/works/04-chrome-ui-externalization.md#41-当前是哪个-tab不去观测直接记账) |
| 被作废的那篇 | [v1/works/07](../../v1/works/07-popup-windows.md) |
| 帧头为什么带 targetId | [02 §1](02-frame-protocol.md#1-为什么是二进制头不是-json) |
