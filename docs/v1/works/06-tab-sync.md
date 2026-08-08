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
Target.setAutoAttach{autoAttach: true, flatten: true, waitForDebuggerOnStart: false}
```

- `setDiscoverTargets` —— 新 target 出生就发 `targetCreated`,关掉发 `targetDestroyed`
- `setAutoAttach` + `flatten` —— 新 target 自动挂上一条 CDP session,
  不用自己 `attachToTarget` 一遍
- `waitForDebuggerOnStart: false` —— **不拦**。它的用处是让新 target 停在第一行 JS
  之前等我们注入,而现在没有 document-start 注入要做了(§3),
  拦一下只会让页面白等

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

## 3. 附加之后做什么(两条路共用)

不管 tab 从哪来,拿到 session 之后就三行:

```
Page.enable         ← 之后 url / title / loading 都是推的
Security.enable     ← 小锁
Runtime.enable      ← favicon 要用
```

**没有 document-start 注入,没有独立世界,没有 binding 回程。**

早先这里有一整套:`addScriptToEvaluateOnNewDocument{worldName}` + `Runtime.addBinding` +
`waitForDebuggerOnStart`(让新 target 停在第一行 JS 之前,等注入完再放行)。
那套东西存在的理由**只有一个**:监听 `visibilitychange` 来判断当前是哪个 tab。

改成 sessiond 自己记账、用 `Target.activateTarget` 把 Chrome 拽过来对齐之后
([api/tabs.md §5](../api/tabs.md#5-当前是哪个-tab是-sessiond-说了算)),
这个需求没了,整套跟着塌掉。

**favicon 也不需要常驻脚本**:`Page.loadEventFired` 之后一次性

```js
Runtime.evaluate: document.querySelector("link[rel~=icon]")?.href
```

就够了。`Runtime.evaluate` 是调试器的能力,**不受页面 CSP 管**,
所以连独立世界都省了。拿到 href 由 sessiond 在容器内代抓并缓存 ——
目标站点可能只有容器访问得到。

## 4. 剩下那些字段从哪来

tab 条要画的东西,除了上面两条路给的 `id`/`opener`/`reason`,其余都是 CDP 推的:

| 字段 | 来源 |
| --- | --- |
| `url` `title` | `Target.targetInfoChanged`、`Page.frameNavigated`、`navigatedWithinDocument`(SPA 换 URL) |
| `loading` | `Page.frameStartedLoading` / `frameStoppedLoading` |
| `security` | `Security.securityStateChanged` |
| `crashed` | `Inspector.targetCrashed` |
| `can_go_back` / `can_go_forward` | **没有事件** —— 每次导航后拉一次 `Page.getNavigationHistory` |
| `favicon` | `load` 之后一次 `Runtime.evaluate` 读 `link[rel~=icon]`,sessiond 代抓并缓存 |
| `index` / 顺序 | **sessiond 自己的列表**,CDP 没有挪 tab 的命令,见下 |

**`reorder` 不进 Chrome。** CDP 没有"把 tab 在 tab 条里挪个位置"的命令,
所以顺序是 sessiond 自己维护的,`POST /api/tabs/reorder` 只重排这个列表 ——
反正 Chrome 真正的 tab 条被裁掉了,没人看得见。
**代价**:人按 `Ctrl+Tab` 走的是 Chrome 的顺序,拖过序之后和你 bar 上的对不上。
v1 接受。

## 5. 待实测

| 要验的 | 怎么验 | 不成立的话 |
| --- | --- | --- |
| `Target.setAutoAttach{flatten}` 拿到的 session 上,`Page`/`Security` 事件是不是都推得到 | 开几个 tab,导航,看 `frameNavigated` / `securityStateChanged` 齐不齐 | 缺哪个就对哪个退回按需 `Runtime.evaluate` 取 |
| `targetCreated` 的 `openerId` 在 `target=_blank` 和 `window.open` 下是不是都给 | 两种各点一次,看 `openerId` 有没有 | 没有就 `opener` 留空,`reason` 退回笼统值 |

都是"字段全不全"级别的,不影响这条路成不成立。

> 早先这里列的三条(独立世界能不能收到 `visibilitychange`、`addBinding` 的绑定时机、
> `waitForDebuggerOnStart` 会不会卡住页面)**全部作废** ——
> 当前 tab 改成记账之后,那套注入机制整个不存在了。
