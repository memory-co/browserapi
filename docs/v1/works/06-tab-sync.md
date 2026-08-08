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

### 会不会漏

人能造出 tab 的方式就那几种,**全都走 `targetCreated`**,没有旁路:

| 人怎么开的 | 收得到 |
| --- | --- |
| 点 `target="_blank"` 链接 | ✅ |
| 页面调 `window.open()` | ✅ |
| Ctrl+点击 / 中键点击(后台开) | ✅ |
| Ctrl+T / Ctrl+Shift+T(恢复关掉的) | ✅ |

两条保证:

- **断线期间的补齐** —— 重新 `setDiscoverTargets{discover:true}` 会把**当前所有
  target 各补一条 `targetCreated`**,不是只推之后的增量。所以 sessiond 重连不会
  留下一个它不知道的 tab。
- **重连后再对一次账** —— 收到 `gap` 就 `Target.getTargets` 拉全量比对,多的补、少的删。

**但必须按 `type` 过滤。** `targetCreated` 推的是所有 target,不只 tab:

```
page  iframe(OOPIF)  worker  service_worker  shared_worker  browser  other
```

只收 `page`,并且排掉子框架的那种。不过滤的话 service worker 会跑进你的 tab 条 ——
那是**多**,不是漏,但一样得治。

### `reason` 怎么判出来的

| reason | 判据 |
| --- | --- |
| `api` | sessiond 自己刚建的,它知道 |
| `link_target_blank` / `window_open` | 有 `openerId`(两者的细分 CDP 给不出,见下) |
| `user_ctrl_t` | 没有 `openerId`,**而且** url 是 NTP / `about:blank` |
| `restored` | Chrome 重启后一批一起冒出来 |
| `unknown` | 其余 —— 见下 |

**`rel="noopener"` 分不出来。** 带 `noopener` 的 `target=_blank` 链接开出来的 tab
**没有 `openerId`**,和 Ctrl+T 开的长得一样。所以判据里必须带上 url:
Ctrl+T 落在 NTP / `about:blank`,noopener 链接落在一个真站点。
两条都对不上就报 `unknown`,**不猜** —— 猜错的代价是你的 tab 条自动切了不该切的 tab。

这个字段是给 tab 条用的([api/tabs.md §4](../api/tabs.md#4-事件)):
`api` 建的不自动切过去,`link_target_blank` 切过去才符合人的预期,`unknown` 按不切处理。

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

## 5. popup 窗口

`window.open('...', '_blank', 'width=500,height=400')` 开出来的是**一个新的浏览器窗口**,
不是 tab。

`targetCreated` 照样收得到,所以**不会漏**。坏的是显示:它浮在页面上,
而 `crop_top` 是按"一个最大化窗口"算的。

这件事单独一篇:[07](07-popup-windows.md) —— 结论是**转化掉**:
在页面层把 `window.open` 包一层、吃掉触发 popup 的 features,Chrome 就原生开成 tab 了。

## 6. 待实测

| 要验的 | 怎么验 | 不成立的话 |
| --- | --- | --- |
| **重新 `setDiscoverTargets` 会不会把已存在的 target 各补一条 `targetCreated`** | 先开三个 tab,再重连 CDP,数收到几条 | 重连后**必须**用 `Target.getTargets` 重建全表,不能只靠事件 |
| `Target.setAutoAttach{flatten}` 拿到的 session 上,`Page`/`Security` 事件是不是都推得到 | 开几个 tab,导航,看 `frameNavigated` / `securityStateChanged` 齐不齐 | 缺哪个就对哪个退回按需 `Runtime.evaluate` 取 |
| `openerId` 在 `target=_blank` / `window.open` / `rel=noopener` 三种下分别给不给 | 三种各点一次 | 按 §2 那张表退 `unknown` |
| **后台 target 的 `Page.captureScreenshot` 到底给什么** —— 空白?旧帧?还是挂住 | 开两个 tab,对后台那个截图 | 如果居然能拍到新帧,就不用"先切前台"那条规则了([api/README §2](../api/README.md#2-一条贯穿全局的规则tab-参数)) |

第一条是"会不会漏"的底,先验它。另外两条是字段全不全,不影响这条路成不成立。

> 早先这里列的三条(独立世界能不能收到 `visibilitychange`、`addBinding` 的绑定时机、
> `waitForDebuggerOnStart` 会不会卡住页面)**全部作废** ——
> 当前 tab 改成记账之后,那套注入机制整个不存在了。
