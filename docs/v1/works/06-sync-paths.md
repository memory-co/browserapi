# 06 · 两条路径:外面那条 bar 怎么和浏览器联动

[04](04-chrome-ui-externalization.md) 说了**为什么**要把 tab 条和地址栏挪到外面,
这篇说**怎么让它们和里面那个 Chrome 保持一致**。

一进一出两条路径:

| | 谁触发 | 怎么走 |
| --- | --- | --- |
| **IN** | `tab.click("登录")`、外面 bar 上点「切 tab」/ 输网址 / 后退 | 命令 → sessiond → CDP → Chrome |
| **OUT** | 人在**画面里**点链接、滚动、提交表单 | Chrome → CDP 事件 + 注入脚本 + VNC tee → sessiond → WS |

**关键的切分不是「lib vs 人」,是「Chrome UI vs 页面内容」。**

因为 Chrome 自带的 UI 被裁掉了([04 §2](04-chrome-ui-externalization.md)),
人能碰到的浏览器 UI 只剩你在外面画的那条 bar —— 而那条 bar 是普通 HTML,
它发的是 `POST /api/tabs/{id}/activate`,和 `tab.activate()` 一模一样。

**所以「人操作浏览器 UI」根本不需要第三条路径,它就是 IN。** 只有人在页面像素里干的事
才需要 OUT 那套抓回来。这是外化换来的最大好处,比省掉一条 UI 还值。

## 1. 全景

```
   你的代码              你画的 tab 条 / 地址栏
   tab.click(...)        [●购物车][订单确认]  ← → ⟳ shop.example.com
        │                        │
        │  HTTP                  │  HTTP        ← 同一组端点,没有第二套
        └────────┬───────────────┘
                 ▼
   ┌─ sessiond ──────────────────────────────────────────┐
   │                                                     │
   │   ①  一个动作锁 → 定位 → 派发                        │──CDP──► Chrome
   │                                                     │           │
   │   ③  一个状态模型 + 一个 seq 计数器                  │           │
   │        ▲       ▲        ▲                           │           │
   │        │       │        │                           │           │
   │      CDP事件  binding  VNC tee   ② ◄────────────────┼───────────┘
   │        │                                            │
   │        └──► WS /api/events ──► lib 的内存 / 你的 bar │
   └─────────────────────────────────────────────────────┘
                                     ▲
                             人的鼠标键盘 ──► KasmVNC ──► X ──► Chrome
```

① 是 IN(§2),② 是 OUT(§3),③ 是两条路的合流点(§4)。

## 2. IN —— 命令怎么进去

### 2.1 一次 `tab.click("登录")` 的完整链路

```
lib                sessiond                                   Chrome
 │ POST /api/act
 │ {tab, actions, user, note}
 │──────────────►│
 │               │ 1. 取动作锁(占着就 409 busy)
 │               │ 2. 人刚动过?→ 409 busy_human
 │               │ 3. 拉可访问性树 ─────────────────────────► Accessibility.getFullAXTree
 │               │ 4. 按定位规则筛 → 命中一个 / 抛 candidates
 │               │ 5. 滚进视口 ────────────────────────────► DOM.scrollIntoViewIfNeeded
 │               │    取盒模型算中心点 ─────────────────────► DOM.getBoxModel
 │               │ 6. 派发 ────────────────────────────────► Input.dispatchMouseEvent
 │               │ 7. settle(network_idle / dom_idle)
 │               │ 8. 算 after.changed、拍照、写日志(seq++)
 │               │ 9. 更新状态模型 → 发 tab.updated / action.done
 │◄──────────────│    返回 results
 │ 回灌内存
```

**第 8 步在第 9 步之前**:日志和事件是同一次状态变更的两个出口,不会出现
"事件说 URL 变了但日志里没有这一条"。

### 2.2 为什么后台 tab 也点得到

`Input.dispatchMouseEvent` 是**发给某个 target 的**,不是发给屏幕的。
sessiond 对每个 tab 都有一条 CDP session(`Target.setAutoAttach` + `flatten`),
所以动作投递不经过窗口焦点,后台 tab 照样能点。

