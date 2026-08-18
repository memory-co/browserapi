# 11 · xpra 那条路

**一句话**:**xpra 只负责像素,别的一律不归它。** 两条 WebSocket —— xpra 那条
只下行画面,输入、光标、tab、原生 UI、裁边全走我们自己的控制通道。

**两个 transport 之间唯一的差别,是像素从哪来**(§5)。

`Page.startScreencast` 那套留着当兜底:它开箱即用,而 xpra 要 Xvfb + xpra 本体。

## 1. 为什么值得换

实测下来 xpra 明显更好(2026-08-18,同机同页对比)。它强的地方**恰好是我们结构上
缺的**:

| | 我们(screencast) | xpra |
| --- | --- | --- |
| 更新粒度 | **整屏一帧** | **按 damage 区域** |
| 选编码 | 固定 jpeg | **每块区域各选** —— 文字走无损 webp/rgb,视频走 h264 |
| 滚动 | 整屏重发 | **`scroll` 编码**,只发位移 |
| 静止之后 | 就那样了 | **`auto-refresh`:先发有损的,静止 N 毫秒后补一张无损的** |
| 光标 | 要注入探针([03 §5](03-input.md)) | 协议自带 |

最后那条是它文字清楚的真正原因:**动的时候糊、停下来就变清晰**。
我们完全没有这个机制 —— 动不动都是同一个 q80
([02 §4](02-frame-protocol.md))。

这台机器上编进去的编码器:`h264`(x264 164 + openh264 2.3)、`vp9` / `vp8`
(vpx 1.12)、`webp`、`avif`、`jpeg`、`scroll`,无损模式支持 `webp` / `rgb24` / `rgb32`。

## 2. 两条 WebSocket,线切在哪

```
浏览器
  ├── ws://host:PORT/xpra        → xpra 协议,**只下行画面**
  └── ws://host:PORT/api/view    → 我们的控制通道:输入、光标、tab、crop_top

机器上
  Xvfb :N
  chromium --display=:N --remote-debugging-port=…
  xpra seamless :N --bind-ws=…
  sessiond(CDP 客户端 + 控制通道)
```

### 2.1 **输入不走 xpra。这是本篇最重要的一条决定。**

xpra 自带完整的输入协议(`pointer-position` / `button-action` / `key-action`),
用它最省事。**但那会把 [03 §1](03-input.md) 那个安全收口拆掉。**

现在的收口是:观看者能表达的全部意图,被限制在 CDP `Input` 域那四个命令里 ——
拿不到 DOM、执行不了脚本、发不出任意 CDP 命令。走 xpra 之后这条边界变成
"在代理层过滤 packet",而**过滤是黑名单思维**:漏一类就破一个口。

所以:**我们自己的客户端根本不往 xpra 那条连接发任何东西。**

| | 过滤(在代理层丢包) | 不发(我们的选择) |
| --- | --- | --- |
| 只读怎么实现 | 认出 3 类 packet 丢掉,其余透传 | **那条连接从构造上就是单向的** |
| 漏一类会怎样 | 破一个口 | 没有"一类"可漏 |
| 谁来保证 | 代理层的过滤规则 | **客户端不写发送代码** |

只读那条([04 §3](04-one-port.md))因此原样成立:输入全在我们的通道上,
服务端一行判断就能丢掉。

> **代价要说清楚**:xpra 的输入路径(它自己做过的加速、组合键处理、IME)
> 我们一样都不继承,得继续用 [03](03-input.md) 那套自己的翻译。
> 换来的是安全模型不动。

### 2.2 那条 xpra 连接要不要经过我们

**要,反代一下,不直接暴露 xpra 的端口。** 理由是 [04](04-one-port.md) 那条
"一个口":人拿到的是一个地址,不是两个;而且 token 校验得在我们这儿做一次 ——
xpra 自己的鉴权是进程级的,不认我们的只读/可写 token。

## 3. 那条 bar:v1 的旧账,这次在像素上还

