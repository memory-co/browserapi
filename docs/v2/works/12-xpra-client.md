# 12 · xpra 客户端:解码那边

**一句话**:xpra-html5 那五千行里,**没有一行是编解码器** —— 图像交给
`createImageBitmap`,视频交给 WebCodecs,它自己只做协议。所以
[11 §7](11-xpra.md) 那个"借用还是自写"的问题,答案是**自写,大约 500 行**。

> 本篇是实测记录,不是读代码的读后感。方法是:**自己写一个 xpra 客户端连上去**,
> 能握手、能收帧、能解码、能合成出正确的画面 —— 下面每个结论后面都有对应的数。
> 测于 2026-08-18,xpra v6.6,Chrome for Testing 152.0.7977.42。

## 1. 先把客户端写出来,再谈要不要借

判断"这活多大"最靠谱的办法是干一遍。**九十行 Python,跑通了**:握手 →
`map-window` → 收 `draw` → 解码 → 合成 → 存成 PNG。

那张图里有页面、有 `<select>` 展开的下拉、有正确的位置和颜色 ——
**整条像素链路是通的**,而且没用 xpra 的任何客户端代码。

这一步的意义不在于那九十行本身,在于它**把"未知"变成了"已知的量"**:
下面所有的账都是在这个基础上算的,不是估的。

## 2. 线上长什么样:8 字节头

对照 [02 §2](02-frame-protocol.md) 我们自己那个 28 字节头:

| 偏移 | 长度 | 内容 |
| --- | --- | --- |
| 0 | 1 | `'P'`(0x50)。对不上就是协议错,直接断 |
| 1 | 1 | proto flags。`0x10` = rencodeplus,`0x2` = 加密,`0x8` 忽略 |
| 2 | 1 | 压缩级别。`0x10` = lz4,`0x40` = brotli,`0` = 不压 |
| 3 | 1 | **packet index** —— 见下 |
| 4–7 | 4 | 载荷长度,**大端** |

`header[3]` 这个字段是整个协议里最值得抄的一处设计。它不是"分片序号",
是**包数组的下标**:

```
draw = ["draw", wid, x, y, w, h, coding, <像素>, seq, rowstride, options]
         0      1    2  3  4  5    6         7     8      9        10
```

像素那一块**不进 rencode**,单独用一个 `index=7` 的帧发过来,客户端收齐后
`packet[7] = raw[7]` 塞回去。于是:**结构化字段走通用编码,大块二进制走裸字节,
两者用同一个头**。

我们那个 28 字节头是另一种解法 —— 头是定长结构体,后面直接跟 JPEG
([09 §3](09-wire-format.md))。两者都避开了"把二进制塞进 JSON"这个坑,
xpra 这个更通用,我们那个更省(28 字节 vs 8 字节 + 一个 rencode 过的数组)。

## 3. 谁在解码:没有谁,浏览器在解

| 文件 | 行数 | 它到底做了什么 |
| --- | --- | --- |
| `ImageDecoder.js` | **41** | `new Blob([data], {type:"image/webp"})` → `createImageBitmap` |
| `VideoDecoder.js` | **261** | `new VideoDecoder(...)` + `EncodedVideoChunk` —— WebCodecs |
| `RgbHelpers.js` | **74** | rgb24→rgb32 补 alpha,lz4 解压 |
| `OffscreenDecodeWorker.js` | **368** | 调度:按 `coding` 分派到上面三个,画到 `OffscreenCanvas` |

jpeg / png / webp / avif **一行解码代码都没有** —— 全是 `createImageBitmap`,
浏览器原生。h264 / vp8 / vp9 也一样,全是 WebCodecs。

> 早年的 xpra-html5 是带 `broadway.js`(纯 JS 的 h264 解码器)的,现在删干净了。
> **我们不必重走那段路。**

`scroll` 是唯一一个"自己实现"的编码,而它的实现是 `drawImage(自己, sx,sy,sw,sh → sx+dx,sy+dy)`
—— 把画布上已有的像素按位移向量挪一下。**零字节,零解码**。

