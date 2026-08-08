# 04 · tab bar 与 url bar 外化

**一句话**:VNC 画面里只剩页面内容,Chrome 自带的 tab 条和地址栏不可见;
tab 列表和 URL 状态走 API 出来,由调用方在外面自己画。
页面里点链接冒出新 tab,外面能立刻感知到。

## 1. 最终形态

```
┌─ 你自己写的网页 ────────────────────────────────────────────────┐
│ ┌──────────┬──────────┬──────────┐                    ← 你画的  │
│ │ ● 购物车 │ 订单确认 │ 帮助中心 │ ＋                    tab 条 │
│ ├──────────┴──────────┴──────────┴──────────────────┐          │
│ │ ← → ⟳  🔒 shop.example.com/cart                   │ ← 你画的 │
│ └───────────────────────────────────────────────────┘   地址栏 │
│ ┌───────────────────────────────────────────────────┐          │
│ │        VNC 画面 —— 只有页面内容                    │          │
│ └───────────────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────────────┘
     ▲ 上面两条是普通 HTML,数据走 /api/tabs + WS
     ▲ 下面那块是 VNC
```

## 2. 怎么把 Chrome 的 UI 弄没

**把窗口整体往上挪,让 tab 条和工具栏移出屏幕顶部,窗口高度补上偏移量。**

```
                    ┌─────────────────────┐  ← y = -78,屏幕外
                    │ tab 条 / 地址栏     │
X 屏幕顶部 y=0 ───► ├─────────────────────┤
                    │   页面内容           │  ← VNC 里只看得到这块
                    └─────────────────────┘  ← 窗口高 = 屏幕高 + 78
```

偏移量运行时算得出来,不用猜:

```js
window.outerHeight - window.innerHeight    // tab条 + 工具栏 的总高度
```

然后 `Browser.setWindowBounds({left:0, top:-offset, width:W, height:H+offset})`。

这么做的好处是 **tab 语义完全原生**——`target=_blank`、`window.open`、Ctrl+点击、tab 顺序,
全是 Chrome 自己的行为,一行都不用模拟。视口也正好等于屏幕分辨率,VNC 坐标和页面坐标 1:1。

**唯一的地基风险**:kasm 里的窗口管理器可能把负坐标 clamp 回可见区。见 §5。
真被 clamp 了就去掉 WM(Chrome 用 `--window-position=0,-78` 自己定位,没人管得着),
或者退回 `--app=` 窗口模式(天生没 UI,但一窗口一页面,多 tab 得自己模拟)。

三条路对上层 API 完全透明,换方案不影响调用方。

## 3. 外面画 tab 条和地址栏需要什么 —— CDP 给不给

| 要画的 | CDP 来源 | 拿得到吗 |
| --- | --- | --- |
| tab 列表、顺序 | `Target.getTargets` | ✅ |
| 新 tab 出现 / 关闭 | `Target.targetCreated` / `targetDestroyed` | ✅ |
| URL / 标题变化 | `Target.targetInfoChanged`、`Page.frameNavigated` | ✅ |
| 切换 / 新建 / 关闭 tab | `Target.activateTarget` / `createTarget` / `closeTarget` | ✅ |
| 导航、刷新、停止 | `Page.navigate` / `reload` / `stopLoading` | ✅ |
| 前进后退是否可用 | `Page.getNavigationHistory`(entries + currentIndex) | ✅ |
| 前进后退跳转 | `Page.navigateToHistoryEntry` | ✅ |
| 转圈(在不在加载) | `Page.frameStartedLoading` / `frameStoppedLoading` | ✅ |
| https 小锁 | `Security.securityStateChanged` | ✅ |
| 当前激活的是哪个 tab | 没有现成事件 | ⚠️ 见 §4.1 |
| favicon | 没有现成事件 | ⚠️ agentd 读 DOM 的 `link[rel~=icon]` 代抓并缓存 |
| 加载进度百分比 | 无 | ❌ 只能转圈,画不了精确进度条 |

**够用。** 缺的两样一个能绕,一个无关紧要。

## 4. API

形状对齐 `chrome.tabs` 扩展 API —— 写过 Chrome 扩展的人零学习成本。

| 方法 | 路径 |
| --- | --- |
| `GET` | `/api/tabs` |
| `POST` | `/api/tabs` 新建 `{url, active}` |
| `POST` | `/api/tabs/{id}/activate` 切过去(VNC 画面随之切) |
| `DELETE` | `/api/tabs/{id}` |
| `POST` | `/api/tabs/{id}/goto` `{url}` |
| `POST` | `/api/tabs/{id}/back` `/forward` `/reload` `/stop` |
| `POST` | `/api/tabs/reorder` `{order:[id,...]}` 拖拽排序 |
| `GET` | `/api/tabs/{id}/favicon` |

