# 11 · xpra 那条路

**一句话**:**xpra 只负责像素,别的一律不归它。** 两条 WebSocket —— xpra 那条
只下行画面,输入、光标、tab、原生 UI 全走我们自己的控制通道。

**两个 transport 之间唯一的差别,是像素从哪来**(§5)。

**0.7.0 起 xpra 是默认**(§6)。`Page.startScreencast` 那套留着当明确的退路 ——
xpra 装不上的机器上用它,`remote` 上它是唯一能用的那个。

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

所以:**我们自己的客户端不往 xpra 那条连接发任何输入。**

> **原来这里写的是"不发任何东西",实测下来那句话是错的。**
> 协议本身要求上行 5 个包(`hello` / `map-window` / `focus` /
> `damage-sequence` / `ping_echo`),少一个就收不到帧或者被断开
> ——[12 §7](12-xpra-client.md) 有实测。
> 但这反而更好:上行是一个**闭集**,代理可以按**白名单**放行这 5 个,
> 其余一律丢弃。白名单不是黑名单,新增的 packet 类型默认被拒。

| | 过滤(在代理层丢包) | 不发(我们的选择) |
| --- | --- | --- |
| 只读怎么实现 | 认出 3 类 packet 丢掉,其余透传 | **那条连接从构造上就是单向的** |
| 漏一类会怎样 | 破一个口 | 没有"一类"可漏 |
| 谁来保证 | 代理层的过滤规则 | **客户端不写 + 代理白名单**,两层 |

只读那条([04 §3](04-one-port.md))因此原样成立:输入全在我们的通道上,
服务端一行判断就能丢掉。

> **代价要说清楚**:xpra 的输入路径(它自己做过的加速、组合键处理、IME)
> 我们一样都不继承,得继续用 [03](03-input.md) 那套自己的翻译。
> 换来的是安全模型不动。

### 2.2 那条 xpra 连接要不要经过我们

**要,反代一下,不直接暴露 xpra 的端口。** 理由是 [04](04-one-port.md) 那条
"一个口":人拿到的是一个地址,不是两个;而且 token 校验得在我们这儿做一次 ——
xpra 自己的鉴权是进程级的,不认我们的只读/可写 token。

## 3. 那条 bar:不裁,**根本不让它画**

xpra 截的是**真实的 chromium 窗口**,所以画面里本来会有 tab 条和地址栏 ——
这正是 [v1/works/04](../../v1/works/04-chrome-ui-externalization.md) 那一整篇
要解决的问题,v2 因为 headless 而免掉了。

原计划是把 v1 的裁边机制搬过来。**实测之后不搬了**([12 §10](12-xpra-client.md)):

| 启动方式 | `outerHeight - innerHeight` |
| --- | --- |
| 普通(带 `--no-sandbox` 警告条) | 143 |
| `--test-type --disable-infobars` | 88 —— 正是 v1 在 kasm 上量到的那个数 |
| 再加 **`--kiosk`** | **0** |

`--kiosk` 之后 Chrome 不画任何自己的 UI,于是:

- 没有 `crop_top`,不用发 `viewport.changed`
- **不用把鼠标 `y` 加回去** —— 原来那个"最容易错、错了还很隐蔽"的坑消失了
- 那 88 行像素不再被编码传输然后扔掉(768 里的 88 = **11.5% 带宽**)

达到的效果和裁边完全一样:**画面里没有 Chrome 的 bar,tab 条由我们自己画**,
数据还是 `/api/tabs`,和 screencast 模式**完全一样的接口**([05 §1](05-active-tab.md))。

