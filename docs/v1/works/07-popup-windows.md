# 07 · popup 窗口

`window.open('...', '_blank', 'width=500,height=400')` 开出来的是**一个浏览器窗口**,
不是 tab([06 §5](06-tab-sync.md#5-popup-窗口))。

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

### D. 页面层 shim —— **答案**

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

**代价小到值得反复确认一下**:转成 tab 之后,页面还能用的有
`opener.postMessage`、`window.opener`、`window.closed`、`window.close()` ——
**OAuth / 支付回调这类最大宗的用法全都照常**。

真正只在 popup 里才有意义的是 `resizeTo` / `moveTo`,以及"按小窗尺寸排版"。
这两样本来就在被各家浏览器逐步阉割,而且**举不出一个非坏不可的具体站点**。

三处窄缝,记着就好:

- **OOPIF**:跨域 iframe 是独立 target,shim 得也装到那边(auto-attach 覆盖到就行)
- **首屏内联脚本抢跑**:新 target 刚建出来、我们还没装 shim 时它就调 `window.open`,
  会漏一次。要堵得上 `waitForDebuggerOnStart`,一般不值
- **`window.open.toString()`** 会露馅,极少数站点靠这个判原生。真碰上再伪装

### E. 不转化,把 popup 收进模型 —— 退路

不动页面,承认它是个窗口,然后**让它在我们的模型里就是一个 tab**:

- `Target.targetCreated` 照收,进 tab 列表,`reason: "window_open"`
- 我们本来就自己记着 `active`([api/tabs.md §5](../api/tabs.md#5-当前是哪个-tab是-sessiond-说了算)),
  切到它时用 `Browser.setWindowBounds{windowState:"maximized"}` 把它顶到全屏,
  切走时把主窗口顶回来 —— **一块屏永远只显示一个,和 tab 的手感一致**
- popup 窗口没有 tab 条,所以它当前时 `crop_top` 不一样 ——
  这个我们已经有事件了,发 `viewport.changed` 让外面重新裁

零页面干预,语义完整。但代价比看上去大:

- tab 列表里混进一个其实是窗口的东西,`activate` 它走的是**另一套机制**
  (raise 窗口,而不是 `Target.activateTarget`)
- 每个窗口一套 `crop_top`(popup 没有 tab 条)
- 要和 kasm 那个每 ~10 秒最大化一次的看门狗共处([04 §5](04-chrome-ui-externalization.md))
- **而且它有两条没验证过的地基**:`Browser.setWindowBounds` 对 popup 窗口生不生效、
  看门狗抢不抢。任一不成立,整个方案就没了

D 的地基是**规范写死的规则**(§1),E 的地基是两条待实测。这是选 D 的主要理由。

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

**默认 D,E 留成退路。**

```bash
-e WEBMUXD_POPUP=tab        # 默认:装 shim,把 popup 转成真 tab(D)
-e WEBMUXD_POPUP=window     # 退路:不转化,当成 tab 收进模型(E)
```

理由,按分量排:

1. **D 的地基是规范,E 的地基是两条待实测。** §1 那条规则是写死的:
   features 为空就是 tab。而 E 依赖 `setWindowBounds` 对 popup 生效、
   且不被 kasm 看门狗掀翻 —— 两条都没验过,任一不成立方案就塌了。
2. **D 是修因,E 是修果。** webmuxd 对外的承诺就是"一个有 tab 条的浏览器";
   把 popup 变成 tab 是让现实对齐这个承诺,E 是留着一个不符的东西再想办法让它看起来像。
3. **代价不对称。** D 掉的是 `resizeTo` / 小窗排版,举不出非坏不可的例子;
   E 掉的是整套窗口编排的复杂度,而且落在最容易出边界 bug 的地方(窗口、焦点、裁剪)。

**A 和 B 明确排除**:一个不存在,一个被 `WindowType` 挡死。
**C 永远不做** —— 断 opener 是静默的、难查的、会坏支付流程的那种错。

> 早先这里推荐的是 E,理由是"不改变页面行为是底线"。
> 那条原则这个仓库里并不存在 —— [04](04-chrome-ui-externalization.md) 说的是
> 不碰 X、不碰窗口管理器、不碰启动参数(别跟平台较劲),而我们本来就要注脚本读 favicon。
> 拿一条临时发明的原则去压两条没验证的假设,是反的。

## 5. 待实测

D(默认)要验的:

| 要验的 | 怎么验 | 不成立的话 |
| --- | --- | --- |
| shim 之后 `window.open(u,n,'width=320')` 真的开成 tab | 开一个,看是窗口还是 tab | §1 的规则理解错了,回去重读 |
| `noopener` 还返回 `null` | `window.open(u,n,'noopener')` 看返回值 | shim 里特判 |
| 跨域 iframe(OOPIF)里调 `window.open` 也被 shim 住 | 嵌个跨域 iframe 弹一个 | 给 OOPIF target 也装一遍 |
| 常见 OAuth 弹窗流转成 tab 之后还能跑通 | 拿一个真的登录流走一遍 | 那个站点加白名单,或整体退 E |

E(退路)只有真要用时才验:`Browser.setWindowBounds{windowState:"maximized"}`
对 popup 生不生效、kasm 的 ~10 秒看门狗抢不抢窗口。