```jsonc
// GET /api/tabs
{ "tabs": [
  { "id":"t_3", "index":0, "active":true,
    "url":"https://shop.example.com/cart", "title":"购物车",
    "loading":false, "security":"secure",
    "can_go_back":true, "can_go_forward":false,
    "favicon":"/api/tabs/t_3/favicon", "opener":null },
  { "id":"t_7", "index":1, "active":false,
    "url":"https://shop.example.com/order/9182", "title":"订单确认",
    "loading":true, "security":"secure",
    "can_go_back":true, "can_go_forward":false,
    "opener":"t_3" }                       // ← 从 t_3 里点链接开出来的
] }
```

### 事件

```jsonc
// WS /api/events
{ "type":"tab.created",   "tab":{...}, "reason":"link_target_blank" }
{ "type":"tab.updated",   "id":"t_7", "changed":{ "title":"订单确认", "loading":false } }
{ "type":"tab.activated", "id":"t_7", "previous":"t_3" }
{ "type":"tab.closed",    "id":"t_7" }
```

`tab.updated` 只发变化的字段,外面做局部更新。

`reason` 说明这个 tab 怎么冒出来的:`api` / `link_target_blank` / `window_open` /
`ctrl_click` / `user_ctrl_t`(人在 VNC 里按了 Ctrl+T)。你的 tab 条可以据此决定要不要自动切过去。

`opener` 标出"从哪个 tab 开出来的",想画成子 tab 或加来源提示都行。

### Python lib

```python
for t in b.tabs():
    print(t.index, t.title, t.url, "●" if t.active else "")

t = b.new_tab("https://example.com")
t.activate(); t.close()

for e in b.watch("tab.*"):       # 实时同步你自己的 tab 条
    ui.update(e)
```

### 4.1 「当前是哪个 tab」没有现成事件

人在 VNC 里按 `Ctrl+Tab` 换了 tab,外面怎么知道?

用 `Page.addScriptToEvaluateOnNewDocument` 给每个 tab 注入一段监听 `visibilitychange` 的脚本,
谁 `visible` 谁就是当前 tab(导航后自动重装)。`about:` 这类注入不进去的页面,
fallback 到轮询 `Target.getTargets`。

## 5. 动手前先跑这个实验

方案 A 全押在一件事上:**kasm 的 WM 允不允许窗口摆到负 Y**。我没实测过,不能拍胸脯。

```bash
# 容器内,10 分钟出结论
WID=$(xdotool search --class chrome | head -1)
xdotool windowmove $WID 0 -78
xdotool getwindowgeometry $WID
#   Y 还是 -78  → 方案 A 成立,照 §2 做
#   Y 被弹回 0  → 去掉 WM,或退 --app 窗口
```

结论只影响 §2 怎么实现,不影响 §3/§4 的 API 设计。

## 6. 顺带会掉出来的东西(不影响架构,以后按需加)

工具栏移出屏幕后,一批挂在工具栏上的原生 UI 会变成"看不见但仍然阻塞":
下载气泡、权限请求(定位/通知/摄像头)、文件选择框、HTTP Basic 认证框、`alert`/`confirm`。

这些**都是 CDP 能拦下来的**(`Browser.downloadWillBegin`、`Browser.setPermission`、
`Page.setInterceptFileChooserDialog`、`Fetch.authRequired`、`Page.javascriptDialogOpening`),
处理方式一律是"拦截 → 抛事件给外面 → 外面自己画 → 回填"。

**每个都是加一个 API 端点 + 一个事件类型,不动架构。** 碰到了再加,不用现在设计。

两个可以顺手就避掉的:
- 全屏播视频会重置窗口偏移 → 监听窗口状态变化,退出后重新施加偏移
- `Ctrl+Shift+B` 开书签栏会让偏移量失准 → 启动禁用书签栏,并监听 `outerHeight-innerHeight` 变化自动重算

一个根治不了的小瑕疵:人按 `Ctrl+L` 会把焦点送到屏幕外的地址栏,之后键盘输入丢失。
检测到焦点离开内容区就 `window.focus()` 抢回来,能缓解;外面 UI 上放个「恢复焦点」按钮兜底。

## 7. 结论

| 事项 | 结论 |
| --- | --- |
| 去掉 tab 条和地址栏 | **可行**,推荐窗口负偏移,两条退路保底 |
| 外面感知 tab 增删改 | **可行**,`Target` 域完全够 |
| 外面控制 tab | **可行** |
| 页面内点链接开新 tab 被感知 | **可行**,还能标出 `opener` |
| 重画地址栏所需信息 | **基本可行**,缺精确进度和 favicon 事件,能绕 |
| 负坐标窗口定位 | **未验证**,先跑 §5 |

**可行。** 先跑 §5 的实验定实现路子,再做 §3/§4 的 tab API。
