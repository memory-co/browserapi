# f · tab:外挂的 bar,和真的那个是同一份数据

**一句话**:画面里没有 tab 条,它由外面画。这不是"我们仿了一个 bar",
而是**同一张表的另一种呈现** —— 数据来自浏览器自己的 target 表,
开关切都是打回浏览器的命令。**没有第二份账本,因此没有可漂移的东西。**

## 1. 「外挂」是什么意思

画面里不含浏览器自身的 UI。两条像素来源各自的原因不同,结果一致:

| | 为什么画面里没有 bar |
| --- | --- |
| `/channel/cdp` | 截的是页面渲染结果,浏览器 UI 本就不在其中 |
| `/channel/xpra` | 截的是真实窗口,但浏览器以 `--kiosk` 启动,**它不绘制 bar**([c §11](c-view.md#11-画面里没有-bar)) |

于是 tab 条、地址栏、前进后退由观看端自己画,数据经 API 取得:

```
GET  /api/tabs              这个 session 现在有哪些 tab
WS   /api/events            增删改切的事件
POST /api/tabs              开一个
POST /api/tabs/{id}/activate 切过去
```

内置观看页画了一套,但它用的接口与外部完全一致 ——
**上层要自己画就自己画**([e §8](e-client.md#8-ui-层内置那个页面不是界面))。

## 2. 为什么它能和真的那个完全一致

因为**它不是一个副本**。

```
        浏览器的 target 表
               │
               │  CDP:Target.getTargets / targetCreated / targetDestroyed
               ▼
        sessiond 的 tab 表  ← 只是把它翻译成 t_1 / t_2 这种稳定 id
               │
               ├──▶ GET /api/tabs      ──▶ 我们画的 bar
               └──▶ WS  /api/events
```

三条性质由这个结构直接得出:

**① 显示的内容不可能与浏览器不符。** 表里的每一行都来自一个真实 target;
我们不维护一份"自己认为有哪些 tab"的清单,因此不存在需要对账的两方。

**② 操作会真正改变浏览器。** 点我们画的 tab 条,发出的是
`Target.activateTarget`;点关闭,发出的是 `Target.closeTarget`。
**不是先改自己的状态再去同步** —— 那才会产生漂移。

> 这句话一度只对了一半:`active` 恰恰是"先改自己的状态"。
> 那个例外和它造成的事故记在 §3。

**③ 可以直接核对。** 用 DevTools 连上同一个浏览器,看到的 target 列表
与我们的 tab 表逐条对应。这是这个项目一贯的逃生舱:
**我们看到的东西,你能用标准工具独立看到。**

> **在 `/channel/xpra` 那条上,这个一致性可以直接用眼睛验证。**
> 那条路上浏览器是有头的,**它有一个真的 bar**,只是被 `--kiosk` 关掉了。
> 去掉 `--kiosk`,画面里就会出现浏览器自己的 tab 条 ——
> 它显示的内容与我们画的那条**逐个对应**,因为两者读的是同一张表。
>
> screencast 那条没有这个对照物(headless 不存在 bar),
> 但数据来源是同一个,结论相同。

### 2.1 那张表的形状

字段与 `chrome.tabs` 对齐,便于直接映射:

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
{ "type":"tab.created",   "tab":{…}, "reason":"page" }
{ "type":"tab.updated",   "id":"t_7", "changed":{ "title":"订单确认" } }
{ "type":"tab.activated", "id":"t_7", "previous":"t_3" }
{ "type":"tab.closed",    "id":"t_7", "reason":"evicted", "final_url":"…" }
```

两个字段值得单说:

- **`reason`** 区分这个 tab 是 API 开的、页面开的还是人开的。
  判据是 CDP 的 `openerId` —— 实测四种开 tab 的方式(`window.open`、
  带 `noopener` 的、`<a target=_blank>`、带 `rel=noopener` 的)**全都带 `openerId`**,
  所以不需要用 url 猜,也不需要一个 `unknown`。
- **`t_N` 不复用。** 一个编号用过就不再出现,即使那个 tab 已经关闭。
  否则"你以为的 t_3"和"现在的 t_3"可能是两个页面。

## 3. `active`:不是一本账,是一个观测值

CDP 没有「tab 被激活了」这种事件。最直接的做法是自己记一个字段,
改完用 `Target.activateTarget` 把浏览器拽过来对齐。

**这项目试过那条路,它错了。** 错的不是实现,是那个没写出来的前提:

> **只有我们会动前台。**

不是的。页面 `window.open` / `<a target=_blank>` 开出来的 tab,
**Chromium 直接把前台切过去,而且不发任何事件。** 实测(Chromium 152):

| 问谁 | 新那个 tab | 原来那个 |
| --- | --- | --- |
| `document.visibilityState` | `visible` | **`hidden`** |
| `document.hasFocus()` | `true` | `false` |
| 那本账里的 `active` | 不是它 | **还是它** |

漂了之后两条腿各错各的,**都不报错**:

- `/channel/xpra`:画面是那个真窗口,人看到的是**新那一页**,
  而 tab 条高亮、地址栏、不带下标的命令**全指着旧那一页**。
  **输入也打在旧那一页上** —— 人看着新闻页,点下去落在一个看不见的页面里。
- `/channel/cdp`:截屏还挂在旧 target 上,后台不产帧 ——
  画面**冻在旧那页最后一帧**。看着一致,其实已经死了。

> 这一节原来写着「漂移在物理上不可能:真漂了就是**黑屏**,立刻可见」。
> **那句话是错的**,而且它是"我们不用管前台"的全部依据。
> 它错在把"没有新帧"当成了"没有画面" —— 没有新帧的结果是上一帧留在那儿,
> 那恰恰是最不容易被发现的一种坏。

### 3.1 结论:让浏览器说了算

> **`active` 就是一个意思:浏览器现在把哪一页放在前台。**
> 我们的命令只是**发个信号**,信号发出去不算数 ——
> 要等那一页自己报回来"我是前台了"才记账。
>
> **这条规矩没有例外,包括我们自己发的命令。**

理由不是"省事",是**浏览器判得比我们好**。同一个 `target=_blank` 链接:

| 怎么点 | Chromium |
| --- | --- |
| 普通左键 | **前台开** |
| Ctrl + 左键 | **后台开** |
| 中键 | **后台开** |

而我们那条输入腿本来就把 `modifiers` 和 `button` 原样转给了 CDP
([b](b-input.md))。所以**人的意图靠手势表达,Chromium 解释它,
结果就是前台是谁**。我们自己再定一套"跟不跟",第一件事就是把 Ctrl+左键
判错 —— 那不是更安全,那是更差。

于是「没有第二份账本」这句话第一次真的成立:`active` 原来是这张表里
**唯一一个**例外,而这次的 bug 就是从那个唯一的例外里长出来的。

### 3.2 怎么观测

`document.visibilityState` 是标准的、页面自己就知道的,DevTools 连上去
读到的是同一个值。页面里那段探针
([`webmuxjs/sidecar/src/foreground.ts`](../../../webmuxjs/sidecar/src/foreground.ts))
监听 `visibilitychange` 报回来,`Session._on_foreground` 收,
`TabTable.front_is()` 记账。

三件配套的事,每件都是被实测逼出来的:

- **每个 tab 一进表就装探针**,不再等到有人操作它。因为没装探针的那一页
  是**哑的** —— 实测页面 `target=_blank` 开出来的 tab 在被人碰之前
  `window.__wm_side` 是 `undefined`,而那恰恰是最常见的那种前台变化。
- **`activate()` 会阻塞到确认为止。** 顺序是硬的:先把那一页准备好
  (attach、注入、放行 —— 它停在 `waitForDebuggerOnStart` 上,一行脚本
  都没跑过),再发 `activateTarget`,再等它报。
- **等不到不许静默成功。** 超时之后**主动问一次**
  `document.visibilityState`(这仍然是观测,不是猜);还问不到就**报错**,
  说"切过去了但那一页没确认自己在前台"。悄悄当它成了,正是那个 bug 的做法。

唯一一处我们不得不猜的地方在 `_forget()`:当值那个 tab 刚被关掉,
表里留一个指向死人的 `active` 比猜错更糟(画面不知道该跟谁、不带下标的
命令没有落点)。所以先挪到邻居上、同时发个信号,**然后照样等观测纠正**。

### 3.3 代价,说在明处

**一、`resolve_tab(None)` 的语义变了** —— 从「我们表里记的那一页」变成
**「屏幕上那一页」**。后者更好解释,但它是个行为变更:人点了个
`target=_blank`,前台跟着换,**不带下标的下一条命令也跟着换**。
要确定性就带下标(`-t nt:0`),那本来就是 agent 该用的。

**二、广告能搭 agent 那次点击的顺风车。** Chrome 会拦掉没有用户手势的
`window.open`,但 agent 的 click 就是一次手势 —— 页面可以顺手弹一个前台 tab。
缓解是上面那条(带下标),而且这件事现在**看得见**:tab 条会跳、
流水里有 `tab.activated`,不再是悄悄不一致。

**三、页面疯狂抢前台我们不打架。** 一个在 `window.focus()` 里打转的页面
会让 tab 条一直跳。这是这条规则的固有代价,**不做防御,只记流水** ——
它看得见,比悄悄歪着好。

### 3.4 为什么这个 bug 在测试里全绿地跑了很久

`v2_browser_new_tab` 用 Playwright 开真浏览器、连光标都验了,**照样没抓到**。
三件事叠在一起:

1. **四条断言,一份账。** bar 高亮、地址栏、后端 `active`、不带下标的命令
   落在谁身上 —— 看着像交叉验证,其实全都是同一张表的四种呈现。
   **一份账抄四遍,再怎么对账也对不出问题。**
2. **画面只被问过"变没变",从没被问过"你放的是哪一页"。**
   `paint()` 答得出 `colors > 1`(有东西)和 `sig` 变了(变过),
   两样都答不了那一页的**身份**。
3. **跑的是 JPG,而这个 bug 在 JPG 下是隐形的**(画面冻在上一帧,
   前两条判据全过)。用户遇到的是 VNC,而那一段从来没在 VNC 上跑过。

对应补了三样:判据换**来源**(页面的 `visibilityState`)、
判据换**问题**(小站每页一个底色,于是"画面上是哪一页"答得出来)、
以及**同一段在 VNC 腿上再跑一遍** —— 一条腿绿不能替另一条说话。

测试在 [`tests/who_is_in_front/`](../../../tests/who_is_in_front/)
和 [`v2_browser_new_tab`](../../../tests/v2_browser_new_tab/) 那条 VNC 用例。

## 4. 切 tab

`/channel/cdp`:

```
Target.activateTarget(新 target)      ← 只是个信号
等它报 foreground:on                   ← 这一刻 active 才变(§3.2)
Page.stopScreencast(旧 target)
Page.startScreencast(新 target)
```

实测首帧延迟 **14–39 ms**,不可感知。多出来的那一步(等确认)是同一个数量级
的一个来回 —— 换来的是**命令返回时那件事已经真的成立了**。

`/channel/xpra`:只需 `Target.activateTarget` —— 截的是同一个窗口,
不存在"把截屏搬过去"这件事。

### 4.1 为什么不采用「常开」

另一种写法是所有 tab 的截屏一直开着,切 tab 只发 `activateTarget`,
反正后台不产帧。实测同样可行,延迟相当。

**仍然选择显式的 stop / start**,理由只有一条:

> 常开把正确性**押在「后台 tab 不产帧」这条实现细节上**。
> 那是浏览器的渲染器节流策略,不是 CDP 的契约 —— 一旦它变化,
> 我们会同时收到几路帧,而且是静默地多花带宽。
> 显式 stop / start 在那种情况下依然正确。

延迟没有差别,那就选不押注的那个。

### 4.2 残帧必须丢弃

`stopScreencast` 之后,管道中仍可能有旧 tab 的帧。这正是帧头里
`targetId` 与 `castSessionId` 的用途:**客户端对不上就丢弃**
([e1 §1.1](e1-wire-format.md#11-下行二进制28-字节头--一整张图)),
不能让上一个 tab 的画面闪现一下。

## 5. popup 不是特殊情况

在带桌面的方案里,`window.open` 开出来的 popup 是一个**独立的窗口**:
不在 tab 条上、会盖住主窗口,「要不要把它转成 tab」是个没有好答案的问题。

这里 popup 就是一个 `type=page` 的 target:有 `openerId`,能 attach、
能 activate、能截屏。**与普通 tab 没有区别** —— 它进 tab 表,
`reason` 为 `page`,`opener` 指向开它的那个。

在 `/channel/xpra` 那条上有一个额外的确认:desktop 模式下,
`<select>` 下拉之类的弹出层被 X 合成进同一个窗口,
客户端只面对一块画布([c §8](c-view.md#8-那一套-x-是什么))——
**popup 不会变成第二个窗口。**

## 6. 一个 session 一份画面

不做「每个观看者各看各的 tab」。

技术上可行(每个观看者一条截屏),但代价很高:`active` 立刻退化为
per-观看者的状态、tab 条要按观看者渲染、`tab.activated` 要带上是谁切的、
而 `Target.activateTarget` 只有一个前台却要服务多个观看者 ——
后台不产帧,第二个观看者只能看到黑屏。**要绕过这一条,就得回到押注
「后台产帧」的那条路上。**

所以:**一个 session 一份画面,所有观看者看同一个 tab。**
与 tmux 多个 client attach 同一个 session 一致。要各看各的,就开两个 session。

## 7. ↔ 别处

| | |
| --- | --- |
| 画面里为什么没有 bar | [c §11](c-view.md#11-画面里没有-bar) |
| 帧头为什么带 `targetId` | [e1 §1.1](e1-wire-format.md#11-下行二进制28-字节头--一整张图) |
| 内置观看页与外部用同一组接口 | [e §8](e-client.md#8-ui-层内置那个页面不是界面) |
| 落地在 | [`tabs.py`](../../../webmuxd/tabs.py) 的 `front_is()` · [`screen.py`](../../../webmuxd/screen.py) 的 `follow()` |
| 「前台是谁」怎么观测的 | [`webmuxjs/sidecar/src/foreground.ts`](../../../webmuxjs/sidecar/src/foreground.ts) · `sessions.py` 的 `_on_foreground` / `_confirm_front` |
| 测试在 | [`tests/tab_identity/`](../../../tests/tab_identity/) · [`tests/who_is_in_front/`](../../../tests/who_is_in_front/) · [`tests/v2_cli_new_tab/`](../../../tests/v2_cli_new_tab/) · [`tests/v2_browser_new_tab/`](../../../tests/v2_browser_new_tab/)(三种点法那条走 VNC) |