## 4. 那 5000 行是什么

`Client.js` 4991 行 + `Window.js` 1467 行 —— 但这两个里面**没有解码**,是:

窗口管理(拖动、缩放、层叠、最小化)、菜单栏、剪贴板、音频(`aurora` 那一套
mp3/aac/flac 解码器 1.7 万行)、文件传输、通知、托盘、虚拟键盘
(`simple-keyboard` 8852 行)、jQuery + jQuery-UI(近 3 万行)。

**这些我们一样都不要。** 窗口管理不要(§6 定了只有一个窗口),
输入不要([11 §2.1](11-xpra.md) 定了不走 xpra),音频/剪贴板/文件传输不要,
UI 不要(我们自己画)。

所以"借用 xpra-html5 的解码部分"这个想法本身是空的 —— **解码部分不存在**,
存在的是我们全都不要的那部分。

## 5. 结论:自写,约 500 行 —— **实际 413**

| 要写的 | 量 | 说明 |
| --- | --- | --- |
| 8 字节头 + chunk 拼装 | ~120 | §2 |
| rencodeplus **解码** | ~250 | 只需要解,不需要编(我们上行的包极少,可以手写) |
| 图像 draw → `createImageBitmap` | ~40 | §3 |
| `scroll` → `drawImage` 自搬 | ~30 | §3 |
| rgb32/24 → `ImageData` | ~40 | §3 |
| 握手 + `map-window` + ack | ~60 | §7 |

**不写的**:WebCodecs 视频(§7)、lz4、brotli、加密、音频、窗口管理、输入。

写完之后回来对账:

| | 行数(含注释) | 去掉注释和空行 |
| --- | --- | --- |
| `view/static/rencode.js` | 126 | **93** |
| `view/static/xpra.js` | 287 | **223** |
| | | **316** |

比估的 500 还少 —— 估多的是 rencodeplus(以为要 250,实际 93,因为**只解不编
全套**:上行那 6 种包用最朴素的显式编码就够,不需要挑最短表示)。

服务端那两个不在这张表里,因为它们不是"客户端":
`webmuxd/xpra.py` 195 行(起 xpra),`view/relay.py` 187 行(代理 + 白名单)。

**东西在哪:**

| | |
| --- | --- |
| 起 xpra + Xvfb + kiosk chrome | [`webmuxd/xpra.py`](../../../webmuxd/xpra.py) |
| 代理 + 上行白名单(§7) | [`webmuxd/view/relay.py`](../../../webmuxd/view/relay.py) |
| rencodeplus 编解码(§2) | [`webmuxd/view/static/rencode.js`](../../../webmuxd/view/static/rencode.js) |
| 协议 + 解码 + 上画(§3) | [`webmuxd/view/static/xpra.js`](../../../webmuxd/view/static/xpra.js) |
| "只换像素从哪来"那个开关 | [`webmuxd/view/cast.py`](../../../webmuxd/view/cast.py) 里几个 `if self.xpra` |
| 测试 | [`tests/pixels_from_xpra/`](../../../tests/pixels_from_xpra/) |

## 6. seamless 还是 desktop:实测定案

[11 §8](11-xpra.md) 把这个列为第一个未决问题。**测了,是 desktop。**

同一个 Chrome、同一个页面,点开一个 `<select>` 下拉:

| | `xpra start`(seamless) | `xpra start-desktop` |
| --- | --- | --- |
| 窗口数 | **2** —— 主窗口 + `new-override-redirect` | **1** |
| 下拉框 | 独立窗口 `(100,291) 89×214`,自己一份 `draw` | **被 X 合成进同一个窗口** |
| 客户端要做 | 多层合成、位置、层叠顺序 | **一块 canvas,`drawImage` 就完了** |
| 装机代价 | — | **要 `python3-pil`**(不装报 `No module named 'PIL'`) |

