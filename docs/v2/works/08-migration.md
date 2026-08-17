# 08 · v1 → v2

**一句话**:变的全在画面这一半。**定位、观测、日志、tab 表、错误模型一个字没动。**

## 1. 变了的东西

### session 的形状

```python
# v1
sess = web.session(id="work", api_port=7900, view_port=8090,
                   image="…/kasmweb-chromium:1.18.0")
print(sess.view_url, sess.view_login, sess.view_password)

# v2
sess = web.session(id="work", port=7900)
print(sess.view_url)          # 带 token,和 API 同一个口
```

| 字段 / 参数 | v2 | 说明 |
| --- | --- | --- |
| `api_port` | → **`port`** | 只剩一个口([04](04-one-port.md)) |
| `view_port` | **删** | |
| `view_login` / `view_password` | **删** | VNC 的规矩,不是我们的。换成 token |
| `view_url` | 保留,含义变了 | 现在指向我们自己的页面 |
| `sess.viewport()` 里的 `crop_top` | **删** | 帧里没有浏览器 UI 可裁([01 §2](01-frame-source.md#2-一整篇设计随之作废)) |
| `share(writable=, ttl=)` | **签名不变**,但只读第一次是真的 | [04 §3](04-one-port.md#3-读和写是两个-token) |
| `image` | **降级** —— 只有 `runtime="container"` 时才用得上,而那个镜像是你自己三行 build 的 | [07 §4.5](07-runtime.md#45-那容器还要不要) |
| `browser=` | **新** —— 指定用哪个浏览器二进制。不传就用 `install` 下的那个 | [07 §4.4](07-runtime.md#44-install-的形状内容换掉规矩全留) |
| 默认 `runtime` | `container` → **`process`**。容器只剩隔离一个理由 | [07 §5](07-runtime.md#5-process-成了默认) |
| `runtime="remote"` | 只要 `cdp=`,不要画面口 | [07 §6](07-runtime.md#6-remote-第一次真正好用) |

### CLI

```bash
# v1
webmuxd new --id work --api-port 7900 --view-port 8090

# v2
webmuxd new --id work --port 7900
```

`--view-port` 退役。其余子命令(`new-tab` / `click` / `observe` / `log` / `kill`)
**一个字没变**。

### 事件

新增一类,其余不动:

```jsonc
{ "type":"dialog.opened",   "subtype":"confirm", "text":"确定要删除吗?" }   // 新([06](06-no-desktop.md))
{ "type":"download.began",  "file":"报表.xlsx" }                            // 新
{ "type":"tab.created", … }  { "type":"tab.updated", … }                    // 原样
```

`viewport.changed` 那个事件删掉了 —— 它存在的唯一理由是 `crop_top` 会变。

## 2. 一个字没动的东西

这一节是本文最重要的一节。**webmuxd 的核心价值全在这儿,而它们和画面从哪来无关:**

| | 为什么不受影响 |
| --- | --- |
| **按人看得见的字定位** —— `click("提交订单")`、分档匹配、有歧义给候选 | 纯 CDP + DOM,[v1/sdk/tab/input.md](../../v1/sdk/tab/input.md) 原样有效 |
| **`observe()`** —— 元素表 + 标注截图 + `notes` | 同上。截图现在和画面同源([01 §3](01-frame-source.md#3-白捡的四样)) |
| **操作日志** —— JSONL scrollback,三类记录 | [v1/works/03](../../v1/works/03-log.md) 原样有效,只是多了几类事件([06 §3](06-no-desktop.md#3-日志里必须看得见)) |
| **tab 表就是 target 表** —— `reason` / `opener` / `openerId` | [v1/works/06](../../v1/works/06-tab-sync.md) 原样有效([05 §1](05-active-tab.md#1-不变的部分)) |
| **`act()` 不抛异常,快捷方法抛** | 错误模型没动 |
| **lib 是主体,api 是导出面** | [v1/works/02](../../v1/works/02-lib-and-api.md) 原样有效 |
| **三层:`Webmuxd` / `Session` / `Tab`** | [v1/works/05](../../v1/works/05-server-session-runtime.md) 原样有效 |
| **逃生舱:你自己拿 DevTools 连上去** | CDP 仍然是契约,而且是**唯一**的契约([07 §1](07-runtime.md#1-契约只剩一条)) |

代码上对应 `core/`(cdp / tabs / locate / observe / act / log)和 `client/` 三个对象 ——
**v2 的改动进不来这些目录**,新增的是 `view/`(帧、输入、权限)和 `serve/` 的两条 WS 路由。

## 3. 作废的三篇 v1 设计稿

| | 为什么 |
| --- | --- |
| [v1/works/04](../../v1/works/04-chrome-ui-externalization.md) tab 条与 url bar 外化 | 帧里本来就没有浏览器 UI。§3 的能力表和 §6 的对话框清单继承下来 |
| [v1/works/07](../../v1/works/07-popup-windows.md) popup 是窗口不是 tab | headless 里没有窗口,popup 就是 target([05 §4](05-active-tab.md#4-popup-不再是特殊情况)) |
| [v1/works/08 §4](../../v1/works/08-browser-runtime.md#4-画面那一半三种实现实测排名) 三种 VNC 实测排名 | 画面不再来自它们。**结论存档,仍然是对的** |

**存档不删。** 这些文档记录的是当时量到的事实,那些事实没有变 ——
KasmVNC 的抽象 socket 冲突、kasm 的窗口看门狗、Chromium 的 CDP 只绑 loopback,
今天依然如此,只是**不再咬我们了**。

## 4. 用 v1 还是 v2

不需要"迁移指南"式的劝说,两条判据:

| 你的情况 | 用 |
| --- | --- |
| 要**完整桌面**(文件管理器、系统对话框、非浏览器程序、音频) | **v1** |
| **带宽是硬约束**(按流量计费、窄带链路) | **v1** —— 区域重传更省字节。但注意换来的是**更省,不是更流畅** |
| 其余一切 | **v2** |

第一条不是客套,v2 明确不做桌面([works/README §明确不做](README.md#明确不做))。

**第二条只谈字节,不谈体验。** 实测在 YouTube 看视频 screencast 比 kasm 更流畅
([01 §4.1](01-frame-source.md#41-但更费带宽--更不流畅))—— 全屏运动是区域重传的负收益区。
所以"带宽敏感就用 v1"是一笔明确的交换:**省流量,换掉流畅度**,
而不是"低配场景用 v1、高配场景用 v2"那种想当然的分法。

落在这两格里的人继续用 v1,它的文档、镜像、实测记录一个字没删。

## 5. 落地顺序

不是一次性替换,按"每步都能自己跑起来"切:

| | 做什么 | 做完能验证什么 |
| --- | --- | --- |
| 1 | `view/` 的帧流:screencast → 28 字节头 → WS → `<img>` | 打开 `/` 能看见页面 |
| 2 | 输入翻译 + 光标 | 能上手点、能打字(含中文) |
| 3 | ack 背压 + RTT 自适应 | 慢客户端不拖累别人(照抄 demo 的那一项自测) |
| 4 | 内置页面的 tab 条 / 地址栏,接 `/api/tabs` | 切 tab、导航,和 API 侧同一份状态 |
| 5 | 六类原生 UI 的前三条(对话框 / 下载 / 文件选择) | **可宣布可用的门槛**([06 §5](06-no-desktop.md#5-排期不是全都要一次做完)) |
| 6 | `webmuxd install` + `process` / `container` / `remote` 三个 runtime | 不装 docker 也能跑、一机多开、云 CDP 自带画面 |
| 7 | 只读 / 可写 token | `share()` 那个承诺兑现 |

1–3 步的参考实现就是 `~/browserbox/demo/`,那 700 行已经跑通并有 17 项自测。

## 6. 落地前必须补的实测

本轮量到的东西散在各篇([01 §6](01-frame-source.md#6-这次量到的) 有汇总),
以下几条**还没量**,而设计押在它们上面:

| 待验 | 押在哪儿 | 不成立会怎样 |
| --- | --- | --- |
| 多个 target 各自 `Emulation.setDeviceMetricsOverride` 是否互不干扰、帧尺寸跟不跟着变 | [02 §5](02-frame-protocol.md#5-分辨率是-per-tab-的) | `resize` 退回 session 级 |
| `window.open` 的 target 类型 / `openerId` / 能否 screencast | [05 §4](05-active-tab.md#4-popup-不再是特殊情况) | popup 要单独处理,v1/works/07 复活 |
| 真实网页(非 data: 页)的帧率与码率 | [01 §4](01-frame-source.md#4-代价老实写) 引的是 demo 在 youtube 上的数字 | 带宽预期要重写 |
| **screencast vs kasm 的流畅度对比数字**(fps 曲线 / 端到端延迟 / 码率 / CPU,同机同链路同视频) | [01 §4.1](01-frame-source.md#41-但更费带宽--更不流畅) 目前只有主观对比 | 结论方向已经实测过,缺的是**能对外讲的数字** |
| 六类原生 UI 的 CDP 拦截逐条验证 | [06 §2](06-no-desktop.md#2-六类逐条) | 排期要重排 |
| **Chrome for Testing 的条款**允不允许 webmuxd 这种用法 | [07 §4.2](07-runtime.md#42-下什么从哪下) | 退回纯 BSD 的 Chromium 构建,"视频能放"那条收回 |
| `install` 在裸机上到底缺哪些 `.so`(Debian / Ubuntu / Alpine 各一遍) | [07 §4.3](07-runtime.md#43-系统依赖和字体照抄-playwright-的姿态) | `install-deps` 的清单要重写 |