xpra 截的是**真实的 chromium 窗口**,所以画面里有 tab 条和地址栏 ——
这正是 [v1/works/04](../../v1/works/04-chrome-ui-externalization.md) 那一整篇
要解决的问题,v2 因为 headless 而免掉了,现在它回来了。

**v1 的做法和结论直接继承,只有一处变**:

| | v1 | 现在 |
| --- | --- | --- |
| 怎么裁 | iframe 负 margin + `overflow:hidden` 的壳 | **客户端在画布上裁**(画面本来就归我们画) |
| 高度从哪来 | CDP 量 `outerHeight - innerHeight` | **一样**,走控制通道报出来 |
| 它会变吗 | **会** —— 视频全屏归 0,`Ctrl+Shift+B` 开书签栏变大 | **一样** |
| 变了怎么办 | 发 `viewport.changed` 让外面重裁 | **一样**,走控制通道 |

```jsonc
{ "type": "viewport.changed", "crop_top": 88 }   // tab条 + 工具栏的实际高度
{ "type": "viewport.changed", "crop_top": 0 }    // 视频全屏了
```

**别写死 88。** v1 在 kasm 上量到的是 88,那是那个基座那一版 Chromium 的值,
换一版就变。

裁掉之后那块位置换成我们自己画的 tab 条和地址栏 —— 数据还是
`/api/tabs`,和 screencast 模式**完全一样的接口**([05 §1](05-active-tab.md))。

> **鼠标坐标要跟着偏移。** v1 用 iframe 位移时"浏览器的命中测试自动对上",
> 我们自己裁就得自己减:控制通道里的 `y` 要加回 `crop_top` 才是窗口坐标。
> **这是最容易错、而且错了很隐蔽的一处** —— 点击会整体偏 88 像素。

## 4. tab 和 active

切 tab 走控制通道发 CDP `Target.activateTarget`,xpra 那边画面自然跟着变 ——
**因为是同一个窗口**。所以 [05 §2](05-active-tab.md) 那条"帧本身就是 active 的
证据"在这儿换了形式,但结论一样:**没有第二份真相**。

一处要留意:**xpra 是按窗口转发的,而 popup 是独立窗口。** [05 §4](05-active-tab.md)
说"popup 在 headless 里就是一个 target,没有窗口这回事" —— 那是 headless 的性质,
xpra 模式下它又变回一个真窗口了。`shim.install` 那个"popup 一律转成 tab"的页面层
补丁([v1/works/07](../../v1/works/07-popup-windows.md))在这儿**更要紧**,
不然会多出一个 xpra 窗口。

## 5. xpra 只负责像素,别的一律不归它

这是整篇的**总原则**,§2.1(输入不走 xpra)和 §3(bar 裁掉)都是它的推论:

> **两个 transport 之间唯一的差别,是像素从哪来。**
> 输入、光标、tab、原生 UI、日志、token、只读 —— **一模一样**。

所以六类原生 UI([06](06-no-desktop.md))那一整套 CDP 拦截**原样留着,而且照旧
由我们自己画卡片** —— 不是"画面里能看见就不用管了":

| | 为什么还要拦 |
| --- | --- |
| **JS 对话框** | 它挡着页面。人能在画面里点是一回事,**程序撞上它还是会永久卡住** —— `/api/pending`、超时、日志一样都不能少 |
| **文件选择** | X 里根本没有文件管理器,那个原生框弹出来也没法用。还是得 `DOM.setFileInputFiles` |
| **下载** | 有气泡,但文件落在那台机器上 —— 还是要 API 取 |
| **权限 / 认证** | 和画面无关,本来就在 CDP 那一层 |

**两个模式下人看到的应该是同一套卡片。** 让 xpra 模式退回"看原生框"等于同一个产品
有两种交互,而且其中一种(原生文件选择框)在那个环境里根本不能用。

一处白拿的好处:人在画面里点了那个原生对话框,`Page.javascriptDialogClosed`
会让我们的记账跟着清([06](06-no-desktop.md))—— 两条路指向同一个对话框,
不会打架。

## 6. 什么时候用哪个

