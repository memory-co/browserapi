# webmuxd · 设计稿

**webmuxd 是浏览器的 tmux + ttyd。** tmux 那一半照搬 —— session 活得比连接久、
tab 就是 window、`log.jsonl` 就是 scrollback;ttyd 那一半是自己写的,
因为**终端传的是语义,浏览器传的是像素**。

这一整套文档就是「ttyd 那一半」的展开。

## 怎么读

**先读 [a](a-architecture.md)。** 它从前到后走一遍整条链路,
把每一跳的职责说清楚;其余各篇是其中一条的展开,可以按需跳读。

带数字后缀的是**参考篇**:[c1](c1-quality.md) 与 [e1](e1-wire-format.md)
只回答「具体是什么值、长什么样」,不做论证 —— 论证在它们对应的主篇里。

## 十三篇

| | | |
| --- | --- | --- |
| **[a](a-architecture.md)** | 架构基础定位 | 整条链路从前到后:Chromium ◀CDP▶ sessiond ◀WS▶ 客户端。**CDP 是 RPC 不是流**(画面和输入都得主动要);sessiond 是唯一持有状态的进程;客户端的位置换了(**ttyd 省去了协议,这一侧省去了渲染**) |
| **[b](b-input.md)** | 输入翻译 | 一次鼠标移动从观看端到 Chromium 的**完整八步**;这层翻译是整个安全模型的收口 —— 观看者可表达的意图只有 `Input` 域那四个命令。IME 组字不出本地,是少数优于 VNC 的地方 |
| **[c](c-view.md)** | 像素从哪来 | 第一条来源(CDP 截屏)的结构上限 → 为什么引入第二条 → **两者产出的本来就是同一种东西**,于是「像素从哪来」是一个干净的接缝。§13 拿 **rrweb 与 Playwright trace** 验了这条判据:两个都不能当来源,**但都能当产物** —— 那三条代价全都指向「有人在上面操作」,而非它们传什么。附:xpra / Xvfb / Xorg 各是什么、要探什么 |
| **[c1](c1-quality.md)** | 画质(参考) | 糊有**三个互不相干的来源**,调错旋钮没有任何效果;渲染倍率要三处同时对上,且它是 session 级的;按往返时间降质,**先降画质再抽帧** |
| **[d](d-install.md)** | install | 产出**不是「装好了」,是一份路径表**;能下载的下载、该装的还是装,判据是**数据还是程序**;七步落地顺序 |
| **[e](e-client.md)** | 观看端的客户端 | 这个位置在 ttyd 侧是 xterm.js,这里**没有现成实现** —— 它做的不是渲染而是协议。§6 是**通道模型**:每条通道对应一个上游系统,由固定的优先级表仲裁(**帧取 xpra、光标取 CDP**),而**输入永远只走一条** |
| **[e1](e1-wire-format.md)** | 线上格式(参考) | 两条通道逐字节:28 字节头与 `targetId` 那个字节序坑、上下行消息集合、xpra 的 8 字节头与包数组下标;额度与缓冲的具体数值 |
| **[f](f-tabs.md)** | tab | 外挂的 bar,**和真的那个是同一份数据** —— 不是副本,因此没有可漂移的东西;`active` 从一本账变成当前事实 |
| **[g](g-native-ui.md)** | 浏览器自己的 UI | 对话框、下载、文件选择、权限、认证 —— 在画面里**要么不存在,要么存在但点不动**,必须逐类接管。不替使用者决定,超时一律偏向取消 |
| **[h](h-runtime.md)** | 浏览器从哪来 | runtime 只产出**一个 CDP 端点**;不碰容器(把 webmuxd 放进去,而不是反过来);root 下自动关沙箱但必须说出来 |
| **[j](j-layout.md)** | 代码摆在哪 | 顶层按语言分两棵树:`webmuxd/`(Python)· `webmuxjs/`(JS,再分 client 和只放协议文档的 server)。Python 那棵先按**两种用法**分(命令行 / import),再按**对谁做事**分;**目录要让接缝看得见** —— 画面和输入必须分开 |
| **[i](i-agent-surface.md)** | agent 的操作面与行为流 | 三层操作面(`open` 为什么不在动词表里)、封闭动词表与 `js` 逃生舱;人和 agent 进**同一条流**且标明是谁做的 —— **记控件身份,不记控件内容** |

## 明确不做