代价是**人在 VNC 里看不见**(画面只显示激活的那个),所以这类动作在日志里标
`background: true`([api/README §2](../api/README.md#2-一条贯穿全局的规则tab-参数))。

### 2.3 外面那条 bar 上的操作走的是同一条路

| 人在 bar 上干的 | 发的请求 | CDP |
| --- | --- | --- |
| 点另一个 tab | `POST /api/tabs/{id}/activate` | `Target.activateTarget` |
| 地址栏敲回车 | `POST /api/tabs/{id}/goto` | `Page.navigate` |
| ← → ⟳ | `POST /api/tabs/{id}/back` `/forward` `/reload` | `Page.navigateToHistoryEntry` / `reload` |
| ＋ 新建 | `POST /api/tabs` | `Target.createTarget` |
| × 关闭 | `DELETE /api/tabs/{id}` | `Target.closeTarget` |

**一行都不是为人单独写的。** 你画的 bar 和 `tab.activate()` 打的是同一个端点,
所以两边永远不会有行为差异 —— 这是"没有第二套实现"在 UI 层的兑现。

### 2.4 一个例外:`reorder` 不进 Chrome

CDP **没有**"把某个 tab 在 tab 条里挪个位置"的命令。

所以 `index` 和顺序是 **sessiond 自己维护的一个列表**,`POST /api/tabs/reorder`
只重排这个列表,Chrome 真正的 tab 条纹丝不动 —— 反正它被裁掉了,没人看得见。

**已知的后果**:人按 `Ctrl+Tab` 时,Chrome 按**它自己的**顺序切,不是你 bar 上的顺序。
拖过序之后,`Ctrl+Tab` 的下一个可能不是你 bar 上的下一个。
v1 接受这个不一致 —— 修它得去模拟 `Ctrl+Shift+PgUp/PgDn`,不值。

## 3. OUT —— 状态怎么出来

人在画面里点了一下,输入是 **VNC → X → Chrome** 直接进去的,**sessiond 不在这条链路上**。
所以状态只能事后抓。三个来源,各管一摊:

| 字段 / 事件 | 来源 |
| --- | --- |
| tab 新建 / 关闭 | CDP `Target.targetCreated` / `targetDestroyed` |
| url / title | CDP `Target.targetInfoChanged`、`Page.frameNavigated`、`navigatedWithinDocument`(SPA) |
| loading | CDP `Page.frameStartedLoading` / `frameStoppedLoading` |
| can_go_back / forward | CDP `Page.getNavigationHistory` —— **没有事件,每次导航后拉一次** |
| security | CDP `Security.securityStateChanged` |
| crashed | CDP `Inspector.targetCrashed` |
| favicon | 注入脚本读 `link[rel~=icon]`,sessiond 代抓并缓存 |
| **当前激活的是哪个 tab** | 注入脚本 `visibilitychange` |
| **滚动位置** | 注入脚本 `scroll` |
| **人点了什么** | 注入脚本 `pointerdown`(捕获阶段)|
| **人到底动没动** | VNC tee |

### 3.1 注入脚本:CDP 拿不到的那几样

```
Page.addScriptToEvaluateOnNewDocument({ source, worldName: "webmuxd" })
        ↓  每次导航自动重装,跑在独立世界
   页面里: addEventListener("visibilitychange" | "scroll" | "pointerdown")
        ↓  回程
   Runtime.addBinding({ name: "__webmuxd", executionContextName: "webmuxd" })
        ↓
   sessiond 收到 Runtime.bindingCalled
```

两个点值得说:

- **独立世界(`worldName`)**,不是主世界。页面的 CSP 管不着它,页面的 JS 也看不见它 ——
  既不会被 CSP 拦,也不会被检测到、被覆盖掉。
- **`Runtime.addBinding` 是回程**。页面调 `__webmuxd(payload)`,sessiond 就收到一条
  `Runtime.bindingCalled`。不用轮询、不用 `Runtime.evaluate` 反复问。

**节流是必须的**,`scroll` 一秒能烧 60 次:

| 信号 | 节流 |
| --- | --- |
| `scroll` | rAF 合并 + 最多 100ms 上报一次,且位移 < 8px 不报 |
| `visibilitychange` | 不节流(低频且要快) |
| `pointerdown` | 不节流,但只报一条摘要(role/name/坐标),不报整棵树 |

滚动位置**不进 `tab.*` 事件**(那是给 tab 条用的,滚动跟 tab 条无关),
它进 `observe()` 的 `page.scroll`,和一条低频的 `page.scrolled` 事件。

### 3.2 VNC tee:人到底动没动

**为什么不能只靠注入脚本**:CDP 的 `Input.dispatchMouseEvent` 派发出来的事件
在页面里 **`isTrusted === true`** —— 和真人点的一模一样。
页面脚本**分不出**这一下是人点的还是 API 点的。

两条办法,都要:

1. **相关性**:sessiond 知道自己刚派发了什么。注入脚本报上来的输入,
   如果落在"我刚发的那一下"的时间窗和坐标附近,就是 API 的;否则是人的。
   够用,但边界模糊。
2. **VNC tee**(权威):人的输入本来就是以 VNC 协议消息的形式经过容器的。
   让 `/vnc/` 这条 websocket **穿过 sessiond** 再到 KasmVNC,sessiond 就能旁路看到
   `PointerEvent` / `KeyEvent`。这条不依赖页面、不依赖注入,PDF 预览页、
   `about:blank`、任何页面都成立。

`human.active` / `busy_human` 的让路窗口([api/README §5](../api/README.md#5-人在操作时的让路))
以 **2** 为准;日志里"人点了什么"用 **1** 补上元素身份,
拿不到就退回坐标(`👤 人点了 (612,340)`)。

> **这条要改 [01](01-container.md) 的拓扑**:现在是 `nginx → KasmVNC`,
> 要变成 `nginx → sessiond → KasmVNC`。代价是 VNC 流量多一跳转发。

### 3.3 特权页面被 ban 之后,这条路没有盲区

注入脚本进不去的页面 = 特权页面(`chrome://` 那一类),而它们**被禁掉了**
([api/tabs.md §5](../api/tabs.md#5-当前是哪个-tab怎么来的))。

所以「当前是哪个 tab」和「滚到哪了」**永远由事件驱动,没有轮询兜底、不会慢半拍**。
人用 `Ctrl+H` 捅出来一个,sessiond 把那个 tab 导回 `about:blank`,并记一条
`user: "human"` 的日志。

## 4. 合流:一个状态模型,一个 `seq`

两条路径最后写进**同一个状态模型**,由 sessiond **单写者**持有:

```
IN 的结果 ──┐
            ├──► 状态模型(tab 表 + viewport + busy)──► seq++ ──► WS 事件
OUT 的信号 ─┘                                            └────► 操作日志
```

三条规矩:

1. **先改模型 → 再发事件 → 最后返回 HTTP 响应。** 所以 `act` 响应里的 `after`
   和 WS 上那条 `tab.updated` 是**同一次变更的两个出口**,值相同。
2. **同一次变更从两条路到达是幂等的。** lib 拿响应先回灌内存,过一会儿 WS 那条到了,
   合并进去值没变 —— 不闪、不回退([sdk/README §3](../sdk/README.md#3-tab-的状态在内存里))。
3. **`seq` 全局单调。** 断线重连带 `?after=`;补不上就发 `gap`,收到 `gap`
   就得重新拉全量([api/events.md §1](../api/events.md#1-信封))。

### 竞态举例

**人点链接开了新 tab,同一时刻 lib 正在 observe:**

```
t0  人点了 <a target=_blank>          → Chrome 开新 target
t1  Target.targetCreated              → 模型加一行,seq=118 tab.created(reason=link_target_blank)
t2  visibilitychange 上报             → seq=119 tab.activated
t3  lib 的 GET /api/observe 返回      → tabs 数组里已经有它了(读的是同一个模型)
```

observe 的 `tabs` 和 WS 事件不会互相打架,因为它们读的是同一份东西。

**lib 要点东西,人正在动:**

```
t0  人在画面里点了一下   → VNC tee → human.active,让路窗口开始(默认 3000ms)
t1  lib POST /api/act    → 409 busy_human {retry_after_ms: 2400}
t3  lib 自己决定等不等   → SDK 不替你 sleep
```

## 5. 有意不同步的东西

| 不同步 | 为什么 |
| --- | --- |
| 鼠标位置、hover | 高频、无状态价值,画 bar 用不上 |
| 人打字的逐字内容 | 太吵,而且可能是密码 |
| 表单中间态 | 要用就 `observe()` 现取 |
| Chrome 真实的 tab 顺序 | 见 §2.4 |
| 加载进度百分比 | CDP 没有,只能转圈 |

原则:**tab 条和地址栏画得出来的才同步**,别的现要现取。
这条界线和 lib 内存里那份表是同一条([sdk/README §3](../sdk/README.md#3-tab-的状态在内存里))。

## 6. 待实测

`kasmweb/chromium:1.18.0` 上还没验的几条,按风险排:

| # | 要验的 | 怎么验 | 不成立的话 |
| --- | --- | --- | --- |
| 1 | `worldName` 独立世界里能不能拿到 `visibilitychange` | 开一个 CSP 严格的站,切 tab 看有没有 `bindingCalled` | 退回主世界注入,CSP 站上失准 |
| 2 | `Runtime.addBinding` 在 `worldName` 下的绑定时机 | 导航后立刻滚动,看第一条报不报得上来 | 每次 `Page.frameNavigated` 后补一次 `addBinding` |
| 3 | VNC 穿 sessiond 转发的延迟代价 | 对比直连 KasmVNC 的手感 | 退回 §3.2 的相关性办法,精度差一点 |
| 4 | `Input.dispatchMouseEvent` 投给后台 target 是否真的不抢焦点 | 后台 tab 点一下,看画面动没动 | 后台动作改成先 activate 再点,并在日志标出来 |
| 5 | `crop_top` 变化(书签栏、全屏)能不能被 `outerHeight-innerHeight` 及时抓到 | `Ctrl+Shift+B` 开书签栏 | 加一个低频轮询兜底 |

前两条决定 OUT 路径成不成立,应该最先做。
