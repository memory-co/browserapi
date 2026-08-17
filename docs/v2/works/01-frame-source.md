# 01 · 画面自己产

**一句话**:画面不再来自镜像里的 VNC,而是 webmuxd 用 CDP 的 `Page.startScreencast`
自己产帧、用 `Input.*` 自己收输入。VNC 这条路整条砍掉,不留开关。

## 1. 判据翻转了

v1 的分界线写得很清楚([v1/works/08 §2](../../v1/works/08-browser-runtime.md#2-判据哪一半在契约里)):

> **CDP 在契约里,画面不在。**
> …webmuxd 对那个端口做的唯一一件事,是把 URL 报出来。它不代理、不转发、
> 不解析里面一个字节,也不知道那边是 WebSocket 还是 WebRTC。

这条判据当时是对的,但它有个**没写出来的前提**:画面是别人的产品。
判的是"用户会不会直接碰到它" —— 而用户碰到的是 kasm 的前端,不是我们的代码,
所以除了报 URL 我们什么也做不了。

现在这个前提没了。`Page.startScreencast` 说明**画面也可以是 CDP 的产物**。
于是同一条判据给出相反的答案:

| | v1 | v2 |
| --- | --- | --- |
| 画面由谁产 | 镜像作者 | **我们** |
| 用户碰到的是谁的代码 | kasm / jlesage 的前端 | **我们的** |
| 换掉画面实现,webmuxd 要不要改 | 不用 | 那就是**改 webmuxd 自己** |
| 结论 | 画面不在契约里 | **画面在契约里** |

**v2 的契约因此塌成一条**:

```
一个 CDP 端点   http://<host>:<port>    ← 唯一的外部依赖
```

产出这一样的东西,就是一个 runtime。画面不再是 runtime 的义务
—— 它是 webmuxd 的产物([07](07-runtime.md))。

## 2. 一整篇设计随之作废

v1 的 [works/04](../../v1/works/04-chrome-ui-externalization.md) 全篇在解决一件事:
**怎么把 Chromium 自带的 tab 条和地址栏弄没**。

VNC 拍的是整个桌面,里面必然有浏览器自己那套 UI,而我们要外面自己画 tab 条
(那是 webmuxd 的卖点之一)。于是有了:iframe 负 margin 裁 `crop_top`、
用 `window.outerHeight - window.innerHeight` 量它、运行时变了还要发
`viewport.changed` 让外面重裁、人按 `Ctrl+L` 焦点跑进被裁掉的地址栏还要抢回来。

**screencast 拍的是页面内容,不含浏览器 chrome。** 上面每一条都不存在了。

```
v1 的帧:  ┌──────────────┐        v2 的帧:  ┌──────────────┐
          │ tab 条/地址栏 │ ← 裁掉            │              │
          ├──────────────┤                  │   页面内容    │
          │   页面内容    │                  │              │
          └──────────────┘                  └──────────────┘
          还有桌面壁纸、任务栏、窗口边框
```

works/04 从"一篇需要论证可行性的设计"降级成 v2 的**前提**。
它剩下的价值只有两处,都继承下来:§3 那张「外面画 tab 条需要什么,CDP 给不给」的
能力对照表,和 §6 那批原生对话框 —— 后者在 v2 从"碰到再加"变成必须做([06](06-no-desktop.md))。

## 3. 白捡的四样

不是"顺便也能做",是这个决定的**直接推论** —— 因为输入和画面都在我们手里了:

**① 只读分享是真的。** v1/works/README 写着"分享链接默认只读,要操作得显式要完整 token",
但 VNC 那条路做不到:我们不在输入通道上,只能给 VNC 密码,而密码只有"给不给"没有"给多少"。
v2 里只读 = **收到的输入事件不翻译成 `Input.*`**,一行判断,而且是**服务端**丢弃的
—— 不是前端把按钮 disable 掉那种假只读([04 §3](04-one-port.md#3-读和写是两个-token))。

**② 中文输入不再是老大难。** VNC 的 IME 要么在服务端装一套输入法(还得同步候选词框的像素),
要么忍受客户端组字与服务端按键的错位。screencast 这条路上,**组字全在客户端本地完成**,
IME 提交后只发最终文本 —— 远端 Chromium 收到的就是一个带 `text` 的 `keyDown`。
这是 v2 相对 v1 的**净胜**,不是打平([03 §3](03-input.md#3-ime输入法这条路反而更短))。

**③ 剪贴板可控。** 客户端的 `paste` 事件 → 一条 `Input.insertText`。
反向(远端复制 → 本地剪贴板)靠 `Runtime` 读 `document.getSelection()`,
或页面调 `navigator.clipboard.writeText` 时拦下来。粒度是我们定的。

**④ 观测和画面同源。** `observe()` 的标注截图和人看到的帧来自同一条 screencast,
同一个 `deviceWidth/deviceHeight`。v1 里前者是 `Page.captureScreenshot`、
后者是 VNC 的桌面,两套坐标系,分辨率对不上过一次(见 CHANGELOG 0.3.1)。

## 4. 代价,老实写

| | 说明 |
| --- | --- |
| **带宽** | 没有帧间压缩,每帧都是完整 JPEG。demo 实测(1280×800 q80,youtube):静止 **0 kbps**,搜索结果页静置 8.5 fps / 2.7 Mbps,持续滚动 10.4 fps / **10.2 Mbps**。VNC 的区域重传在这一项上更省。缓解手段(RTT 自适应降质 + 抽帧)见 [02 §3](02-frame-protocol.md#3-rtt-自适应画质),但**改变不了量级**。**注意这一条只是带宽,不是体验** —— 见 §4.1 |
| **音频** | 没有。kasm 的镜像有,这是净损失 |
| **原生 UI 全部失去兜底** | 文件选择、下载、权限请求、Basic 认证、`alert`、PDF 查看器 —— headless 里根本不渲染。必须一条条用 CDP 收回来,这是 v2 唯一的真实工作量([06](06-no-desktop.md)) |
| **`--force-device-scale-factor` 是浏览器级的** | demo 实测:让 screencast 按 2x 出图只能靠这个启动参数,`Emulation.setDeviceMetricsOverride` 里的 `deviceScaleFactor` 对 screencast **完全无效**。所以一个 session 里所有 tab、所有观看者共用一个 dsf,不能按观看端的 dpr 各自匹配([02 §4](02-frame-protocol.md#4-清晰度三个独立的旋钮)) |
| **扩展 / 特殊页面** | headless 下扩展的 popup UI、`chrome://` 设置页这类浏览器自身界面,截不到也不该截 |

**带宽那条要说清楚**:它不是"实现得不够好",是 JPEG 截图流这条路线的本质特征。
真正的解法是 H.264/VP8 走 WebRTC,而那是另一个量级的工程,v2 明确不做
([works/README §明确不做](README.md#明确不做))。

## 4.1 但更费带宽 ≠ 更不流畅

这两件事必须分开说,**本文初稿把它们混成了一条,是错的**。

实测(2026-08-17):**在 YouTube 上看视频,screencast 比 kasm 和其它 VNC 方案都更流畅。**

也就是说 v2 在**最吃带宽的那个场景**上体验反而是最好的。这不是巧合,
全屏运动恰恰是区域重传的负收益区:

| | KasmVNC 那条路 | screencast 这条路 |
| --- | --- | --- |
| 帧从哪儿采 | 从 X framebuffer **抓屏** —— 等合成器画完、等 damage 事件、做 tile diff | 直接挂在 Chromium 合成器的输出上,**有新帧才产帧** |
| 视频/滚动时 | 整屏每帧全变,tile diff 是**纯开销**:既要 diff 又要整屏重编码 | 没有 diff 这一步 |
| 链路 | 渲染 → X → VNC 编码 → noVNC 解码 → canvas | 渲染 → JPEG → `<img>` |
| 帧节奏 | VNC 自己的采样节奏,和页面合成节奏**拍频**,抖动不均匀 | 跟着页面的合成节奏走 |

区域重传的收益全部来自"只有一小块变了" —— 打字、鼠标悬停、小面积重绘。
**画面整体在动时它没有优势,只有开销。**

两条推论:

- **v1 的[画面实测排名](../../v1/works/08-browser-runtime.md#4-画面那一半三种实现实测排名)
  (KasmVNC > TigerVNC > Selkies)是 VNC 方案之间的排名**,不是和 screencast 比出来的。
  别拿它当"v1 画面更好"的依据。
- **做 WebRTC 的压力比预想的小。** 如果 JPEG 流在最难的场景上已经赢了 VNC,
  那 H.264 要换的就只是带宽,不是流畅度 —— [明确不做](README.md#明确不做)那条更站得住。

> **待补**:这条目前是主观流畅度对比,还缺可复现的数字 ——
> 同一台机器、同一条链路、同一个视频,两边各量 fps 曲线、端到端延迟、码率、CPU。
> 落地前补上,它是 v2 最值得对外讲的一条。

## 5. 为什么不留一个开关

最容易想到的折中是 `view="vnc" | "screencast"`,让用户自己选。**不做。**

因为这两条路**没有一处能共用**:

| | VNC 路 | screencast 路 |
| --- | --- | --- |
| 画面 | 镜像里的 KasmVNC | 我们的 WS 帧流 |
| 输入 | RFB,我们不在链路上 | 我们翻译成 `Input.*` |
| 权限 | 一个 VNC 密码,给了就是全权 | 读 / 写两个 token |
| 帧里有什么 | 整个桌面,要 `crop_top` 裁 | 只有页面内容 |
| runtime 契约 | 两个端点 | 一个 CDP 端点 |
| 浏览器从哪来 | 4.4 GB 的桌面镜像 | `webmuxd install` 下一个([07 §4](07-runtime.md#4-webmuxd-install-下一个浏览器)) |
| 原生对话框 | 桌面里能看见 | 必须 CDP 拦截 |
| `session()` 参数 | `api_port` + `view_port` + `view_password` | `port` + token |

留开关等于**两套输入模型、两套权限模型、两套 runtime 契约同时在线**,
而且每加一个功能(下载、剪贴板、只读)都要问一句"另一条路怎么办"。
文档也会从"webmuxd 是什么"退化成"取决于你选了哪个"。

要桌面的场景不是没有,但那个场景的正确答案是**用 v1**,不是在 v2 里塞一个分支。
v1 的文档、镜像、实测记录都还在,`docs/v1/` 一个字没删。

## 6. 这次量到的

2026-08-17,本机 Chromium 151,`--headless=new`。完整结论散在各篇,这里只列跟"能不能成立"有关的:

| 量的是什么 | 结果 |
| --- | --- |
| headless 下能不能 screencast | **能**。demo 用 `--headless=new` 跑完 17 项 e2e |
| 三个 tab 同时 `startScreencast` | 2 秒内 **只有前台那个产帧**(前台 41 帧,另两个各 0 帧) |
| `Target.activateTarget` 之后 | 后台那个**立刻开始产帧**(前 1 秒 0 帧 → 后 1 秒 20 帧) |
| 切 tab 的首帧延迟 | **14 – 39 ms**([05 §3](05-active-tab.md#3-切-tab-是把-screencast-搬过去)) |
| 静止页面开着 screencast 静置 3 秒 | **1 帧,13 KB** —— 没人动就几乎不发 |
| 简单动画页面 | 20.3 fps,均帧 7 KB,1.08 Mbps(真实网页要看 §4 那组 youtube 数字) |
| ~~`--network host` 下宿主机直连容器里的 CDP~~ | 通,零转发 —— **但用不上了**,见下 |
| ~~三个 headless chromium 容器共享 host netns 同时跑~~ | 零冲突 —— **同样用不上了** |

划掉的那两条是本轮量的,量完之后[容器整个不要了](07-runtime.md#2-容器不要了),
于是它们要回答的那个问题(**怎么把 CDP 从容器里捞出来**,v1 论证最重的一节)
**不是被解决了,是被删掉了** —— webmuxd 和 Chromium 现在同处一个 network namespace,
`127.0.0.1` 就是 `127.0.0.1`。数据存档:它证明了即使你自己把两者塞进容器,这一段也不会碍事。

## 7. ↔ 别处

| | |
| --- | --- |
| 帧怎么发 | [02](02-frame-protocol.md) |
| 输入怎么翻译 | [03](03-input.md) |
| 一个口之后 session 长什么样 | [04](04-one-port.md) |
| 被作废的那篇 | [v1/works/04](../../v1/works/04-chrome-ui-externalization.md) |
| 被翻转的那条判据 | [v1/works/08 §2](../../v1/works/08-browser-runtime.md#2-判据哪一半在契约里) |
| 同一条判据在 tmuxd 里的样子 | tmuxd `works/06 §1` —— *ttyd 是实现细节,tmux 是契约的一部分* |
