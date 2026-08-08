# 07 · popup 窗口

`window.open('...', '_blank', 'width=500,height=400')` 开出来的是**一个浏览器窗口**,
不是 tab([06 §5](06-tab-sync.md#5-一个没解决的popup-窗口))。

webmuxd 只有**一块 VNC 屏**,屏上是 X 的整个画面。多一个窗口就是多一块浮在页面上的东西,
而 `crop_top` 是按"一个最大化窗口"算的([04 §2](04-chrome-ui-externalization.md))。
所以这个问题必须有个答案。

**问题不是"会不会漏"** —— `Target.targetCreated` 照样推,tab 列表里不会少。
问题是**画面和模型对不上**。

## 1. 先把触发条件钉死

所有方案都建在这条规则上([MDN](https://developer.mozilla.org/en-US/docs/Web/API/Window/open)):

> 如果 `windowFeatures` 里除了 `noopener` / `noreferrer` / `attributionsrc`
> 之外**还有任何特性**(包括无法识别的),并且 `location`+`toolbar` 都缺失、
> 或 `menubar` 缺失、或 `resizable=false`、或 `scrollbars` 缺失、或 `status` 缺失 ——
> 就开成 popup。

反过来:**`windowFeatures` 省略或为空,开出来的就是普通 tab。**

```js
window.open(url, "name")                              // → tab
window.open(url, "name", "popup")                     // → popup
window.open(url, "name", "width=320,height=320")      // → popup
```

**这条是唯一的杠杆**:能把 features 抹掉,popup 就自动变 tab,不需要任何"转换"动作。

## 2. 四条路

### A. 启动参数 / 企业策略 —— 没有

查了 Chromium 的命令行开关和 Chrome Enterprise 策略列表,**没有**"把 popup 一律开成 tab"
这种开关。`--disable-popup-blocking` 管的是**拦不拦**,不是**开成什么**。
策略里的 `DefaultPopupsSetting` / `PopupsAllowedForUrls` 同理。

Chrome 是有意不给这个设置的(Firefox 早年有 `browser.link.open_newwindow.restriction`,
Chrome 从来没有)。所以**你问的"启动时转化掉"这条路是堵的**。

### B. 扩展 `chrome.tabs.move` —— 也堵

装个扩展、监听窗口创建、把里面那个 tab 挪进主窗口 —— 听起来最干净,但:

> `tabs.move()` 只能在 **`WindowType` 为 `normal`** 的窗口之间移动。

popup 窗口的类型是 `popup`,**挪不出来**。应用商店里那些 "Pop-up to Tab" 扩展
干的其实是:在主窗口新建一个同 URL 的 tab,然后把 popup 关掉。

这就带来了 C 的同一个问题。

### C. CDP 拦截后重开 —— 会断掉 opener

`Page.windowOpen` 是个**通知事件**,带 `url` / `windowName` / `windowFeatures` /
`userGesture`,但**拦不住**,没有"取消"这一说。能做的只有事后补救:
`Target.createTarget` 开个 tab,再 `Target.closeTarget` 关掉 popup。

代价是**语义断了**:

- 页面手里那个 `window.open()` 的返回值(WindowProxy)指向的窗口没了
- `newWin.postMessage(...)` / `newWin.closed` / `newWin.location = ...` 全废
- 新 tab 那边 `window.opener` 也断了

OAuth、支付回调这类**大量依赖 opener 双向通信**的流程会直接坏掉。B 和 C 是同一条路,
不推荐。

### D. 页面层 shim —— 唯一保住语义的转化

在 document-start 把 `window.open` 包一层,**把触发 popup 的 features 吃掉**:

```js
const nativeOpen = window.open;
window.open = function (url, name, features) {
  const keep = String(features || "")
    .split(",")
    .filter(f => /^\s*(noopener|noreferrer|attributionsrc)\s*$/i.test(f))
    .join(",");            // 只留这三个 —— 它们不触发 popup,但改变返回值语义
  return nativeOpen.call(this, url, name, keep);
};
```

`Page.addScriptToEvaluateOnNewDocument`(**主世界**,不是独立世界 —— 要覆盖的正是页面看到的
那个 `window.open`)。因为是**页面自己**调的原生 `open`,所以:

- 返回的是真的 WindowProxy,`opener` 关系完整
- `noopener` 照常返回 `null`,不破坏这个约定
- 不需要回程通道、不需要 `waitForDebuggerOnStart` —— shim 装在**调用方那一页**,
  那页早就 attach 好了

**它的代价**:确实有站点是奔着"小窗"去的(量尺寸、`resizeTo`、靠窗口大小做布局),
被转成 tab 之后行为会变。这类站点少,但不是零。

### E. 不转化,把 popup 收进模型 —— 视觉上归一化

不动页面,承认它是个窗口,然后**让它在我们的模型里就是一个 tab**:

- `Target.targetCreated` 照收,进 tab 列表,`reason: "window_open"`
- 我们本来就自己记着 `active`([api/tabs.md §5](../api/tabs.md#5-当前是哪个-tab是-sessiond-说了算)),
  切到它时用 `Browser.setWindowBounds{windowState:"maximized"}` 把它顶到全屏,
  切走时把主窗口顶回来 —— **一块屏永远只显示一个,和 tab 的手感一致**
- popup 窗口没有 tab 条,所以它当前时 `crop_top` 不一样 ——
  这个我们已经有事件了,发 `viewport.changed` 让外面重新裁

**零页面干预,语义 100% 完整。** 代价是 tab 列表里混进了一个其实是窗口的东西,
以及要和 kasm 那个每 ~10 秒最大化一次的看门狗共处
([04 §5](04-chrome-ui-externalization.md))—— 不过那个看门狗做的事恰好和我们想做的一致。

## 3. 别人怎么做的

| | 怎么渲染 | popup 怎么办 |
| --- | --- | --- |
| **Browserbase** | **一个 tab 一个 live view URL**,`pages` 列表里逐个给 | **问题不存在** —— 每个 target 单独渲染,popup 只是又一个 target |
| **neko** | 整块 X 屏 + openbox 窗口管理器 | **就是个桌面**,popup 就是浮窗,交给 WM |
| **Kasm Workspaces** | 整块 X 屏 + 完整 xfce 桌面 | 同上 |
| **Chrome 扩展生态** | — | 新建同 URL 的 tab + 关掉 popup,**断 opener**(见 B) |

两个有意思的点:

**Browserbase 那条是架构性的躲开。** 它不渲染"屏幕",渲染"target" ——
每个 tab 一个独立的 live view,自然没有窗口叠窗口的问题。代价是**没有统一的画面**,
你得自己决定嵌哪个 tab 的 iframe,而且**人看不到浏览器该有的样子**。
webmuxd 选的是相反的路:一块屏,人看到的和脚本操作的是同一个东西。

**neko / Kasm 是"那就是个桌面"。** 它们不承诺"这是一个浏览器",承诺的是"这是一台机器"。
webmuxd 承诺的是前者 —— 外面画着 tab 条,所以不能让一个浮窗把这个抽象戳破。

**所以这三家谁都没有"把 popup 变成 tab"这件事** —— 要么问题不存在,要么不把它当问题。
webmuxd 是唯一需要正面回答的,因为它既是一块屏、又对外假装成一个有 tab 条的浏览器。

## 4. 结论

**v1 走 E,把 D 做成开关。**

```bash
-e WEBMUXD_POPUP=window     # 默认:不转化,当成 tab 收进模型(E)
-e WEBMUXD_POPUP=tab        # 装 shim,把 popup 转成真 tab(D)
```

理由:

- **E 不碰页面**,而"不改变页面行为"是这东西的底线 —— 一旦装了 shim,
  用户就得怀疑"我这个站点表现异常是不是 webmuxd 干的"
- E 要的两样东西**我们已经有了**:自己记 `active`、`viewport.changed` 重报 `crop_top`
- 真遇到 popup 满天飞的站点、又不在乎那点语义,再开 `WEBMUXD_POPUP=tab`

**A 和 B 明确排除**:一个不存在,一个被 `WindowType` 挡死。
**C 永远不做** —— 断 opener 是静默的、难查的、会坏支付流程的那种错。

## 5. 待实测

| 要验的 | 怎么验 | 不成立的话 |
| --- | --- | --- |
| `Browser.setWindowBounds{windowState:"maximized"}` 对 popup 窗口生不生效 | 开个 popup,把它顶全屏,看画面 | E 塌掉,只能退 D |
| kasm 那个 ~10 秒最大化看门狗会不会和我们抢窗口 | 开 popup 之后放着不动,看窗口跳不跳 | 停掉看门狗,或改成我们自己维持 |
| popup 当前时 `outerHeight - innerHeight` 量出来的 `crop_top` 对不对 | 切到 popup,看外面裁得对不对 | popup 的 `crop_top` 写死 0(它没有 tab 条) |
| D 的 shim 对 `noopener` 是不是还返回 `null` | `window.open(u,n,'noopener')` 看返回值 | shim 里特判 |

前两条决定 E 成不成立,先做。
