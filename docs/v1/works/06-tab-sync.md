# 06 · tab 怎么进去,怎么出来

tab 条被挪到外面之后([04](04-chrome-ui-externalization.md)),它得和里面那个 Chrome
保持一致。只有两件事要说清楚:

- **IN** —— `web.open(url)` 怎么变成 Chrome 里一个真的 tab
- **OUT** —— 人在页面里点了个 `target="_blank"` 的链接,冒出来的那个 tab 怎么被感知到

**注意外面那条 tab 条上的「＋」不是 OUT,是 IN。** Chrome 自带的 tab 条被裁掉了,
你画的那条是普通 HTML,它点「＋」发的就是 `POST /api/tabs`,和 `web.open()` 同一个端点。
所以只有**人在页面像素里**开出来的 tab 才需要 OUT 那条路。

## 1. IN —— `web.open("https://shop.example.com")`

```
lib                      sessiond                          Chrome
 │ POST /api/tabs {url}
 │───────────────────────►│
 │                        │ 1. Target.createTarget{url} ──────►│  ← 一次调用,建 + 导航
 │                        │                    ◄── targetId ───│
 │                        │ 2. 分配 t_7,记进 id 映射表
 │                        │ 3. 附加 + 注入(见 §3)
 │                        │ 4. 写状态模型,seq++
 │                        │ 5. 发 tab.created{reason:"api"} ──► WS
 │◄───────────────────────│ 201 + Tab 对象
 │ 建句柄 tab
```

**一次请求,不是两次。** `Target.createTarget` 本来就收 `url`,
所以 `POST /api/tabs {url}` 一步到位,不用建完再 `goto`。

**`t_7` 是 sessiond 分配的,不是 CDP 的 `targetId`。** CDP 那个是 32 位 hex,
对调用方没意义,而且 Chrome 崩溃重启后会全变。sessiond 维护一张映射表:

| 对外 | CDP | 生命周期 |
| --- | --- | --- |
| `t_7` | `4F1A...C2` | tab 活着就不变;关掉后**不复用**这个号 |

不复用是为了让日志和历史观测里的 `t_7` 永远指同一个东西 —— 回看时不会张冠李戴。

**第 5 步的事件照发。** 哪怕这个 tab 是 API 自己建的,也走同一条 WS 出去 ——
这样你的 tab 条不用管是谁开的,照单全收就行。

## 2. OUT —— 人点了 `<a target="_blank">`

人的鼠标走的是 **VNC → X → Chrome**,sessiond 完全不在这条链路上。
它是**事后从 CDP 收到通知**的:

```
人点了链接
   │
   ▼
Chrome 自己开了个 target
   │
   │  Target.targetCreated{targetInfo:{targetId, url, openerId}}   ← 推过来的,不是轮询
   ▼
sessiond
   │ 1. 这个 targetId 我没建过 → 是外面冒出来的
   │ 2. 分配 t_9;openerId 查映射表 → opener: "t_7"
   │ 3. 判 reason(见下)
   │ 4. 附加 + 注入(见 §3)
   │ 5. 写状态模型,seq++
   │ 6. 发 tab.created{reason:"link_target_blank", opener:"t_7"}
   ▼
WS ──► lib 内存里那张表 +1 ──► 你的 tab 条 +1
```

### 订阅是怎么建起来的

一次性开好,之后全是推送:

```
Target.setDiscoverTargets{discover: true}
Target.setAutoAttach{autoAttach: true, flatten: true, waitForDebuggerOnStart: true}
```

- `setDiscoverTargets` —— 新 target 出生就发 `targetCreated`,关掉发 `targetDestroyed`
- `setAutoAttach` + `flatten` —— 新 target 自动挂上一条 CDP session,
  不用自己 `attachToTarget` 一遍
- `waitForDebuggerOnStart` —— **关键**:让新 target 停在第一行 JS 之前,
  等我们注入完再 `Runtime.runIfWaitingForDebugger` 放行。不这么做,
  页面自己的脚本可能先跑,注入就漏了开头那一段

