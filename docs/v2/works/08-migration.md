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
| `api_port` | → **`port`** | 只剩一个口([04](b-input.md)) |
| `view_port` | **删** | |
| `view_login` / `view_password` | **删** | VNC 的规矩,不是我们的。换成 token |
| `view_url` | 保留,含义变了 | 现在指向我们自己的页面 |
| `sess.viewport()` 里的 `crop_top` | **删** | 帧里没有浏览器 UI 可裁([01 §2](01-frame-source.md#2-一整篇设计随之作废)) |
| `share(writable=, ttl=)` | **签名不变**,但只读第一次是真的 | [04 §3](b-input.md#1-收口在哪) |
| `image=` / `--image` | **删** —— 连同 `runtime="container"`、`network=`、镜像的 `webmuxd.*` 标签机制、`discover()` 一起 | [07 §2](07-runtime.md#2-容器不要了) |
| `browser=` | **新** —— 指定用哪个浏览器二进制。不传就用 `install` 下的那个 | [07 §4.4](07-runtime.md#44-install-的形状内容换掉规矩全留) |
| `runtime=` | 三分法塌成两种:**本机起一个**(默认)或 `remote` | [07 §1](07-runtime.md#1-契约只剩一条) |
| `runtime="remote"` | 只要 `cdp=`,不要画面口。**隔离要的话在这儿** | [07 §6](07-runtime.md#6-remote--隔离要的话在这儿) |

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
{ "type":"dialog.opened",  "subtype":"confirm", "text":"确定要删除吗?" }  // 新([06](06-no-desktop.md))
{ "type":"dialog.closed",  "action":"timeout", "by":"default" }           // 新
{ "type":"file.opened",    "mode":"selectSingle" }                        // 新
{ "type":"download.began" } { "type":"download.done" }                    // 新
{ "type":"auth.required" }  { "type":"permission.changed" }               // 新
{ "type":"tab.created", … }  { "type":"tab.updated", … }                  // 原样
```

日志也多了四类(`dialog` / `download` / `file` / `permission` / `auth`)——
v1 是三类。它们是"页面为什么停住"的唯一解释([06 §3](06-no-desktop.md#3-日志里必须看得见))。

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
| 要**开箱即用的隔离** | **v1** —— v2 不碰容器([07 §2](07-runtime.md#2-容器不要了))。v2 里隔离要你自己给:把 webmuxd 放进容器,或者用 `remote` 连一个别处的浏览器 |
| **带宽是硬约束**(按流量计费、窄带链路) | **v1** —— 区域重传更省字节。但注意换来的是**更省,不是更流畅** |
| 其余一切 | **v2** |

第一条不是客套,v2 明确不做桌面([works/README §明确不做](README.md#明确不做))。

**第二条只谈字节,不谈体验。** 实测在 YouTube 看视频 screencast 比 kasm 更流畅
([01 §4.1](01-frame-source.md#41-但更费带宽--更不流畅))—— 全屏运动是区域重传的负收益区。
所以"带宽敏感就用 v1"是一笔明确的交换:**省流量,换掉流畅度**,
而不是"低配场景用 v1、高配场景用 v2"那种想当然的分法。

落在这两格里的人继续用 v1,它的文档、镜像、实测记录一个字没删。

## 5. 落地顺序 —— **七步全部做完了**

不是一次性替换,按"每步都能自己跑起来"切。**这张表现在是回顾,不是计划**:

| | 做什么 | 落在哪 | 守着它的测试 |
| --- | --- | --- | --- |
| 1 | `view/` 的帧流:screencast → 28 字节头 → WS → `<img>` | [`view/cast.py`](../../../webmuxd/view/cast.py) | [`pixels_on_a_wire/`](../../../tests/pixels_on_a_wire/) |
| 2 | 输入翻译 + 光标 | [`view/input.py`](../../../webmuxd/view/input.py) · [`cursor.py`](../../../webmuxd/view/cursor.py) | 同上 |
| 3 | ack 背压 + RTT 自适应 | [`view/viewer.py`](../../../webmuxd/view/viewer.py) · [`quality.py`](../../../webmuxd/view/quality.py) | 同上 |
| 4 | 内置页面的 tab 条 / 地址栏 | [`static/index.html`](../../../webmuxd/view/static/index.html) | — |
| 5 | 六类原生 UI | [`native/`](../../../webmuxd/native/) | [`no_desktop/`](../../../tests/no_desktop/)(10 条) |
| 6 | `webmuxd install` + 本机起进程 + `remote` | [`cli/install.py`](../../../webmuxd/cli/install.py) · [`runtime/`](../../../webmuxd/runtime/) | [`installing/`](../../../tests/installing/) · [`one_endpoint/`](../../../tests/one_endpoint/) |
| 7 | 只读 / 可写 token | [`serve/app.py`](../../../webmuxd/serve/app.py) | [`the_http_face/`](../../../tests/the_http_face/) |

1–3 步的参考实现是 `~/browserbox/demo/`,那 700 行已经跑通并有 17 项自测 ——
**照抄,不重新设计,也不顺手调参**([02 §0](02-frame-protocol.md#0-这一篇的地位照抄不重新设计))。

**第 8 步是当初没排的**:换一条像素来源(xpra)。它没有出现在这张表里,
因为写这篇的时候还不知道有这条路 —— 它是[11](11-xpra.md) · [12](12-xpra-client.md),
0.7.0 起是默认,落在 [`xpra.py`](../../../webmuxd/xpra.py) ·
[`view/relay.py`](../../../webmuxd/view/relay.py) ·
[`static/xpra.js`](../../../webmuxd/view/static/xpra.js),
测试在 [`pixels_from_xpra/`](../../../tests/pixels_from_xpra/)。

## 6. 落地前必须补的实测 —— 现在的账

本轮量到的东西散在各篇([01 §6](01-frame-source.md#6-这次量到的) 有汇总)。
**下面这张表是当初列的"押在上面但没量"的东西,逐条对了一遍**:

| 待验 | 状态 | |
| --- | --- | --- |
| `window.open` 的 target 类型 / `openerId` | **✓ 验了** | [`chrome_facts`](../../../tests/chrome_facts/) 实测四种开 tab 的方式**全带 `openerId`**,所以不需要 url 兜底,也不需要 `unknown`([05 §4](05-active-tab.md#4-popup-不再是特殊情况))。带 `windowFeatures` 那条 headless 下测不了,**标着 skip 留在那儿** |
| 六类原生 UI 的 CDP 拦截逐条验证 | **✓ 验了** | [`no_desktop/`](../../../tests/no_desktop/) 10 条,判据是**页面自己动了**,不是我们收到了事件 |
| 真实网页的帧率与码率 | **✓ 部分** | xpra 那条量全了([12 §9](12-xpra-client.md#9-量到的数)):滚动 3.71 Mbps、全屏动画 2.86–9.34 Mbps ≈ 20 fps。screencast 那条仍然引的是 demo 的数 |
| `install` 在裸机上缺哪些 `.so` | **✓ 部分** | 清单落在 [`deps.py`](../../../webmuxd/cli/deps.py),apt / dnf / yum 三份。RHEL 那份是真机上撞出来的,Alpine 还没试 |
| 多个 target 各自 `setDeviceMetricsOverride` 是否互不干扰 | **✗ 还没量** | 押在 [02 §5](02-frame-protocol.md#5-分辨率是-per-tab-的)。不成立的话 `resize` 要退回 session 级。**没有测试守着** |
| screencast vs kasm 的流畅度数字 | **✗ 还没量** | 押在 [01 §4.1](01-frame-source.md#41-但更费带宽--更不流畅)。方向实测过(主观),缺的是能对外讲的数 |
| **Chrome for Testing 的条款**允不允许这种用法 | **✗ 还没查** | 押在 [07 §4.2](07-runtime.md#42-下什么从哪下)。不行就退回纯 BSD 的 Chromium 构建,**不损失功能** |

xpra 那条路自己的待验项另有一份,在 [12 §13](12-xpra-client.md#13-还没验的)。