seamless 那条路要求客户端做窗口管理,而窗口管理正是 §4 里"我们全都不要"的
那部分。**为了省一个 PIL 去写一套窗口管理,不划算。**

而且这直接推翻了 [11 §4](11-xpra.md) 那条担心:"popup 在 xpra 模式下又变回真窗口了,
`shim.install` 更要紧"。**在 desktop 模式下不成立** —— popup 被合成进同一个窗口,
客户端根本看不见它是个窗口。

## 7. 上行不是"什么都不发",是**六个包**

[11 §2.1](11-xpra.md) 写的是"我们自己的客户端根本不往 xpra 那条连接发任何东西"。
**这句话字面上是错的,得改。** 实测下来,不发这些协议根本不动:

| 包 | 不发会怎样 |
| --- | --- |
| `hello` | 连不上 |
| `map-window` | **一帧都不来** —— 服务端认为你没在看 |
| `focus` | 键盘焦点(我们不用,但省不掉几行) |
| `damage-sequence` | 发几帧就停 —— 这是 xpra 的背压 ack,对应我们的 ring B([02 §3](02-frame-protocol.md)) |
| `ping_echo` | 一段时间后服务端主动断开 |

> 写实现时补上了第六个 `disconnect` —— 探针没发它是因为探针不在乎自己走得好不好看。

**但原则活下来了,而且变强了。** §2.1 反对的是"在代理层按黑名单丢 packet",
理由是漏一类就破一个口。现在我们知道上行是一个**闭集**,于是可以走白名单:

> 代理只放行这 5 个包类型,其余一律丢弃并记一条日志。

白名单不是黑名单 —— **新增的 packet 类型默认是被拒的**,漏不了。而且这条
校验在服务端,不再只靠"客户端没写发送代码"。只读([04 §3](04-one-port.md))
因此是**两层**保证的。

## 8. 能力声明就是契约:我们解多少,由我们说了算

握手时客户端报 `encodings`,**服务端只会发你报过的**。这不是约定俗成,是
`video_compress.py:450` 那段硬逻辑:

```python
csc_modes = self.full_csc_modes.strtupleget(x)
if not csc_modes or x not in self.core_encodings:
    exclude.append(x)      # 客户端没报 csc 模式 → 这个视频编码直接排除
```

我的探针客户端在 `encodings` 里报了 `h264`、`vp8`,**但没报 `full_csc_modes`**
—— 结果是整整 24 秒全屏动画、480 帧,**一次 h264 都没走**,全是 webp。
后来用 `xpra control :92 encoding h264 1` 从服务端强指定,**照样是 webp**。

这条的份量:**"客户端要背多重"不是 xpra 决定的,是我们自己声明的。**
不报视频编码 → 不用 WebCodecs,不用管 IDR、色彩范围、VP9 profile 参数、
解码器 reset —— `VideoDecoder.js` 那 261 行里一大半是在处理这些。

所以 §5 那张表里"不写 WebCodecs"不是偷懒,是**一个可以随时反悔的决定**:
哪天要视频了,加上 `full_csc_modes` 和一个 WebCodecs 分支即可,协议层不动。

## 9. 量到的数

**滚动** —— Wikipedia 长页,连续滚 60 次,22 秒:

| 编码 | 帧数 | 字节 | 覆盖面积 |
| --- | --- | --- | --- |
| webp | 650 | 9937 KB | 30.2 Mpx |
| **scroll** | 50 | **0 KB** | **39.3 Mpx** |
| png | 40 | 5 KB | ~0 |
| | | **3.71 Mbps** | |

**`scroll` 用零字节干掉了 57% 的重绘面积。** 这是 [11 §1](11-xpra.md) 那张表里
"滚动:只发位移"的实测值,也是滚动手感差别的**全部来源** —— 我们那边滚动
是整屏重发([02 §4](02-frame-protocol.md))。

**全屏动画** —— 1024×768 canvas 每帧重画 300 个色块,24 秒:

| | 帧数 | 字节 | 覆盖 | 码率 |
| --- | --- | --- | --- | --- |
| 第一轮 | 480 webp | 27314 KB | 377 Mpx(≈20 fps) | 9.34 Mbps |
| 第二轮 | 504 webp | 7674 KB | 396 Mpx(≈22 fps) | **2.86 Mbps** |

同样的画面,第二轮码率只有第一轮的 30% 而帧数更多 —— **服务端把质量降下来了**。
这就是 [11 §1](11-xpra.md) 说的自适应,方向和我们的 RTT 自适应
([02 §3](02-frame-protocol.md))一样,但它是按区域、按内容做的。

> 一处要注意:**全屏持续运动是 xpra 的劣势区**,和
> [01 §4.1](01-frame-source.md) 里我们对 VNC 的那个判断是同一个道理 ——
> 分区域重传在"全屏都在动"的时候退化成整屏重传,还多背了分区的开销。
> 上面 9.34 Mbps 就是这个退化。**这正是 screencast 留着当兜底的理由之一。**

## 10. bar 的账:143 / 88 / 0

[11 §3](11-xpra.md) 整节在讲"怎么把 Chrome 的 bar 裁掉"。**测完之后这一节可以删掉大半。**

CDP 量 `outerHeight - innerHeight`:

| 配置 | bar 高度 | 那是什么 |
| --- | --- | --- |
| 普通启动(带 `--no-sandbox` 警告条) | **143** | 标签栏 40 + 地址栏 ~48 + 警告条 ~55 |
| 加 `--test-type --disable-infobars` | **88** | 标签栏 + 地址栏 —— 正好是 v1 在 kasm 上量到的那个 88 |
| 再加 **`--kiosk`** | **0** | `outerHeight == innerHeight == 748` |

**`--kiosk` 让整个裁边机制归零。** 不是"裁得更方便了",是**没有东西要裁**:

- 不用发 `viewport.changed`,不用在客户端算 crop
- 不用把鼠标 `y` 加回 `crop_top` —— [11 §3](11-xpra.md) 那个"最容易错而且很隐蔽"的坑**不存在了**
- 那 88 行像素不再被编码、传输、然后扔掉(768 里的 88 = **11.5% 的带宽**)

而它达到的效果和裁边**完全一样**:画面里没有 Chrome 的 bar,tab 由我们自己画。