```bash
webmuxd new --id work --port 7900                  # screencast,开箱即用
webmuxd new --id work --port 7900 --transport xpra # 画面更好,但要 Xvfb + xpra
```

**screencast 是缺省,因为它零依赖。** xpra 要 Xvfb、xpra 本体、编码器 ——
`webmuxd install` 现在只下一个浏览器([07 §4](07-runtime.md))。

**不静默降级。** 要了 xpra 而机器上没有,就报错并说清缺什么 ——
这条和 [07](07-runtime.md) 那句"不可用时抛,不降级"是同一条:
静默退回 screencast 等于让你以为自己在看 xpra 的画质。

> 这和 [01 §5](01-frame-source.md#5-为什么不留一个开关) 那句"不留开关"矛盾吗?
> **那一条要修正。** 它当时的论证是"两套画面路径意味着两套输入路径、两套权限模型、
> 两套 runtime 契约,没有一处能共用"—— 而 §2.1 的决定恰恰让**输入路径和权限模型
> 完全共用**,只有画面那一段不同。当年拒绝的那个形状(VNC 连输入一起换)和现在
> 这个不是一回事。

## 7. 客户端:`09 §7` 那个空缺,现在必须填了

[09 §7](09-wire-format.md) 说"xterm.js 在我们这儿对应的位置是空的,逻辑全埋在
index.html 里"。xpra 模式下**它不能再空着** —— 因为客户端要同时做两件事:

```
xpra 那条 → 解 xpra 协议 → 拿到像素 → **裁掉 crop_top** → 画
我们那条 → 输入归一化 / IME / 光标 / tab / crop_top 更新
```

**最大的未知数在这儿。** xpra 的协议不是"一个头加一张图"那么简单:
packet 编码(rencodeplus)、多种图像编码的解码(h264 要 WebCodecs)、窗口管理语义 ——
`xpra-html5` 那个官方客户端是几千行。

两条路,得先量再定:

| | 做法 | 风险 |
| --- | --- | --- |
| **A 借用** | 直接用 `xpra-html5` 的解码部分,只换掉输入和 UI 那层 | 它是整套 app 的形状,拆出来可能比重写还麻烦 |
| **B 自己写** | 只实现我们要的子集(下行画面 + 必要的窗口事件) | 工作量未知,h264 解码是硬骨头 |

**下一步就是量这个**,不是先写代码:拿 `xpra-html5` 跑起来,看它的解码路径能不能
单独拿出来用。这是 §8 的第一项。

## 8. 还没定的

| | 为什么现在定不了 |
| --- | --- |
| 客户端走 A 还是 B(§7) | 要先看 `xpra-html5` 的解码能不能拆 |
| xpra 用 `seamless` 还是 `shadow` | seamless 是按窗口转发(popup 会变成第二个窗口),shadow 是整屏。和 §4 那条绑在一起 |
| 画质参数的默认值 | 实测拉满(`quality=100 min-quality=100 speed=1 auto-refresh-delay=0.05`)效果好,但那套牺牲流畅度;**滚动/视频那一轮还没量** |
| `install` 要不要管 Xvfb 和 xpra | 装它们要 root、要发行版判断 —— 和 [10 §7](10-install.md) 那条"不碰系统包管理器"冲突 |
| 音频 | xpra 有(要 GStreamer)。[works/README](README.md#明确不做) 里"不做音频"那条要不要改 |

## 9. ↔ 别处

| | |
| --- | --- |
| 现在这条画面路 | [01](01-frame-source.md) · [02](02-frame-protocol.md) |
| 输入为什么是安全收口 | [03 §1](03-input.md) |
| 只读怎么实现 | [04 §3](04-one-port.md) |
| bar 怎么裁 —— v1 的实测记录 | [v1/works/04](../../v1/works/04-chrome-ui-externalization.md) |
| popup 为什么在这儿又是问题 | [v1/works/07](../../v1/works/07-popup-windows.md) · [05 §4](05-active-tab.md) |
| 那个缺掉的协议客户端 | [09 §7](09-wire-format.md) |
