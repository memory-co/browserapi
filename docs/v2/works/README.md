# webmuxd v2 · 设计稿

**v1 是 tmux + 一个租来的 ttyd,v2 里 ttyd 那一半是自己写的。**

[v1/works/README](../../v1/works/README.md) 开篇那句"webmuxd ≈ tmux + ttyd"到 v2 才真正成立。
v1 的画面是 kasm / jlesage 的产品,我们只报 URL;v2 的画面是 CDP 吐出来的 JPEG 帧,
从编码参数到背压到输入翻译,每一段都在我们手里。

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
| 画面从哪来 | 镜像里的 KasmVNC / TigerVNC | **CDP `Page.startScreencast`** |
| 人的输入怎么进去 | VNC 协议,我们不参与 | **CDP `Input.*`,我们翻译** |
| 对外几个口 | 两个(画面口 + API 口) | **一个** |
| 画面里有什么 | 整个桌面(含 tab 条、地址栏,要裁掉) | **只有页面内容** |
| 定位 / 观测 / 日志 / tab 表 | | **一个字没动** |

## 文档

| 文件 | 内容 |
| --- | --- |
| [01-frame-source.md](01-frame-source.md) | **画面自己产** —— 判据为什么翻转,VNC 整条砍掉,代价老实写 |
| [02-frame-protocol.md](02-frame-protocol.md) | 帧怎么发 —— **原样照抄 demo**,写的是"抄的时候哪几处不能想当然改" |
| [03-input.md](03-input.md) | 输入翻译**是**安全收口;IME、剪贴板、光标同步 |
| [04-one-port.md](04-one-port.md) | 一个口:session 形状、token、只读分享 |
| [05-active-tab.md](05-active-tab.md) | tab 外挂模式一字不改;`active` 从两份真相合成一份 |
| [06-no-desktop.md](06-no-desktop.md) | 没有桌面之后:六类原生 UI 用 CDP 收回来 —— **v2 唯一的真实工作量** |
| [07-runtime.md](07-runtime.md) | 浏览器从哪来:**容器不要了**、`webmuxd install` 下一个(照着 playwright)、本机起一个进程 |
| [08-migration.md](08-migration.md) | v1 → v2:什么变了、什么一个字没动 |
| [09-wire-format.md](09-wire-format.md) | **一帧逐字节长什么样** —— ttyd 一个字节、我们二十八个,为什么;三家的上行怎么组织;以及**那个缺掉的协议客户端** |
| [10-install.md](10-install.md) | **playwright 的 install 拆开看** —— 下的是 bin 还是 rpm(两条都有,刻意分开)、标记文件、镜像轮转、依赖怎么探。末尾是该抄什么不该抄什么 |
| [11-xpra.md](11-xpra.md) | **画面默认走 xpra** —— 但它只负责像素:两条 WS、输入不走它(收口不动)、`--kiosk` 让 bar 根本不出现、原生 UI 照旧归我们 |
| [12-xpra-client.md](12-xpra-client.md) | **客户端解码,实测** —— xpra-html5 里没有解码器,自写约 500 行;`start-desktop` + `--kiosk`;`scroll` 用零字节干掉 57% 重绘面积 |

## 明确不做

v1 那份[「明确不做」](../../v1/works/README.md#明确不做)全部继承(控制面 / 数据库 / 多租户 /
内置 LLM / k8s operator),判据仍然是那一句:**tmux 会做这个吗?**

v2 自己新增四条,都是"自己产画面"这个决定的直接推论:

- ❌ **不做 H.264 / VP8 / WebRTC。** 帧间编码是对的方向,但它是另一个量级的工程
  (编码器、抖动缓冲、NACK/PLI、SFU),会把这个项目变成流媒体项目。
  v2 就是 JPEG + 自适应降质,带宽账[明写在 01](01-frame-source.md#4-代价老实写)。
  **而且实测 JPEG 流在最难的场景(YouTube 看视频)上已经比 VNC 更流畅**
  ([01 §4.1](01-frame-source.md#41-但更费带宽--更不流畅))—— WebRTC 能换的是带宽,
  不是流畅度,那笔交易没有想象中划算。图片流这层**先照抄 demo 跑起来**,
  以后要优化从哪儿动、什么条件下动,列在 [02 §6](02-frame-protocol.md#6-以后可以再优化的)。
- ❌ **不做音频。** kasm 的镜像有,我们没有。这是 v2 相对 v1 的**净损失**,不装作没有。
- ❌ **不做桌面。** 窗口管理器、右键菜单、文件管理器 —— headless 里根本没有这些东西,
  也不打算模拟。要桌面的场景,v1 那条路仍然可用。
- ❌ **不碰容器。** 不起容器、不认容器、不探 docker,`image=` / `network=` 一起删掉。
  tmuxd 不会 `docker run` 一个 tmux。要隔离就**把 webmuxd 放进容器里**,
  那是你的部署决定,不是我们的参数([07 §2](07-runtime.md#2-容器不要了))。
- ❌ **不保留 VNC 作为开关。** 不做 `view="vnc" | "screencast"`。两套画面路径意味着
  两套输入路径、两套权限模型、两套 runtime 契约,而它们没有一处能共用。
  结论只能有一个([01 §5](01-frame-source.md#5-为什么不留一个开关))。