**不轮询 `Target.getTargets`。** 事件是推的,毫秒级到;轮询只在断线重连之后
拉一次全量对账([api/events.md §1](../api/events.md#1-信封) 的 `gap`)。

### `reason` 怎么判出来的

| reason | 判据 |
| --- | --- |
| `api` | sessiond 自己刚建的,它知道 |
| `link_target_blank` / `window_open` | 有 `openerId`;两者的细分靠注入脚本在 **opener 那一页**记一笔(点了带 `target` 的链接 / 调了 `window.open`) |
| `user_ctrl_t` | 没有 `openerId`,而且不是 API 建的 |
| `restored` | Chrome 重启后一批一起冒出来 |

分不出细分时退回一个笼统值,**不猜**。这个字段是给你的 tab 条用的
([api/tabs.md §4](../api/tabs.md#4-事件)):`api` 建的不自动切过去,
`link_target_blank` 切过去才符合人的预期。

### 点完当场就能拿到,不用等事件

如果这个链接是 **API 点的**,`POST /api/act` 的响应里直接带:

```jsonc
{ "ok": true, "after": { "new_tabs": [ {"id":"t_9", "url":"...", "title":"帮助中心"} ] } }
```

lib 把它转成句柄放进 `r.new_tabs`。**同一次变更从响应和 WS 两条路到达,值一样,
合并是幂等的** —— 不闪、不回退([sdk/README §3](../sdk/README.md#3-tab-的状态在内存里))。

## 3. 附加与注入(两条路共用)

不管 tab 从哪来,拿到 session 之后做的事一样:

```
Page.enable / Security.enable                      ← 之后 url/title/loading/锁 都是推的
Page.addScriptToEvaluateOnNewDocument{             ← 每次导航自动重装
    source, worldName: "webmuxd" }                 ← 独立世界,见下
Runtime.addBinding{name: "__webmuxd",              ← 页面调它 → sessiond 收 bindingCalled
    executionContextName: "webmuxd"}
Runtime.runIfWaitingForDebugger                    ← 放行(配 waitForDebuggerOnStart)
```

**`worldName` = 独立世界**,和扩展 content script 待的地方是同一种:

| | 主世界(页面的) | 独立世界(我们的) |
| --- | --- | --- |
| JS 全局、内置原型 | 页面的 | **各自一套**,互不可见 |
| DOM | ← 同一棵 → | 同一棵,只是 JS wrapper 不同 |
| 页面的 CSP | 管 | **不管** |

用它就为一条:**页面的 CSP 拦不住独立世界**。注进主世界的话,
`script-src 'self'` 那类站会直接把我们挡掉。顺带的好处是页面既看不见也覆盖不掉我们的东西。

注入脚本只干一件和 tab 有关的事:**报告本页 `visibilitychange`**,
谁 `visible` 谁就是当前 tab —— CDP 没有"tab 被激活了"这种事件,只能这么补
([api/tabs.md §5](../api/tabs.md#5-当前是哪个-tab怎么来的))。

特权页面(`chrome://` 那类)注入不进去,所以它们**被禁掉了** ——
于是这条路没有盲区,当前 tab 永远由事件驱动,不需要轮询兜底。

## 4. 剩下那些字段从哪来

tab 条要画的东西,除了上面两条路给的 `id`/`opener`/`reason`,其余都是 CDP 推的:

| 字段 | 来源 |
| --- | --- |
| `url` `title` | `Target.targetInfoChanged`、`Page.frameNavigated`、`navigatedWithinDocument`(SPA 换 URL) |
| `loading` | `Page.frameStartedLoading` / `frameStoppedLoading` |
| `security` | `Security.securityStateChanged` |
| `crashed` | `Inspector.targetCrashed` |
| `can_go_back` / `can_go_forward` | **没有事件** —— 每次导航后拉一次 `Page.getNavigationHistory` |
| `favicon` | 注入脚本读 `link[rel~=icon]`,sessiond 代抓并缓存 |
| `index` / 顺序 | **sessiond 自己的列表**,CDP 没有挪 tab 的命令,见下 |

**`reorder` 不进 Chrome。** CDP 没有"把 tab 在 tab 条里挪个位置"的命令,
所以顺序是 sessiond 自己维护的,`POST /api/tabs/reorder` 只重排这个列表 ——
反正 Chrome 真正的 tab 条被裁掉了,没人看得见。
**代价**:人按 `Ctrl+Tab` 走的是 Chrome 的顺序,拖过序之后和你 bar 上的对不上。
v1 接受。

## 5. 待实测

| 要验的 | 怎么验 | 不成立的话 |
| --- | --- | --- |
| **没人连 VNC 时,窗口会不会被判成不可见** —— 那样**所有** tab 都 `hidden`,"谁 visible 谁是当前"就答不出来 | 断开所有 VNC 连接,切 tab,看还有没有 `visible` 的那个 | 全 hidden 时**不更新**,保留最后一次已知的当前 tab |
| `Runtime.addBinding{executionContextName}` 对**之后新建**的执行上下文生不生效、够不够早 | 导航后立刻切 tab,看 `bindingCalled` 到不到 | 每次 `Runtime.executionContextCreated` 后补一次 `addBinding` |
| `waitForDebuggerOnStart` 会不会把 `target=_blank` 开出来的页面卡住 | 点一堆 `_blank` 链接,看有没有卡在空白 | 去掉它,接受注入偶尔漏开头 |

第一条最要命:它不是"世界"的问题,是 `visibilityState` **本来就是整窗口语义**的问题。
容器里没有人看着的时候,这套机制可能整个失效。

> **不用验的**:「独立世界里能不能收到 `visibilitychange`」。事件派发在 DOM 层,
> 一次派发会把**所有世界**注册的 listener 都调一遍 —— 扩展的 content script
> 就是靠这个监听页面事件的。共享 DOM、隔离 JS 全局,这是独立世界的定义。
