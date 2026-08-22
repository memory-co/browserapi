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

## 3. `active`:从一本账,变成当前事实

CDP 没有「tab 被激活了」这种事件。最直接的做法是自己记一个字段,
改完用 `Target.activateTarget` 把浏览器拽过来对齐。

这个做法能用,但它承认了两件事:**存在两份真相**,以及**它们会漂移**
(例如人在浏览器里用快捷键切了 tab)。

**这里不需要那本账,因为帧本身就是证据。**

`/channel/cdp` 那条的依据是实测:

| 量的是什么 | 结果 |
| --- | --- |
| A / B / C 三个 tab 同时开启截屏,前台是 C | 2 秒内 A=0 帧,B=0 帧,**C=41 帧** |
| 对后台的 A 开着截屏干等 | 1 秒 **0 帧** |
| 随后 `Target.activateTarget(A)` | 后续 1 秒 **20 帧** |

**后台 tab 不产帧。** 这不是缺陷 —— 没人看的东西不该占带宽。

由此:

- 没有 activate 就没有帧,**帧本身就是 active 的证据**
- 漂移在物理上不可能:真漂了就是**黑屏**,立刻可见,而不是悄悄不一致

`/channel/xpra` 那条的形式不同,结论相同:它截的是**同一个窗口**,
切 tab 后窗口内容随之改变,画面自然跟随。**同样没有第二份真相。**

> `Target.activateTarget` 仍然要发,但它的地位变了 ——
> 从「把记的账同步给浏览器」变成了**「让帧流起来的那条命令」**。
> 同一个调用,完全不同的含义。

## 4. 切 tab

`/channel/cdp`:

```
Page.stopScreencast(旧 target)
Target.activateTarget(新 target)
Page.startScreencast(新 target)
```

实测首帧延迟 **14–39 ms**,不可感知。

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
| 落地在 | [`core/tabs.py`](../../../webmuxd/tabs.py) · [`view/cast.py`](../../../webmuxd/screen.py) 的 `follow()` |
| 测试在 | [`tests/tab_identity/`](../../../tests/tab_identity/) · [`tests/v2_cli_new_tab/`](../../../tests/v2_cli_new_tab/) |
