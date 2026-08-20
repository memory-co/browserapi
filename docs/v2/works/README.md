# webmuxd v2 · 设计稿

**v1 是 tmux + 一个租来的 ttyd,v2 里 ttyd 那一半是自己写的。**

[v1/works/README](../../v1/works/README.md) 开篇那句"webmuxd ≈ tmux + ttyd"到 v2 才真正成立。
v1 的画面是 kasm / jlesage 的产品,我们只报 URL;**v2 的画面是我们自己产的** ——
从编码参数到背压到输入翻译,每一段都在我们手里。

> **读之前先知道一件事:像素有两个来源,而别的一切只有一套。**
>
> `01`–`10` 写的是 CDP `Page.startScreencast` 那条(v2 的第一条,也是现在的退路);
> `11`–`12` 是 xpra 那条,**0.7.0 起它是默认**。
> 两条之间**唯一的差别是像素从哪来** —— 输入、光标、tab、只读、原生 UI、日志、
> token 完全共用([11 §5](c-pixels.md#5-接缝切在哪))。
> 所以 `03`(输入)、`04`(一个口)、`05`(tab)、`06`(原生 UI)这四篇**两条路都算数**;
> `02`(帧协议)和 `09`(线格式)只讲 screencast 那条。

思路的来源是 [BrowserBox](https://github.com/BrowserBox/BrowserBox) 那套 RBI 架构,
以及照着它写的一个约 700 行的最小实现(`~/browserbox/demo/`)——
本目录里凡是标着**「demo 实测」**的数字都出自那儿,标着**「本轮实测」**的出自
2026-08-17 在 Chromium 151 上跑的探针。

## 变的是哪一半

```
        人 ──HTTP/WS──> webmuxd ──CDP──> Chromium
                          ▲                  │
        代码 ─HTTP/lib──┘   帧 / 输入 ←──────┘

v1:    ────────────────┘        └──── VNC 桌面(别人的)────> 人
```

| | v1 | v2 |
| --- | --- | --- |
| 画面从哪来 | 镜像里的 KasmVNC / TigerVNC | **自己产**:默认 xpra 按区域编码,退路是 CDP `Page.startScreencast` |
| 人的输入怎么进去 | VNC 协议,我们不参与 | **CDP `Input.*`,我们翻译** |
| 对外几个口 | 两个(画面口 + API 口) | **一个** |
| 画面里有什么 | 整个桌面(含 tab 条、地址栏,要裁掉) | **只有页面内容** |
| 定位 / 观测 / 日志 / tab 表 | | **一个字没动** |

## 文档

> **正在重写。** `01`–`13` 是按落地顺序攒出来的,读起来像流水账 ——
> 一个新来的人得读完七篇才知道这东西整体长什么样。
>
> 新的一套按**字母**编,按"要理解这个系统,该先知道什么"排,
> **是重写不是搬运** —— 写完一篇,对应的旧篇就删掉。
> 所以新篇**不往 `01`–`13` 引**;旧篇在被删之前原地留着,仅供参考。

### 新的一套(重写中)

| 文件 | 内容 |
| --- | --- |
| [e1-wire-format.md](e1-wire-format.md) | **线上格式(e 的参考篇)** —— 两条通道逐字节:28 字节头的布局与 `targetId` 那个字节序坑、下行/上行消息集合、xpra 的 8 字节头与包数组下标;末尾是额度与缓冲的具体数值。**不做论证,只回答「长什么样」** |
| [e-client.md](e-client.md) | **观看端的客户端** —— 这个位置在 ttyd 侧由 xterm.js 承担,这里**没有现成实现**;它做的不是渲染而是协议;分三层,**只有协议层无法由外部实现**;§6 是**通道模型**:每条通道对应一个上游系统(`/channel/cdp` ↔ Chromium,`/channel/xpra` ↔ xpra),声明自己能提供什么,由固定的优先级表仲裁 —— **帧优先取 xpra、光标优先取 CDP**;可并列加第三条(**写代码,不是注册插件** —— 这个模型买的是写客户端时的清晰度),但**输入永远只走 `/channel/cdp`** |
| [d-install.md](d-install.md) | **install:一次探清楚,之后不再猜** —— 产出是**一份路径表**(浏览器 / xpra / Xvfb / 跑 xpra 的那个解释器),不是「装好了」;能下载的下载、该装的还是装,判据是**数据还是程序**;七步落地顺序 |
| [c-pixels.md](c-pixels.md) | **像素从哪来:两条腿** —— CDP 的 JPEG 和 xpra 的区域图**本来就是同一种东西**,所以"像素从哪来"是个干净的接缝:接缝之上只有一套,之下可以有两条腿。附:Xvfb/xpra/Xorg 各是什么、要探什么、以后还能插什么进来 |
| [b-input.md](b-input.md) | **输入翻译,以及它换来的东西** —— 观看者能表达的意图被限制在 `Input` 域那四个命令里;键盘要发真实 `keyDown` 不是 `insertText`;**IME 反而比 VNC 短**(组字不出本地);光标既不在像素也不在协议里 |
| [a-architecture.md](a-architecture.md) | **架构基础定位** —— 从前到后走一遍整条链路:Chromium ◀CDP▶ sessiond ◀WS▶ 客户端。CDP 是 RPC 不是流(画面和输入都得主动要);sessiond 是唯一有状态的那个;客户端的位置换了(**ttyd 省下了协议,我们省下了渲染**) |

完整路线图见 [a §8](a-architecture.md#8-往下写什么)。

### 旧的一套(写完对应篇就删)

| 文件 | 内容 |
| --- | --- |
| [01-frame-source.md](01-frame-source.md) | **画面自己产** —— 判据为什么翻转,VNC 整条砍掉,代价老实写 |
| [02-frame-protocol.md](02-frame-protocol.md) | 帧怎么发 —— **原样照抄 demo**,写的是"抄的时候哪几处不能想当然改" |
| [e1-wire-format.md](e1-wire-format.md) | **线上格式(e 的参考篇)** —— 两条通道逐字节:28 字节头的布局与 `targetId` 那个字节序坑、下行/上行消息集合、xpra 的 8 字节头与包数组下标;末尾是额度与缓冲的具体数值。**不做论证,只回答「长什么样」** |
| [e-client.md](e-client.md) | **观看端的客户端** —— 这个位置在 ttyd 侧由 xterm.js 承担,这里**没有现成实现**;它做的不是渲染而是协议;分三层,**只有协议层无法由外部实现**;§6 是**通道模型**:每条通道对应一个上游系统(`/channel/cdp` ↔ Chromium,`/channel/xpra` ↔ xpra),声明自己能提供什么,由固定的优先级表仲裁 —— **帧优先取 xpra、光标优先取 CDP**;可并列加第三条(**写代码,不是注册插件** —— 这个模型买的是写客户端时的清晰度),但**输入永远只走 `/channel/cdp`** |
| [d-install.md](d-install.md) | **install:一次探清楚,之后不再猜** —— 产出是**一份路径表**(浏览器 / xpra / Xvfb / 跑 xpra 的那个解释器),不是「装好了」;能下载的下载、该装的还是装,判据是**数据还是程序**;七步落地顺序 |
| [c-pixels.md](c-pixels.md) | **像素从哪来:两条腿** —— CDP 的 JPEG 和 xpra 的区域图**本来就是同一种东西**,所以"像素从哪来"是个干净的接缝:接缝之上只有一套,之下可以有两条腿。附:Xvfb/xpra/Xorg 各是什么、要探什么、以后还能插什么进来 |
| [b-input.md](b-input.md) | 输入翻译**是**安全收口;IME、剪贴板、光标同步 |
| [e1-wire-format.md](e1-wire-format.md) | **线上格式(e 的参考篇)** —— 两条通道逐字节:28 字节头的布局与 `targetId` 那个字节序坑、下行/上行消息集合、xpra 的 8 字节头与包数组下标;末尾是额度与缓冲的具体数值。**不做论证,只回答「长什么样」** |
| [e-client.md](e-client.md) | **观看端的客户端** —— 这个位置在 ttyd 侧由 xterm.js 承担,这里**没有现成实现**;它做的不是渲染而是协议;分三层,**只有协议层无法由外部实现**;§6 是**通道模型**:每条通道对应一个上游系统(`/channel/cdp` ↔ Chromium,`/channel/xpra` ↔ xpra),声明自己能提供什么,由固定的优先级表仲裁 —— **帧优先取 xpra、光标优先取 CDP**;可并列加第三条(**写代码,不是注册插件** —— 这个模型买的是写客户端时的清晰度),但**输入永远只走 `/channel/cdp`** |
| [d-install.md](d-install.md) | **install:一次探清楚,之后不再猜** —— 产出是**一份路径表**(浏览器 / xpra / Xvfb / 跑 xpra 的那个解释器),不是「装好了」;能下载的下载、该装的还是装,判据是**数据还是程序**;七步落地顺序 |
| [c-pixels.md](c-pixels.md) | **像素从哪来:两条腿** —— CDP 的 JPEG 和 xpra 的区域图**本来就是同一种东西**,所以"像素从哪来"是个干净的接缝:接缝之上只有一套,之下可以有两条腿。附:Xvfb/xpra/Xorg 各是什么、要探什么、以后还能插什么进来 |
| [b-input.md](b-input.md) | 一个口:session 形状、token、只读分享 |
| [05-active-tab.md](05-active-tab.md) | tab 外挂模式一字不改;`active` 从两份真相合成一份 |
| [06-no-desktop.md](06-no-desktop.md) | 没有桌面之后:六类原生 UI 用 CDP 收回来 —— **v2 唯一的真实工作量** |
| [07-runtime.md](07-runtime.md) | 浏览器从哪来:**容器不要了**、`webmuxd install` 下一个(照着 playwright)、本机起一个进程 |
| [e1-wire-format.md](e1-wire-format.md) | **一帧逐字节长什么样** —— ttyd 一个字节、我们二十八个,为什么;三家的上行怎么组织;以及**那个缺掉的协议客户端** |
| [e1-wire-format.md](e1-wire-format.md) | **线上格式(e 的参考篇)** —— 两条通道逐字节:28 字节头的布局与 `targetId` 那个字节序坑、下行/上行消息集合、xpra 的 8 字节头与包数组下标;末尾是额度与缓冲的具体数值。**不做论证,只回答「长什么样」** |
| [e-client.md](e-client.md) | **观看端的客户端** —— 这个位置在 ttyd 侧由 xterm.js 承担,这里**没有现成实现**;它做的不是渲染而是协议;分三层,**只有协议层无法由外部实现**;§6 是**通道模型**:每条通道对应一个上游系统(`/channel/cdp` ↔ Chromium,`/channel/xpra` ↔ xpra),声明自己能提供什么,由固定的优先级表仲裁 —— **帧优先取 xpra、光标优先取 CDP**;可并列加第三条(**写代码,不是注册插件** —— 这个模型买的是写客户端时的清晰度),但**输入永远只走 `/channel/cdp`** |
| [d-install.md](d-install.md) | **install:一次探清楚,之后不再猜** —— 产出是**一份路径表**(浏览器 / xpra / Xvfb / 跑 xpra 的那个解释器),不是「装好了」;能下载的下载、该装的还是装,判据是**数据还是程序**;七步落地顺序 |
| [c-pixels.md](c-pixels.md) | **画面默认走 xpra** —— 但它只负责像素:两条 WS、输入不走它(收口不动)、`--kiosk` 让 bar 根本不出现、原生 UI 照旧归我们 |
| [13-agent-surface.md](13-agent-surface.md) | **给 agent 的操作面 + 一条行为流** —— 横向看了七家云浏览器;`open` 为什么不在动词表里;人和 agent 在同一条流里且带 `user`(**这条是白拿的,给 CDP 直通的平台做不到**);人一碰 agent 自动让路 vs 他们的显式交接 |
| [c-pixels.md](c-pixels.md) | **客户端解码,实测** —— xpra-html5 里没有解码器,自写三百来行;`start-desktop` + `--kiosk`;`scroll` 用零字节干掉 57% 重绘面积 |

## 落地在哪

设计稿不是计划书 —— 下面每一行都已经在跑,`tests/` 里有对应的场景守着。

| | 代码 | 测试 |
| --- | --- | --- |
| 帧协议 · 两个 ack 环 · 自适应 | [`view/cast.py`](../../../webmuxd/view/cast.py) · [`viewer.py`](../../../webmuxd/view/viewer.py) · [`quality.py`](../../../webmuxd/view/quality.py) | [`pixels_on_a_wire/`](../../../tests/pixels_on_a_wire/) |
| 输入翻译(安全收口) | [`view/input.py`](../../../webmuxd/view/input.py) · [`cursor.py`](../../../webmuxd/view/cursor.py) | [`pixels_on_a_wire/`](../../../tests/pixels_on_a_wire/) |
| 一个口 · token · 只读 | [`serve/app.py`](../../../webmuxd/serve/app.py) | [`one_endpoint/`](../../../tests/one_endpoint/) · [`the_http_face/`](../../../tests/the_http_face/) |
| 六类原生 UI | [`native/`](../../../webmuxd/native/) | [`no_desktop/`](../../../tests/no_desktop/) |
| runtime(process · remote) | [`runtime/`](../../../webmuxd/runtime/) | [`one_endpoint/`](../../../tests/one_endpoint/) |
| `webmuxd install` · 系统包 | [`cli/install.py`](../../../webmuxd/cli/install.py) · [`cli/deps.py`](../../../webmuxd/cli/deps.py) | [`installing/`](../../../tests/installing/) |
| xpra:起 · 代理 · 白名单 | [`xpra.py`](../../../webmuxd/xpra.py) · [`view/relay.py`](../../../webmuxd/view/relay.py) | [`pixels_from_xpra/`](../../../tests/pixels_from_xpra/) |
| xpra 客户端(协议 + 解码) | [`static/xpra.js`](../../../webmuxd/view/static/xpra.js) · [`rencode.js`](../../../webmuxd/view/static/rencode.js) | [`pixels_from_xpra/`](../../../tests/pixels_from_xpra/) |
| 观看页(两条路共用) | [`static/index.html`](../../../webmuxd/view/static/index.html) | [`pixels_from_xpra/`](../../../tests/pixels_from_xpra/) |

## 明确不做

v1 那份[「明确不做」](../../v1/works/README.md#明确不做)全部继承(控制面 / 数据库 / 多租户 /
内置 LLM / k8s operator),判据仍然是那一句:**tmux 会做这个吗?**

v2 自己新增四条,都是"自己产画面"这个决定的直接推论。**0.7.0 换了默认之后,
四条的结论都没变,但其中三条的理由变了** —— 理由变了却不改,文档就开始撒谎:

- ❌ **不做 H.264 / VP8 / WebRTC。**
  原来的理由是"帧间编码是另一个量级的工程(编码器、抖动缓冲、NACK/PLI、SFU)"。
  **现在这条理由不成立了** —— xpra 那边编码器是现成的,h264/vp8/vp9 都在。
  真正的理由换成了一句更准的话:**我们的客户端不报视频编码,所以服务端永远不发。**
  这不是做不到,是**一个随时可以反悔的选择**:加上 `full_csc_modes` 和一个
  WebCodecs 分支就有了,协议层不动([12 §8](c-pixels.md#11-客户端))。
  不急着做的原因是还没量到它值多少 —— 那是 [12 §13](c-pixels.md#13-还没定的) 的第一条。
- ❌ **不做音频。**
  原来的理由是"kasm 的镜像有,我们没有",算 v2 相对 v1 的净损失。
  **现在也不成立了** —— xpra 自带音频转发(要 GStreamer),我们是**主动关掉的**
  ([`xpra.py` 的 `OFF`](../../../webmuxd/xpra.py))。理由换成:它和"画面只负责像素"
  这条主线无关,而且会把 GStreamer 拖进依赖里。**从"没有"变成了"不要"。**
- ❌ **不做桌面。**
  原来的理由是"headless 里根本没有这些东西"。**xpra 那条路上浏览器是有头的**,
  X 显示是真的,`start-desktop` 里甚至有窗口管理器。所以理由要换:
  我们用 `--kiosk` 让浏览器铺满整个显示,**画面里永远只有一个窗口**;
  文件管理器、右键菜单、非浏览器程序仍然没有,也不打算有
  ([11 §5](c-pixels.md#5-接缝切在哪))。要完整桌面就该用远程桌面,不是用这个。
- ❌ **不保留 VNC 作为开关。**
  这一条**理由没变,但要限定范围**。[01 §5](01-frame-source.md#5-为什么不留一个开关)
  拒绝的是 `view="vnc" | "screencast"` 那个形状,论证是"两套输入路径、两套权限模型、
  两套 runtime 契约,没有一处能共用"—— **那对 VNC 仍然全对**。
  而 `--transport screencast|xpra` 不是同一个东西:输入路径和权限模型**完全共用**,
  只有像素那一段不同,而且**默认只有一个**([11 §6](c-pixels.md#10-默认走哪条))。
  screencast 是 xpra 装不上时的明确退路,以及 `remote` 上唯一能用的那个 ——
  不是"两边都行、你挑一个"。
