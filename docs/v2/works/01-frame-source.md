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
| **带宽** | 没有帧间压缩,每帧都是完整 JPEG。demo 实测(1280×800 q80,youtube):静止 **0 kbps**,搜索结果页静置 8.5 fps / 2.7 Mbps,持续滚动 10.4 fps / **10.2 Mbps**。VNC 的区域重传在这一项上是明确更优。缓解手段(RTT 自适应降质 + 抽帧)见 [02 §3](02-frame-protocol.md#3-rtt-自适应画质),但**改变不了量级** |
| **音频** | 没有。kasm 的镜像有,这是净损失 |
| **原生 UI 全部失去兜底** | 文件选择、下载、权限请求、Basic 认证、`alert`、PDF 查看器 —— headless 里根本不渲染。必须一条条用 CDP 收回来,这是 v2 唯一的真实工作量([06](06-no-desktop.md)) |
| **`--force-device-scale-factor` 是浏览器级的** | demo 实测:让 screencast 按 2x 出图只能靠这个启动参数,`Emulation.setDeviceMetricsOverride` 里的 `deviceScaleFactor` 对 screencast **完全无效**。所以一个 session 里所有 tab、所有观看者共用一个 dsf,不能按观看端的 dpr 各自匹配([02 §4](02-frame-protocol.md#4-清晰度三个独立的旋钮)) |
| **扩展 / 特殊页面** | headless 下扩展的 popup UI、`chrome://` 设置页这类浏览器自身界面,截不到也不该截 |

**带宽那条要说清楚**:它不是"实现得不够好",是 JPEG 截图流这条路线的本质特征。
真正的解法是 H.264/VP8 走 WebRTC,而那是另一个量级的工程,v2 明确不做
([works/README §明确不做](README.md#明确不做))。

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
| 镜像 | 4.4 GB 带 xfce | 几百 MB headless |
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
| `--network host` 下宿主机直连容器里的 CDP | **通**,`curl 127.0.0.1:9345/json/version` 有返回,**零转发** |
| 三个 headless chromium 容器共享 host netns 同时跑 | **零冲突**,三个 CDP 口都活着([07 §3](07-runtime.md#3-一机多开天然成立)) |

最后两条把 v1 [works/08 §3.1](../../v1/works/08-browser-runtime.md#31-所以-runtime-的真正工作是把-cdp-搬到一个能连的地方)
那个"CDP 搬运问题"直接消掉了:镜像里那一跳转发(`cdp-relay.py` / socat)**不用再垫**。

## 7. ↔ 别处

| | |
| --- | --- |
| 帧怎么发 | [02](02-frame-protocol.md) |
| 输入怎么翻译 | [03](03-input.md) |
| 一个口之后 session 长什么样 | [04](04-one-port.md) |
| 被作废的那篇 | [v1/works/04](../../v1/works/04-chrome-ui-externalization.md) |
| 被翻转的那条判据 | [v1/works/08 §2](../../v1/works/08-browser-runtime.md#2-判据哪一半在契约里) |
| 同一条判据在 tmuxd 里的样子 | tmuxd `works/06 §1` —— *ttyd 是实现细节,tmux 是契约的一部分* |