- ❌ **不做 H.264 / VP8 / WebRTC。** 不是做不到 —— xpra 那边编码器是现成的。
  真正的理由是:**客户端不声明视频编码,服务端就不会发送**。
  这是一个随时可以反悔的选择,加上色彩空间声明和一个解码分支即可,协议层不动。
  不急的原因是还没量到它值多少([c §17](c-view.md#17-还没定的))。
- ❌ **不做音频。** xpra 自带音频转发,是我们主动关的 —— 它与「只负责像素」这条
  主线无关,而且会把 GStreamer 拖进依赖。**从「没有」变成了「不要」。**
- ❌ **不做桌面。** 有头那条路上 X 显示是真的,但浏览器以 `--kiosk` 铺满整个显示,
  **画面里永远只有一个窗口**。文件管理器、右键菜单、非浏览器程序都没有,也不打算有。
- ❌ **不碰容器。** 不起容器、不认容器、不探 docker。要隔离就**把 webmuxd 放进容器里**
  ([h §2](h-runtime.md#2-不碰容器))。
- ❌ **不做编排 / 多租户 / 计费。** 判据是那一句:**tmux 会做这个吗?**

## 落地在哪

每一篇都不是计划书 —— 下面每一行都在跑,`tests/` 里有对应的场景守着。

| | 代码 | 测试 |
| --- | --- | --- |
| **画面模式与切换** | [`view/modes.py`](../../../webmuxd/view/modes.py) · [`view/cast.py`](../../../webmuxd/view/cast.py) `switch()` | [`pixels_from_xpra/`](../../../tests/pixels_from_xpra/) |
| 帧协议 · 回执 · 自适应 | [`view/cast.py`](../../../webmuxd/view/cast.py) · [`viewer.py`](../../../webmuxd/view/viewer.py) · [`quality.py`](../../../webmuxd/view/quality.py) | [`pixels_on_a_wire/`](../../../tests/pixels_on_a_wire/) |
| 输入翻译(安全收口) | [`view/input.py`](../../../webmuxd/view/input.py) · [`cursor.py`](../../../webmuxd/view/cursor.py) | [`pixels_on_a_wire/`](../../../tests/pixels_on_a_wire/) |
| 一个口 · token · 只读 | [`serve/app.py`](../../../webmuxd/serve/app.py) | [`one_endpoint/`](../../../tests/one_endpoint/) · [`the_http_face/`](../../../tests/the_http_face/) |
| tab 表 | [`core/tabs.py`](../../../webmuxd/core/tabs.py) | [`tab_identity/`](../../../tests/tab_identity/) · [`chrome_facts/`](../../../tests/chrome_facts/) |
| 浏览器自己的 UI | [`native/`](../../../webmuxd/native/) | [`no_desktop/`](../../../tests/no_desktop/) |
| runtime | [`runtime/`](../../../webmuxd/runtime/) | [`one_endpoint/`](../../../tests/one_endpoint/) |
| install · 系统包 | [`cli/install.py`](../../../webmuxd/cli/install.py) · [`cli/deps.py`](../../../webmuxd/cli/deps.py) | [`installing/`](../../../tests/installing/) |
| xpra:起 · 代理 · 白名单 | [`xpra.py`](../../../webmuxd/xpra.py) · [`view/relay.py`](../../../webmuxd/view/relay.py) | [`pixels_from_xpra/`](../../../tests/pixels_from_xpra/) |
| 观看端客户端 | [`static/index.html`](../../../webmuxd/view/static/index.html) · [`xpra.js`](../../../webmuxd/view/static/xpra.js) · [`rencode.js`](../../../webmuxd/view/static/rencode.js) | [`pixels_from_xpra/`](../../../tests/pixels_from_xpra/) |
| 动作与行为流 | [`core/act.py`](../../../webmuxd/core/act.py) · [`core/log.py`](../../../webmuxd/core/log.py) | [`pointing_at_things/`](../../../tests/pointing_at_things/) · [`the_scrollback/`](../../../tests/the_scrollback/) |
| **文档本身** | — | [`the_docs_are_true/`](../../../tests/the_docs_are_true/) —— 链接、锚点、以及文档里的数字与代码一致 |

## 文档与实现的差距

已知不一致,写在这里而不是散在各篇:

| | |
| --- | --- |
| 中途切到 DOM | 当前页要等下一次导航才有记录器 —— 补注入那条路是现成的,还没接上([c §9.4](c-view.md#94-切到-dom-要先把记录器注进去)) |
| 协议客户端 | DOM 那条的重放器是第三方库,和另外两条不一样(直接引 rrweb),没有独立成模块 |
| 协议客户端 | xpra 那条已独立成模块,另一条仍在内置页内([e §9](e-client.md#9-该发出去的是哪一层)) |