> 这符合[结论只能有一个](01-frame-source.md#5-为什么不留一个开关)。`crop_top` 一旦存在,
> 就得处理它变化的情况(视频全屏归 0、`Ctrl+Shift+B` 开书签栏变大);
> kiosk 下它**恒等于 0**,没有"变化"这回事,整套机制不用存在。

## 4. tab 和 active

切 tab 走控制通道发 CDP `Target.activateTarget`,xpra 那边画面自然跟着变 ——
**因为是同一个窗口**。所以 [05 §2](05-active-tab.md) 那条"帧本身就是 active 的
证据"在这儿换了形式,但结论一样:**没有第二份真相**。

原来这里担心的是:**xpra 按窗口转发,而 popup 是独立窗口**。
[12 §6](12-xpra-client.md) 实测下来,**在 `start-desktop` 模式下不成立** ——
`<select>` 下拉在 seamless 模式确实是个独立的 `new-override-redirect` 窗口,
但在 desktop 模式下被 X 合成进了同一个窗口,客户端只看见一块画布。

`shim.install` 那个"popup 一律转成 tab"的补丁([v1/works/07](../../v1/works/07-popup-windows.md))
照旧要,但理由回到原来那条(popup 该是个 tab),不是"不然会多出一个 xpra 窗口"。

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

**实测推翻了一处想当然**([12 §11](12-xpra-client.md))。原来这里写着
"人在画面里点了那个原生对话框,记账会跟着清" —— **人点不了**:

- 有头的 Chrome 在 `Page.enable` 之后**照样把对话框画出来**
  (headless 下看不见,是因为它什么都不画)
- 那个 OK 按钮是**浏览器进程的 UI**,`Input.dispatchMouseEvent` 打的是渲染进程,
  点了没有任何反应
- 而 §2.1 又定了输入不走 xpra

于是**我们允许的任何输入路径都关不掉它**,只有 `Page.handleJavaScriptDialog` 能。
两条推论:

1. 我们那张卡片是**必需品** —— 它的按钮是画面上唯一有效的按钮
2. 它必须是**盖住整个视口的 scrim**,否则画面上会同时出现两个对话框,
   而其中一个是死的

## 6. 默认走哪条

```bash
webmuxd install                                          # 有 root 就把 xpra 那套装上
webmuxd new --id work --port 7900                        # **默认 xpra**
webmuxd new --id work --port 7900 --transport screencast # 零系统依赖那条
```

**默认是 xpra。** 这一条在 0.7.0 翻过来了,原来写的是"screencast 是缺省,
因为它零依赖"。翻的理由不是偏好,是[12 §9](12-xpra-client.md)那组数:
滚动时 `scroll` 包**零字节**干掉了 57% 的重绘面积,而 screencast 那边滚动
是整屏重发。**默认值该给的是好的那个**,不是好装的那个。

"好装"那一半由 `webmuxd install` 兜:它本来就是跑之前必须走一遍的
(浏览器得下下来),现在顺手把 xpra / Xvfb / PIL 也装了 ——
有 root 就装,没 root 就打出完整的那行命令([10](10-install.md))。

**起不来就报错,不静默退回 screencast。** 静默退回等于让你以为自己在看 xpra
的画质,而那正是 [07](07-runtime.md) 那句"不可用时抛,不降级"要防的事。
退路是**显式说一声**:

```
✗ 默认走 xpra,但这台机器起不来:缺:Xvfb(Debian/Ubuntu:xvfb;RHEL:xorg-x11-server-Xvfb)
   装上:`webmuxd install`(有 root 就自动装,没 root 会打出该跑的那行);
   不想装就显式说:`--transport screencast`
```

**`remote` 上没有这个问题**:那儿我们只有一个 CDP 端点,碰不到对面的 X 显示,
所以 screencast 是**唯一可能**的画面来源 —— 它在那条路上是默认,而这不是降级。

> 这和 [01 §5](01-frame-source.md#5-为什么不留一个开关) 那句"不留开关"矛盾吗?
> **那一条要修正。** 它当时的论证是"两套画面路径意味着两套输入路径、两套权限模型、
> 两套 runtime 契约,没有一处能共用"—— 而 §2.1 的决定恰恰让**输入路径和权限模型
> 完全共用**,只有画面那一段不同。当年拒绝的那个形状(VNC 连输入一起换)和现在
> 这个不是一回事。
>
> 而且 `--transport` 不是一个"两边都行、你挑一个"的旋钮:**默认只有一个**,
> screencast 是 xpra 装不上时的明确退路,以及 `remote` 上唯一能用的那个。

## 7. 客户端:`09 §7` 那个空缺,现在必须填了

[09 §7](09-wire-format.md) 说"xterm.js 在我们这儿对应的位置是空的,逻辑全埋在
index.html 里"。xpra 模式下**它不能再空着**。

**这一节原来是本篇最大的未知数,现在量完了 ——[12](12-xpra-client.md) 是它的答案。**

结论:**自己写**,三百来行(去掉注释,[12 §5](12-xpra-client.md#5-结论自写约-500-行--实际三百出头))。因为"借用 xpra-html5 的解码部分"这个想法是空的 ——
`xpra-html5` 里**没有解码器**:图像走 `createImageBitmap`,视频走 WebCodecs,
它自己只做协议。那五千行是窗口管理、菜单、剪贴板、音频、虚拟键盘、jQuery ——
**我们全都不要**([12 §3、§4](12-xpra-client.md))。

```
xpra 那条 → 8 字节头 → rencodeplus → draw → createImageBitmap → 画
我们那条 → 输入归一化 / IME / 光标 / tab / 原生 UI
```

要不要背 WebCodecs,**由我们自己说了算**:服务端只发客户端在 `encodings` 里
报过的编码,视频编码还要额外报 `full_csc_modes`,不报就永远不会发过来
([12 §8](12-xpra-client.md))。所以第一版不报视频编码,只解 webp/jpeg/png/rgb/scroll。

## 8. 还没定的

| | 状态 |
| --- | --- |
| ~~客户端走 A(借用)还是 B(自写)~~ | **定了:B,约 500 行**([12 §5](12-xpra-client.md)) |
| ~~`seamless` 还是 `shadow`~~ | **定了:`start-desktop`** —— seamless 下 popup 是独立窗口,要写窗口合成([12 §6](12-xpra-client.md)) |
| ~~画面里那条 bar 怎么裁~~ | **不裁了:`--kiosk`,bar 高度 0**([12 §10](12-xpra-client.md)) |
| h264 值不值得上 | 没测到 —— 探针没报 `full_csc_modes`,服务端就不发([12 §8、§12](12-xpra-client.md)) |
| 画质参数的默认值 | 滚动实测 3.71 Mbps、全屏动画 2.86–9.34 Mbps([12 §9](12-xpra-client.md));默认值还没定 |
| `install` 要不要管 Xvfb / xpra / **PIL** | 装它们要 root、要发行版判断 —— 和 [10 §7](10-install.md) 那条"不碰系统包管理器"冲突。desktop 模式还多一个 `python3-pil`([12 §6](12-xpra-client.md)) |
| 音频 | xpra 有(要 GStreamer)。[works/README](README.md#明确不做) 里"不做音频"那条要不要改 |

## 9. ↔ 别处

| | |
| --- | --- |
| 现在这条画面路 | [01](01-frame-source.md) · [02](02-frame-protocol.md) |
| 输入为什么是安全收口 | [03 §1](03-input.md) |
| 只读怎么实现 | [04 §3](04-one-port.md) |
| 客户端解码 / 实测数据 | [12](12-xpra-client.md) |
| bar 怎么裁 —— v1 的实测记录 | [v1/works/04](../../v1/works/04-chrome-ui-externalization.md) |
| popup 为什么在这儿又是问题 | [v1/works/07](../../v1/works/07-popup-windows.md) · [05 §4](05-active-tab.md) |
| 那个缺掉的协议客户端 | [09 §7](09-wire-format.md) |