> 这一条改动了原来的说法。原计划是"带 bar 截,客户端裁掉换成我们的 tab 控制";
> 现在是"**根本不让它画 bar**"。目的没变 —— Chrome 的 bar 不出现在画面里、
> tab 控制是我们的 —— 但少了一整套会出错的机制。
> 这也符合[结论只能有一个](01-frame-source.md#5-为什么不留一个开关):
> `crop_top` 一旦存在就得处理它变化的情况(视频全屏归 0、书签栏变大),
> 而 kiosk 下它**恒等于 0**,没有"变化"这回事。

一个遗留的小账,**已经解决了但值得记下来**:kiosk + `--window-size=1024,768`
在 1024×768 的显示上实际拿到 **1023×767** —— 右边和下边各露出一列 X 根窗口,
像素值实测 `(0,0,0)`,浅色页面上很显眼。

有意思的是它不是"固定减一":要 `1026×770` 时 Chrome 给的**正好是 1026×770**,
没有被裁。所以那 1 像素是"窗口铺满屏幕时"才发生的事。

于是做法是**多要两格**,超出显示的部分被裁掉,画面铺满。代价写在明处:

| | 黑边方案(原来) | 多要两格(现在) |
| --- | --- | --- |
| 画面 | 1024×768,**右下各一列纯黑** | 1024×768,**铺满** |
| 页面视口 | 1023×767 | 1026×770 |
| 代价 | 一条始终可见的黑边 | 页面右下各 2 像素在可见区域外 |

选后者:一条黑边在浅色页面上一直看得见,而 2 像素的页面内容切掉基本不可察觉。

## 11. 原生对话框:实测推翻了一个假设

有一种说法是"只要 CDP 客户端执行了 `Page.enable`,Chrome 就不再渲染原生弹窗"。
**在 headless 下看起来成立,在有头下不成立** —— 而 xpra 模式恰恰是有头的。

实测:`Page.enable` → 页面里 `alert()` → `Page.javascriptDialogOpening` 确实抛了,
**同时 Chrome 把对话框画了出来**,页面变灰、顶部一个 "example.com says" 的框。
headless 下看不见它,是因为**它什么都不画**,不是因为 CDP 抑制了它。

更要命的是第二步实测:**那个 OK 按钮点不掉。**

```
Input.dispatchMouseEvent(mousePressed/mouseReleased @ OK 按钮坐标)
  → 没有 Page.javascriptDialogClosed
```

因为它是**浏览器进程画的 UI,不是页面内容**,而 `Input.*` 打的是渲染进程。
[11 §2.1](11-xpra.md) 又规定了输入不走 xpra —— 于是**我们允许的任何输入路径
都关不掉这个框**,只有 `Page.handleJavaScriptDialog` 能。

三条结论:

1. **我们自己那张卡片不是可选项,是必需品。** 它的按钮是画面上唯一有效的按钮。
   [11 §5](11-xpra.md) 的结论对,但理由要换 —— 不只是"程序会卡住",
   是**人也点不动**。
2. **卡片必须是覆盖整个视口的 scrim,不能是浮在角落的提示条。**
   因为它要盖住 Chrome 自己画的那一份,否则画面上同时有两个对话框,
   而其中一个是死的。这是 xpra 模式独有的约束,screencast 下无所谓。
3. [11 §5](11-xpra.md) 末尾那段"白拿的好处:人在画面里点了原生对话框,
   `javascriptDialogClosed` 会让我们的记账跟着清" —— **删掉,人点不了。**

## 12. 落地时撞到的三件事

设计稿写完之后照着实现了一遍(`webmuxd/xpra.py`、`view/relay.py`、
`view/static/{rencode,xpra}.js`)。**跑通之前撞了三个坑,每个都值得记下来**,
因为它们都属于"看代码看不出来、跑一次立刻现形"的那一类。

### 12.1 `steal: false` 会被拒,哪怕我们是唯一的客户端

握手里报 `"steal": false`(意思是"我不抢别人的位子")看起来是最礼貌的选择。
实测**连不上**,服务端回 `session busy (this session is already active)`。

看它的判断([`server/subsystem/sharing.py`](https://github.com/Xpra-org/xpra)):

```python
if not c.boolget("steal", True) and self.server._server_sources:
    return f"{SESSION_BUSY}:this session is already active"
```

而 `_server_sources` **在我们这个唯一的客户端连上去之前就不是空的**。
所以正确的组合是 `steal: true` + `share: true`:前者绕开这个检查,
后者才是"多人同看"真正靠的那个字段(配 `--sharing=yes`)。

顺带一条:服务端会把 **uuid 相同**的旧连接踢掉。uuid 要真随机 ——
用时间戳的话,同一毫秒开两个标签页会互相踢。

### 12.2 `heartbeat=0` 不是"关掉心跳",是"立刻超时"

代理那头 `web.WebSocketResponse(heartbeat=0)` —— 我的本意是"这一层不要再加一份
心跳,xpra 自己有 `ping`/`ping_echo`"。aiohttp 的实现是
`call_later(heartbeat, ping)` 加一个 `heartbeat/2` 的 pong 超时,
**0 的意思是马上 ping、马上判超时**,于是连上就断。要写 `None`。

症状极具误导性:WebSocket 升级返回 101(日志里看着一切正常),然后立刻关。
一开始我以为是 xpra 拒了我们。

### 12.3 虚拟显示是打包方定的,不是我们定的 —— 探到了也没用

真机上(阿里云,RHEL 系,xpra 6.5.2)第一次跑就挂:

```
failed to locate Xorg binary to run
Xvfb command has terminated! xpra cannot continue
 full command: "xpra_Xdummy -novtswitch … -config '${XORG_CONFIG_PREFIX}/root/xorg.conf' …"
```

**同一份 xpra,虚拟显示由发行版的打包方选**,写在
`/etc/xpra/conf.d/55_server_x11.conf` 的 `xvfb =` 那一行:

| | 默认的 vfb | 要什么 |
| --- | --- | --- |
| Debian / Ubuntu | `Xvfb` | `xvfb` 包 |
| RHEL / CentOS / 阿里云 | **`xpra_Xdummy`** | **整个 Xorg** —— 云主机上基本没有 |

最难受的一点是它**绕过了我们的探测**:`shutil.which("Xvfb")` 明明探到了,
xpra 转头去用 Xdummy,然后挂在完全另一个地方。

> **探的东西和用的东西必须是同一个。** 探测只有在"我们探的那个就是接下来要跑的
> 那个"时才成立;中间隔着一层别人的配置,探测就变成了一句安慰话。

所以改成 `--xvfb=Xvfb …` 显式指定,不看发行版配置 —— 这和
[07 §4.1](07-runtime.md) 把浏览器版本钉死是同一条:**跑的是哪一个,得由我们说了算。**

顺带,那次报错的头一句是"xpra 起来了但浏览器的 CDP 没监听",把人往浏览器的方向指,
而问题在 X 那一层。现在会先看 xpra 进程还在不在,分别说"xpra 自己退了 ——
多半是虚拟显示没起来"和"xpra 在跑,但浏览器的 CDP 没监听"。
**头一句话指错方向,后面的日志再全也白搭。**

### 12.4 顺带发现:观看页已经坏了两个版本

写这一篇时给观看页加了一条 `node --check`,**当场发现 0.5.5 和 0.5.6 发出去的
`index.html` 整个 `<script>` 是语法错的** —— 删一个分支时,
`} else if (m.type === "quality") {` 这一整行被吞进了上一行注释里。

语法错意味着**整个脚本一行都不执行**:没有画面、没有输入、没有 tab 条。
两个版本没人发现,是因为**没有任何测试碰过那个文件**。

现在有两条挡着(`tests/pixels_from_xpra/`):

| | 覆盖什么 | 依赖 |
| --- | --- | --- |
| 注释里不许出现 `) {` / `} else` | **正是这个错法** | 无,永远跑 |
| `node --check` + `import()` 每个模块 | 一切语法错 | 有 node 才跑 |

第一条不依赖任何外部工具,所以它**永远会跑** —— 这是刻意的:一条"装了才跑"的
测试,在没装的机器上等于不存在。

## 13. 还没验的

- **h264 到底强多少**。§8 解释了为什么没测到,但"报上 `full_csc_modes` 之后
  同一段动画的码率"这个数还是空的。这是决定要不要上 WebCodecs 的唯一依据。
- **那 1 像素到底是谁吃的**(§10)。现在是绕过去的(多要两格),不是查清了。
  要是哪天 Chrome 改成少两格,黑边会回来 —— 更稳的做法是起来之后用 CDP 量一遍
  实际窗口尺寸,对不上就纠正,而不是靠一个常数。
- **`auto-refresh`**([11 §1](11-xpra.md) 说的"静止后补一张无损的")在我们
  这套 caps 下有没有生效。滚动那轮里有 40 个 png、总共 5 KB,像是它,但没确认。
- **多 tab 时的 X 窗口数**。desktop 模式下 popup 被合成了(§6),但
  `window.open` 出来的**真窗口**是另一回事,还没测。

## 14. ↔ 别处

- [11](11-xpra.md) —— 本篇是它 §7、§8 的答案,并修正了它的 §2.1、§3、§4、§5
- [02](02-frame-protocol.md) —— 我们自己那套帧协议,§2/§9 全程在和它对照
- [09](09-wire-format.md) —— 线格式横向对比,本篇给它补上了 xpra 那一列
- [06](06-no-desktop.md) —— 六类原生 UI,§11 加强了它在 xpra 下的必要性
